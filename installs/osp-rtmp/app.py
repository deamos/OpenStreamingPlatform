# -*- coding: UTF-8 -*-
from gevent import monkey

monkey.patch_all(thread=True)

# Import Standary Python Libraries

import sys
import logging
import os
import uuid

# Import 3rd Party Libraries
from flask import Flask, redirect, request, abort, flash
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

# Import Paths
cwp = sys.path[0]
sys.path.append(cwp)

version = "0.9.11"

# ----------------------------------------------------------------------------#
# Configuration Imports
# ----------------------------------------------------------------------------#
try:
    from conf import config

except:
    from dotenv import load_dotenv

    class configObj:
        pass

    load_dotenv()
    config = configObj()
    config.ospCoreAPI = os.getenv("OSP_API_HOST")
    config.secretKey = os.getenv("OSP_RTMP_SECRETKEY")
    config.debugMode = os.getenv("OSP_RTMP_DEBUG").lower() in ("true", "1", "t")

    config.redisHost = os.getenv("OSP_REDIS_HOST", "127.0.0.1")
    config.redisPort = int(os.getenv("OSP_REDIS_PORT", 6379))
    config.redisPassword = os.getenv("OSP_REDIS_PASSWORD", "")

# ----------------------------------------------------------------------------#
# Global Vars Imports
# ----------------------------------------------------------------------------#
from globals import globalvars

# ----------------------------------------------------------------------------#
# App Configuration Setup
# ----------------------------------------------------------------------------#
coreNginxRTMPAddress = "127.0.0.1"

globalvars.apiLocation = config.ospCoreAPI

app = Flask(__name__)

# Flask App Environment Setup
app.debug = config.debugMode
app.wsgi_app = ProxyFix(app.wsgi_app)
app.jinja_env.cache = {}
app.config["WEB_ROOT"] = globalvars.videoRoot

app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_NAME"] = "ospSession"
app.config["SECRET_KEY"] = config.secretKey

logger = logging.getLogger("gunicorn.error").handlers

# ----------------------------------------------------------------------------#
# Begin App Initialization
# ----------------------------------------------------------------------------#

####### Sentry.IO Metrics and Error Logging (Disabled by Default) #######
if hasattr(config, "sentryIO_Enabled") and hasattr(config, "sentryIO_DSN"):
    if config.sentryIO_Enabled:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration

        sentryEnv = "Not Specified"
        if hasattr(config, "sentryIO_Environment"):
            sentryEnv = config.sentryIO_Environment

        sentry_sdk.init(
            dsn=config.sentryIO_DSN,
            integrations=[
                FlaskIntegration()
            ],
            # Set traces_sample_rate to 1.0 to capture 100%
            # of transactions for performance monitoring.
            # We recommend adjusting this value in production.
            traces_sample_rate=1.0,
            release=version,
            environment=sentryEnv,
            server_name="osp_rtmp" + str(uuid.uuid4),
            _experiments={
                "profiles_sample_rate": 1.0,
            }
        )

# Initialize Flask-CORS Config
cors = CORS(app, resources={r"/apiv1/*": {"origins": "*"}})

# ----------------------------------------------------------------------------#
# Blueprint Filter Imports
# ----------------------------------------------------------------------------#
from blueprints.rtmp import rtmp_bp
from blueprints.root import root_bp
from blueprints.api import api_v1

# Register all Blueprints
app.register_blueprint(rtmp_bp)
app.register_blueprint(root_bp)
app.register_blueprint(api_v1)

# ----------------------------------------------------------------------------#
# Health Monitor and PID Cleanup
# ----------------------------------------------------------------------------#
import threading
import time
import signal
import requests

def cleanup_stale_pids():
    r = globalvars.get_redis()
    for key in r.scan_iter("osp:rtmp:pids:*"):
        for pid in r.smembers(key):
            try:
                os.kill(int(pid), signal.SIGTERM)
                app.logger.info(f"Killed stale ffmpeg process PID {pid} for {key}")
            except ProcessLookupError:
                pass
        r.delete(key)

def restream_monitor_thread():
    import subprocess
    import time
    while True:
        try:
            r = globalvars.get_redis()
            if not hasattr(globalvars, 'restreamMetadata'):
                globalvars.restreamMetadata = {}
                
            for channel_loc, meta_dict in list(globalvars.restreamMetadata.items()):
                status_payload = {}
                for dest_id, meta in list(meta_dict.items()):
                    proc = globalvars.restreamSubprocesses.get(channel_loc, {}).get(dest_id)
                    
                    if proc is None:
                        if meta.get("state") == "Running":
                            meta["state"] = "Disconnected"
                        status_payload[dest_id] = {"state": meta.get("state", "Disconnected"), "message": "No active subprocess"}
                    else:
                        retcode = proc.poll()
                        if retcode is not None:
                            app.logger.warning(f"[HealthMonitor] Restream ffmpeg for {channel_loc} to dest {dest_id} exited with {retcode}")
                            
                            try:
                                del globalvars.restreamSubprocesses[channel_loc][dest_id]
                            except KeyError:
                                pass
                                
                            retry_count = meta.get("retry_count", 0)
                            if retry_count < 5:
                                meta["retry_count"] = retry_count + 1
                                meta["state"] = "Retrying"
                                meta["last_retry_time"] = time.time()
                                app.logger.info(f"[HealthMonitor] Retrying restream for {channel_loc} to dest {dest_id} (Attempt {meta['retry_count']}/5)")
                                
                                try:
                                    p = subprocess.Popen(
                                        meta["cmd"],
                                        stdout=subprocess.DEVNULL,
                                        stderr=subprocess.PIPE,
                                    )
                                    if channel_loc not in globalvars.restreamSubprocesses:
                                        globalvars.restreamSubprocesses[channel_loc] = {}
                                    globalvars.restreamSubprocesses[channel_loc][dest_id] = p
                                    r.sadd(f"osp:rtmp:pids:{channel_loc}", str(p.pid))
                                    
                                    from blueprints.rtmp import log_stream
                                    t = threading.Thread(target=log_stream, args=(p.stderr, channel_loc, meta["name"]), daemon=True)
                                    t.start()
                                    
                                    meta["state"] = "Running"
                                    status_payload[dest_id] = {"state": "Running", "message": ""}
                                except Exception as restart_err:
                                    app.logger.error(f"[HealthMonitor] Failed to restart restream: {restart_err}")
                                    meta["state"] = "Disconnected"
                                    status_payload[dest_id] = {"state": "Disconnected", "message": str(restart_err)}
                            else:
                                meta["state"] = "Error"
                                status_payload[dest_id] = {"state": "Error", "message": f"Exited with code {retcode} (Max retries exceeded)"}
                        else:
                            meta["state"] = "Running"
                            meta["retry_count"] = 0
                            status_payload[dest_id] = {"state": "Running", "message": ""}
                
                if status_payload:
                    try:
                        requests.post(
                            globalvars.apiLocation + "/apiv1/rtmp/restreamStatus",
                            json={"channelLoc": channel_loc, "status": status_payload},
                            timeout=5
                        )
                    except Exception as e:
                        app.logger.error(f"Failed to push restream status to core: {e}")
        except Exception as e:
            app.logger.error(f"[HealthMonitor] Error in monitor loop: {e}")
        time.sleep(10)

cleanup_stale_pids()
monitor = threading.Thread(target=restream_monitor_thread, daemon=True)
monitor.start()

# ----------------------------------------------------------------------------#
# Finalize App Init
# ----------------------------------------------------------------------------#
if __name__ == "__main__":
    app.run(Debug=config.debugMode)
