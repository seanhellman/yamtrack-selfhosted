import sqlite3
from datetime import datetime, timezone
from typing import Optional

_OUTSTANDING_EPISODES_SQL = """
WITH in_progress_seasons AS (
    SELECT
        s.id AS season_id,
        s.related_tv_id,
        s.item_id AS season_item_id,
        si.season_number
    FROM app_season s
    JOIN app_item si ON si.id = s.item_id
    WHERE s.user_id = :user_id
      AND s.status = 'In progress'
),
-- Episode-numbered Items only exist once an episode has actually been
-- watched (created lazily by Yamtrack's own episode_save). Air-date
-- schedule instead lives on Event rows attached to the *season's* Item,
-- with content_number standing in for the episode number.
watched_episode_numbers AS (
    SELECT
        we.related_season_id AS season_id,
        wi.episode_number
    FROM app_episode we
    JOIN app_item wi ON wi.id = we.item_id
),
outstanding_episodes AS (
    SELECT
        ips.season_id,
        ips.related_tv_id,
        ips.season_number,
        ev.content_number AS episode_number,
        ev.datetime AS air_datetime,
        ROW_NUMBER() OVER (
            PARTITION BY ips.season_id
            ORDER BY ev.content_number ASC
        ) AS rn,
        COUNT(*) OVER (PARTITION BY ips.season_id) AS outstanding_count
    FROM in_progress_seasons ips
    JOIN events_event ev ON ev.item_id = ips.season_item_id
    WHERE ev.content_number IS NOT NULL
      AND ev.datetime <= :now
      AND NOT EXISTS (
          SELECT 1 FROM watched_episode_numbers w
          WHERE w.season_id = ips.season_id
            AND w.episode_number = ev.content_number
      )
)
SELECT
    tv_item.title AS show_title,
    tv_item.image AS show_image,
    tv_item.media_id AS media_id,
    tv_item.source AS source,
    oe.season_number,
    oe.episode_number,
    oe.outstanding_count
FROM outstanding_episodes oe
JOIN app_tv tv ON tv.id = oe.related_tv_id
JOIN app_item tv_item ON tv_item.id = tv.item_id
WHERE oe.rn = 1
ORDER BY oe.air_datetime ASC;
"""

_SOLE_USER_SQL = "SELECT id, username FROM users_user"


def _connect(db_path: str) -> sqlite3.Connection:
    # Yamtrack's DB runs in WAL mode. A read-only (`mode=ro`) connection or a
    # read-only filesystem mount can't read a WAL database reliably: the reader
    # needs read/write access to the `-shm`/`-wal` sidecars to attach to the
    # write-ahead log, and only sees a consistent, current snapshot that way.
    # So open a normal read/write connection, then enforce read-only-ness at the
    # engine level with `PRAGMA query_only=ON` — SQLite rejects any write with
    # SQLITE_READONLY, while WAL read coordination still works.
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def resolve_user_id(db_path: str, username: Optional[str]) -> int:
    """Look up the target user. If username isn't configured, requires
    exactly one user to exist (the expected case for this single-user
    deployment) and picks it, to avoid silently guessing wrong."""
    conn = _connect(db_path)
    try:
        if username:
            row = conn.execute(
                "SELECT id FROM users_user WHERE username = ?", (username,)
            ).fetchone()
            if row is None:
                raise ValueError(f"No Yamtrack user found with username {username!r}")
            return row["id"]

        rows = conn.execute(_SOLE_USER_SQL).fetchall()
        if len(rows) != 1:
            usernames = ", ".join(r["username"] for r in rows)
            raise ValueError(
                "WATCHNEXT_USERNAME must be set when there isn't exactly one "
                f"Yamtrack user (found: {usernames or 'none'})"
            )
        return rows[0]["id"]
    finally:
        conn.close()


def resolve_username(db_path: str, username: Optional[str]) -> str:
    """Return the Yamtrack login username. If not configured, defaults to the
    sole user in the DB (the expected single-user case). Used by the mark-watched
    client so YAMTRACK_USERNAME can be left unset."""
    if username:
        return username
    conn = _connect(db_path)
    try:
        rows = conn.execute(_SOLE_USER_SQL).fetchall()
        if len(rows) != 1:
            names = ", ".join(r["username"] for r in rows)
            raise ValueError(
                "YAMTRACK_USERNAME must be set when there isn't exactly one "
                f"Yamtrack user (found: {names or 'none'})"
            )
        return rows[0]["username"]
    finally:
        conn.close()


def get_outstanding_episodes(db_path: str, user_id: int) -> list[dict]:
    conn = _connect(db_path)
    try:
        # Match the DB's stored datetime format exactly ("YYYY-MM-DD HH:MM:SS",
        # naive UTC — Django stores timezone-aware datetimes as naive UTC in
        # SQLite) so the string comparison in the query is unambiguous.
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        rows = conn.execute(
            _OUTSTANDING_EPISODES_SQL,
            {"user_id": user_id, "now": now},
        ).fetchall()
    finally:
        conn.close()

    episodes = []
    for row in rows:
        episodes.append(
            {
                "show_title": row["show_title"],
                "show_image": row["show_image"],
                "media_id": row["media_id"],
                "source": row["source"],
                "season_number": row["season_number"],
                "episode_number": row["episode_number"],
                "outstanding_count": row["outstanding_count"],
                "badge": "PREMIERE" if row["episode_number"] == 1 else "NEW",
                "episode_title": None,  # filled in by the TMDB lookup (Phase 1b)
            }
        )
    return episodes
