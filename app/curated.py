"""Curated suggestion lists for the setup wizard and settings forms.

The subreddit input is a ``<datalist>``: a hand-kept list of suggestions that
still accepts any free-text value. The genre and Bandcamp-tag inputs are backed
instead by ``bandcamp_taxonomy``: Bandcamp's real discover genres, so users pick
from what actually exists rather than guessing a slug.

Nothing here is a *default* — the fields ship empty and the user chooses.
"""

from fastapi import Request

from app import bandcamp_taxonomy

# Popular music subreddits, loosely grouped by broad genre. Order is roughly
# general-interest first, then genre-specific. Values are the sub name without
# the leading ``r/``.
SUBREDDIT_SUGGESTIONS: list[str] = [
    # General / discovery
    "Music",
    "listentothis",
    "indieheads",
    "popheads",
    # Rock / metal / punk
    "rock",
    "postrock",
    "shoegaze",
    "punk",
    "poppunkers",
    "Metal",
    "Metalcore",
    "progmetal",
    "deathmetal",
    "blackmetal",
    "doommetal",
    # Electronic
    "electronicmusic",
    "House",
    "Techno",
    "edm",
    "ambientmusic",
    "vaporwave",
    # Hip-hop / R&B
    "hiphopheads",
    "trapmuzik",
    "rnb",
    # Jazz / classical / folk / world
    "jazz",
    "classicalmusic",
    "folk",
    "country",
    "reggae",
    "kpop",
]


def curated_context(request: Request) -> dict:
    """Jinja context processor: expose the suggestion lists and genre taxonomy.

    ``genre_taxonomy`` is embedded in the page (via Jinja's ``tojson``) for the
    browser-side picker, so choosing a genre needs no round-trip to Bandcamp.
    """
    return {
        "subreddit_suggestions": SUBREDDIT_SUGGESTIONS,
        "genre_taxonomy": bandcamp_taxonomy.as_picker_payload(),
    }
