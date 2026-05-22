import subprocess
import requests

from flask import Blueprint, request, redirect, current_app, abort
import threading

from globals import globalvars

rtmp_bp = Blueprint("rtmp", __name__)

def log_stream(stream, channel_loc, dest_name):
    for line in iter(stream.readline, b''):
        current_app.logger.warning(f"[Restream {channel_loc}->{dest_name}] {line.decode('utf-8', errors='replace').strip()}")
    stream.close()


@rtmp_bp.route("/auth-key", methods=["POST"])
def streamkey_check():

    key = request.form["name"]
    ipaddress = request.form["addr"]

    # Execute Stage 1 RTMP Authentication
    stage1Request = requests.post(
        globalvars.apiLocation + "/apiv1/rtmp/stage1",
        data={"name": key, "addr": ipaddress},
    )
    if stage1Request.status_code == 200:
        stage1Response = stage1Request.json()
        if stage1Response["results"]["success"] is True:
            channelLocation = stage1Response["results"]["channelLoc"]

            # Redirect based on API Response of Stream Type and Expected Stage 2 Handoff
            if stage1Response["results"]["type"] == "adaptive":
                return redirect(
                    "rtmp://127.0.0.1/stream-data-adapt/" + channelLocation, code=302
                )
            else:
                return redirect(
                    "rtmp://127.0.0.1/stream-data/" + channelLocation, code=302
                )
        else:
            returnMessage = stage1Response
            print(returnMessage)
            return abort(400)
    else:
        return abort(400)


@rtmp_bp.route("/auth-user", methods=["POST"])
def user_auth_check():
    key = request.form["name"]
    ipaddress = request.form["addr"]

    # Execute Stage 2 RTMP Authentication
    stage2Request = requests.post(
        globalvars.apiLocation + "/apiv1/rtmp/stage2",
        data={"name": key, "addr": ipaddress},
    )
    if stage2Request.status_code == 200:
        stage2Response = stage2Request.json()
        if stage2Response["results"]["success"] is True:

            channelLocation = stage2Response["results"]["channelLoc"]

            adaptiveState = stage2Response["results"]["adaptive"]
            if adaptiveState is True:
                inputLocation = (
                    "rtmp://127.0.0.1:1935/stream-data-adapt/" + channelLocation
                )
            else:
                inputLocation = "rtmp://127.0.0.1:1935/stream-data/" + channelLocation

            # Validate OSP's System Settings
            sysSettingsRequest = requests.get(globalvars.apiLocation + "/apiv1/server")
            if sysSettingsRequest.status_code == 200:
                sysSettingsResults = sysSettingsRequest.json()
            else:
                return abort(400)

            serverRestreamAllowed = False
            if "allowRestream" not in sysSettingsResults["results"]:
                serverRestreamAllowed = True
            elif sysSettingsResults["results"]["allowRestream"] is True:
                serverRestreamAllowed = True

            if serverRestreamAllowed is True:
                # Request a list of the Restream Destinations for a Channel via APIv1
                restreamDataRequest = requests.get(
                    globalvars.apiLocation
                    + "/apiv1/channel/"
                    + channelLocation
                    + "/restreams"
                )
                if restreamDataRequest.status_code == 200:
                    restreamDataResults = restreamDataRequest.json()
                    globalvars.restreamSubprocesses[channelLocation] = {}
                    r = globalvars.get_redis()

                    # Iterate Over Restream Destinations and Create ffmpeg Subprocess to Handle
                    for destination in restreamDataResults["results"]:
                        if destination["enabled"] is True:
                            max_bitrate = sysSettingsResults["results"].get("restreamMaxBitRate", 0)
                            if max_bitrate > 0:
                                cmd = [
                                    "/usr/bin/ffmpeg",
                                    "-i", inputLocation,
                                    "-c:v", "libx264",
                                    "-preset", "veryfast",
                                    "-maxrate", f"{max_bitrate}k",
                                    "-bufsize", f"{max_bitrate*2}k",
                                    "-c:a", "aac",
                                    "-b:a", "160k",
                                    "-ac", "2",
                                    "-f", "flv",
                                    destination["url"],
                                ]
                            else:
                                cmd = [
                                    "/usr/bin/ffmpeg",
                                    "-i", inputLocation,
                                    "-c:v", "copy",
                                    "-c:a", "copy",
                                    "-f", "flv",
                                    destination["url"],
                                ]
                            
                            p = subprocess.Popen(
                                cmd,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE,
                            )
                            globalvars.restreamSubprocesses[channelLocation][str(destination["id"])] = p
                            r.sadd(f"osp:rtmp:pids:{channelLocation}", str(p.pid))
                            
                            t = threading.Thread(target=log_stream, args=(p.stderr, channelLocation, destination["name"]), daemon=True)
                            t.start()
                else:
                    return abort(400)

            # Request List of OSP Edge Servers to Send a Restream To
            edgeNodeDataRequest = requests.get(
                globalvars.apiLocation + "/apiv1/server/edges"
            )
            if edgeNodeDataRequest.status_code == 200:
                edgeNodeDataResults = edgeNodeDataRequest.json()
                globalvars.edgeRestreamSubprocesses[channelLocation] = {}
                r = globalvars.get_redis()

                # Iterate Over Edge Node Results and Create ffmpeg Subprocess to Handle
                for node in edgeNodeDataResults["results"]:
                    if node["active"] is True:
                        if (
                            node["address"]
                            != sysSettingsResults["results"]["siteAddress"]
                        ):
                            subprocessConstructor = [
                                "/usr/bin/ffmpeg",
                                "-i",
                                inputLocation,
                                "-c",
                                "copy",
                            ]
                            subprocessConstructor.append("-f")
                            subprocessConstructor.append("flv")

                            # Sets Destination Endpoint based on System Adaptive Streaming Results
                            if (
                                sysSettingsResults["results"]["adaptiveStreaming"]
                                is True
                            ):
                                subprocessConstructor.append(
                                    "rtmp://"
                                    + node["address"]
                                    + "/edge-data-adapt/"
                                    + channelLocation
                                )
                            else:
                                subprocessConstructor.append(
                                    "rtmp://"
                                    + node["address"]
                                    + "/edge-data/"
                                    + channelLocation
                                )

                            p = subprocess.Popen(
                                subprocessConstructor,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE,
                            )
                            globalvars.edgeRestreamSubprocesses[channelLocation][str(node["id"])] = p
                            r.sadd(f"osp:rtmp:pids:{channelLocation}", str(p.pid))
                            
                            t = threading.Thread(target=log_stream, args=(p.stderr, channelLocation, f"Edge_{node['address']}"), daemon=True)
                            t.start()
                return "OK"
            else:
                return abort(400)
        else:
            return abort(400)
    else:
        return abort(400)


@rtmp_bp.route("/auth-record", methods=["POST"])
def record_auth_check():
    key = request.form["name"]

    # Execute Video Recording Start Check
    recStartRequest = requests.post(
        globalvars.apiLocation + "/apiv1/rtmp/reccheck", data={"name": key}
    )
    if recStartRequest.status_code == 200:
        recStartResponse = recStartRequest.json()
        if recStartResponse["results"]["success"] is True:
            return "OK"
    return abort(400)


@rtmp_bp.route("/deauth-user", methods=["POST"])
def user_deauth_check():

    key = request.form["name"]
    ipaddress = request.form["addr"]

    # Execute Stream Close Request
    streamCloseRequest = requests.post(
        globalvars.apiLocation + "/apiv1/rtmp/streamclose",
        data={"name": key, "addr": ipaddress},
    )
    if streamCloseRequest.status_code == 200:
        streamCloseResponse = streamCloseRequest.json()
        if streamCloseResponse["results"]["success"] is True:
            channelLocation = streamCloseResponse["results"]["channelLoc"]

            # End RTMP Restream Function
            if channelLocation in globalvars.restreamSubprocesses:
                for restream_id, restream in globalvars.restreamSubprocesses[channelLocation].items():
                    restream.kill()
                    try:
                        restream.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        restream.kill()
                        restream.wait(timeout=30)
            try:
                del globalvars.restreamSubprocesses[channelLocation]
            except KeyError:
                pass

            # End RTMP Edge Restreams
            if channelLocation in globalvars.edgeRestreamSubprocesses:
                for edge_id, p in globalvars.edgeRestreamSubprocesses[channelLocation].items():
                    p.kill()
                    try:
                        p.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        p.kill()
                        p.wait(timeout=30)
                try:
                    del globalvars.edgeRestreamSubprocesses[channelLocation]
                except KeyError:
                    pass
            
            # Clean up PIDs in Redis
            r = globalvars.get_redis()
            r.delete(f"osp:rtmp:pids:{channelLocation}")

            return "OK"
        else:
            return abort(400)
    return abort(400)


@rtmp_bp.route("/deauth-record", methods=["POST"])
def rec_Complete_handler():
    key = request.form["name"]
    path = request.form["path"]

    # Execute Recording Close Request
    recCloseRequest = requests.post(
        globalvars.apiLocation + "/apiv1/rtmp/recclose",
        data={"name": key, "path": path},
    )
    if recCloseRequest.status_code == 200:
        recCloseResponse = recCloseRequest.json()
        if recCloseResponse["results"]["success"] is True:
            channelLocation = recCloseResponse["results"]["channelLoc"]
            return "OK"
        else:
            abort(400)
    else:
        abort(400)

@rtmp_bp.route("/closeStream", methods=["POST"])
def stream_force_close():
    key = request.form["name"]
    if key != None and key.strip() != "":
        dropRequest = requests.get(f"http://127.0.0.1:9000/control/client?app=stream&name={key}")
        return "OK"
    else:
        abort(400)

@rtmp_bp.route("/restream/control", methods=["POST"])
def restream_control():
    data = request.get_json()
    if not data:
        return abort(400, "Missing JSON payload")
    
    channelLocation = data.get("channelLoc")
    restreamID = str(data.get("restreamID"))
    restreamURL = data.get("restreamURL")
    restreamName = data.get("restreamName", "Restream")
    action = data.get("action")
    adaptive = data.get("adaptive", False)
    
    if not all([channelLocation, restreamID, restreamURL, action]):
        return abort(400, "Missing required parameters")
    
    r = globalvars.get_redis()
    
    if action == "start":
        sysSettingsRequest = requests.get(globalvars.apiLocation + "/apiv1/server")
        if sysSettingsRequest.status_code == 200:
            sysSettingsResults = sysSettingsRequest.json()
        else:
            return abort(500, "Unable to reach OSP-Core API")
            
        serverRestreamAllowed = False
        if "allowRestream" not in sysSettingsResults["results"]:
            serverRestreamAllowed = True
        elif sysSettingsResults["results"]["allowRestream"] is True:
            serverRestreamAllowed = True
            
        if not serverRestreamAllowed:
            return abort(403, "Restreaming is disabled by server administrator")
            
        if adaptive is True:
            inputLocation = "rtmp://127.0.0.1:1935/stream-data-adapt/" + channelLocation
        else:
            inputLocation = "rtmp://127.0.0.1:1935/stream-data/" + channelLocation
            
        if channelLocation not in globalvars.restreamSubprocesses:
            globalvars.restreamSubprocesses[channelLocation] = {}
            
        if restreamID in globalvars.restreamSubprocesses[channelLocation]:
            return {"results": {"success": True, "message": "Already running"}}
            
        max_bitrate = sysSettingsResults["results"].get("restreamMaxBitRate", 0)
        if max_bitrate > 0:
            cmd = [
                "/usr/bin/ffmpeg",
                "-i", inputLocation,
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-maxrate", f"{max_bitrate}k",
                "-bufsize", f"{max_bitrate*2}k",
                "-c:a", "aac",
                "-b:a", "160k",
                "-ac", "2",
                "-f", "flv",
                restreamURL,
            ]
        else:
            cmd = [
                "/usr/bin/ffmpeg",
                "-i", inputLocation,
                "-c:v", "copy",
                "-c:a", "copy",
                "-f", "flv",
                restreamURL,
            ]
            
        p = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        globalvars.restreamSubprocesses[channelLocation][restreamID] = p
        r.sadd(f"osp:rtmp:pids:{channelLocation}", str(p.pid))
        
        t = threading.Thread(target=log_stream, args=(p.stderr, channelLocation, restreamName), daemon=True)
        t.start()
        
        return {"results": {"success": True, "message": "Restream started"}}
        
    elif action == "stop":
        if channelLocation in globalvars.restreamSubprocesses and restreamID in globalvars.restreamSubprocesses[channelLocation]:
            p = globalvars.restreamSubprocesses[channelLocation][restreamID]
            p.kill()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=5)
            
            r.srem(f"osp:rtmp:pids:{channelLocation}", str(p.pid))
            
            try:
                del globalvars.restreamSubprocesses[channelLocation][restreamID]
            except KeyError:
                pass
            return {"results": {"success": True, "message": "Restream stopped"}}
        else:
            return {"results": {"success": True, "message": "Restream not running"}}
            
    return abort(400, "Invalid action")