# ADR-0009: Two-level, data-driven status model for the imported history

Status was computed from the watch data rather than carried over from TV Time. A *season* is In progress when its own aired episodes are incomplete (`watched < aired`, or still-airing with `total > aired`) and Completed otherwise. A *show* is In progress if any of its seasons is, and Completed if none are.

That makes a caught-up but still-Returning series **Completed**, which is deliberate: it lets Yamtrack's `reload_calendar` reopen mechanism auto-create a Planning season and flip the show back to In progress once the next season is actually scheduled, rather than leaving it permanently half-finished. Only the *show* flips, though; the reopened season stays Planning. → [ADR-0013](0013-planning-seasons-count-as-outstanding.md). Shows unfollowed in TV Time became Dropped.

## Consequences

Three exclusions were made deliberately, and each is visible in the data:

- **Season-0 specials dropped** (31 episodes). TMDB's season 0 is a grab-bag that floods the Watch Next list.
- **RuPaul's Drag Race All Stars** (id 67482) left out of the CSV entirely, handled by hand, because the live instance already had recent All Stars watches that TV Time lacked.
- **34 "haven't started" / watchlist shows skipped** — this was a history-only import.

A skipped or unstarted season is invisible to the status rules by design, so some shows read Completed despite an unwatched season: Altered Carbon, for instance, with S2 never started.
