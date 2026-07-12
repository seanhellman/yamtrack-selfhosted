import os

from flask import Flask, render_template

import queries

DB_PATH = os.environ.get("WATCHNEXT_DB_PATH", "/yamtrack/db/db.sqlite3")
USERNAME = os.environ.get("WATCHNEXT_USERNAME") or None

app = Flask(__name__)


@app.route("/")
def watch_next():
    error = None
    episodes = []
    try:
        user_id = queries.resolve_user_id(DB_PATH, USERNAME)
        episodes = queries.get_outstanding_episodes(DB_PATH, user_id)
    except Exception as exc:  # surface config/DB problems in the page, don't 500
        error = str(exc)
    return render_template("watch_next.html", episodes=episodes, error=error)


@app.route("/healthz")
def healthz():
    return {"status": "ok"}
