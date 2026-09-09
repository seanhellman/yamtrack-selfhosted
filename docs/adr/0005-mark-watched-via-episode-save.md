# ADR-0005: Mark episodes watched through Yamtrack's `episode_save`, not a DB write

Two alternatives were considered for the mark-watched action. Writing the SQLite database directly would mean reimplementing Yamtrack's episode → season → show status cascade, which lives in `Episode.save()` at the model level. Yamtrack's token webhook was rejected as fragile: it needs a per-episode IMDB lookup and a faked Jellyfin payload.

Because the cascade fires at the model level, both `episode_save` and the webhooks trigger it — so `episode_save` was chosen for precise targeting (an exact TMDB id, season, and episode), not because it is uniquely safe. Its cost is holding a Yamtrack password in the companion's environment, accepted because the app already has filesystem access to the same database.
