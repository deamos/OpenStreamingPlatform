from flask import Blueprint, render_template
from urllib.parse import unquote

from functions import themes
from functions import cachedDbCalls

tags_bp = Blueprint("tags", __name__, url_prefix="/tags")


@tags_bp.route("/")
def tags_page():
    """Tag cloud — all tags across videos, channels, and clips ranked by usage."""
    tag_counts = cachedDbCalls.getAllTagsWithCounts()
    return render_template(
        themes.checkOverride("tags.html"),
        tagCounts=tag_counts,
        title="Labels",
    )


@tags_bp.route("/<path:tagName>/")
def tag_view_page(tagName: str):
    """Detail view — all channels, videos, and clips bearing a specific tag."""
    tagName = unquote(tagName)
    content = cachedDbCalls.getContentByTagName(tagName)
    return render_template(
        themes.checkOverride("tagview.html"),
        tagName=tagName,
        channelList=content["channels"],
        recordedVids=content["videos"],
        clipsList=content["clips"],
        title=f"Label: {tagName}",
    )
