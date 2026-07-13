import os

from flask import Flask, render_template

import queries
import tmdb

DB_PATH = os.environ.get("WATCHNEXT_DB_PATH", "/yamtrack/db/db.sqlite3")
USERNAME = os.environ.get("WATCHNEXT_USERNAME") or None

app = Flask(__name__)


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
        "watch_next.html", episodes=episodes, error=error, tmdb_enabled=tmdb.enabled()
    )


@app.route("/healthz")
def healthz():
    return {"status": "ok"}
