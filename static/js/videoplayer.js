// Socket.IO Connection
var conn_options = { 'sync disconnect on unload': true };
var socket = io();

var easymdeVideoEditor = new EasyMDE({ autoDownloadFontAwesome: false, spellChecker: false, element: document.getElementById("description") });

socket.on('connect', function () {
    console.log('Connected to SocketIO');
    socket.emit('getUpvoteTotal', { loc: videoID, vidType: 'video' });
    socket.emit('newVideoViewer', { data: "video-" + videoID });
});

window.addEventListener('beforeunload', function () {
    socket.emit('removeVideoViewer', { data: "video-" + videoID });
});

setInterval(function () {
    socket.emit('getUpvoteTotal', { loc: videoID, vidType: 'video' });
}, 30000);

socket.on('upvoteTotalResponse', function (msg) {
    if (msg['type'] === 'video') {
        upvoteDivID = 'totalUpvotes';
        upvoteIconID = 'upVoteIcon';
        upvoteButtonID = 'upvoteButton';
    } else if (msg['type'] === 'comment') {
        upvoteDivID = 'upvoteTotalComments-' + msg['loc'];
        upvoteIconID = 'commentUpvoteIcon-' + msg['loc'];
        upvoteButtonID = 'commentUpvoteButton-' + msg['loc'];
    }

    document.getElementById(upvoteDivID).innerHTML = msg['totalUpvotes'];

    if (msg['myUpvote'] === 'True') {
        if (document.getElementById(upvoteIconID).classList.contains('far')) {
            document.getElementById(upvoteIconID).classList.remove('far');
            document.getElementById(upvoteIconID).classList.add('fas');
        }
        if (document.getElementById(upvoteButtonID).classList.contains('btn-outline-success')) {
            document.getElementById(upvoteButtonID).classList.remove('btn-outline-success');
            document.getElementById(upvoteButtonID).classList.add('btn-success');
        }
    } else if (msg['myUpvote'] === 'False') {
        if (document.getElementById(upvoteIconID).classList.contains('fas')) {
            document.getElementById(upvoteIconID).classList.remove('fas');
            document.getElementById(upvoteIconID).classList.add('far');
        }
        if (document.getElementById(upvoteButtonID).classList.contains('btn-success')) {
            document.getElementById(upvoteButtonID).classList.remove('btn-success');
            document.getElementById(upvoteButtonID).classList.add('btn-outline-success');
        }
    }
});

socket.on('sendChanSubResults', function (msg) {
    var subButton = document.getElementById('chanSubStateButton');
    if (msg['state'] === true) {
        subButton.innerHTML = "<i class='fas fa-star'></i><span class='d-none d-sm-none d-md-inline'> Unsubscribe</span>";
        subButton.className = "btn boxshadow btn-success";
    } else {
        subButton.innerHTML = "<i class='far fa-star'></i><span class='d-none d-sm-none d-md-inline'> Subscribe</span>";
        subButton.className = "btn boxshadow btn-outline-success";
    }
});

function secondsToTimeHMS(seconds) {
    var secondString = (seconds % 60).toString().padStart(2, '0');
    if (seconds < 60) {
        return `0:00:${secondString}`;
    }

    var minuteString = (Math.floor(seconds / 60) % 60).toString().padStart(2, '0');
    if (seconds < 3600) {
        return `0:${minuteString}:${secondString}`;
    }

    var hourString = Math.floor(seconds / 3600).toString();
    return `${hourString}:${minuteString}:${secondString}`;
}

function changeUpvote(type, id) {
    socket.emit('changeUpvote', { loc: id, vidType: type });
}

function toggleChannelSub(chanID) {
    socket.emit('toggleChannelSubscription', { channelID: chanID });
}

socket.on('checkScreenShot', function (msg) {
    console.log('Received New Thumbnail');
    document.getElementById('screenshotPendingBox').style.display = "none";
    document.getElementById('screenshotImageBox').style.display = "block";
    document.getElementById("newScreenShotImg").src = msg['thumbnailLocation'];
    document.getElementById('newScreenShotSetThumbButton').disabled = false;
});

function toggleShareTimestamp(requestURL, startTime) {
    if (document.getElementById('shareTimestamp').checked) {
        document.getElementById('embedURLInput').value = '<iframe src="' + requestURL + '?embedded=True&autoplay=True&startTime='.replace('?startTime=' + startTime, '') + player.currentTime() + '" width=600 height=345></iframe>';
        document.getElementById('linkShareInput').value = requestURL.replace('?startTime=' + startTime, '') + '?startTime=' + player.currentTime();
    } else {
        document.getElementById('embedURLInput').value = '<iframe src="' + requestURL + '?embedded=True&autoplay=True" width=600 height=345></iframe>'.replace('?startTime=' + startTime, '');
        document.getElementById('linkShareInput').value = requestURL.replace('?startTime=' + startTime, '');
    }
}

function newThumbnailRequest() {
    player.pause();
    window.whereYouAt = player.currentTime();
    document.getElementById("thumbnailTimestamp").value = window.whereYouAt;
    socket.emit('newScreenShot', { loc: videoID, timeStamp: window.whereYouAt });
    document.getElementById('screenshotPendingBox').style.display = "block";
    document.getElementById('screenshotImageBox').style.display = "none";
    document.getElementById('newScreenShotSetThumbButton').disabled = true;
    openModal('newSSModal');
}

function setNewThumbnail() {
    var timestamp = document.getElementById("thumbnailTimestamp").value;
    socket.emit('setScreenShot', { loc: videoID, timeStamp: timestamp });
    createNewBSAlert("New Thumbnail Set", "success")
    document.getElementById('screenshotPendingBox').style.display = "block";
    document.getElementById('screenshotImageBox').style.display = "none";
    document.getElementById('newScreenShotSetThumbButton').disabled = true;
}


function openClipModal() {
    player.pause();
    var playerCurrentTime = player.currentTime();
    clipplayer.currentTime(playerCurrentTime);

    var startInput = document.getElementById('clipStartTime');
    startInput.value = null;

    var stopInput = document.getElementById('clipStopTime');
    stopInput.value = null;

    var clipDescriptionInput = document.getElementById('clipDescription');
    clipDescriptionInput.value = null;

    var clipCurrentLengthSpan = document.getElementById('clipCurrentLength');
    clipCurrentLengthSpan.innerText = null;

    var clipErrorDiv = document.getElementById('clipError');
    clipErrorDiv.innerHTML = "";
    clipErrorDiv.style.display = "none";

    var clipMaxLengthSpan = document.getElementById('clipMaxLength');
    if (maxClipLength > 300) {
        clipMaxLengthSpan.innerText = 'Infinite';
    } else {
        clipMaxLengthSpan.innerText = secondsToTimeHMS(maxClipLength);
    }

    $("#clipModal").modal('show');
}

function clipStartGoTo() {
    var startInputValue = parseInt(document.getElementById('clipStartTime').value);
    if (isNaN(startInputValue)) return;
    clipplayer.currentTime(startInputValue);
}

function clipStopGoTo() {
    var stopInputValue = parseInt(document.getElementById('clipStopTime').value);
    if (isNaN(stopInputValue)) return;
    clipplayer.currentTime(stopInputValue);
}

function setClipStart() {
    var startInput = document.getElementById('clipStartTime');
    startInput.value = parseInt(clipplayer.currentTime());
    checkClipConstraints();
}

function setClipStop() {
    var stopInput = document.getElementById('clipStopTime');
    stopInput.value = parseInt(clipplayer.currentTime());
    checkClipConstraints();
}

function checkClipConstraints() {
    var startTime = parseInt(document.getElementById('clipStartTime').value);
    var stopTime = parseInt(document.getElementById('clipStopTime').value);
    var systemMaxClipLength = maxClipLength;
    var clipErrorDiv = document.getElementById('clipError');
    var clipSubmitButton = document.getElementById('clipSubmitButton');

    var clipCurrentLengthSpan = document.getElementById('clipCurrentLength');

    if (isNaN(startTime) || isNaN(stopTime)) {
        clipErrorDiv.innerHTML = "";
        clipErrorDiv.style.display = "none";
        clipSubmitButton.disabled = true;
        clipCurrentLengthSpan.innerText = '';
        return;
    }

    try {
        if (startTime >= stopTime) {
            clipCurrentLengthSpan.innerText = '';
            throw new Error("Start Time must be less than End Time");
        }

        var clipLength = stopTime - startTime;
        clipCurrentLengthSpan.innerText = secondsToTimeHMS(clipLength);
        if (systemMaxClipLength < 301) {
            if (clipLength > systemMaxClipLength) {
                throw new Error(`Clip is longer than the maximum allowed length of ${secondsToTimeHMS(systemMaxClipLength)}!`);
            }
        }

        clipErrorDiv.innerHTML = "";
        clipErrorDiv.style.display = "none";
        clipSubmitButton.disabled = false;
    } catch (err) {
        clipErrorDiv.innerHTML = err.message;
        clipErrorDiv.style.display = "block";
        clipSubmitButton.disabled = true;
    }
}

function createClip() {
    clipplayer.pause();
    var videoID = document.getElementById('clipvideoID').value;
    var clipName = document.getElementById('clipName').value;
    var clipDescription = document.getElementById('clipDescription').value;
    var clipStart = document.getElementById('clipStartTime').value;
    var clipStop = document.getElementById('clipStopTime').value;

    socket.emit('createClip', { videoID: videoID, clipName: clipName, clipDescription: clipDescription, clipStart: clipStart, clipStop: clipStop });
    createNewBSAlert("Clip Queued for Creation", "Success");
}

function hideComments() {
    var commentsDiv = document.getElementById('commentsPanel');
    var contentsDiv = document.getElementById('mainContentPanel');
    commentsDiv.style.display = 'none';
    contentsDiv.className = 'col-9 mx-auto';
}

function submitVideoComment(videoID) {
    var commentText = easymde_Comments.value();
    if (commentText.trim() === "") {
        return;
    }
    socket.emit('newVideoComment', { videoID: videoID, commentText: commentText });
    easymde_Comments.value("");
}

socket.on('newVideoCommentData', function (msg) {
    var comment = msg.comment;

    var emptyMessage = document.getElementById('emptyCommentsMessage');
    if (emptyMessage) {
        emptyMessage.style.display = 'none';
    }

    var commentHTML = `
    <div id="vidComment-${comment.id}" class="row mb-3 video-comment border-bottom pb-3">
        <div class="col-auto">
            <a href="/streamer/${comment.userID}">
                <img class="rounded-circle shadow" style="width: 44px; height: 44px; object-fit: cover;" src="${comment.userPicture}" onerror="this.src='/static/img/user2.png';">
            </a>
        </div>
        <div class="col px-0">
            <div class="d-flex justify-content-between align-items-baseline mb-1">
                <div>
                    <a href="/streamer/${comment.userID}" class="fw-bold text-decoration-none text-body">${comment.userName}</a>
                    <span class="text-secondary small ms-2">${comment.date}</span>
                </div>
                <!-- Controls Placeholder - Real page refresh required for full ownership verification currently, but appending UI handles immediate display -->
                <button type="button" class="btn btn-sm text-danger ms-2 p-0" title="Delete Comment" onclick="confirmDeleteComment(${comment.id});">
                    <i class="fas fa-trash-alt"></i>
                </button>
            </div>
            <div class="comment-text mb-2 text-wrap text-break" style="font-size: 15px;">
                ${comment.comment}
            </div>
            <div class="d-flex align-items-center gap-3">
                <button id="commentUpvoteButton-${comment.id}" type="button" class="btn btn-outline-success btn-sm border-0 px-2 py-1" onclick="changeUpvote('comment',${comment.id});">
                    <i id="commentUpvoteIcon-${comment.id}" class="far fa-thumbs-up"></i>
                    <span id="upvoteTotalComments-${comment.id}" class="ms-1">0</span>
                </button>
            </div>
        </div>
    </div>`;

    var commentsBody = document.getElementById('commentsBody');
    if (commentsBody) {
        commentsBody.insertAdjacentHTML('afterbegin', commentHTML);
    }
});

function confirmDeleteComment(commentId) {
    document.getElementById('deleteCommentId').value = commentId;
    openModal('confirmDeleteCommentModal');
}

function deleteComment() {
    var commentId = document.getElementById('deleteCommentId').value;
    document.getElementById('deleteCommentId').value = '';
    socket.emit('deleteVideoComment', { commentID: commentId });
}

socket.on('deleteVideoCommentData', function (msg) {
    var commentId = msg.commentID;
    var commentDiv = document.getElementById('vidComment-' + commentId);
    if (commentDiv) {
        commentDiv.parentElement.removeChild(commentDiv);
    }

    var commentsBody = document.getElementById('commentsBody');
    if (commentsBody && commentsBody.children.length === 0) {
        var emptyMessage = document.getElementById('emptyCommentsMessage');
        if (emptyMessage) {
            emptyMessage.style.display = 'block';
        }
    }
});
