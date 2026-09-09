"""Optional lookups via the TMDB API, for what the database cannot supply.

Yamtrack stores full per-episode metadata (including the title) only once an
episode has been watched, so unwatched "watch next" episodes have no local
title; and nothing it stores records which network a show airs on. This module
fetches both on demand, along with the episode_type the season response carries
— "finale" is what upgrades a card's badge. Every lookup is best-effort and
never raises: a failure leaves the fields None and the caller degrades.

Episode lookups are made a season at a time. A settled answer is never asked
about again; a *miss* is what re-fetches the season, held off per episode by
_REFETCH_FLOOR. Why a miss rather than an expiry, and why the whole season
rather than the one missing episode, are argued in
docs/adr/0010-refetch-on-miss-not-on-a-timer.md.

A show's own facts — the network it airs on, whether it has finished, and which
episode aired last — need none of that machinery: one response answers all
three, once. →
docs/adr/0012-network-not-watch-providers.md.
"""

import logging
import os
import re
import time
from datetime import date, datetime
from typing import NamedTuple

import requests

logger = logging.getLogger(__name__)

_API_TOKEN = os.environ.get("TMDB_API") or None
_BASE_URL = "https://api.themoviedb.org/3"
_TIMEOUT = 4  # seconds; keep the page snappy even if TMDB is slow

SeasonKey = tuple[str, int]  # (series_id, season_number)
EpisodeKey = tuple[str, int, int]  # (series_id, season_number, episode_number)


class EpisodeFacts(NamedTuple):
    """What TMDB knows about one episode; every field can be None. air_date is
    here to date a numbered name, not to be shown."""

    title: str | None
    air_date: str | None
    episode_type: str | None  # "standard", "finale", "mid_season"


class ShowFacts(NamedTuple):
    """What TMDB knows about a show, from the one response that answers both
    the platform line and whether the show has finished."""

    network: str | None
    ended: bool  # TMDB says the show is over, not that it may yet return
    final_episode: tuple[int, int] | None  # (season, episode) that aired last

    def is_series_finale(self, season_number: int, episode_number: int) -> bool:
        """Whether that episode is the last one the show will ever air. False
        for a show still returning, and for anything TMDB didn't answer — so a
        card only ever reads SERIES FINALE on an answer, never on a gap."""
        return self.ended and self.final_episode == (season_number, episode_number)


SeasonMap = dict[int, EpisodeFacts]  # keyed by episode_number

_NOTHING_KNOWN = EpisodeFacts(None, None, None)
_NOTHING_KNOWN_SHOW = ShowFacts(None, False, None)

# The two TMDB statuses that mean the show will not return. The others —
# "Returning Series", "Planned", "In Production", "Pilot" — all still might.
# A tuple, not a set: `in` on a tuple compares with ==, so a malformed response
# whose status is a dict or list answers False instead of raising TypeError.
_ENDED_STATUSES = ("Ended", "Canceled")

# What the last answered fetch said about a season, or None for a season TMDB
# doesn't have. Replaced wholesale on re-fetch.
_season_cache: dict[SeasonKey, SeasonMap | None] = {}

# What TMDB answered about a show. An absent key means "not asked yet, or the
# last attempt failed".
_show_cache: dict[str, ShowFacts] = {}

# When a request was last spent trying to resolve one specific episode and came
# back without a settled answer. This is what the floor below is measured
# against, and it has to be per episode rather than per season: a season map
# fetched before an episode aired is stale *for that episode*, and the first
# person to ask should trigger the re-fetch that fixes it.
_last_miss_attempt: dict[EpisodeKey, float] = {}

# How long to leave an episode alone after a fetch failed to settle it. Without
# this, an episode Yamtrack says aired but TMDB hasn't published would re-fetch
# the season on every single page load. Six hours caps that waste at four
# fetches a day and, against _PLACEHOLDER_WINDOW, a numbered name at eight
# re-checks total.
_REFETCH_FLOOR = 6 * 60 * 60  # seconds

# Returned when TMDB gave no usable answer and the failure looks temporary, as
# opposed to answering "there is no such thing". A transient failure is never
# cached and must not count as an attempt against the floor.
_TRANSIENT = object()

# TMDB sends "Episode 7" both as a stand-in for a title it doesn't have yet and
# as the real, permanent name (e.g. soaps, news, daily serials). Only air date
# separates them. → docs/adr/0011-numbered-episode-names-as-sent.md
_NUMBERED_TITLE = re.compile(r"(?i)^episode\s*\d+$")
_PLACEHOLDER_WINDOW = 2  # days after air


def enabled() -> bool:
    """Whether a TMDB token is configured."""
    return _API_TOKEN is not None


def _within_placeholder_window(air_date) -> bool:
    """Whether the episode aired recently enough that a numbered name might
    still be a stand-in (or hasn't aired at all). A missing or unparseable date
    counts as recent: better to re-check a few times than freeze a stand-in."""
    if not air_date:
        return True
    try:
        aired = datetime.strptime(air_date, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return True
    return (date.today() - aired).days <= _PLACEHOLDER_WINDOW


def _is_provisional(title, air_date) -> bool:
    """Whether this episode is worth asking TMDB about again. Only the title
    decides. An episode_type TMDB adds after the title has settled is therefore
    never picked up, and the card keeps the badge the database gave it — the
    same degradation as running without a token."""
    if title is None:
        return True
    if not _NUMBERED_TITLE.match(title):
        return False  # a real title, and those don't change
    return _within_placeholder_window(air_date)


def _episode_entry(season, episode_number):
    """(facts, provisional) for one episode of a fetched season. An episode the
    season doesn't list is (nothing known, provisional) — TMDB may add it later."""
    if season is None or episode_number not in season:
        return _NOTHING_KNOWN, True
    facts = season[episode_number]
    return facts, _is_provisional(facts.title, facts.air_date)


def _get_object(path: str):
    """GET a TMDB path and return the response body. Returns the dict, None if
    TMDB answered "no such thing", or _TRANSIENT if it couldn't answer at all.
    Never raises.

    The answer-vs-hiccup judgement lives here, so both lookups make it alike."""
    try:
        resp = requests.get(
            f"{_BASE_URL}{path}",
            headers={
                "Authorization": f"Bearer {_API_TOKEN}",
                "accept": "application/json",
            },
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.warning("TMDB request failed for %s: %s", path, exc)
        return _TRANSIENT

    if resp.status_code == 404:
        return None  # answered: no such thing
    if resp.status_code != 200:
        logger.warning("TMDB returned %s for %s", resp.status_code, path)
        return _TRANSIENT  # e.g. 401 bad token, 429 rate limit

    try:
        body = resp.json()
    except ValueError as exc:  # 200 with a non-JSON body
        logger.warning("TMDB returned unparseable JSON for %s: %s", path, exc)
        return _TRANSIENT
    if not isinstance(body, dict):  # a 200 that isn't an object at all
        logger.warning("TMDB response for %s is not an object", path)
        return _TRANSIENT
    return body


def _list_field(body: dict, path: str, field: str):
    """`field` out of a response body, or _TRANSIENT if it isn't a list. A 200
    missing the list it should carry is likelier an upstream hiccup than a
    permanent truth."""
    items = body.get(field)
    if not isinstance(items, list):
        logger.warning("TMDB response for %s has no %s list", path, field)
        return _TRANSIENT
    return items


def _fetch_season(series_id: str, season_number: int):
    """Fetch the season and cache what TMDB said. Returns the season map, None
    if TMDB answered "no such season", or _TRANSIENT if it couldn't answer at
    all."""
    key = (series_id, season_number)
    path = f"/tv/{series_id}/season/{season_number}"
    body = _get_object(path)
    if body is _TRANSIENT:
        return _TRANSIENT
    if body is None:
        _season_cache[key] = None  # answered: no such season
        return None
    episodes = _list_field(body, path, "episodes")
    if episodes is _TRANSIENT:
        return _TRANSIENT

    season = {}
    for ep in episodes:
        if not isinstance(ep, dict):
            continue
        number = ep.get("episode_number")
        if type(number) is not int:  # bool is an int subclass; True would key as 1
            continue
        episode_type = ep.get("episode_type")
        season[number] = EpisodeFacts(
            (ep.get("name") or "").strip() or None,
            ep.get("air_date"),
            episode_type if isinstance(episode_type, str) else None,
        )
    _season_cache[key] = season
    return season


def get_episode_facts(
    series_id: str, season_number: int, episode_number: int
) -> EpisodeFacts:
    """Return what TMDB knows about the episode. Fields are None where it knows
    nothing, or where the lookup failed for any reason."""
    if _API_TOKEN is None:
        return _NOTHING_KNOWN

    key = (series_id, season_number)
    miss_key = (series_id, season_number, episode_number)

    season = _season_cache.get(key)
    facts, provisional = _episode_entry(season, episode_number)
    if not provisional:
        _last_miss_attempt.pop(miss_key, None)
        return facts  # settled — never ask about it again

    # Not settled: the episode isn't listed yet, TMDB gave no name, or the name
    # is a number on an episode that only just aired. All of those can change as
    # TMDB publishes, so re-fetch — unless we asked about this one recently.
    last_attempt = _last_miss_attempt.get(miss_key)
    if last_attempt is None or time.monotonic() - last_attempt >= _REFETCH_FLOOR:
        result = _fetch_season(series_id, season_number)
        if result is not _TRANSIENT:  # transient doesn't count against the floor
            facts, provisional = _episode_entry(result, episode_number)
            if not provisional:
                _last_miss_attempt.pop(miss_key, None)
                return facts
            _last_miss_attempt[miss_key] = time.monotonic()

    # Show whatever TMDB last gave us, even if it may yet improve.
    return facts


def _first_network_name(networks) -> str | None:
    """The first network TMDB named for the show. A co-production lists several;
    TMDB puts the primary one first, which is the one worth showing."""
    for entry in networks:
        if not isinstance(entry, dict):
            continue
        name = (entry.get("name") or "").strip()
        if name:
            return name
    return None


def _final_episode(last_episode_to_air) -> tuple[int, int] | None:
    """The (season, episode) TMDB says aired most recently, or None where it
    didn't say usefully. On a show that has ended this names the series finale."""
    if not isinstance(last_episode_to_air, dict):
        return None
    season = last_episode_to_air.get("season_number")
    episode = last_episode_to_air.get("episode_number")
    # bool is an int subclass; True would otherwise read as season 1.
    if type(season) is not int or type(episode) is not int:
        return None
    return (season, episode)


def _fetch_show(series_id: str):
    """Fetch the show and cache what TMDB said about it. Returns the facts, or
    _TRANSIENT if TMDB couldn't answer at all."""
    path = f"/tv/{series_id}"
    body = _get_object(path)
    if body is _TRANSIENT:
        return _TRANSIENT

    if body is None:
        # Answered: no such show. Nothing known is the right thing to record.
        facts = _NOTHING_KNOWN_SHOW
    else:
        # networks is the one list every show response carries; a body without
        # it is the wrong shape, so none of the rest is worth trusting either.
        networks = _list_field(body, path, "networks")
        if networks is _TRANSIENT:
            return _TRANSIENT
        facts = ShowFacts(
            _first_network_name(networks),
            body.get("status") in _ENDED_STATUSES,
            _final_episode(body.get("last_episode_to_air")),
        )
    _show_cache[series_id] = facts
    return facts


def get_show_facts(series_id: str) -> ShowFacts:
    """What TMDB knows about the show: the network it airs on — "HBO", "Apple
    TV+" — and whether it has finished. Fields fall back to "nothing known"
    where TMDB named none, doesn't have the show, or couldn't be reached.
    → docs/adr/0012-network-not-watch-providers.md
    """
    if _API_TOKEN is None:
        return _NOTHING_KNOWN_SHOW
    if series_id in _show_cache:
        return _show_cache[series_id]
    result = _fetch_show(series_id)
    return _NOTHING_KNOWN_SHOW if result is _TRANSIENT else result
