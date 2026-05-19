import time
import re

import httpx

from app.services import settings_service

_ACCOUNTS = "https://accounts.spotify.com"
_API = "https://api.spotify.com/v1"
SCOPES = "playlist-modify-public playlist-modify-private playlist-read-private"


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
    settings_service.put_many({
        "spotify_access_token": data["access_token"],
        "spotify_refresh_token": data["refresh_token"],
        "spotify_token_expiry": str(time.time() + data["expires_in"]),
    })


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
                json={"uris": uris[i:i + 100], "position": 0},
            )
            r.raise_for_status()


def search_track(
    query: str,
    artist: str | None = None,
    genre_filter: str | None = None,
    min_duration_ms: int | None = None,
) -> str | None:
    """Return the best Spotify track ID matching query, or None.

    When artist is provided, uses field-filtered search (artist:"X" track:"Y"),
    and ranks candidates by title/artist token overlap. When genre_filter is set,
    candidates with known non-matching artist genres are rejected. Tracks shorter
    than min_duration_ms are treated as no match.
    """
    if artist:
        q = f'artist:"{artist}" track:"{query}"'
    else:
        q = f"{query} genre:{genre_filter}" if genre_filter else query
    token = get_access_token()
    with httpx.Client() as client:
        r = client.get(
            f"{_API}/search",
            headers={"Authorization": f"Bearer {token}"},
            params={"q": q, "type": "track", "limit": 10},
        )
        r.raise_for_status()
    items = r.json().get("tracks", {}).get("items", [])
    if not items:
        return None
    artist_genres_by_id: dict[str, list[str]] = {}
    if genre_filter:
        artist_ids = {
            str(a.get("id"))
            for track in items
            for a in track.get("artists", [])
            if isinstance(a, dict) and a.get("id")
        }
        if artist_ids:
            with httpx.Client() as client:
                ar = client.get(
                    f"{_API}/artists",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"ids": ",".join(sorted(aid for aid in artist_ids if aid))},
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
    )


def _tokenize(value: str | None) -> set[str]:
    if not value:
        return set()
    return {t for t in re.split(r"[^a-z0-9]+", value.lower()) if t}


def _genre_terms(genre_filter: str | None) -> list[str]:
    if not genre_filter:
        return []
    return [part.strip().lower() for part in genre_filter.split(",") if part.strip()]


def _genre_matches(artist_genres: list[str], wanted_terms: list[str]) -> bool:
    lowered = [g.lower() for g in artist_genres]
    return any(term in genre for term in wanted_terms for genre in lowered)


def _select_best_track(
    items: list[dict],
    query: str,
    artist: str | None = None,
    genre_filter: str | None = None,
    artist_genres_by_id: dict[str, list[str]] | None = None,
    min_duration_ms: int | None = None,
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
        if artist_tokens and artist_overlap == 0:
            continue

        if wanted_genres and artists and isinstance(artists[0], dict):
            primary_artist_id = artists[0].get("id")
            known_genres = genres_by_id.get(primary_artist_id, []) if primary_artist_id else []
            if known_genres and not _genre_matches(known_genres, wanted_genres):
                continue

        score = float(title_overlap * 3 + artist_overlap * 4)
        score += (track.get("popularity", 0) or 0) / 100.0
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


def remove_tracks(playlist_id: str, track_ids: list[str]) -> None:
    if not track_ids:
        return
    token = get_access_token()
    with httpx.Client() as client:
        for i in range(0, len(track_ids), 100):
            batch = [{"uri": f"spotify:track:{tid}"} for tid in track_ids[i:i + 100]]
            r = client.request(
                "DELETE",
                f"{_API}/playlists/{playlist_id}/tracks",
                headers={"Authorization": f"Bearer {token}"},
                json={"tracks": batch},
            )
            r.raise_for_status()
