from celery.canvas import subtask
from celery.result import AsyncResult

import datetime
import logging
import redis as redis_lib

from classes.shared import celery, db
from classes import Stream, Channel, Sec
from functions import xmpp, cachedDbCalls

log = logging.getLogger("app.functions.scheduler.channel_tasks")

# Redis key prefix used by connections.py for viewer counters.
# Full key pattern:  osp:viewers:<channelLoc>
VIEWER_KEY_PREFIX = "osp:viewers:"


def _get_redis():
    """Return a Redis client using the application config."""
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
        return redis_lib.Redis(
            host=config.redisHost, port=config.redisPort, decode_responses=True
        )
    return redis_lib.Redis(
        host=config.redisHost,
        port=config.redisPort,
        password=config.redisPassword,
        decode_responses=True,
    )


def setup_channel_tasks(sender, **kwargs):
    """Register periodic channel tasks with Celery Beat."""
    # Sync Redis viewer counters → DB every 30 seconds.
    sender.add_periodic_task(
        30.0,
        sync_viewer_counts_to_db.s(),
        name="Sync viewer counts from Redis to DB",
    )


@celery.task(bind=True)
def sync_viewer_counts_to_db(self):
    """
    Read all active-channel viewer counters from Redis and flush them to the DB.

    Viewer counts are incremented/decremented in Redis by connections.py on every
    SocketIO connect/disconnect event (O(1) Redis operation).  This task runs every
    30 s and is the *only* place that writes currentViewers to MariaDB, reducing
    DB write load from N-per-event to 1-per-30s-per-channel.

    Redis key format:  osp:viewers:<channelLoc>
    """
    r = _get_redis()

    # Find every active stream's channel location so we know which keys to sync.
    activeStreams = (
        Stream.Stream.query.filter_by(active=True, complete=False)
        .join(Channel.Channel, Channel.Channel.id == Stream.Stream.linkedChannel)
        .with_entities(
            Stream.Stream.id,
            Stream.Stream.linkedChannel,
            Channel.Channel.channelLoc,
        )
        .all()
    )

    if not activeStreams:
        return

    updated = 0
    for stream in activeStreams:
        key = VIEWER_KEY_PREFIX + stream.channelLoc
        raw = r.get(key)
        if raw is None:
            # No key yet — channel may not have had any viewers since last restart.
            # Treat as 0 rather than leaving a stale value in the DB.
            count = 0
        else:
            try:
                count = max(0, int(raw))
            except (ValueError, TypeError):
                count = 0

        Channel.Channel.query.filter_by(id=stream.linkedChannel).update(
            dict(currentViewers=count)
        )
        Stream.Stream.query.filter_by(id=stream.id).update(
            dict(currentViewers=count)
        )

        # Invalidate Flask-Cache so the updated count is visible immediately.
        cachedDbCalls.invalidateChannelCache(stream.linkedChannel)

        updated += 1

    db.session.commit()
    db.session.close()

    log.info("sync_viewer_counts_to_db: synced %d active channel(s) to DB.", updated)


# ---------------------------------------------------------------------------
# Legacy XMPP-based tasks — preserved but not scheduled.
# These queried ejabberd XML-RPC on every channel, which was slow and fragile.
# Superseded by the Redis-counter approach above.
# ---------------------------------------------------------------------------


@celery.task(bind=True)
def update_channel_counts(self):
    """
    [LEGACY — not scheduled] Poll ejabberd for viewer counts on all live streams.
    Superseded by sync_viewer_counts_to_db.
    """
    streamQuery = (
        Stream.Stream.query.filter_by(active=True)
        .with_entities(Stream.Stream.id, Stream.Stream.linkedChannel)
        .all()
    )
    liveStreamCount = 0
    for stream in streamQuery:
        liveStreamCount += 1
        subtask(
            "functions.scheduled_tasks.channel_tasks.update_channel_count",
            args=(stream.id, stream.linkedChannel),
        ).apply_async()
    log.info(
        "Scheduled Channel Update Performed on %d channels.", liveStreamCount
    )


@celery.task(bind=True)
def update_channel_count(self, streamId, channelId):
    """[LEGACY — not scheduled] Update a single channel's count from ejabberd."""
    channelQuery = cachedDbCalls.getChannel(channelId)
    if channelQuery is not None:
        count = xmpp.getChannelCounts(channelQuery.channelLoc)
        Channel.Channel.query.filter_by(id=channelQuery.id).update(
            dict(currentViewers=count)
        )
        Stream.Stream.query.filter_by(id=streamId).update(
            dict(currentViewers=count)
        )
        log.info(
            "Update Channel/Stream Live Counts: %s:%s to %d",
            channelQuery.channelLoc,
            streamId,
            count,
        )


@celery.task(bind=True)
def check_channel_stream_time(self, streamId):
    activeStreamQuery = (
        Stream.Stream.query.filter_by(id=streamId, active=True)
        .with_entities(
            Stream.Stream.id,
            Stream.Stream.linkedChannel,
            Stream.Stream.startTimestamp,
        )
        .first()
    )
    if activeStreamQuery is not None:
        channelId = activeStreamQuery.linkedChannel
        channelQuery = cachedDbCalls.getChannel(channelId)
        if channelQuery is not None:
            streamTime = datetime.datetime.utcnow() - activeStreamQuery.startTimestamp
            streamTimeMins = streamTime.total_seconds() / 60.0


@celery.task(bind=True)
def new_channel_assign_global_chat_mods(self, owner_id, channel_loc):
    for gcm_user in (
        Sec.Role.query.filter_by(name="GlobalChatMod")
        .one()
        .users.filter(Sec.User.id != owner_id)
        .with_entities(Sec.User.id, Sec.User.uuid)
        .all()
    ):
        xmpp.set_user_affiliation(gcm_user.uuid, channel_loc, "admin")


@celery.task(bind=True)
def add_new_global_chat_mod_to_channels(self, user_id, user_uuid):
    for channel in Channel.Channel.query.with_entities(
        Channel.Channel.owningUser,
        Channel.Channel.channelLoc,
    ).all():
        new_affiliation = "admin"
        if channel.owningUser == user_id:
            new_affiliation = "owner"
        xmpp.set_user_affiliation(user_uuid, channel.channelLoc, new_affiliation)


@celery.task(bind=True)
def remove_global_chat_mod_from_channels(self, user_id, user_uuid):
    for channel in Channel.Channel.query.with_entities(
        Channel.Channel.owningUser,
        Channel.Channel.channelLoc,
    ).all():
        new_affiliation = "member"
        if channel.owningUser == user_id:
            new_affiliation = "owner"
        xmpp.set_user_affiliation(user_uuid, channel.channelLoc, new_affiliation)