# ADR-0008: Import TV Time history via Yamtrack's native CSV importer, not Simkl

Simkl was the obvious route and had paused free-tier imports, so the TV Time GDPR export was converted straight into Yamtrack's own CSV importer instead. Yamtrack ingests only `source=tmdb` — its `tvdb.py` provider is an internal TVDB→TMDB translator needing a `TVDB_API` key this deployment does not set — so every watched episode had to be mapped from TVDB ids to TMDB through TMDB's `find` API (episode-level `tvdb_id` → `tv_episode_results` for 4,758 of them; the series map plus TV Time's own season/episode numbering for the rest).

The importer bulk-creates, which bypasses `Episode.save()`'s status cascade. The CSV therefore has to carry explicit `tv`, `season`, and `episode` rows, with status set from the CSV rather than derived — see [ADR-0009](0009-two-level-status-model.md) for how it is computed.

## Consequences

Exactly 7 episodes (0.14%) cannot be imported: they do not exist in TMDB's numbering, either because TVDB numbers past a season's TMDB length (Brooklyn Nine-Nine S8E10, where TMDB's S8 has 9) or because they are "episode 0" specials. Any TMDB-based path loses these, Simkl included. No episode was mis-mapped onto a wrong number — the failures drop rather than corrupt.

Landed 2026-07-14: 172 shows, 446 seasons, 4,983 episodes, with real watch dates from 2020 to 2026. Rollback backups bracket the live import in `~/yamtrack-backups/` (pre-import `...224806`, post-import `...231041`).

The importer is reached at Settings → Import → **Yamtrack CSV**. Mode **New** is the non-destructive one — it skips shows already tracked — and is what this import used.
