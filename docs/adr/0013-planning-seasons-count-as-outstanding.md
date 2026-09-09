# ADR-0013: A Planning season counts as outstanding

The Watch Next query originally selected seasons whose status was `In progress`, on the reading that a season you have started but not finished is exactly what the list is for. That silently excluded every season that had just begun airing.

Yamtrack's `reload_calendar` job creates a newly-scheduled season as **Planning**, and nothing promotes it: the status flips to `In progress` only when an episode is marked watched, which is the very action the card exists to prompt. So a returning show stayed invisible for the whole window it most needed to be visible — Ted Lasso S4 had three aired, unwatched episodes and no card. [ADR-0009](0009-two-level-status-model.md) anticipated the reopen but tracked it at the show level, where `app_tv.status` does become `In progress`; the season underneath does not.

The filter is therefore `s.status IN ('In progress', 'Planning')`. `Paused`, `Dropped` and `Completed` stay excluded, and that exclusion is doing real work — seven Paused seasons in the live data carry eight aired unwatched episodes each and would swamp the list.

Widening it costs one carve-out. Dropping a show used to suppress it for free, because every season of a dropped show is itself Dropped; a season scheduled *after* the drop is Planning, and would put a show back on the list precisely because it was still being followed when it was dropped. So the query also joins `app_tv` to exclude a Planning season whose show is Dropped. A season already under way when the show was dropped is left alone — it was visible before this change, and how it behaves is not this decision's business.

## Consequences

Planning is also where a manually-added, never-started show lands, so those now appear too — The Vampire Lestat arrived this way. That is accepted rather than worked around: a show on the watchlist with aired episodes is a reasonable thing to be offered next, and Dropped is the only status carrying an explicit "stop showing me this".
