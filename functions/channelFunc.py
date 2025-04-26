import os
import shutil
import logging

from flask_security import current_user
from flask_socketio import emit

from classes.shared import db, socketio

from globals import globalvars

from classes.shared import db
from classes import Channel
from classes import RecordedVideo
from classes import panel
from classes import banList
from classes import upvotes
from classes import invites
from classes import subscriptions
from classes import webhook
from classes import stickers

from functions import videoFunc
from functions import cachedDbCalls
from functions import system

log = logging.getLogger("app.functions.channelFunctions")


def delete_channel(channelID: int) -> bool:

    channelQuery = Channel.Channel.query.filter_by(id=channelID).with_entities(
        Channel.Channel.id,
        Channel.Channel.channelLoc
    ).first()

    if channelQuery is None:
        db.session.close()
        return False

    try:
        panel.panelMapping.query.filter_by(
            panelType=2, panelLocationId=channelQuery.id
        ).delete()

        panel.channelPanel.query.filter_by(
            channelId=channelQuery.id
        ).delete()

        panel.globalPanel.query.filter_by(
            type=6, target=channelQuery.id
        ).delete()

        banList.chatBannedMessages.query.filter_by(
            channelLoc=channelQuery.channelLoc
        ).delete()

        banList.channelBanList.query.filter_by(
            channelLoc=channelQuery.channelLoc
        ).delete()

        clipQuery = RecordedVideo.Clip.query.filter_by(
            channelID=channelQuery.id
        ).with_entities(
            RecordedVideo.Clip.id
        ).all()

        for clip in clipQuery:
            videoFunc.deleteClip(clip.id)

        recordedVideoQuery = RecordedVideo.RecordedVideo.query.filter_by(
            channelID=channelQuery.id
        ).with_entities(
            RecordedVideo.RecordedVideo.id
        ).all()

        for vid in recordedVideoQuery:
            videoFunc.deleteVideo(vid.id)

        upvotes.channelUpvotes.query.filter_by(
            channelID=channelQuery.id
        ).delete()

        upvotes.streamUpvotes.query.filter_by(
            linkedChannel=channelQuery.id
        ).delete()

        invites.channelInviteCodes.query.filter_by(
            channelID=channelQuery.id
        ).delete()

        invites.invitedViewers.query.filter_by(
            channelID=channelQuery.id
        ).delete()

        subscriptions.channelSubs.query.filter_by(
            channelID=channelQuery.id
        ).delete()

        webhook.channelWebhooks.query.filter_by(
            channelID=channelQuery.id
        ).delete()

        stickers.stickers.query.filter_by(
            channelID=channelQuery.id
        ).delete()

        stickerFolder = os.path.join(globalvars.videoRoot, "images/stickers", channelQuery.channelLoc)
        if os.path.exists(stickerFolder):
            shutil.rmtree(stickerFolder)

        videosFolder = os.path.join(globalvars.videoRoot, "videos", channelQuery.channelLoc)
        if videosFolder != globalvars.videoRoot and os.path.exists(videosFolder):
            shutil.rmtree(videosFolder)

        from app import ejabberd

        ejabberd.destroy_room(
            channelQuery.channelLoc, "conference." + globalvars.defaultChatDomain
        )

        system.newLog(
            1,
            f"User {current_user.username} deleted Channel {channelQuery.id}",
        )

        cachedDbCalls.invalidateChannelCache(channelQuery.id)

        db.session.delete(channelQuery)
        db.session.commit()
    except Exception as e:
        log.error("Error in deleting Channel " + str(channelQuery.id) + ": " + str(e))
        db.session.close()
        return False

    db.session.close()
    return True


def broadcastEventStream(channelLoc: str, message: str) -> None:
    emit('eventStream', {'message': message}, namespace="ES_" + channelLoc, broadcast=True)
