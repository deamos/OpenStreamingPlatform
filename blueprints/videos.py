from flask import Blueprint, render_template

from functions import themes
from functions import cachedDbCalls

videos_bp = Blueprint("videos", __name__, url_prefix="/video")


@videos_bp.route("/")
def videos_page():
    videoList = cachedDbCalls.getAllVideo()
    # Newest first
    videoList = sorted(videoList, key=lambda v: v.videoDate, reverse=True)
    return render_template(
        themes.checkOverride("videos.html"),
        videoList=videoList,
        title="Videos",
    )
