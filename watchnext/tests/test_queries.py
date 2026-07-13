"""Self-contained edge-case tests for the outstanding-episodes query.

Run: `python watchnext/tests/test_queries.py` (no deps, no live DB, no network).

Why this exists: the query in queries.py is coupled to Yamtrack's DB schema
(app_season / app_item / events_event.content_number / app_episode). If you bump
the pinned Yamtrack image and that schema shifts, the query can go silently wrong
(wrong/stale "watch next" list, no error). This builds a minimal fixture DB and
asserts the behaviors that matter, so a drift shows up as a failing test here.
"""

import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import queries

now = datetime.now(timezone.utc)
def ago(days): return (now - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
def ahead(days): return (now + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
TS = now.strftime("%Y-%m-%d %H:%M:%S")

# Minimal subset of Yamtrack's schema — only the columns the query touches.
SCHEMA = """
CREATE TABLE users_user (id INTEGER PRIMARY KEY, username TEXT);
CREATE TABLE app_item (id INTEGER PRIMARY KEY, media_type TEXT, title TEXT, image TEXT,
    season_number INTEGER, episode_number INTEGER, source TEXT, media_id TEXT);
CREATE TABLE app_tv (id INTEGER PRIMARY KEY, user_id INTEGER, status TEXT, item_id INTEGER);
CREATE TABLE app_season (id INTEGER PRIMARY KEY, status TEXT, user_id INTEGER,
    related_tv_id INTEGER, item_id INTEGER);
CREATE TABLE app_episode (id INTEGER PRIMARY KEY, related_season_id INTEGER, item_id INTEGER);
CREATE TABLE events_event (id INTEGER PRIMARY KEY, item_id INTEGER, datetime TEXT, content_number INTEGER);
"""


class Fixture:
    def __init__(self, db):
        self.db = db
        self.uid = db.execute("INSERT INTO users_user (username) VALUES ('me')").lastrowid

    def _item(self, mt, mid, title, season=None, ep=None):
        return self.db.execute(
            "INSERT INTO app_item (media_type,title,image,season_number,episode_number,source,media_id)"
            " VALUES (?,?,?,?,?,?,?)", (mt, title, "img", season, ep, "tmdb", mid)).lastrowid

    def show(self, mid, title, tv_status, seasons):
        """seasons = {season_no: (status, [(ep_no, air_or_None, watched_bool), ...])}"""
        tv_item = self._item("tv", mid, title)
        tv_id = self.db.execute(
            "INSERT INTO app_tv (user_id,status,item_id) VALUES (?,?,?)",
            (self.uid, tv_status, tv_item)).lastrowid
        for sno, (sstatus, eps) in seasons.items():
            s_item = self._item("season", mid, title, season=sno)
            s_id = self.db.execute(
                "INSERT INTO app_season (status,user_id,related_tv_id,item_id) VALUES (?,?,?,?)",
                (sstatus, self.uid, tv_id, s_item)).lastrowid
            for (eno, air, watched) in eps:
                if air is not None:
                    self.db.execute(
                        "INSERT INTO events_event (item_id,datetime,content_number) VALUES (?,?,?)",
                        (s_item, air, eno))
                if watched:
                    e_item = self._item("episode", mid, title, season=sno, ep=eno)
                    self.db.execute(
                        "INSERT INTO app_episode (related_season_id,item_id) VALUES (?,?)",
                        (s_id, e_item))
        self.db.commit()


def build(path):
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    f = Fixture(db)
    # Gap: E1,E3 watched, E2 not, all aired -> earliest outstanding is E2 (not E4).
    f.show("gap", "Gap", "In progress", {1: ("In progress", [
        (1, ago(10), True), (2, ago(10), False), (3, ago(10), True),
        (4, ago(3), False), (5, ago(3), False)])})
    # Aired filter: E1 aired, E2 future -> only E1 counts.
    f.show("future", "Future", "In progress", {1: ("In progress", [
        (1, ago(3), False), (2, ahead(7), False)])})
    # Premiere badge on E1.
    f.show("prem", "Premiere", "In progress", {1: ("In progress", [(1, ago(3), False)])})
    # Status filter: none of these appear despite aired-unwatched episodes.
    for st in ("Paused", "Planning", "Dropped", "Completed"):
        f.show(st.lower(), st, st, {1: (st, [(1, ago(3), False)])})
    # Ordering: earlier-airing next episode sorts first.
    f.show("late", "Late", "In progress", {1: ("In progress", [(1, ago(1), False)])})
    f.show("early", "Early", "In progress", {1: ("In progress", [(1, ago(9), False)])})
    # Multi-season: two in-progress seasons -> two cards.
    f.show("multi", "Multi", "In progress", {
        1: ("In progress", [(1, ago(9), False)]),
        2: ("In progress", [(1, ago(3), False)])})
    db.close()
    return f.uid


passes = fails = 0
def check(label, cond, detail=""):
    global passes, fails
    passes, fails = passes + bool(cond), fails + (not cond)
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")


def main():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "fixture.sqlite3")
        uid = build(path)
        eps = queries.get_outstanding_episodes(path, uid)
        by = {e["show_title"]: e for e in eps}
        titles = [e["show_title"] for e in eps]

        g = by.get("Gap")
        check("gap: earliest outstanding is E2 (not E4)", g and g["episode_number"] == 2)
        check("gap: +N counts E2,E4,E5 => count 3", g and g["outstanding_count"] == 3)
        check("gap: E2 badged NEW", g and g["badge"] == "NEW")
        fut = by.get("Future")
        check("aired filter: only E1 (future E2 excluded)",
              fut and fut["episode_number"] == 1 and fut["outstanding_count"] == 1)
        check("premiere: E1 badged PREMIERE", by.get("Premiere", {}).get("badge") == "PREMIERE")
        for st in ("Paused", "Planning", "Dropped", "Completed"):
            check(f"status filter: {st} excluded", st not in by)
        if "Early" in titles and "Late" in titles:
            check("ordering: earlier-airing sorts first", titles.index("Early") < titles.index("Late"))
        else:
            check("ordering: both order shows present", False)
        check("multi-season: two cards", sum(t == "Multi" for t in titles) == 2)
        check("empty: no outstanding in an empty DB returns []",
              _empty_returns_empty())

    print(f"\n==== {passes} passed, {fails} failed ====")
    return 1 if fails else 0


def _empty_returns_empty():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "empty.sqlite3")
        db = sqlite3.connect(path)
        db.executescript(SCHEMA)
        uid = db.execute("INSERT INTO users_user (username) VALUES ('me')").lastrowid
        db.commit(); db.close()
        return queries.get_outstanding_episodes(path, uid) == []


if __name__ == "__main__":
    sys.exit(main())
