import logging
import os

from flask import Flask, flash, get_flashed_messages, redirect, render_template, request, url_for

import queries
import tmdb
import yamtrack_client

# waitress-serve imports this module before it configures logging, so this call
# wins; without it the root logger stays at WARNING and nothing below an
# exception is emitted.
logging.basicConfig(level=logging.INFO)

DB_PATH = os.environ.get("WATCHNEXT_DB_PATH", "/yamtrack/db/db.sqlite3")
USERNAME = os.environ.get("WATCHNEXT_USERNAME") or None

app = Flask(__name__)
# Ephemeral key — only used to sign the flash-message cookie. A fresh key each
# start just invalidates old flash cookies, which is harmless.
app.secret_key = os.urandom(32)

# When marking is enabled but no explicit Yamtrack username was given, default
# it to the sole DB user so YAMTRACK_USERNAME can be left unset.
if yamtrack_client.enabled() and not yamtrack_client.username:
    try:
        yamtrack_client.username = queries.resolve_username(DB_PATH, USERNAME)
    except Exception:
        app.logger.exception("Could not resolve a default Yamtrack username")


def _add_tmdb_facts(episodes):
    """Best-effort enrichment from TMDB: the episode title, the network the show
    airs on, and the FINALE / SERIES FINALE upgrade to the badge the database
    computed. Only tmdb-source shows are eligible; any failure leaves
    episode_title and platform as None (the template falls back to the SxxExx
    label and drops the platform line) and the badge as the database wrote it."""
    if not tmdb.enabled():
        return
    for ep in episodes:
        if ep["source"] == "tmdb":
            facts = tmdb.get_episode_facts(
                ep["media_id"], ep["season_number"], ep["episode_number"]
            )
            # The show lookup answers the platform line and the SERIES FINALE
            # upgrade from one cached response.
            show = tmdb.get_show_facts(ep["media_id"])
            ep["episode_title"] = facts.title
            ep["badge"] = queries.upgrade_badge(
                ep["badge"],
                facts.episode_type,
                show.is_series_finale(ep["season_number"], ep["episode_number"]),
            )
            ep["platform"] = show.network


def _load_episodes():
    """Fetch the outstanding-episode list. Returns (episodes, error_message)."""
    try:
        user_id = queries.resolve_user_id(DB_PATH, USERNAME)
        episodes = queries.get_outstanding_episodes(DB_PATH, user_id)
    except Exception as exc:  # surface config/DB problems in the page, don't 500
        app.logger.exception("Could not load outstanding episodes")
        return [], str(exc)
    try:
        _add_tmdb_facts(episodes)
    except Exception:
        # Titles and the finale badge are decoration. Sharing the try above
        # would let one bad TMDB response replace the whole list with an error
        # banner.
        app.logger.exception("Could not enrich episodes from TMDB")
    return episodes, None


def _wants_json():
    """True when the request came from the page's own fetch() calls."""
    return request.headers.get("X-Requested-With") == "fetch"


def _unconfirmed(media_id, season_number, episode_number):
    """Why the mark can't be called done, or None once the list confirms it.

    Deliberately a bare query rather than _load_episodes: confirming needs the
    episode numbers, not the TMDB titles, and the no-JS path would otherwise pay
    for an enrichment it throws away before redirecting.
    """
    try:
        user_id = queries.resolve_user_id(DB_PATH, USERNAME)
        outstanding = queries.get_outstanding_episodes(DB_PATH, user_id)
    except Exception as exc:
        app.logger.exception("Could not confirm the mark landed")
        return f"couldn't confirm it saved ({exc})"
    if queries.still_outstanding(outstanding, media_id, season_number, episode_number):
        app.logger.error(
            "mark_watched did not take: media %s S%sE%s still outstanding",
            media_id,
            season_number,
            episode_number,
        )
        return "Yamtrack accepted the request but the episode is still unwatched"
    return None


@app.route("/")
def watch_next():
    episodes, error = _load_episodes()
    return render_template(
        "watch_next.html",
        episodes=episodes,
        error=error,
        tmdb_enabled=tmdb.enabled(),
        # Only show the checkmark if marking can actually work: a password AND a
        # resolvable username. (Single-user always resolves; guards the multi-user
        # "password set but username unresolved" case from showing a dead button.)
        marking_enabled=yamtrack_client.enabled() and bool(yamtrack_client.username),
        flashes=get_flashed_messages(with_categories=True),
    )


@app.route("/api/episodes")
def api_episodes():
    """JSON form of the same list the page renders. Lets the client refresh in
    place instead of reloading, which would rebuild (and visibly repaint) every
    poster even when nothing changed."""
    episodes, error = _load_episodes()
    if error:
        return {"error": error}, 500
    return {"episodes": episodes}


@app.route("/mark_watched", methods=["POST"])
def mark_watched():
    error = None
    try:
        # Parsed in here so malformed form data takes the same reported path as
        # a failed save rather than surfacing as a 400/500 with no log line.
        media_id = request.form["media_id"]
        season_number = int(request.form["season_number"])
        episode_number = int(request.form["episode_number"])
        yamtrack_client.mark_watched(
            media_id, season_number, episode_number, request.form["source"]
        )
    except Exception as exc:
        app.logger.exception("mark_watched failed")
        # Falls back to the class name because an empty message would be falsy,
        # and every test below reads a falsy error as "it worked".
        error = str(exc) or type(exc).__name__

    # episode_save answers 200 even when it saved nothing, so the list has the
    # final say. → CODING_STANDARDS.md
    if not error:
        error = _unconfirmed(media_id, season_number, episode_number)

    if _wants_json():
        if error:
            return {"ok": False, "error": error}, 502
        # Hand back the refreshed list so the client can patch just the affected
        # card — no reload, and the list keeps its current order.
        episodes, load_error = _load_episodes()
        return {"ok": True, "episodes": None if load_error else episodes}

    # No-JS fallback: unchanged Post/Redirect/Get.
    if error:
        flash(f"Couldn't mark watched: {error}", "error")
    else:
        flash("Marked watched.", "success")
    return redirect(url_for("watch_next"))


@app.route("/healthz")
def healthz():
    return {"status": "ok"}
