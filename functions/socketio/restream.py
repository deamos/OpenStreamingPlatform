from flask import abort, current_app
from flask_socketio import emit
from flask_security import current_user

from classes.shared import db, socketio
from classes import Channel

from functions import cachedDbCalls


@socketio.on("newRestream")
def newRestream(message):
    restreamChannel = message["restreamChannelID"]
    channelQuery = cachedDbCalls.getChannel(int(restreamChannel))
    if channelQuery is not None:
        if channelQuery.owningUser == current_user.id:
            restreamName = message["name"]
            restreamURL = message["restreamURL"]
            newRestreamObject = Channel.restreamDestinations(
                channelQuery.id, restreamName, restreamURL
            )

            db.session.add(newRestreamObject)
            db.session.commit()

            restreamQuery = Channel.restreamDestinations.query.filter_by(
                name=restreamName,
                url=restreamURL,
                channel=int(restreamChannel),
                enabled=False,
            ).with_entities(Channel.restreamDestinations.id).first()
            restreamID = restreamQuery.id

            emit(
                "newRestreamAck",
                {
                    "restreamName": restreamName,
                    "restreamURL": restreamURL,
                    "restreamID": str(restreamID),
                    "channelID": str(restreamChannel),
                },
                broadcast=False,
            )
        else:
            db.session.commit()
            db.session.close()
            return abort(401)
    else:
        db.session.commit()
        db.session.close()
        return abort(500)
    db.session.commit()
    db.session.close()
    return "OK"


@socketio.on("toggleRestream")
def toggleRestream(message):
    restreamID = message["id"]
    restreamQuery = (
        Channel.restreamDestinations.query
        .filter_by(id=int(restreamID))
        .with_entities(
            Channel.restreamDestinations.id,
            Channel.restreamDestinations.channel,
            Channel.restreamDestinations.enabled
            )
        .first()
    )
    if restreamQuery is not None:
        channelQuery = cachedDbCalls.getChannel(restreamQuery.channel)
        if channelQuery is not None:
            if channelQuery.owningUser == current_user.id:
                restreamUpdate = Channel.restreamDestinations.query.filter_by(id=int(restreamID)).update(dict(enabled=not restreamQuery.enabled))
                db.session.commit()
            else:
                db.session.commit()
                db.session.close()
                return abort(401)
        else:
            db.session.commit()
            db.session.close()
            return abort(500)
    else:
        db.session.commit()
        db.session.close()
        return abort(500)
    db.session.commit()
    db.session.close()
    return "OK"


@socketio.on("deleteRestream")
def deleteRestream(message):
    restreamID = message["id"]
    restreamQuery = (
        Channel.restreamDestinations.query
        .filter_by(id=int(restreamID))
        .with_entities(
            Channel.restreamDestinations.id,
            Channel.restreamDestinations.channel,
            Channel.restreamDestinations.enabled
            )
        .first()
    )
    if restreamQuery is not None:
        channelQuery = cachedDbCalls.getChannel(restreamQuery.channel)
        if channelQuery is not None:
            if channelQuery.owningUser == current_user.id:
                restreamUpdate = Channel.restreamDestinations.query.filter_by(id=int(restreamID)).delete()
                db.session.commit()
            else:
                db.session.commit()
                db.session.close()
                return abort(401)
        else:
            db.session.commit()
            db.session.close()
            return abort(500)
    else:
        db.session.commit()
        db.session.close()
        return abort(500)
    db.session.commit()
    db.session.close()
    return "OK"


@socketio.on("toggleLiveRestream")
def toggleLiveRestream(message):
    restreamID = message["id"]
    action = message["action"]  # "start" or "stop"
    restreamQuery = (
        Channel.restreamDestinations.query
        .filter_by(id=int(restreamID))
        .first()
    )
    if restreamQuery is not None:
        channelQuery = cachedDbCalls.getChannel(restreamQuery.channel)
        if channelQuery is not None:
            if channelQuery.owningUser == current_user.id:
                from classes import Stream
                from classes.settings import rtmpServer
                import requests

                activeStream = Stream.Stream.query.filter_by(linkedChannel=channelQuery.id, active=True).first()
                if activeStream is not None:
                    # Stream is live, send request to OSP-RTMP node
                    rtmp_node = rtmpServer.query.filter_by(id=activeStream.rtmpServer).first()
                    rtmp_address = rtmp_node.address if rtmp_node else "127.0.0.1"
                    
                    sysSettings = cachedDbCalls.getSystemSettings()
                    adaptive = sysSettings.adaptiveStreaming if sysSettings else False

                    url = f"http://{rtmp_address}:5099/restream/control"
                    payload = {
                        "channelLoc": channelQuery.channelLoc,
                        "restreamID": str(restreamQuery.id),
                        "restreamURL": restreamQuery.url,
                        "restreamName": restreamQuery.name,
                        "action": action,
                        "adaptive": adaptive
                    }
                    try:
                        resp = requests.post(url, json=payload, timeout=5)
                        if resp.status_code == 200:
                            new_state = (action == "start")
                            Channel.restreamDestinations.query.filter_by(id=int(restreamID)).update(dict(enabled=new_state))
                            db.session.commit()
                            emit("toggleLiveRestreamAck", {
                                "id": str(restreamID),
                                "status": "Running" if new_state else "Offline",
                                "enabled": new_state,
                                "success": True
                            })
                        else:
                            emit("toggleLiveRestreamAck", {
                                "id": str(restreamID),
                                "success": False,
                                "message": f"RTMP server error: {resp.text}"
                            })
                    except Exception as e:
                        emit("toggleLiveRestreamAck", {
                            "id": str(restreamID),
                            "success": False,
                            "message": f"Connection to RTMP server failed: {str(e)}"
                        })
                else:
                    # Stream is offline, just update default enabled state in DB
                    new_state = (action == "start")
                    Channel.restreamDestinations.query.filter_by(id=int(restreamID)).update(dict(enabled=new_state))
                    db.session.commit()
                    emit("toggleLiveRestreamAck", {
                        "id": str(restreamID),
                        "status": "Offline",
                        "enabled": new_state,
                        "success": True
                    })
            else:
                db.session.commit()
                db.session.close()
                return abort(401)
        else:
            db.session.commit()
            db.session.close()
            return abort(500)
    else:
        db.session.commit()
        db.session.close()
        return abort(500)
    db.session.commit()
    db.session.close()
    return "OK"
