import os

from flask import Flask, flash, get_flashed_messages, redirect, render_template, request, url_for

import queries
import tmdb
import yamtrack_client

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


def _add_titles(episodes):
    """Best-effort enrich each episode with a TMDB title. Only tmdb-source
    shows are eligible; any failure leaves episode_title as None and the
    template falls back to the SxxExx label."""
    if not tmdb.enabled():
        return
    for ep in episodes:
        if ep["source"] == "tmdb":
            ep["episode_title"] = tmdb.get_episode_title(
                ep["media_id"], ep["season_number"], ep["episode_number"]
            )


@app.route("/")
def watch_next():
    error = None
    episodes = []
    try:
        user_id = queries.resolve_user_id(DB_PATH, USERNAME)
        episodes = queries.get_outstanding_episodes(DB_PATH, user_id)
        _add_titles(episodes)
    except Exception as exc:  # surface config/DB problems in the page, don't 500
        error = str(exc)
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


@app.route("/mark_watched", methods=["POST"])
def mark_watched():
    try:
        yamtrack_client.mark_watched(
            request.form["media_id"],
            int(request.form["season_number"]),
            int(request.form["episode_number"]),
            request.form["source"],
        )
        flash("Marked watched.", "success")
    except Exception as exc:
        app.logger.exception("mark_watched failed")
        flash(f"Couldn't mark watched: {exc}", "error")
    # Post/Redirect/Get: re-run the query so the list reflects the change.
    return redirect(url_for("watch_next"))


@app.route("/healthz")
def healthz():
    return {"status": "ok"}
