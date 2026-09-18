"""Self-contained tests for the mark-watched HTTP client.

Run: `python watchnext/tests/test_yamtrack_client.py` (no deps, no network).

Why this exists: a Yamtrack session lasts 14 days, so every path here is one the
app takes a few times a year and nobody watches. When the expiry went undetected
the app reported success for a week of marks that saved nothing — the failure
these pin is silent by construction, which is exactly why it needs a test.

What is pinned: an expired session is recognised however Django dresses the
bounce (the `?next=` query is what defeated the original check), it costs exactly
one re-login and one retry, a retry that fails again raises rather than passing
the failure off as success, and the healthy path stays at one request.

`requests` is stubbed into sys.modules before yamtrack_client is imported, so
this runs on a bare interpreter with no virtualenv and can never reach the
network.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import check, run  # noqa: E402  (needs the path above)

# The no-network guarantee only holds if nothing imported these first — an
# already-imported yamtrack_client keeps its binding to the real `requests`.
assert "yamtrack_client" not in sys.modules and "requests" not in sys.modules, (
    "yamtrack_client/requests were imported before the stub; these tests would "
    "hit the network"
)

BASE = "http://yamtrack:8000"
LOGIN_PAGE = '<input name="csrfmiddlewaretoken" value="tok123">'

# What Django's LoginRequiredMiddleware redirects an expired POST to. The query
# string is the whole point: matching it against the end of the URL fails.
BOUNCED = BASE + "/accounts/login/?next=/episode_save"


class FakeResponse:
    def __init__(self, url, status_code=200, text=""):
        self.url = url
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise FakeHTTPError(f"HTTP {self.status_code}")


class FakeHTTPError(Exception):
    pass


class FakeSession:
    """Scripted session. `responses` maps (method, path) to a list of replies,
    popped in order, so a test says what the *second* save attempt answers. The
    last reply repeats, which is how "it keeps bouncing" is expressed."""

    def __init__(self, responses):
        self.responses = responses
        self.cookies = {}
        self.calls = []

    def _reply(self, method, url):
        call = (method, url[len(BASE):])
        self.calls.append(call)
        queued = self.responses[call]
        return queued.pop(0) if len(queued) > 1 else queued[0]

    def get(self, url, timeout=None):
        return self._reply("GET", url)

    def post(self, url, data=None, headers=None, timeout=None):
        resp = self._reply("POST", url)
        # allauth hands back a session cookie only when the login succeeds,
        # which is also when it redirects away from the login page.
        if url.endswith("/accounts/login/") and not resp.url.endswith("/accounts/login/"):
            self.cookies["sessionid"] = "abc"
        return resp


class FakeRequests:
    """Stands in for the `requests` module; the client uses only Session."""

    Session = None  # set per-test to a factory returning the scripted session


sys.modules["requests"] = FakeRequests

os.environ["YAMTRACK_PASSWORD"] = "hunter2"
os.environ["YAMTRACK_USERNAME"] = "sean"

import yamtrack_client  # noqa: E402  (needs the stub above)


def _install(responses):
    """Point the client at a fresh scripted session and return it."""
    session = FakeSession(responses)
    FakeRequests.Session = lambda: session
    yamtrack_client._session = None
    return session


def _login_ok():
    """A login that always works: the form carries a CSRF token, and posting it
    redirects away from the login page."""
    return {
        ("GET", "/accounts/login/"): [
            FakeResponse(BASE + "/accounts/login/", text=LOGIN_PAGE)
        ],
        ("POST", "/accounts/login/"): [FakeResponse(BASE + "/", text="home")],
    }


def _mark():
    yamtrack_client.mark_watched(97546, 4, 4, "tmdb")


def test_healthy_mark_posts_once():
    responses = _login_ok()
    responses[("POST", "/episode_save")] = [FakeResponse(BASE + "/")]
    session = _install(responses)

    _mark()

    posts = [c for c in session.calls if c == ("POST", "/episode_save")]
    check("healthy mark posts episode_save exactly once", len(posts) == 1, str(session.calls))
    check(
        "healthy mark logs in exactly once",
        len([c for c in session.calls if c == ("POST", "/accounts/login/")]) == 1,
    )


def test_expired_session_is_detected_and_retried():
    responses = _login_ok()
    # First POST bounces to the login page; after re-login the retry lands.
    responses[("POST", "/episode_save")] = [
        FakeResponse(BOUNCED),
        FakeResponse(BASE + "/"),
    ]
    session = _install(responses)

    _mark()  # raises if the bounce went unnoticed and was called a success

    saves = [c for c in session.calls if c == ("POST", "/episode_save")]
    logins = [c for c in session.calls if c == ("POST", "/accounts/login/")]
    check("expired session retries the save once", len(saves) == 2, str(session.calls))
    check("expired session re-logs-in once", len(logins) == 2, str(session.calls))


def test_bounce_is_not_reported_as_success():
    responses = _login_ok()
    # Yamtrack keeps refusing the session even though the login succeeds.
    responses[("POST", "/episode_save")] = [FakeResponse(BOUNCED)]
    _install(responses)

    raised = None
    try:
        _mark()
    except Exception as exc:
        raised = exc
    check("a save that only ever reaches the login page raises", raised is not None)


def test_failed_login_raises():
    responses = _login_ok()
    # A wrong password re-renders the login page instead of redirecting away.
    responses[("POST", "/accounts/login/")] = [
        FakeResponse(BASE + "/accounts/login/", text=LOGIN_PAGE)
    ]
    responses[("POST", "/episode_save")] = [FakeResponse(BASE + "/")]
    session = _install(responses)

    raised = None
    try:
        _mark()
    except Exception as exc:
        raised = exc
    check("a login that never leaves the login page raises", raised is not None)
    check(
        "a failed login never posts the save",
        ("POST", "/episode_save") not in session.calls,
        str(session.calls),
    )


def test_csrf_rejection_is_retried():
    responses = _login_ok()
    responses[("POST", "/episode_save")] = [
        FakeResponse(BASE + "/episode_save", status_code=403),
        FakeResponse(BASE + "/"),
    ]
    session = _install(responses)

    _mark()

    saves = [c for c in session.calls if c == ("POST", "/episode_save")]
    check("a 403 retries the save once", len(saves) == 2, str(session.calls))


def test_bad_request_raises():
    responses = _login_ok()
    # episode_save answers 400 when its form doesn't validate.
    responses[("POST", "/episode_save")] = [
        FakeResponse(BASE + "/episode_save", status_code=400)
    ]
    _install(responses)

    raised = None
    try:
        _mark()
    except Exception as exc:
        raised = exc
    check("a 400 from episode_save raises", raised is not None)


if __name__ == "__main__":
    sys.exit(run(dict(globals())))
