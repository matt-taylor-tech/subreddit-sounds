import time

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


def search_track(query: str, artist: str | None = None, genre_filter: str | None = None) -> str | None:
    """Return the first Spotify track ID matching query, or None.

    When artist is provided, uses field-filtered search (artist:"X" track:"Y"),
    which is far more precise than freetext. genre_filter is only applied for
    freetext fallback (when artist is None).
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
            params={"q": q, "type": "track", "limit": 1},
        )
        r.raise_for_status()
    items = r.json().get("tracks", {}).get("items", [])
    return items[0]["id"] if items else None


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
