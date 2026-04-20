from flask import Blueprint, render_template

from functions import themes
from functions import cachedDbCalls

livestreams_bp = Blueprint("livestreams", __name__, url_prefix="/streams")


@livestreams_bp.route("/")
def live_streams_page():
    streamList = cachedDbCalls.getAllStreams()
    # Sort by current viewers descending so busiest streams appear first
    streamList = sorted(streamList, key=lambda s: s.currentViewers, reverse=True)
    return render_template(
        themes.checkOverride("live_streams.html"),
        streamList=streamList,
        title="Live Streams",
    )
