"""Optional episode-title lookups via the TMDB API.

Yamtrack stores full per-episode metadata (including the title) only once an
episode has been watched, so unwatched "watch next" episodes have no local
title. This module fetches it from TMDB on demand. It is strictly best-effort:
any problem (no token configured, network error, rate limit, 404) returns None
and the caller falls back to a plain "SxxExx" label — a title lookup must never
break the page.
"""

import logging
import os

import requests

logger = logging.getLogger(__name__)

_API_TOKEN = os.environ.get("TMDB_API") or None
_BASE_URL = "https://api.themoviedb.org/3"
_TIMEOUT = 4  # seconds; keep the page snappy even if TMDB is slow

# Process-lifetime cache keyed by (series_id, season, episode). Episode titles
# are effectively immutable, so caching successes (and definitive 404s, as None)
# avoids re-hitting TMDB on every page load. Transient errors are not cached, so
# they retry on the next request.
_cache: dict[tuple[str, int, int], "str | None"] = {}


def enabled() -> bool:
    """Whether a TMDB token is configured. When False, callers skip lookups
    entirely and render number-only labels."""
    return _API_TOKEN is not None


def get_episode_title(series_id: str, season_number: int, episode_number: int):
    """Return the episode's title, or None if unavailable for any reason."""
    if _API_TOKEN is None:
        return None

    key = (series_id, season_number, episode_number)
    if key in _cache:
        return _cache[key]

    url = f"{_BASE_URL}/tv/{series_id}/season/{season_number}/episode/{episode_number}"
    try:
        resp = requests.get(
            url,
            headers={
                "Authorization": f"Bearer {_API_TOKEN}",
                "accept": "application/json",
            },
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.warning("TMDB request failed for %s: %s", key, exc)
        return None  # transient — don't cache, retry next time

    if resp.status_code == 404:
        _cache[key] = None  # definitive: no such episode, cache the miss
        return None
    if resp.status_code != 200:
        logger.warning("TMDB returned %s for %s", resp.status_code, key)
        return None  # e.g. 401 bad token, 429 rate limit — don't cache

    title = (resp.json().get("name") or "").strip() or None
    _cache[key] = title
    return title
