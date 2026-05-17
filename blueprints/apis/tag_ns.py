from flask_restx import Resource, Namespace, reqparse

from classes.shared import db
from functions import cachedDbCalls

api = Namespace("tag", description="Tag Suggestion Queries")

tagSuggestGet = reqparse.RequestParser()
tagSuggestGet.add_argument(
    "term", type=str, required=True, help="Partial tag name to search for (min 3 chars)"
)


@api.route("/suggest")
class api_1_TagSuggest(Resource):
    @api.expect(tagSuggestGet)
    @api.doc(responses={200: "Success", 400: "Request Error"})
    def get(self):
        """
        Returns up to 25 distinct tag name suggestions matching a partial term.
        Searches across video, channel, and clip tags. Minimum 3 characters required.
        """
        args = tagSuggestGet.parse_args()
        term = args.get("term", "")
        if term is None or len(term) < 3:
            return {"results": []}, 200
        results = cachedDbCalls.searchTags(term)
        db.session.commit()
        return {"results": results}
