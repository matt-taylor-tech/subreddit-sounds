import re
import time

import httpx

from app.services import settings_service

_ACCOUNTS = "https://accounts.spotify.com"
_API = "https://api.spotify.com/v1"
SCOPES = "playlist-modify-public playlist-modify-private playlist-read-private"
_TITLE_OVERLAP_WEIGHT = 3
_ARTIST_OVERLAP_WEIGHT = 4
_POPULARITY_WEIGHT = 0.01
_MAX_SEARCH_CANDIDATES = 10


def is_connected() -> bool:
    return bool(settings_service.get("spotify_refresh_token"))


def get_access_token() -> str:
    expiry = float(settings_service.get("spotify_token_expiry", "0"))
    if time.time() < expiry - 60:
        return settings_service.get("spotify_access_token")
    return _refresh()


def _refresh() -> str:
    refresh_token = settings_service.get("spotify_refresh_token")
    if not refresh_token:
        raise RuntimeError("Spotify not connected — complete OAuth first via the dashboard")
    client_id = settings_service.get("spotify_client_id")
    client_secret = settings_service.get("spotify_client_secret")
    with httpx.Client() as client:
        r = client.post(
            f"{_ACCOUNTS}/api/token",
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
            auth=(client_id, client_secret),
        )
        r.raise_for_status()
    data = r.json()
    updates = {
        "spotify_access_token": data["access_token"],
        "spotify_token_expiry": str(time.time() + data["expires_in"]),
    }
    if "refresh_token" in data:
        updates["spotify_refresh_token"] = data["refresh_token"]
    settings_service.put_many(updates)
    return data["access_token"]


def exchange_code(code: str, redirect_uri: str) -> None:
    """Exchange an authorization code for access + refresh tokens and persist them."""
    client_id = settings_service.get("spotify_client_id")
    client_secret = settings_service.get("spotify_client_secret")
    with httpx.Client() as client:
        r = client.post(
            f"{_ACCOUNTS}/api/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            },
            auth=(client_id, client_secret),
        )
        r.raise_for_status()
    data = r.json()
    settings_service.put_many(
        {
            "spotify_access_token": data["access_token"],
            "spotify_refresh_token": data["refresh_token"],
            "spotify_token_expiry": str(time.time() + data["expires_in"]),
        }
    )


def get_playlist_name(playlist_id: str) -> str:
    """Return the playlist's display name."""
    token = get_access_token()
    with httpx.Client() as client:
        r = client.get(
            f"{_API}/playlists/{playlist_id}",
            headers={"Authorization": f"Bearer {token}"},
            params={"fields": "name"},
        )
        r.raise_for_status()
    return r.json().get("name", playlist_id)


def get_playlist_track_ids(playlist_id: str) -> list[str]:
    token = get_access_token()
    track_ids: list[str] = []
    url: str | None = f"{_API}/playlists/{playlist_id}/tracks"
    params: dict = {"fields": "next,items(track(id))", "limit": 100}
    with httpx.Client() as client:
        while url:
            r = client.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
            r.raise_for_status()
            data = r.json()
            for item in data.get("items", []):
                track = item.get("track")
                if track and track.get("id"):
                    track_ids.append(track["id"])
            url = data.get("next")
            params = {}
    return track_ids


def add_tracks(playlist_id: str, track_ids: list[str]) -> None:
    if not track_ids:
        return
    token = get_access_token()
    uris = [f"spotify:track:{tid}" for tid in track_ids]
    with httpx.Client() as client:
        for i in range(0, len(uris), 100):
            r = client.post(
                f"{_API}/playlists/{playlist_id}/tracks",
                headers={"Authorization": f"Bearer {token}"},
                json={"uris": uris[i : i + 100], "position": 0},
            )
            r.raise_for_status()


def search_track(
    query: str,
    artist: str | None = None,
    genre_filter: str | None = None,
    min_duration_ms: int | None = None,
    artist_is_hint: bool = False,
    include_substyles: bool = True,
    include_unclassified: bool = True,
) -> str | None:
    """Return the best Spotify track ID matching query, or None.

    A *known* artist (parsed from the title, or a "- Topic" channel) drives a
    field-filtered search (artist:"X" track:"Y") and rejects candidates by a
    different artist.

    A *hinted* artist (``artist_is_hint``) is a bare channel name, which is
    sometimes the artist's own upload and sometimes a label or curator. Both are
    tried, precise first: the field-filtered search nails the self-upload case,
    and only if it comes back empty do we fall back to a freetext search where the
    hint merely boosts ranking. Searching artist:"Majestic Casual" alone would
    return nothing and lose the post entirely.

    When genre_filter is set, candidates with known non-matching artist genres are
    rejected. Tracks shorter than min_duration_ms are treated as no match.
    """
    if artist:
        precise = _search_and_select(
            f'artist:"{artist}" track:"{query}"',
            query=query,
            artist=artist,
            genre_filter=genre_filter,
            min_duration_ms=min_duration_ms,
            artist_is_hint=False,
            include_substyles=include_substyles,
            include_unclassified=include_unclassified,
        )
        if precise or not artist_is_hint:
            return precise

    # Only the first genre term is usable as a search filter; every term still
    # applies as a rejection term in _select_best_track. Quoted so multi-word
    # genres survive.
    terms = _genre_terms(genre_filter)
    q = f'{query} genre:"{terms[0]}"' if terms else query
    return _search_and_select(
        q,
        query=query,
        artist=artist,
        genre_filter=genre_filter,
        min_duration_ms=min_duration_ms,
        artist_is_hint=True,
        include_substyles=include_substyles,
        include_unclassified=include_unclassified,
    )


def _search_and_select(
    q: str,
    query: str,
    artist: str | None,
    genre_filter: str | None,
    min_duration_ms: int | None,
    artist_is_hint: bool,
    include_substyles: bool = True,
    include_unclassified: bool = True,
) -> str | None:
    """Run one Spotify track search for ``q`` and pick the best candidate."""
    token = get_access_token()
    artist_genres_by_id: dict[str, list[str]] = {}
    with httpx.Client() as client:
        r = client.get(
            f"{_API}/search",
            headers={"Authorization": f"Bearer {token}"},
            params={"q": q, "type": "track", "limit": _MAX_SEARCH_CANDIDATES},
        )
        r.raise_for_status()
        items = r.json().get("tracks", {}).get("items", [])
        if not items:
            return None
        if genre_filter:
            artist_ids = {
                str(a.get("id"))
                for track in items
                for a in track.get("artists", [])
                if isinstance(a, dict) and a.get("id")
            }
            if artist_ids:
                ar = client.get(
                    f"{_API}/artists",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"ids": ",".join(sorted(artist_ids))},
                )
                ar.raise_for_status()
                for row in ar.json().get("artists", []):
                    if row and row.get("id"):
                        artist_genres_by_id[row["id"]] = row.get("genres", [])
    return _select_best_track(
        items,
        query=query,
        artist=artist,
        genre_filter=genre_filter,
        artist_genres_by_id=artist_genres_by_id,
        min_duration_ms=min_duration_ms,
        artist_is_hint=artist_is_hint,
        include_substyles=include_substyles,
        include_unclassified=include_unclassified,
    )


def _tokenize(value: str | None) -> set[str]:
    if not value:
        return set()
    return {t for t in re.split(r"[^a-z0-9]+", value.lower()) if t}


def _genre_terms(genre_filter: str | None) -> list[str]:
    if not genre_filter:
        return []
    return [part.strip().lower() for part in genre_filter.split(",") if part.strip()]


def _fold(value: str) -> str:
    """Fold punctuation to single spaces so slugs match Spotify's own spelling.

    Spotify writes its genres with spaces and ampersands ("math rock", "r&b"),
    so a hyphenated term like "math-rock" would otherwise substring-match
    nothing and silently reject every classified artist.
    """
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _genre_matches(artist_genres: list[str], wanted_terms: list[str], include_substyles: bool = True) -> bool:
    """Does an artist's genre list satisfy the wanted terms?

    Terms are real Spotify genre names the user picked from a scan, so the base
    rule is exact equality: predictable, with no strictness to second-guess.

    ``include_substyles`` additionally accepts any genre that *contains* a wanted
    term as a phrase, so picking "death metal" also takes "melodic death metal"
    and "technical death metal". Without it, picking "death metal" would quietly
    exclude most of the family, which is the trap that made the old free-text
    field unpredictable.
    """
    folded = [_fold(g) for g in artist_genres]
    wanted = [_fold(term) for term in wanted_terms]
    if any(term == genre for term in wanted for genre in folded):
        return True
    if not include_substyles:
        return False
    return any(_phrase_in(term, genre) for term in wanted for genre in folded)


def _phrase_in(term: str, genre: str) -> bool:
    """Is ``term`` a whole-word phrase inside ``genre``? Both already folded.

    Word-boundary aware so "metal" doesn't match "metalcore" while "death metal"
    still matches "melodic death metal".
    """
    if not term:
        return False
    genre_words = genre.split()
    term_words = term.split()
    n = len(term_words)
    return any(genre_words[i : i + n] == term_words for i in range(len(genre_words) - n + 1))


def _select_best_track(
    items: list[dict],
    query: str,
    artist: str | None = None,
    genre_filter: str | None = None,
    artist_genres_by_id: dict[str, list[str]] | None = None,
    min_duration_ms: int | None = None,
    artist_is_hint: bool = False,
    include_substyles: bool = True,
    include_unclassified: bool = True,
) -> str | None:
    query_tokens = _tokenize(query)
    artist_tokens = _tokenize(artist)
    wanted_genres = _genre_terms(genre_filter)
    genres_by_id = artist_genres_by_id or {}
    best_id: str | None = None
    best_score = -1.0

    for track in items:
        if min_duration_ms and track.get("duration_ms", 0) < min_duration_ms:
            continue
        name_tokens = _tokenize(track.get("name", ""))
        title_overlap = len(query_tokens & name_tokens)
        if query_tokens and title_overlap == 0:
            continue

        artists = track.get("artists", [])
        candidate_artist_tokens = _tokenize(" ".join(a.get("name", "") for a in artists if isinstance(a, dict)))
        artist_overlap = len(artist_tokens & candidate_artist_tokens) if artist_tokens else 0
        # A hinted artist may be a curator/label channel, so a mismatch means
        # "no evidence", not "wrong track". It still boosts score when it agrees.
        if artist_tokens and artist_overlap == 0 and not artist_is_hint:
            continue

        if wanted_genres and artists and isinstance(artists[0], dict):
            primary_artist_id = artists[0].get("id")
            known_genres = genres_by_id.get(primary_artist_id, []) if primary_artist_id else []
            if known_genres:
                if not _genre_matches(known_genres, wanted_genres, include_substyles):
                    continue
            elif not include_unclassified:
                # Spotify leaves many artists (especially small ones) unclassified.
                # Whether that counts as a match is the target's explicit setting.
                continue

        score = title_overlap * _TITLE_OVERLAP_WEIGHT + artist_overlap * _ARTIST_OVERLAP_WEIGHT
        score += track.get("popularity", 0) * _POPULARITY_WEIGHT
        if score > best_score and track.get("id"):
            best_score = score
            best_id = track["id"]

    return best_id


def get_tracks_info(track_ids: list[str]) -> dict[str, str]:
    """Return {track_id: 'Artist — Title'} for each ID, batched in groups of 50."""
    if not track_ids:
        return {}
    token = get_access_token()
    result: dict[str, str] = {}
    with httpx.Client() as client:
        for i in range(0, len(track_ids), 50):
            batch = track_ids[i : i + 50]
            r = client.get(
                f"{_API}/tracks",
                headers={"Authorization": f"Bearer {token}"},
                params={"ids": ",".join(batch)},
            )
            r.raise_for_status()
            for track in r.json().get("tracks", []):
                if track and track.get("id"):
                    artists = ", ".join(a["name"] for a in track.get("artists", []))
                    result[track["id"]] = f"{artists} — {track['name']}"
    return result


def get_primary_artist_genres(track_ids: list[str]) -> dict[str, tuple[str, list[str]]]:
    """Return {track_id: (primary_artist_name, genres)} for the given tracks.

    Genres only exist on Spotify *artist* objects (tracks have no genre field and
    album genres come back empty), so this is a two-hop lookup: tracks to their
    primary artist, then artists to their genres. An artist Spotify hasn't
    classified yields an empty list, which callers report rather than hide.
    """
    if not track_ids:
        return {}
    token = get_access_token()
    primary: dict[str, tuple[str, str]] = {}  # track_id -> (artist_id, artist_name)
    with httpx.Client() as client:
        for i in range(0, len(track_ids), 50):
            r = client.get(
                f"{_API}/tracks",
                headers={"Authorization": f"Bearer {token}"},
                params={"ids": ",".join(track_ids[i : i + 50])},
            )
            r.raise_for_status()
            for track in r.json().get("tracks", []):
                if not track or not track.get("id"):
                    continue
                artists = [a for a in track.get("artists", []) if isinstance(a, dict) and a.get("id")]
                if artists:
                    primary[track["id"]] = (artists[0]["id"], artists[0].get("name", ""))

        genres_by_artist: dict[str, list[str]] = {}
        artist_ids = sorted({aid for aid, _ in primary.values()})
        for i in range(0, len(artist_ids), 50):
            r = client.get(
                f"{_API}/artists",
                headers={"Authorization": f"Bearer {token}"},
                params={"ids": ",".join(artist_ids[i : i + 50])},
            )
            r.raise_for_status()
            for row in r.json().get("artists", []):
                if row and row.get("id"):
                    genres_by_artist[row["id"]] = row.get("genres", [])

    return {tid: (name, genres_by_artist.get(aid, [])) for tid, (aid, name) in primary.items()}


def remove_tracks(playlist_id: str, track_ids: list[str]) -> None:
    if not track_ids:
        return
    token = get_access_token()
    with httpx.Client() as client:
        for i in range(0, len(track_ids), 100):
            batch = [{"uri": f"spotify:track:{tid}"} for tid in track_ids[i : i + 100]]
            r = client.request(
                "DELETE",
                f"{_API}/playlists/{playlist_id}/tracks",
                headers={"Authorization": f"Bearer {token}"},
                json={"tracks": batch},
            )
            r.raise_for_status()
