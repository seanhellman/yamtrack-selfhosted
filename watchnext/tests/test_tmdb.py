"""Self-contained tests for the TMDB episode-title and show lookups.

Run: `python watchnext/tests/test_tmdb.py` (no deps, no network).

Why this exists: tmdb.py must degrade rather than break — no token, a timeout, a
429 or a 404 all have to leave the page working with plain SxxExx labels and no
platform line. Those paths never run in normal use, so nothing else would catch
a regression in them. It also pins the request contract, which is the part that
is easy to get subtly wrong: a resolved title is never re-requested, a miss
re-fetches the season once, a season that keeps not answering is held off by a
floor, and a show is asked about exactly once — one response answering both
the platform line and whether the show has finished.

`requests` is stubbed into sys.modules before tmdb is imported, so this runs on a
bare interpreter with no virtualenv and can never reach the network.
"""

import logging
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import check, run  # noqa: E402  (needs the path above)

# The no-network guarantee only holds if nothing imported these first — an
# already-imported tmdb keeps its binding to the real `requests`.
assert "tmdb" not in sys.modules and "requests" not in sys.modules, (
    "tmdb/requests were imported before the stub; these tests would hit the network"
)

_NO_PAYLOAD = object()


class FakeRequestException(Exception):
    pass


class FakeResponse:
    def __init__(self, status_code, payload=_NO_PAYLOAD):
        self.status_code = status_code
        self._payload = {} if payload is _NO_PAYLOAD else payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload  # a 200 whose body doesn't parse
        return self._payload


class FakeRequests:
    """Stand-in for the `requests` module: records calls, replays queued responses."""

    RequestException = FakeRequestException

    def __init__(self):
        self.calls = []
        self.responses = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        # No default response: a request a test didn't queue is the bug these
        # tests exist to catch, so it fails loudly instead of being served.
        assert self.responses, f"unexpected TMDB request: {url}"
        outcome = self.responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


fake_requests = FakeRequests()
sys.modules["requests"] = fake_requests
os.environ["TMDB_API"] = "test-token"

import tmdb  # noqa: E402  (must follow the stub above)

# Swallow the module's warnings; they are expected on the failure paths below and
# would otherwise interleave with the results and read as errors.
logging.getLogger("tmdb").addHandler(logging.NullHandler())


# Air dates chosen either side of the placeholder window, so a numbered name
# can be tested both as a stand-in (just aired) and as a real title (long past).
OLD_AIR = "2016-07-21"
FRESH_AIR = date.today().isoformat()


def season_payload(*names, start=1, air=OLD_AIR, types=None):
    """A TMDB season response listing episodes with the given names, and their
    episode_types where a test cares (omitted entirely otherwise, which is the
    shape a response missing the field has)."""
    episodes = [{"episode_number": i, "name": n, "air_date": air}
                for i, n in enumerate(names, start)]
    for ep, episode_type in zip(episodes, types or []):
        ep["episode_type"] = episode_type
    return FakeResponse(200, {"episodes": episodes})


def one_episode(name, air):
    """A season listing exactly one episode, with an explicit air date."""
    return FakeResponse(
        200, {"episodes": [{"episode_number": 1, "name": name, "air_date": air}]}
    )


def show_payload(*network_names, status=None, last=None):
    """A TMDB show response listing the given networks, in order. status and
    last_episode_to_air are omitted unless a test cares — the shape a response
    without them has. `last` is (season, episode), or a raw value to stand in
    for a malformed one."""
    body = {"networks": [{"name": n} for n in network_names]}
    if status is not None:
        body["status"] = status
    if last is not None:
        body["last_episode_to_air"] = (
            {"season_number": last[0], "episode_number": last[1]}
            if isinstance(last, tuple) else last
        )
    return FakeResponse(200, body)


def reset(*responses):
    """Clear cache and call log, then queue the responses TMDB should return."""
    tmdb._season_cache.clear()
    tmdb._last_miss_attempt.clear()
    tmdb._show_cache.clear()
    fake_requests.calls = []
    fake_requests.responses = list(responses)


def pass_the_floor():
    """Backdate every unresolved episode past the re-fetch floor, standing in
    for six hours going by."""
    for key, last_attempt in list(tmdb._last_miss_attempt.items()):
        tmdb._last_miss_attempt[key] = last_attempt - tmdb._REFETCH_FLOOR - 1


def title(series_id, season_number, episode_number):
    """The title half of a lookup — what most of these tests assert on."""
    return tmdb.get_episode_facts(series_id, season_number, episode_number).title


def network(series_id):
    """The network half of a show lookup — what most of these tests assert on."""
    return tmdb.get_show_facts(series_id).network


def calls():
    return len(fake_requests.calls)


# --- basic resolution -------------------------------------------------------

def test_titles_resolve():
    reset(season_payload("Pilot", "Second", "Third"))
    check("title: episode 1 resolves", title("1399", 1, 1) == "Pilot")
    check("title: episode 3 resolves", title("1399", 1, 3) == "Third")


def test_hits_the_season_endpoint():
    reset(season_payload("Pilot"))
    title("1399", 2, 1)
    url = fake_requests.calls[0] if fake_requests.calls else ""
    check("endpoint: season URL, not per-episode",
          url.endswith("/tv/1399/season/2") and "/episode/" not in url, url)


def test_one_request_per_season():
    reset(season_payload("Pilot", "Second", "Third"))
    titles = [title("1399", 1, n) for n in (1, 2, 3)]
    check("cache: three episodes of one season cost one request", calls() == 1,
          f"{calls()} calls")
    check("cache: all three titles still correct",
          titles == ["Pilot", "Second", "Third"], str(titles))


def test_separate_seasons_and_shows():
    reset(season_payload("S1E1"), season_payload("S2E1"), season_payload("Other"))
    title("1399", 1, 1)
    title("1399", 2, 1)
    title("2316", 1, 1)
    check("cache: each (show, season) fetched separately", calls() == 3, f"{calls()} calls")


# --- the request contract ---------------------------------------------------

def test_resolved_title_is_never_refetched():
    # A finished season the viewer is caught up on costs nothing, forever.
    reset(season_payload("Pilot", "Second"))
    title("1399", 1, 1)
    pass_the_floor()
    title("1399", 1, 1)
    title("1399", 1, 2)
    check("resolved: a known title never triggers another request", calls() == 1,
          f"{calls()} calls")


def test_missing_episode_refetches_immediately():
    # This week's episode is absent from a map saved last week; the miss is
    # what re-fetches, so the title lands on the very next render.
    reset(season_payload("Pilot"), season_payload("Pilot", "Week two"))
    check("airing: week one resolves", title("1399", 1, 1) == "Pilot")
    check("airing: week two resolves on the next render",
          title("1399", 1, 2) == "Week two")
    check("airing: that cost exactly one extra request", calls() == 2, f"{calls()} calls")


def test_backlog_is_filled_by_one_refetch():
    # Away a while, ten episodes piled up: one request covers the lot.
    reset(season_payload("E1"), season_payload(*[f"E{i}" for i in range(1, 11)]))
    title("1399", 1, 1)
    check("backlog: the first miss re-fetches the season",
          title("1399", 1, 2) == "E2")
    got = [title("1399", 1, n) for n in range(3, 11)]
    check("backlog: the rest of the run is served from that one re-fetch",
          got == [f"E{i}" for i in range(3, 11)], str(got))
    check("backlog: two requests total, not one per episode", calls() == 2,
          f"{calls()} calls")


def test_floor_holds_off_a_season_that_keeps_missing():
    # Yamtrack says episode 2 aired; TMDB hasn't published it. Without a floor
    # this would re-fetch the season on every page load, forever.
    reset(season_payload("Pilot"), season_payload("Pilot"))
    title("1399", 1, 1)
    check("floor: the first miss is allowed through",
          title("1399", 1, 2) is None)
    for _ in range(5):
        title("1399", 1, 2)
    check("floor: repeat renders inside the window make no request", calls() == 2,
          f"{calls()} calls")


def test_floor_expires():
    reset(season_payload("Pilot"), season_payload("Pilot"),
          season_payload("Pilot", "Arrived"))
    title("1399", 1, 1)
    title("1399", 1, 2)  # miss, re-fetch, still absent
    pass_the_floor()
    check("floor: after the window the episode is asked about again",
          title("1399", 1, 2) == "Arrived")


# --- numbered names: stand-in vs real title ---------------------------------

def test_numbered_name_is_shown_as_is():
    # For a soap or a news programme, "Episode 4978" IS the episode's name.
    reset(one_episode("Episode 4978", OLD_AIR))
    check("numbered: shown exactly as TMDB sends it",
          title("secretlives", 1, 1) == "Episode 4978")


def test_long_aired_numbered_name_is_final():
    # Fleabag's episodes really are called "Episode 1"; long past air, that is
    # taken as the real name and never re-requested.
    reset(one_episode("Episode 1", OLD_AIR))
    got = [title("67070", 1, 1) for _ in range(6)]
    check("settled: a long-aired numbered name resolves once",
          got == ["Episode 1"] * 6, str(set(got)))
    check("settled: and is never re-requested", calls() == 1, f"{calls()} calls")
    pass_the_floor()
    title("67070", 1, 1)
    check("settled: not even after the floor lapses", calls() == 1, f"{calls()} calls")


def test_just_aired_numbered_name_is_provisional():
    # The narrow case the window exists for: TMDB has not caught up yet.
    reset(one_episode("Episode 1", FRESH_AIR),
          one_episode("Only the Strong Survive", FRESH_AIR))
    check("provisional: the number is shown while that is all TMDB has",
          title("1416", 23, 1) == "Episode 1")
    pass_the_floor()
    check("provisional: the real title replaces it once TMDB has one",
          title("1416", 23, 1) == "Only the Strong Survive")
    pass_the_floor()
    title("1416", 23, 1)
    check("provisional: and then it settles and stops asking", calls() == 2,
          f"{calls()} calls")


def test_provisional_window_is_bounded():
    # Worst case for a show that never gets a real title but only just aired:
    # one re-check per floor until the window passes, then silence.
    reset(*[one_episode("Episode 1", FRESH_AIR) for _ in range(3)])
    title("1416", 23, 1)
    for _ in range(5):
        title("1416", 23, 1)
    check("window: repeat renders inside the floor cost nothing", calls() == 1,
          f"{calls()} calls")
    pass_the_floor()
    title("1416", 23, 1)
    check("window: one more request per floor while still fresh", calls() == 2,
          f"{calls()} calls")


def test_which_names_count_as_numbered():
    # Tested against the rule directly: asking the module for several unsettled
    # episodes of one season in a burst is not a real access pattern (the page
    # shows one episode per season) and would only exercise the re-fetch contract.
    cases = [
        ("Episode 1", True), ("episode 2", True), ("Episode  3", True),
        ("EPISODE 4", True), ("Episode 4978", True),
        ("Episode 4: The Reckoning", False), ("Episodes", False),
        ("Episode Zero", False), ("The Episode 9", False),
    ]
    got = [bool(tmdb._NUMBERED_TITLE.match(n)) for n, _ in cases]
    check("numbered: only a bare 'Episode N' counts",
          got == [want for _, want in cases],
          str([n for (n, w), g in zip(cases, got) if w != g]))


def test_missing_air_date_stays_provisional():
    # No date means we cannot tell a stand-in from a real title, so keep asking
    # rather than freezing a number in place.
    reset(FakeResponse(200, {"episodes": [{"episode_number": 1, "name": "Episode 1"}]}),
          one_episode("Real Title", FRESH_AIR))
    check("no air date: the number is shown",
          title("1399", 1, 1) == "Episode 1")
    pass_the_floor()
    check("no air date: still checked, and upgrades when a title lands",
          title("1399", 1, 1) == "Real Title")


def test_unparseable_air_date_stays_provisional():
    reset(one_episode("Episode 1", "not-a-date"), one_episode("Real Title", OLD_AIR))
    check("bad air date: treated as recent rather than crashing",
          title("1399", 1, 1) == "Episode 1")
    pass_the_floor()
    check("bad air date: re-checked like any other provisional name",
          title("1399", 1, 1) == "Real Title")


def test_blank_name():
    # TMDB listing an episode with no name at all: nothing to show, so the card
    # falls back to its bare SxxExx code, and we keep checking for a real title.
    reset(one_episode("  ", OLD_AIR), one_episode("Arrived", OLD_AIR))
    check("blank: whitespace-only name shows nothing",
          title("1399", 1, 1) is None)
    pass_the_floor()
    check("blank: and is re-checked, since a name may yet appear",
          title("1399", 1, 1) == "Arrived")


# --- failure paths ----------------------------------------------------------

def test_missing_episode_in_season():
    reset(season_payload("Pilot", "Second"), season_payload("Pilot", "Second"))
    facts = tmdb.get_episode_facts("1399", 1, 9)
    check("miss: an episode absent from the season has neither title nor type",
          facts.title is None and facts.episode_type is None, str(facts))


def test_season_404_is_held_off():
    reset(FakeResponse(404))
    check("404: unknown season returns None", title("1399", 9, 1) is None)
    for _ in range(4):
        title("1399", 9, 1)
    check("404: an answered miss is not re-asked inside the floor", calls() == 1,
          f"{calls()} calls")


def test_season_404_expires():
    reset(FakeResponse(404), season_payload("Pilot"))
    title("1399", 9, 1)
    pass_the_floor()
    check("404: a season TMDB has since added resolves after the floor",
          title("1399", 9, 1) == "Pilot")


def test_rate_limit_is_not_cached():
    reset(FakeResponse(429), season_payload("Pilot"))
    first = title("1399", 1, 1)
    second = title("1399", 1, 1)
    check("429: returns None, then retries on the next render without waiting",
          first is None and second == "Pilot", f"{first!r}, {second!r}")


def test_bad_token_is_not_cached():
    reset(FakeResponse(401), season_payload("Pilot"))
    first = title("1399", 1, 1)
    second = title("1399", 1, 1)
    check("401: returns None, then retries", first is None and second == "Pilot")


def test_network_error_is_not_cached():
    reset(FakeRequestException("timeout"), season_payload("Pilot"))
    first = title("1399", 1, 1)
    second = title("1399", 1, 1)
    check("network error: returns None, then retries and succeeds",
          first is None and second == "Pilot", f"{first!r}, {second!r}")


def test_malformed_payload():
    reset(FakeResponse(200, {"unexpected": True}), season_payload("Pilot"))
    check("malformed: response without episodes[] returns None",
          title("1399", 1, 1) is None)
    check("malformed: treated as transient, so it retries immediately",
          title("1399", 1, 1) == "Pilot")


def test_non_object_json_body():
    for body, label in [([], "bare list"), ("nope", "bare string"), (None, "null")]:
        reset(FakeResponse(200, body), season_payload("Pilot"))
        check(f"body: a 200 carrying a {label} returns None, page survives",
              title("1399", 1, 1) is None)


def test_unparseable_body():
    reset(FakeResponse(200, ValueError("no json")), season_payload("Pilot"))
    check("body: a 200 that doesn't parse returns None",
          title("1399", 1, 1) is None)
    check("body: and is treated as transient, so it retries",
          title("1399", 1, 1) == "Pilot")


def test_bool_episode_number_ignored():
    reset(FakeResponse(200, {"episodes": [
        {"episode_number": 1, "name": "Real one"},
        {"episode_number": True, "name": "Bogus"},
    ]}))
    check("shape: a bool episode_number can't shadow episode 1",
          title("1399", 1, 1) == "Real one")


def test_no_token():
    reset()
    token = tmdb._API_TOKEN
    tmdb._API_TOKEN = None
    try:
        check("no token: enabled() is False", tmdb.enabled() is False)
        facts = tmdb.get_episode_facts("1399", 1, 1)
        check("no token: neither title nor type", facts == (None, None, None), str(facts))
        check("no token: makes no request", calls() == 0)
    finally:
        tmdb._API_TOKEN = token
    check("token restored: enabled() is True again", tmdb.enabled() is True)


# --- episode_type: what upgrades a badge ------------------------------------

def test_finale_flag_is_read():
    reset(season_payload("Pilot", "Last One", types=["standard", "finale"]))
    check("type: the season's last episode reads finale",
          tmdb.get_episode_facts("1399", 1, 2).episode_type == "finale")
    check("type: an ordinary episode reads standard",
          tmdb.get_episode_facts("1399", 1, 1).episode_type == "standard")


def test_missing_episode_type_is_none():
    # A response without the field must degrade to no badge upgrade, not crash.
    reset(season_payload("Pilot"))
    check("type: absent from the payload returns None",
          tmdb.get_episode_facts("1399", 1, 1).episode_type is None)


def test_non_string_episode_type_ignored():
    reset(FakeResponse(200, {"episodes": [
        {"episode_number": 1, "name": "Pilot", "air_date": OLD_AIR, "episode_type": 7}]}))
    facts = tmdb.get_episode_facts("1399", 1, 1)
    check("type: a non-string value is dropped, title still resolves",
          facts.episode_type is None and facts.title == "Pilot", str(facts))


def test_episode_type_does_not_drive_refetching():
    # Only the title decides whether an episode is settled. A standard episode
    # with a real name costs no further requests — so a finale flag TMDB adds
    # after that point is never picked up, and the card stays NEW.
    reset(season_payload("Pilot", types=["standard"]))
    tmdb.get_episode_facts("1399", 1, 1)
    pass_the_floor()
    tmdb.get_episode_facts("1399", 1, 1)
    check("type: a settled title is never re-requested for its type",
          calls() == 1, f"{calls()} calls")


# --- the show lookup: network, status, final episode ------------------------

def test_network_resolves():
    reset(show_payload("HBO"))
    check("network: the show's network name resolves",
          network("1399") == "HBO")


def test_network_hits_the_show_endpoint():
    reset(show_payload("Apple TV+"))
    network("95396")
    url = fake_requests.calls[0] if fake_requests.calls else ""
    check("network: the show URL, not a season and not /watch/providers",
          url.endswith("/tv/95396")
          and "/season/" not in url
          and "watch/providers" not in url, url)


def test_one_request_per_show():
    reset(show_payload("Hulu"))
    got = [network("1396") for _ in range(5)]
    check("network: repeat lookups are served from cache", calls() == 1,
          f"{calls()} calls")
    check("network: and keep answering the same thing", set(got) == {"Hulu"}, str(set(got)))


def test_each_show_fetched_separately():
    reset(show_payload("HBO"), show_payload("Hulu"))
    check("network: first show", network("1399") == "HBO")
    check("network: second show", network("1396") == "Hulu")
    check("network: one request each", calls() == 2, f"{calls()} calls")


def test_network_and_titles_are_separate_lookups():
    # The season endpoint carries no networks, so a fetched season must not be
    # mistaken for an answered network lookup (or the reverse).
    reset(season_payload("Pilot"), show_payload("HBO"))
    title("1399", 1, 1)
    check("network: a fetched season doesn't answer the network question",
          network("1399") == "HBO")


def test_first_named_network_wins():
    # Co-productions list several; TMDB puts the primary one first.
    reset(show_payload("AMC", "BBC Two"))
    check("network: the first listed network is the one shown",
          network("1399") == "AMC")


def test_blank_network_names_skipped():
    reset(FakeResponse(200, {"networks": [
        {"name": "   "}, {"logo_path": "/x.png"}, "not-an-object", {"name": "Showtime"},
    ]}))
    check("network: unnamed entries are skipped, the first real name wins",
          network("1399") == "Showtime")


def test_no_networks_is_an_answer():
    # A web series or a self-distributed show genuinely has no network. That is
    # an answer, so the card simply has no platform line and never re-asks.
    reset(FakeResponse(200, {"networks": []}))
    check("network: an empty list means no platform line",
          network("1399") is None)
    for _ in range(4):
        network("1399")
    check("network: and is never asked about again", calls() == 1, f"{calls()} calls")


def test_network_404_is_an_answer():
    reset(FakeResponse(404))
    check("network 404: unknown show returns None", network("nope") is None)
    for _ in range(4):
        network("nope")
    check("network 404: an answered miss is not re-asked", calls() == 1, f"{calls()} calls")


def test_network_rate_limit_is_not_cached():
    reset(FakeResponse(429), show_payload("HBO"))
    first = network("1399")
    second = network("1399")
    check("network 429: returns None, then retries on the next render",
          first is None and second == "HBO", f"{first!r}, {second!r}")


def test_network_error_is_not_cached():
    reset(FakeRequestException("timeout"), show_payload("HBO"))
    first = network("1399")
    second = network("1399")
    check("network error: returns None, then retries and succeeds",
          first is None and second == "HBO", f"{first!r}, {second!r}")


def test_network_malformed_payload():
    # A 200 in an unexpected shape is likelier an upstream hiccup than a truth.
    for body, label in [({"networks": "HBO"}, "networks as a string"),
                        ({"name": "Show"}, "no networks key"),
                        ([], "bare list")]:
        reset(FakeResponse(200, body), show_payload("HBO"))
        check(f"network malformed: a 200 with {label} returns None",
              network("1399") is None)
        check(f"network malformed: {label} is treated as transient, so it retries",
              network("1399") == "HBO")


def test_network_unparseable_body():
    reset(FakeResponse(200, ValueError("no json")), show_payload("HBO"))
    check("network body: a 200 that doesn't parse returns None",
          network("1399") is None)
    check("network body: and is treated as transient, so it retries",
          network("1399") == "HBO")


# --- whether an episode ends the whole series --------------------------------

def test_ended_show_ends_on_its_final_episode():
    reset(show_payload("HBO", status="Ended", last=(8, 6)))
    facts = tmdb.get_show_facts("1399")
    check("ends: the last episode TMDB aired ends the series",
          facts.is_series_finale(8, 6))
    check("ends: an earlier episode of the same season does not",
          not facts.is_series_finale(8, 5))
    check("ends: the same episode number in an earlier season does not",
          not facts.is_series_finale(7, 6))


def test_cancelled_show_ends_too():
    reset(show_payload("Fox", status="Canceled", last=(1, 11)))
    check("ends: a cancelled show ends the series as much as an ended one",
          tmdb.get_show_facts("1437").is_series_finale(1, 11))


def test_returning_series_never_ends():
    # TMDB marks a *season* finale "finale" on a returning show too, so status
    # is the only thing keeping SERIES FINALE off a show that will be back.
    reset(show_payload("Fox", status="Returning Series", last=(37, 15)))
    check("ends: a returning series' latest episode is not the series' last",
          not tmdb.get_show_facts("456").is_series_finale(37, 15))


def test_show_facts_cost_one_request():
    reset(show_payload("Hulu", status="Ended", last=(4, 28)))
    for _ in range(5):
        facts = tmdb.get_show_facts("1429")
    check("ends: network and status come from the same cached response",
          facts.network == "Hulu" and facts.is_series_finale(4, 28))
    check("ends: and cost one request between them", calls() == 1, f"{calls()} calls")


def test_missing_status_or_final_episode():
    # A field TMDB didn't send can't end a series; the network still resolves.
    for body, label in [(dict(status="Ended"), "no last_episode_to_air"),
                        (dict(last=(3, 8)), "no status")]:
        reset(show_payload("HBO", **body))
        facts = tmdb.get_show_facts("1399")
        check(f"ends: {label} means no SERIES FINALE", not facts.is_series_finale(3, 8))
        check(f"ends: {label} still gives the network", facts.network == "HBO")


def test_unusable_final_episode_ends_nothing():
    cases = [
        ({"season_number": "3", "episode_number": 8}, "a string season"),
        ({"season_number": 3}, "no episode number"),
        ("S3E8", "a bare string"),
        ([3, 8], "a list"),
    ]
    for last, label in cases:
        reset(show_payload("HBO", status="Ended", last=last))
        facts = tmdb.get_show_facts("1399")
        check(f"ends: a last_episode_to_air of {label} ends nothing",
              not (facts.is_series_finale(3, 8) or facts.is_series_finale(1, 1)))


def test_bool_episode_number_does_not_end_episode_one():
    # bool is an int subclass, so an unguarded True would compare equal to 1 and
    # badge S3E1 SERIES FINALE. This is the only shape where the type check on
    # last_episode_to_air is observable at all.
    reset(show_payload("HBO", status="Ended",
                       last={"season_number": 3, "episode_number": True}))
    check("ends: episode_number True does not make S3E1 the finale",
          not tmdb.get_show_facts("1399").is_series_finale(3, 1))


def test_unusable_status_ends_nothing_without_raising():
    # A lookup must never raise (CODING_STANDARDS): a status that isn't a string
    # has to answer "not ended", not blow up the whole enrichment pass.
    for status, label in [({"name": "Ended"}, "a dict"), (["Ended"], "a list"),
                          (7, "a number")]:
        reset(show_payload("HBO", status=status, last=(3, 8)))
        facts = tmdb.get_show_facts("1399")
        check(f"ends: a status of {label} ends nothing", not facts.is_series_finale(3, 8))
        check(f"ends: a status of {label} still gives the network",
              facts.network == "HBO")


def test_unknown_show_ends_nothing():
    reset(FakeResponse(404))
    check("ends: a show TMDB doesn't have ends nothing",
          not tmdb.get_show_facts("nope").is_series_finale(1, 1))


def test_no_token_knows_nothing_about_the_show():
    reset()
    token = tmdb._API_TOKEN
    tmdb._API_TOKEN = None
    try:
        facts = tmdb.get_show_facts("1399")
        check("no token: the network is unknown", facts.network is None)
        check("no token: nothing ends the series", not facts.is_series_finale(1, 1))
        check("no token: and no request is made", calls() == 0)
    finally:
        tmdb._API_TOKEN = token


if __name__ == "__main__":
    sys.exit(run(globals()))
