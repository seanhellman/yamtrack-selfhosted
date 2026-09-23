# yamtrack-selfhosted

Self-hosted deployment config for [Yamtrack](https://github.com/FuzzyGrim/Yamtrack) (media tracker). This repo holds only the Docker Compose deployment, not the app source. Built to migrate off TV Time, which shut down 2026-07-15.

**Before editing anything under `watchnext/` or `docker-compose.yml`, read `CODING_STANDARDS.md`.**

This file holds the standing rules and the live operational facts. Settled decisions and the arguments behind them live in `docs/adr/`; open, declined, and completed work lives in the issue tracker. Both are pointed at, never repeated here.

## Locked decisions

- **Deploy:** Docker Compose, image pinned to an explicit version, never `latest`.
- **DB:** SQLite (default), bind-mounted `./db:/yamtrack/db`. Redis is required regardless (broker/cache), run as a separate container. → [ADR-0001](docs/adr/0001-sqlite-over-postgres.md)
- **Secrets:** real `SECRET` lives in git-ignored `.env`; committed `.env.example` holds a placeholder. `.gitignore` excludes `.env` and `db/`. Never commit either.
- **Registration:** closed in `docker-compose.yml`, never in `.env`; the first account is made with `manage.py createsuperuser`. → [ADR-0014](docs/adr/0014-registration-closed-in-compose.md)
- **Never test against the live DB or the live instance.** Always use a copy (e.g. one produced by `backup.sh`) — that includes throwaway-Yamtrack runs and any import or migration dry-run. The single carve-out is `watchnext/tests/`, which `deploy.sh` runs on the instance: they stub the network and build their own fixture DB, so they open neither the live DB nor a live service.
- **`local/` contains PII** — the TV Time GDPR dump, with access tokens, IP addresses, and auth rows. The whole folder is git-ignored; never commit it. It also preserves the migration tooling (`tv-time-migration/convert.py`, its TMDB caches, and the CSV that was actually uploaded), so keep the folder itself.

## The live instance

Oracle Cloud "Always Free" ARM VM, live since 2026-07-07, reached exclusively via Tailscale. → [ADR-0002](docs/adr/0002-oracle-always-free-over-owned-hardware.md)

- **Shape:** `VM.Standard.A1.Flex`, Ubuntu 24.04 Minimal **aarch64**. Both `ghcr.io/fuzzygrim/yamtrack` and `redis:8-alpine` are multi-arch and pull natively as arm64 — ARM needs no image or compose changes.
- **Access:** Tailscale-only, zero public inbound — the default security list's SSH (port 22) rule from `0.0.0.0/0` was deleted after setup. Reach it at the MagicDNS name `martlab` (`martlab.taile99e32.ts.net`), never the raw Tailscale IP, which is ephemeral. SSH key is `~/.ssh/oracle-yamtrack.key` on the Mac.
- **`martlab` serves multiple apps**, not only this stack — the host is not yamtrack's alone.
- **Do not detach the instance's public IP.** It is also the *outbound* path — OCI has no default NAT Gateway — so removing it kills Tailscale entirely. → [ADR-0003](docs/adr/0003-close-ingress-not-the-public-ip.md)

## Where state lives

- **`.env` exists only on the instance**, regenerated there directly and never transferred from the Mac. Holds `SECRET` and nothing else.
- **The live DB exists only on the instance**, at `~/yamtrack/db/db.sqlite3`. `db/` is absent on the Mac; Compose would recreate it as an empty bind mount if the stack were ever run here.
- **`backup.sh` runs on the Mac** and pulls a WAL-consistent, integrity-checked snapshot to `~/yamtrack-backups/`. It uses SQLite's online backup API over SSH rather than copying the file — a plain `scp db.sqlite3` would silently miss uncheckpointed `-wal` data. Still manual → [#1](https://github.com/seanhellman/yamtrack-selfhosted/issues/1).

## How code reaches the instance

- **`~/yamtrack` is an HTTPS clone of the public repo** — no key, since the repo is public. Whatever merges to `main` is what the next deploy ships.
- **`deploy.sh` runs on the Mac** and does the whole refresh over SSH: abort on a dirty tree → pull → run `watchnext/tests/` on the instance → rebuild → `up -d` → print the deployed commit. Its comments carry the rest, including why it cannot run on the instance and the one command that must never be run there.

## Watch Next companion app (`watchnext/`)

A small Flask app that reads Yamtrack's SQLite DB to render a TV Time-style list of aired-but-unwatched episodes — the view Yamtrack's own Home page lacks. A separate compose service (`yamtrack-watchnext`, port 8090), **not** a fork of Yamtrack.

- **Schema facts that drove the query** (verified against the real DB, not assumed): there is no per-episode "watched" flag; a row in `app_episode` *is* a watch instance, and its `item_id` → `app_item.episode_number` gives which episode. Crucially, **episode-numbered `app_item` rows only exist for episodes already watched** — the air-date schedule for *unwatched* episodes lives on `events_event` rows attached to the *season's* `app_item`, with `content_number` standing in for episode number. The query joins open `app_season` → `events_event` (aired, `content_number` not yet in the watched set). A version keyed off per-episode items silently returns nothing. Which season statuses count as open is [ADR-0013](docs/adr/0013-planning-seasons-count-as-outstanding.md).
- **Reads the DB, writes over HTTP.** The container mounts `./db` read/write and runs as uid/gid 1000, with read-only-ness enforced in-process by `PRAGMA query_only`; the one write action (mark-watched) POSTs to Yamtrack's own `episode_save`. → [ADR-0004](docs/adr/0004-read-write-mount-with-query-only.md), [ADR-0005](docs/adr/0005-mark-watched-via-episode-save.md)
- **Coupling to watch on a version bump:** the app depends on three Yamtrack internals across the pinned image — the login-form HTML (`yamtrack_client.py` CSRF regex), `episode_save` field names, and the DB schema the query reads. Mark-watched fails *loudly* (error banner); the read query could go *silently* wrong. **Run `python3 watchnext/tests/test_queries.py` after bumping Yamtrack** — it is committed, stdlib-only, and asserts the query's edge cases.
- **Config:** `WATCHNEXT_DB_PATH` (default `/yamtrack/db/db.sqlite3`), `WATCHNEXT_USERNAME` (optional; defaults to the sole user), `TMDB_API`, `YAMTRACK_PASSWORD`/`YAMTRACK_USERNAME`/`YAMTRACK_URL` (all optional). Container `TZ=America/Los_Angeles`, so `end_date=now` records correct local time.
- **The TMDB token is account-tied.** Unlike Yamtrack's `SECRET` it cannot be regenerated on the instance — the same value has to exist in `watchnext/.env` in both places. Compose loads that file via optional `env_file` (`required: false`, needs Compose ≥ v2.24). Titles come from `GET /3/tv/{media_id}/season/{n}` with bearer auth on the v4 read token — one request per season, every title read out of the response's `episodes[]`, along with each episode's `episode_type`, which is what badges a card `FINALE`; `series_id` is `app_item.media_id` when `source='tmdb'`. A settled title is never re-requested and a *miss* is what re-fetches the season, held off per episode by `_REFETCH_FLOOR`. → [ADR-0010](docs/adr/0010-refetch-on-miss-not-on-a-timer.md). A numbered name (`Episode 7`) is shown as TMDB sends it and counts as settled once the episode is more than `_PLACEHOLDER_WINDOW` days past air. → [ADR-0011](docs/adr/0011-numbered-episode-names-as-sent.md). The platform line is a second lookup, `GET /3/tv/{media_id}` → the first name in `networks[]`, answered once per show and never re-asked; **not** `/watch/providers`, which is region-scoped and answers a different question. → [ADR-0012](docs/adr/0012-network-not-watch-providers.md). That same response's `status` and `last_episode_to_air` are what badge a card `SERIES FINALE`, at no extra request. `tests/test_tmdb.py` pins all of it plus the degrade-to-no-lookup paths, on a bare interpreter (3.10+) with no venv. Whenever a token is set the footer must show `static/tmdb.svg` and the required "not endorsed or certified by TMDB" notice.
- **Client/server contract:** `GET /api/episodes` returns the list as JSON, and `/mark_watched` returns JSON when the request carries `X-Requested-With: fetch`; the client patches only the cards that actually changed, and updates the form's hidden `episode_number` so the next tap targets the new episode. **The list never re-sorts as a side effect of your own tap** — server order is `ORDER BY air_datetime` on each show's next outstanding episode, applied only on a real page render. The conventions this imposes on the template and JS are in `CODING_STANDARDS.md`.
- **Cold launch is 3-4s and that is the end state**, masked by the launch splash. → [ADR-0006](docs/adr/0006-no-service-worker-cached-shell.md)
- **Launch splash:** `static/splash/` holds solid `#212529` PNGs, one per supported device, generated by a small pure-stdlib zlib/struct PNG writer. When a new iPhone flashes white, read its `(device-width, device-height, -webkit-device-pixel-ratio)` triple and add one `<link>` plus a PNG at the physical pixel size. **Testing any of this requires deleting and re-adding the Home Screen shortcut** — iOS caches icons, splash, and manifest at add-time. → [ADR-0007](docs/adr/0007-exact-per-device-startup-images.md)
- **Home Screen icon:** `app-icon/` at the repo root is the source set (its README documents each file); the shipped copies live in `watchnext/static/`. Yamtrack's own icons can't be customized without forking the pinned image — the workaround there is an iOS Shortcut that opens the URL with a custom photo as its icon.

## Upstream facts (verified 2026-07-06 against github.com/FuzzyGrim/Yamtrack `release` branch and ghcr.io; re-checked 2026-08-13)

- Image is `ghcr.io/fuzzygrim/yamtrack:<version>`, tagged without a `v` prefix (release `v0.25.3` → image tag `0.25.3`). **Don't record the latest release here** — it rots; read https://github.com/FuzzyGrim/Yamtrack/releases at the time of bumping.
- The Django secret key env var is exactly `SECRET`, not `SECRET_KEY`.
- The Redis var is `REDIS_URL`, format `redis://{service}:{port}` — `redis://redis:6379` here.
- The SQLite data dir mounts at `./db:/yamtrack/db`.
- Full env var reference: https://fuzzygrim.github.io/Yamtrack/release/env-variables/ — note the `/release/` segment, the unversioned URL 404s.
- Upstream's own compose inlines `SECRET` under `environment:`. This repo deviates deliberately — see `CODING_STANDARDS.md`.

## Gotchas

- `env_file: .env` is required by Compose, not optional — a missing `.env` fails `docker compose up` immediately. Regenerate it from `.env.example` before first run: `SECRET=$(openssl rand -base64 48)`.
- Adding a reverse proxy in front of this needs `URLS=https://<public-origin>` in `.env`, or CSRF/OAuth break with 403s.

## Agent skills

- **Issue tracker:** GitHub Issues on `seanhellman/yamtrack-selfhosted`; always pass `--repo`. It is the only tracker: planned work, declined features, and completed history all live there rather than in this file. See `docs/agents/issue-tracker.md`.
- **Triage labels:** the five canonical roles, unchanged. See `docs/agents/triage-labels.md`.
- **Domain docs:** single-context, root `CONTEXT.md` + `docs/adr/`. See `docs/agents/domain.md`.
