import logging
import redis as redis_lib

from flask_security import current_user
from flask_socketio import join_room, leave_room, emit

from classes.shared import db, socketio
from classes import Channel
from classes import Stream
from classes import views

from functions import templateFilters
from functions import xmpp
from functions import cachedDbCalls
from functions.scheduled_tasks import message_tasks

from functions.socketio.stream import handle_viewer_total_request

# Redis key prefix for viewer counts — must match channel_tasks.VIEWER_KEY_PREFIX.
# Full key: osp:viewers:<channelLoc>
_VIEWER_KEY_PREFIX = "osp:viewers:"

log = logging.getLogger("app.functions.socketio.connections")


def _get_redis():
    """Return a module-level Redis client (lazy-initialized)."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        from conf import config
    except Exception:
        import os

        class _C:
            redisHost = os.getenv("OSP_REDIS_HOST", "127.0.0.1")
            redisPort = int(os.getenv("OSP_REDIS_PORT", 6379))
            redisPassword = os.getenv("OSP_REDIS_PASSWORD", "")

        config = _C()

    if not config.redisPassword:
        _redis_client = redis_lib.Redis(
            host=config.redisHost, port=config.redisPort, decode_responses=True
        )
    else:
        _redis_client = redis_lib.Redis(
            host=config.redisHost,
            port=config.redisPort,
            password=config.redisPassword,
            decode_responses=True,
        )
    return _redis_client


_redis_client = None


def _incr_viewer(channelLoc: str) -> int:
    """
    Atomically increment the Redis viewer counter for a channel.
    Sets a 2-hour expiry so keys self-clean after a stream ends.
    Returns the new count.
    """
    r = _get_redis()
    key = _VIEWER_KEY_PREFIX + channelLoc
    count = r.incr(key)
    r.expire(key, 7200)  # 2-hour TTL — auto-cleans if stream ended unexpectedly
    return count


def _decr_viewer(channelLoc: str) -> int:
    """
    Atomically decrement the Redis viewer counter for a channel (floor 0).
    Returns the new count.
    """
    r = _get_redis()
    key = _VIEWER_KEY_PREFIX + channelLoc
    count = r.decr(key)
    if count < 0:
        r.set(key, 0)
        count = 0
    return count


def _get_viewer_count(channelLoc: str) -> int:
    """Read the current Redis viewer counter for a channel."""
    r = _get_redis()
    raw = r.get(_VIEWER_KEY_PREFIX + channelLoc)
    if raw is None:
        return 0
    try:
        return max(0, int(raw))
    except (ValueError, TypeError):
        return 0


@socketio.on("disconnect")
def disconnect():
    return "OK"


@socketio.on("newViewer")
def handle_new_viewer(streamData):
    channelLoc = str(streamData["data"])

    sysSettings = cachedDbCalls.getSystemSettings()
    requestedChannel = cachedDbCalls.getChannelByLoc(channelLoc)

    # Increment Redis counter — fast, atomic, no DB write.
    currentViewers = _incr_viewer(channelLoc)

    stream = (
        Stream.Stream.query.filter_by(active=True, streamKey=requestedChannel.streamKey)
        .with_entities(Stream.Stream.id, Stream.Stream.streamName, Stream.Stream.topic)
        .first()
    )

    streamName = stream.streamName if stream is not None else requestedChannel.channelName
    streamTopic = stream.topic if stream is not None else requestedChannel.topic

    if requestedChannel.imageLocation is None:
        channelImage = (
            sysSettings.siteProtocol
            + sysSettings.siteAddress
            + "/static/img/video-placeholder.jpg"
        )
    else:
        channelImage = (
            sysSettings.siteProtocol
            + sysSettings.siteAddress
            + "/images/"
            + requestedChannel.imageLocation
        )

    join_room(streamData["data"])

    # Build shared webhook payload to avoid duplicating the large dict twice.
    webhook_kwargs = dict(
        channelname=requestedChannel.channelName,
        channelurl=(
            sysSettings.siteProtocol
            + sysSettings.siteAddress
            + "/channel/"
            + str(requestedChannel.id)
        ),
        channeltopic=requestedChannel.topic,
        channelimage=channelImage,
        streamer=templateFilters.get_userName(requestedChannel.owningUser),
        channeldescription=str(requestedChannel.description),
        streamname=streamName,
        streamurl=(
            sysSettings.siteProtocol
            + sysSettings.siteAddress
            + "/view/"
            + requestedChannel.channelLoc
        ),
        streamtopic=templateFilters.get_topicName(streamTopic),
        streamimage=(
            sysSettings.siteProtocol
            + sysSettings.siteAddress
            + "/stream-thumb/"
            + requestedChannel.channelLoc
            + ".png"
        ),
    )

    if current_user.is_authenticated:
        pictureLocation = current_user.pictureLocation
        if pictureLocation is None:
            pictureLocation = "/static/img/user2.png"
        else:
            pictureLocation = "/images/" + pictureLocation
        webhook_kwargs["user"] = current_user.username
        webhook_kwargs["userpicture"] = (
            sysSettings.siteProtocol + sysSettings.siteAddress + str(pictureLocation)
        )
    else:
        webhook_kwargs["user"] = "Guest"
        webhook_kwargs["userpicture"] = (
            sysSettings.siteProtocol
            + sysSettings.siteAddress
            + "/static/img/user2.png"
        )

    message_tasks.send_webhook.delay(requestedChannel.id, 2, **webhook_kwargs)

    handle_viewer_total_request(streamData, room=streamData["data"])
    return "OK"


@socketio.on("addUserCount")
def handle_add_usercount(streamData):
    channelLoc = str(streamData["data"])

    requestedChannel = (
        Channel.Channel.query.filter_by(channelLoc=channelLoc)
        .with_entities(
            Channel.Channel.channelLoc,
            Channel.Channel.id,
            Channel.Channel.views,
            Channel.Channel.streamKey,
        )
        .first()
    )
    streamData = (
        Stream.Stream.query.filter_by(active=True, streamKey=requestedChannel.streamKey)
        .with_entities(Stream.Stream.id, Stream.Stream.totalViewers)
        .first()
    )

    # Increment the persistent total-views counter (this is historical, not live,
    # so it remains a direct DB write — it only fires once per unique viewing session).
    Channel.Channel.query.filter_by(channelLoc=channelLoc).update(
        dict(views=requestedChannel.views + 1)
    )

    if streamData is not None:
        Stream.Stream.query.filter_by(id=streamData.id).update(
            dict(totalViewers=streamData.totalViewers + 1)
        )

    db.session.commit()

    newView = views.views(0, requestedChannel.id)
    db.session.add(newView)
    db.session.commit()
    db.session.close()
    return "OK"


@socketio.on("removeViewer")
def handle_leaving_viewer(streamData):
    channelLoc = str(streamData["data"])

    requestedChannel = (
        Channel.Channel.query.filter_by(channelLoc=channelLoc)
        .with_entities(
            Channel.Channel.channelLoc,
            Channel.Channel.id,
            Channel.Channel.streamKey,
        )
        .first()
    )

    # Decrement Redis counter — fast, atomic, floored at 0.
    _decr_viewer(channelLoc)

    leave_room(streamData["data"])
    handle_viewer_total_request(streamData, room=streamData["data"])
    return "OK"


@socketio.on("openPopup")
def handle_new_popup_viewer(streamData):
    join_room(streamData["data"])
    return "OK"


@socketio.on("closePopup")
def handle_leaving_popup_viewer(streamData):
    leave_room(streamData["data"])
    return "OK"


@socketio.on("newVideoViewer")
def handle_new_video_viewer(videoData):
    join_room(videoData["data"])
    return "OK"


@socketio.on("removeVideoViewer")
def handle_leaving_video_viewer(videoData):
    leave_room(videoData["data"])
    return "OK"
