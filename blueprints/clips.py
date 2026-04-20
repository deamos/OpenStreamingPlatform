from flask import Blueprint, render_template

from functions import themes
from functions import cachedDbCalls

clips_bp = Blueprint("clips", __name__, url_prefix="/clips")


@clips_bp.route("/")
def clips_page():
    clipList = cachedDbCalls.getAllClips()
    # Most-viewed first
    clipList = sorted(clipList, key=lambda c: c.views, reverse=True)
    return render_template(
        themes.checkOverride("clips.html"),
        clipList=clipList,
        title="Clips",
    )
