from functools import cache
from flask import abort
from flask_security import current_user

from classes.shared import db, socketio
from classes import RecordedVideo
from classes import settings
from classes import notifications
from classes import subscriptions
from classes import comments
from classes import upvotes

from functions import system
from functions import webhookFunc
from functions import templateFilters
from functions import videoFunc
from functions import subsFunc
from functions import cachedDbCalls
from functions.scheduled_tasks import video_tasks, message_tasks

from app import r


@socketio.on("deleteVideo")
def deleteVideoSocketIO(message):
    if current_user.is_authenticated:
        videoID = int(message["videoID"])
        videoQuery = cachedDbCalls.getVideo(videoID)
        if videoQuery.owningUser == current_user.id:
            video_tasks.delete_video.delay(videoID)
            db.session.commit()
            db.session.close()
            return "OK"
    db.session.commit()
    db.session.close()
    return abort(401)


@socketio.on("editVideo")
def editVideoSocketIO(message):
    if current_user.is_authenticated:
        videoID = int(message["videoID"])
        videoName = system.strip_html(message["videoName"])
        videoTopic = int(message["videoTopic"])
        videoDescription = message["videoDescription"]
        videoAllowComments = False
        if str(message["videoAllowComments"]).upper() == "TRUE":
            videoAllowComments = True
        videoQuery = cachedDbCalls.getVideo(videoID)
        if videoQuery is not None:
            if (
                current_user.has_role("Admin")
                or videoQuery.owningUser == current_user.id
            ):
                if "videoTags" in message:
                    videoTagString = message["videoTags"]
                    tagArray = system.parseTags(videoTagString)
                    existingTagArray = RecordedVideo.video_tags.query.filter_by(
                        videoID=videoID
                    ).all()

                    for currentTag in existingTagArray:
                        if currentTag.name not in tagArray:
                            db.session.delete(currentTag)
                        else:
                            tagArray.remove(currentTag.name)
                    db.session.commit()
                    for currentTag in tagArray:
                        newTag = RecordedVideo.video_tags(
                            currentTag, videoID, current_user.id
                        )
                        db.session.add(newTag)
                        db.session.commit()

                result = videoFunc.changeVideoMetadata(
                    videoID, videoName, videoTopic, videoDescription, videoAllowComments
                )
                if result is True:
                    db.session.commit()
                    db.session.close()
                    return "OK"
                else:
                    db.session.commit()
                    db.session.close()
                    return abort(500)
            else:
                db.session.commit()
                db.session.close()
                return abort(403)
        else:
            db.session.commit()
            db.session.close()
            return abort(500)
    else:
        db.session.commit()
        db.session.close()
        return abort(401)


@socketio.on("createClip")
def createclipSocketIO(message):
    if current_user.is_authenticated:
        videoID = int(message["videoID"])
        clipName = system.strip_html(message["clipName"])
        clipDescription = message["clipDescription"]
        startTime = float(message["clipStart"])
        stopTime = float(message["clipStop"])
        videoQuery = cachedDbCalls.getVideo(videoID)
        if videoQuery.owningUser == current_user.id:
            video_tasks.create_video_clip.delay(
                videoID, startTime, stopTime, clipName, clipDescription
            )
            db.session.commit()
            db.session.close()
            return "OK"
        else:
            db.session.commit()
            db.session.close()
            return abort(401)


@socketio.on("moveVideo")
def moveVideoSocketIO(message):
    if current_user.is_authenticated:
        videoID = int(message["videoID"])
        newChannel = int(message["destinationChannel"])

        result = videoFunc.moveVideo(videoID, newChannel)
        if result is True:
            db.session.commit()
            db.session.close()
            return "OK"
        else:
            db.session.commit()
            db.session.close()
            return abort(500)
    else:
        db.session.commit()
        db.session.close()
        return abort(401)


@socketio.on("togglePublished")
def togglePublishedSocketIO(message):
    sysSettings = cachedDbCalls.getSystemSettings()
    if current_user.is_authenticated:
        videoID = int(message["videoID"])
        videoQuery = RecordedVideo.RecordedVideo.query.filter_by(
            owningUser=current_user.id, id=videoID
        ).with_entities(
            RecordedVideo.RecordedVideo.id,
            RecordedVideo.RecordedVideo.published
        ).first()
        if videoQuery is not None:

            newState = not videoQuery.published
            RecordedVideo.RecordedVideo.query.filter_by(id=videoQuery.id).update(dict(published=newState))
            db.session.commit()
            
            cache.delete_memoized(cachedDbCalls.getVideo, videoQuery.id)
            cache.delete_memoized(cachedDbCalls.getChannelVideos, videoQuery.channel.id)
            cache.delete_memoized(cachedDbCalls.getAllVideo_View, videoQuery.channelID)
            cache.delete_memoized(cachedDbCalls.getAllVideoByOwnerId, videoQuery.owningUser)
            cache.delete_memoized(cachedDbCalls.getAllVideo)

            videoQuery = cachedDbCalls.getVideo(videoQuery.id)

            if videoQuery.channel.imageLocation is None:
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
                    + videoQuery.channel.imageLocation
                )

            if newState is True:

                # ActivityPub: Publish video to ActivityPub when published
                try:
                    from conf import config
                    if getattr(config, 'activitypubEnabled', False):
                        from functions.activitypub import get_activitypub_service
                        service = get_activitypub_service()
                        if service:
                            # Get the channel owner (user)
                            user = cachedDbCalls.getUser(videoQuery.channel.owningUser)
                            if user:
                                actor = service.create_user_actor(user)
                                if actor:
                                    ap_video_obj, note_obj = service.create_video_object(videoQuery, actor)
                                    if ap_video_obj:
                                        service.send_activity("Create", actor, object_data=ap_video_obj.object_data)
                                    if note_obj and getattr(config, 'activitypubCreateNotes', False):
                                        service.send_activity("Create", actor, object_data=note_obj)
                except Exception as e:
                    import logging
                    log = logging.getLogger(__name__)
                    log.warning(f"ActivityPub: Failed to publish video {videoQuery.id} to ActivityPub: {e}")

                message_tasks.send_webhook.delay(
                    videoQuery.channel.id,
                    6,
                    channelname=videoQuery.channel.channelName,
                    channelurl=(
                        sysSettings.siteProtocol
                        + sysSettings.siteAddress
                        + "/channel/"
                        + str(videoQuery.channel.id)
                    ),
                    channeltopic=templateFilters.get_topicName(
                        videoQuery.channel.topic
                    ),
                    channelimage=channelImage,
                    streamer=templateFilters.get_userName(
                        videoQuery.channel.owningUser
                    ),
                    channeldescription=str(videoQuery.channel.description),
                    videoname=videoQuery.channelName,
                    videodate=videoQuery.videoDate,
                    videodescription=str(videoQuery.description),
                    videotopic=templateFilters.get_topicName(videoQuery.topic),
                    videourl=(
                        sysSettings.siteProtocol
                        + sysSettings.siteAddress
                        + "/play/"
                        + str(videoQuery.id)
                    ),
                    videothumbnail=(
                        sysSettings.siteProtocol
                        + sysSettings.siteAddress
                        + "/videos/"
                        + str(videoQuery.thumbnailLocation)
                    ),
                )

                subscriptionQuery = subscriptions.channelSubs.query.filter_by(
                    channelID=videoQuery.channel.id
                ).all()
                for sub in subscriptionQuery:
                    # Create Notification for Channel Subs
                    newNotification = notifications.userNotification(
                        templateFilters.get_userName(videoQuery.channel.owningUser)
                        + " has posted a new video to "
                        + videoQuery.channel.channelName
                        + " titled "
                        + videoQuery.channelName,
                        "/play/" + str(videoQuery.id),
                        "/images/" + str(videoQuery.channel.owner.pictureLocation),
                        sub.userID,
                    )
                    db.session.add(newNotification)
                db.session.commit()

                subsFunc.processSubscriptions(
                    videoQuery.channel.id,
                    sysSettings.siteName
                    + " - "
                    + videoQuery.channel.channelName
                    + " has posted a new video",
                    "<html><body><img src='"
                    + sysSettings.siteProtocol
                    + sysSettings.siteAddress
                    + sysSettings.systemLogo
                    + "'><p>Channel "
                    + videoQuery.channel.channelName
                    + " has posted a new video titled <u>"
                    + videoQuery.channelName
                    + "</u> to the channel.</p><p>Click this link to watch<br><a href='"
                    + sysSettings.siteProtocol
                    + sysSettings.siteAddress
                    + "/play/"
                    + str(videoQuery.id)
                    + "'>"
                    + videoQuery.channelName
                    + "</a></p>",
                    "video",
                )

            db.session.commit()
            db.session.close()
            return "OK"
        else:
            db.session.commit()
            db.session.close()
            return abort(500)
    else:
        db.session.commit()
        db.session.close()
        return abort(401)


@socketio.on("togglePublishedClip")
def togglePublishedClipSocketIO(message):
    if current_user.is_authenticated:
        clipID = int(message["clipID"])
        clipQuery = RecordedVideo.Clips.query.filter_by(id=clipID).first()

        if (
            clipQuery is not None
            and current_user.id == clipQuery.owningUser
        ):
            newState = not clipQuery.published
            clipQuery.published = newState

            if newState is True:

                subscriptionQuery = subscriptions.channelSubs.query.filter_by(
                    channelID=clipQuery.channelID
                ).all()
                for sub in subscriptionQuery:
                    # Create Notification for Channel Subs
                    newNotification = notifications.userNotification(
                        templateFilters.get_userName(clipQuery.owningUser)
                        + " has posted a new clip to "
                        + clipQuery.channel.channelName
                        + " titled "
                        + clipQuery.clipName,
                        "/clip/" + str(clipQuery.id),
                        "/images/"
                        + str(clipQuery.owner.pictureLocation),
                        sub.userID,
                    )
                    db.session.add(newNotification)
            db.session.commit()
            db.session.close()
            return "OK"
        else:
            db.session.commit()
            db.session.close()
            return abort(500)
    else:
        db.session.commit()
        db.session.close()
        return abort(401)


@socketio.on("editClip")
def changeClipMetadataSocketIO(message):
    if current_user.is_authenticated:
        clipID = int(message["clipID"])
        clipName = message["clipName"]
        clipTopic = int(message["clipTopic"])
        clipDescription = message["clipDescription"]

        clipTags = None
        if "clipTags" in message:
            clipTags = message["clipTags"]

        result = videoFunc.changeClipMetadata(
            clipID, clipName, clipTopic, clipDescription, clipTags
        )

        if result is True:
            db.session.commit()
            db.session.close()
            return "OK"
        else:
            db.session.commit()
            db.session.close()
            return abort(500)
    else:
        db.session.commit()
        db.session.close()
        return abort(401)


@socketio.on("deleteClip")
def deleteClipSocketIO(message):
    if current_user.is_authenticated:
        clipID = int(message["clipID"])
        clipQuery = RecordedVideo.Clips.query.filter_by(id=clipID).first()
        if clipQuery.owningUser == current_user.id:
            video_tasks.delete_video_clip.delay(clipID)
            db.session.commit()
            db.session.close()
            return "OK"
        else:
            db.session.commit()
            db.session.close()
            return abort(401)
    else:
        db.session.commit()
        db.session.close()
        return abort(401)


@socketio.on("newVideoComment")
def newVideoCommentSocketIO(message):
    sysSettings = cachedDbCalls.getSystemSettings()
    
    if current_user.is_authenticated:
        videoID = int(message["videoID"])
        comment = system.strip_html(message["commentText"])
        currentUser = current_user.id

        recordedVid = cachedDbCalls.getVideo(videoID)
        if recordedVid is not None:
            if len(comment) > 2048:
                comment = comment[:2048]

            newComment = comments.videoComments(currentUser, comment, recordedVid.id)
            db.session.add(newComment)
            db.session.commit()

            channelQuery = cachedDbCalls.getChannel(recordedVid.channelID)
            if channelQuery.imageLocation is None:
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
                    + channelQuery.imageLocation
                )

            pictureLocation = ""
            if current_user.pictureLocation is None:
                pictureLocation = "/static/img/user2.png"
            else:
                pictureLocation = "/images/" + str(current_user.pictureLocation)

            newNotification = notifications.userNotification(
                templateFilters.get_userName(current_user.id)
                + " commented on your video - "
                + recordedVid.channelName,
                "/play/" + str(recordedVid.id),
                pictureLocation,
                recordedVid.owningUser,
            )
            db.session.add(newNotification)
            db.session.commit()

            message_tasks.send_webhook.delay(
                channelQuery.id,
                7,
                channelname=channelQuery.channelName,
                channelurl=(
                    sysSettings.siteProtocol
                    + sysSettings.siteAddress
                    + "/channel/"
                    + str(channelQuery.id)
                ),
                channeltopic=templateFilters.get_topicName(channelQuery.topic),
                channelimage=channelImage,
                streamer=templateFilters.get_userName(channelQuery.owningUser),
                channeldescription=str(channelQuery.description),
                videoname=recordedVid.channelName,
                videodate=recordedVid.videoDate,
                videodescription=recordedVid.description,
                videotopic=templateFilters.get_topicName(recordedVid.topic),
                videourl=(
                    sysSettings.siteProtocol
                    + sysSettings.siteAddress
                    + "/videos/"
                    + str(recordedVid.videoLocation)
                ),
                videothumbnail=(
                    sysSettings.siteProtocol
                    + sysSettings.siteAddress
                    + "/videos/"
                    + str(recordedVid.thumbnailLocation)
                ),
                user=current_user.username,
                userpicture=(
                    sysSettings.siteProtocol
                    + sysSettings.siteAddress
                    + str(pictureLocation)
                ),
                comment=comment,
            )
            
            system.newLog(
                4,
                "Video Comment Added by "
                + current_user.username
                + " to Video ID #"
                + str(recordedVid.id),
            )
            
            import jinja2

            # Render the comment HTML to broadcast
            from render import render_template
            
            try:
                from flask import current_app
                with current_app.app_context():
                    # We can't easily render a macro directly from outside a template, 
                    # so we will construct a dictionary representing the comment to send to the client
                    comment_data = {
                        "id": newComment.id,
                        "userID": current_user.id,
                        "userPicture": pictureLocation,
                        "userName": current_user.username,
                        "date": templateFilters.normalize_date(newComment.timestamp),
                        "comment": comment,
                        "upvotes": 0,
                    }
                    socketio.emit('newVideoCommentData', {'comment': comment_data}, room='video-' + str(recordedVid.id))
            except Exception as e:
                import logging
                import traceback
                log = logging.getLogger(__name__)
                log.error("SocketIO Comment render emit error: " + str(e))
                with open("socket_error.log", "w") as f:
                    f.write(traceback.format_exc())
                pass

        db.session.commit()
        db.session.close()
        return "OK"
    db.session.commit()
    db.session.close()
    return abort(401)


@socketio.on("deleteVideoComment")
def deleteVideoCommentSocketIO(message):
    if current_user.is_authenticated:
        commentID = int(message["commentID"])
        commentQuery = comments.videoComments.query.filter_by(id=commentID).first()
        if commentQuery is not None:
            recordedVid = cachedDbCalls.getVideo(commentQuery.videoID)
            if (
                current_user.has_role("Admin")
                or recordedVid.owningUser == current_user.id
                or commentQuery.userID == current_user.id
            ):
                videoID = recordedVid.id
                upvoteQuery = upvotes.commentUpvotes.query.filter_by(
                    commentID=commentQuery.id
                ).all()
                for vote in upvoteQuery:
                    db.session.delete(vote)
                db.session.delete(commentQuery)
                db.session.commit()
                system.newLog(
                    4,
                    "Video Comment Deleted by "
                    + current_user.username
                    + " to Video ID #"
                    + str(recordedVid.id),
                )
                
                socketio.emit('deleteVideoCommentData', {'commentID': commentID}, room='video-' + str(videoID))
        db.session.commit()
        db.session.close()
        return "OK"
    db.session.commit()
    db.session.close()
    return abort(401)
