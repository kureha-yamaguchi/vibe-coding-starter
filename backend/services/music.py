"""Deezer client: keyless source of 30-second audio previews.

Everything the game needs from the music provider goes through this module so
the provider can be swapped (e.g. for the iTunes Search API) in one place.
"""

from __future__ import annotations

import random
import time
from typing import Any, Literal

import httpx
from pydantic import BaseModel

DEEZER_BASE = "https://api.deezer.com"
CACHE_TTL_SECONDS = 300
FETCH_LIMIT = 100

Source = Literal["chart", "search"]


class Track(BaseModel):
    id: int
    title: str
    artist: str
    album: str = ""
    cover_url: str = ""
    preview_url: str


class MusicError(Exception):
    """Raised when the music provider is unreachable or returns no usable tracks."""


_cache: dict[str, tuple[float, list[Track]]] = {}


def _normalise(items: list[dict[str, Any]]) -> list[Track]:
    tracks: list[Track] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        preview = item.get("preview")
        if not preview:
            continue
        title = item.get("title_short") or item.get("title") or ""
        artist = (item.get("artist") or {}).get("name", "")
        if not title or not artist:
            continue
        key = (artist.lower(), title.lower())
        if key in seen:
            continue
        seen.add(key)
        album = item.get("album") or {}
        tracks.append(
            Track(
                id=int(item["id"]),
                title=title,
                artist=artist,
                album=album.get("title", ""),
                cover_url=album.get("cover_medium") or album.get("cover") or "",
                preview_url=preview,
            )
        )
    return tracks


async def _fetch_tracks(path: str, params: dict[str, Any]) -> list[Track]:
    cache_key = f"{path}?{sorted(params.items())}"
    cached = _cache.get(cache_key)
    now = time.monotonic()
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    try:
        async with httpx.AsyncClient(base_url=DEEZER_BASE, timeout=10.0) as client:
            response = await client.get(path, params=params)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        raise MusicError(f"Deezer request failed: {exc}") from exc

    if isinstance(payload, dict) and "error" in payload:
        raise MusicError(f"Deezer error: {payload['error'].get('message', 'unknown')}")

    tracks = _normalise(payload.get("data", []))
    _cache[cache_key] = (now, tracks)
    return tracks


async def get_chart_tracks(limit: int = FETCH_LIMIT) -> list[Track]:
    return await _fetch_tracks("/chart/0/tracks", {"limit": limit})


async def search_tracks(query: str, limit: int = FETCH_LIMIT) -> list[Track]:
    return await _fetch_tracks("/search", {"q": query, "limit": limit, "order": "RANKING"})


async def build_playlist(source: Source, query: str | None, rounds: int) -> list[Track]:
    """Return `rounds` shuffled, playable tracks for the requested source."""
    if source == "chart":
        tracks = await get_chart_tracks()
    elif source == "search":
        if not query or not query.strip():
            raise MusicError("A search query is required for the search source.")
        tracks = await search_tracks(query.strip())
    else:
        raise MusicError(f"Unknown source: {source}")

    if len(tracks) < rounds:
        raise MusicError(
            f"Only {len(tracks)} playable track(s) found; need {rounds}. Try a broader search or fewer rounds."
        )
    return random.sample(tracks, rounds)
