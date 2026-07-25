"""Curated suggestion lists for the setup wizard and settings forms.

These populate the ``<datalist>`` dropdowns on the subreddit and genre inputs:
suggestions the user can pick from, while still accepting any free-text value.
Kept in one place so the lists are easy to extend without touching templates.

Nothing here is a *default* — the fields ship empty and the user chooses.
"""

from fastapi import Request

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

# Common genre keywords for the Spotify genre filter and Bandcamp tag inputs.
GENRE_SUGGESTIONS: list[str] = [
    "metal",
    "rock",
    "punk",
    "indie",
    "pop",
    "electronic",
    "house",
    "techno",
    "ambient",
    "hip-hop",
    "r&b",
    "soul",
    "funk",
    "jazz",
    "blues",
    "classical",
    "folk",
    "country",
    "reggae",
]


def curated_context(request: Request) -> dict:
    """Jinja context processor: expose the curated suggestion lists to templates."""
    return {
        "subreddit_suggestions": SUBREDDIT_SUGGESTIONS,
        "genre_suggestions": GENRE_SUGGESTIONS,
    }
