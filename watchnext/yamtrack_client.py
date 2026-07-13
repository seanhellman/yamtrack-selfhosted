"""Minimal client that marks an episode watched by driving Yamtrack's own
web endpoints — the same path Yamtrack's UI uses.

Why go through Yamtrack rather than writing the DB directly: creating an
`Episode` triggers Yamtrack's model-level status cascade (episode -> season ->
show auto-completion). Reproducing that outside Yamtrack would be fragile and
drift over time. So this logs in as the user (allauth session + CSRF) and POSTs
to `/episode_save`. The companion app's own SQLite connection stays strictly
read-only (PRAGMA query_only); the only writes happen here, over HTTP.

Auth is optional: with no YAMTRACK_PASSWORD set, `enabled()` is False and the
UI simply doesn't show the mark-watched control.
"""

import logging
import os
import re
import threading
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

BASE_URL = os.environ.get("YAMTRACK_URL", "http://yamtrack:8000").rstrip("/")
_PASSWORD = os.environ.get("YAMTRACK_PASSWORD") or None

# Login username. Defaults to the sole DB user (filled in by app.py via
# queries.resolve_username) when YAMTRACK_USERNAME is unset.
username = os.environ.get("YAMTRACK_USERNAME") or None

_TIMEOUT = 8
_CSRF_INPUT_RE = re.compile(r'name="csrfmiddlewaretoken"\s+value="([^"]+)"')

# waitress serves on multiple threads; requests.Session isn't safe for
# concurrent use and login must not race, so serialize all of it.
_lock = threading.Lock()
_session = None


def enabled() -> bool:
    """Whether mark-watched is configured (a password is available)."""
    return _PASSWORD is not None


def _login(session):
    """Establish an authenticated Yamtrack session. Raises on failure."""
    login_url = f"{BASE_URL}/accounts/login/"

    resp = session.get(login_url, timeout=_TIMEOUT)
    resp.raise_for_status()
    match = _CSRF_INPUT_RE.search(resp.text)
    if not match:
        raise RuntimeError("Could not find CSRF token on the Yamtrack login page")

    resp = session.post(
        login_url,
        data={
            "login": username,
            "password": _PASSWORD,
            "csrfmiddlewaretoken": match.group(1),
        },
        headers={"Referer": login_url},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()

    # allauth redirects away from the login page on success and sets a session
    # cookie; a failed login re-renders the login page (still 200).
    if _on_login_page(resp) or "sessionid" not in session.cookies:
        raise RuntimeError(
            "Yamtrack login failed — check YAMTRACK_USERNAME / YAMTRACK_PASSWORD"
        )
    logger.info("Logged in to Yamtrack as %s", username)


def _post_episode_save(session, payload):
    return session.post(
        f"{BASE_URL}/episode_save",
        data=payload,
        headers={
            "X-CSRFToken": session.cookies.get("csrftoken", ""),
            "Referer": f"{BASE_URL}/",
        },
        timeout=_TIMEOUT,
    )


def _on_login_page(resp) -> bool:
    return resp.url.rstrip("/").endswith("/accounts/login")


def _auth_failed(resp) -> bool:
    # login-required middleware redirects unauthenticated POSTs to the login
    # page (followed to a 200), and a stale CSRF yields a 403.
    return resp.status_code == 403 or _on_login_page(resp)


def mark_watched(media_id, season_number, episode_number, source):
    """Mark one episode watched (end_date = now). Raises on any failure."""
    if not enabled():
        raise RuntimeError("Marking is not configured (no YAMTRACK_PASSWORD set)")
    if not username:
        raise RuntimeError("No Yamtrack username configured or resolvable")

    payload = {
        "media_id": str(media_id),
        "season_number": str(season_number),
        "episode_number": str(episode_number),
        "source": source,
        # TRACK_TIME defaults to True upstream, so episode_save expects a
        # datetime-local value. Container TZ is set to match Yamtrack's.
        "end_date": datetime.now().strftime("%Y-%m-%dT%H:%M"),
    }

    global _session
    with _lock:
        if _session is None:
            _session = requests.Session()
            _login(_session)

        resp = _post_episode_save(_session, payload)
        if _auth_failed(resp):
            # Session likely expired — re-login once and retry.
            logger.info("Yamtrack session stale; re-authenticating and retrying")
            _login(_session)
            resp = _post_episode_save(_session, payload)

        if _auth_failed(resp) or resp.status_code >= 400:
            raise RuntimeError(f"episode_save failed (HTTP {resp.status_code})")

    logger.info(
        "Marked watched: media %s S%sE%s", media_id, season_number, episode_number
    )
