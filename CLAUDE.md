# yamtrack-selfhosted

Self-hosted deployment config for [Yamtrack](https://github.com/FuzzyGrim/Yamtrack) (media tracker). This repo holds only the Docker Compose deployment, not the app source.

Built to migrate off TV Time, which shut down 2026-07-15.

## Locked decisions

- **Deploy:** Docker Compose. Image pinned to a specific version (currently `0.25.3`), never `latest` — so any host runs an identical, reproducible build.
- **DB:** SQLite (default), bind-mounted `./db:/yamtrack/db`. Chosen over Postgres for portability — backup/migration is just copying a folder. Redis is required regardless (broker/cache), run as a separate container.
- **Secrets:** real `SECRET` lives in git-ignored `.env`; committed `.env.example` holds a placeholder. `.gitignore` excludes `.env` and `db/`. Never commit either.

## Deployment phases

- **Phase 2 (retired 2026-07-07):** was hosted on this Mac, LAN-only. Stack stopped (`docker compose down`) once data was migrated to Phase 3 — not run going forward. Kept in history for reference only.
- **Phase 3 (current, live since 2026-07-07):** Oracle Cloud "Always Free" tier — a permanently free ARM VM, reached exclusively via Tailscale.
  - **Instance:** `VM.Standard.A1.Flex`, 2 OCPU / 12 GB (full Always Free allocation), Ubuntu 24.04 Minimal **aarch64**. Both `ghcr.io/fuzzygrim/yamtrack:0.25.3` and `redis:8-alpine` pulled natively as arm64 — confirmed multi-arch, no image/compose changes needed.
  - **Access:** Tailscale-only. The default security list's SSH (port 22) ingress rule from `0.0.0.0/0` was deleted after setup — zero public inbound exposure. MagicDNS hostname `yamtrack-vnic` (full: `yamtrack-vnic.taile99e32.ts.net`) resolves from any tailnet device — used instead of the raw Tailscale IP (`100.70.228.90` as of creation; ephemeral, can change if ever detached/reattached).
  - **SSH key:** `~/.ssh/oracle-yamtrack.key` on this Mac.
  - **Tailnet devices:** this Mac, iPhone, and the Oracle instance (`yamtrack-vnic`) itself.
  - Billing converted to Pay-As-You-Go (required for idle-instance-reclamation exemption — see below); OCI Budget Alert set at $1/absolute-$0.01-threshold as a spend tripwire.
  - `backup.sh` pulls `db.sqlite3` from this instance over SSH/Tailscale — the Mac is no longer the live host, so backups are no longer a local tar of `./db`.
- **Phase 4 (optional, no longer the near-term plan):** self-owned refurb mini-PC. Since Phase 3 already solves remote access at $0, this is optional — worth revisiting only if there's a separate reason to own the hardware.

## Oracle instance setup — real gotchas hit (read before touching this instance again)

- **Image picker lists a plain and an "aarch64"-suffixed build per Ubuntu version.** The plain one is amd64 and gets rejected by `VM.Standard.A1.Flex` ("shape not compatible with image"). Always pick the aarch64-suffixed image for this ARM shape.
- The Flex shape defaults to 1 OCPU/6 GB; the sliders to reach the full 2 OCPU/12 GB free allocation live inside the "Change shape" panel, not the main create-instance form.
- The console's "View estimated cost" button shows a non-zero figure (~$2/month) purely because the boot volume is priced at list rate there — it doesn't net out the 200 GB Always Free block storage allowance. Known display quirk, not a real forthcoming charge; actual billing (Cost Analysis) reflects the free allowance correctly.
- The "Automatically assign public IPv4 address" toggle in the instance-creation wizard got stuck disabled/off even with a public subnet selected (console state bug). Workaround: create the instance anyway, then attach an ephemeral public IP afterward via Instance → Networking → VNIC → IP Addresses → Edit → Public IP Type → Ephemeral Public IP.
- **Critical — do not remove the instance's public IP without a NAT Gateway.** OCI's public-subnet Internet Gateway model requires the instance to hold its own public IP for *outbound* internet too — unlike AWS, there's no default SNAT/NAT Gateway equivalent unless one is explicitly built. Removing the public IP (attempted once, as a hardening step) killed all outbound connectivity, which broke Tailscale entirely (it couldn't reach its coordination servers) and required attaching a fresh ephemeral IP to recover. The correct way to close public exposure instead: delete the security list's SSH (port 22) ingress rule. This doesn't touch the public IP or outbound routing, and doesn't affect Tailscale either (Tailscale traffic tunnels outside the normal VCN ingress path, so it was never gated by that rule to begin with).
- OCI's Instance Console Connection (hypervisor-level serial console, via the web console) is a genuine network-independent break-glass fallback if Tailscale and SSH are ever both unreachable. Not set up, but available if ever needed — requires its own one-time SSH key upload.

## Migration context (TV Time → Yamtrack)

- Importing TV Time history is **blocked, do not attempt**: Simkl has paused free-tier imports (PRO-only currently). The TV Time export ZIP is safe and does not expire, so the import happens later once Simkl free imports resume or a PRO plan is used.
- The app started empty and now has real (if minimal) user data from normal use — absence of TV Time history specifically is expected, not a bug.

## Features considered and not adopted (for now)

- **Calendar / iCal subscribe:** explicitly not wanted — release dates should not show up in the personal calendar. Don't reintroduce this.
- **Apprise notifications:** not set up. Apprise has no direct APNs/native-iOS target — it would require a companion app (ntfy, Bark, or Pushover) to get a real iOS push notification, rather than a one-line config. Possible to add later if wanted, but not a current priority — no work has been done toward it.

## Layout

- `docker-compose.yml` — SQLite variant (yamtrack + redis). No Postgres variant in use.
- `.env` — real secrets, gitignored. Contains `SECRET` (Django secret key) and `REGISTRATION=False`. Lives only on the Oracle instance now (regenerated there directly, never transferred from the Mac).
- `.env.example` — committed placeholder template for `.env`.
- `db/` — gitignored; historical local copy from when the Mac was the host. Live data now lives only on the Oracle instance at `~/yamtrack/db/db.sqlite3`.
- `backup.sh` — pulls `db.sqlite3` from the Oracle instance over SSH/Tailscale and snapshots it to `~/yamtrack-backups/` with a timestamp.
- `watchnext/` — the "Watch Next" companion app (Flask). Separate compose service, port 8090. See its own section below.

## Watch Next companion app (`watchnext/`)

A small Flask app that reads Yamtrack's SQLite DB to render a TV Time-style list of aired-but-unwatched episodes — the view Yamtrack's own Home page lacks. A separate compose service (`yamtrack-watchnext`, port 8090), **not** a fork of Yamtrack. Built during a `simplify`/companion-app effort after the core deployment was live.

- **Read path, not write path.** Phases 1 and 1b are read-only: open the DB and run SELECTs only (plus, in 1b, outbound GETs to TMDB). Phase 2 (mark-as-watched, not built) will POST to Yamtrack's *own* `episode_save` endpoint rather than writing the DB directly, because that endpoint has cascading status logic (episode→season→show auto-transitions) that must not be reimplemented.
- **WAL gotcha (the key technical decision):** Yamtrack's DB runs in WAL mode (verified: live `-wal`/`-shm` sidecars). A `:ro` mount or `mode=ro` connection does NOT reliably read a WAL DB — the reader must be able to update the `-shm` wal-index, and `mode=ro` only works when the `-wal` file is empty (intermittent, and silently misses uncheckpointed writes). So: mount `./db` **read/write**, run the container as **uid/gid 1000** (owner of the DB files, so it can touch the sidecars), and enforce read-only-ness in-process via `PRAGMA query_only = ON` (verified it rejects writes with `SQLITE_READONLY`). Do not "harden" this back to a `:ro` mount — it will break reads.
- **Schema facts that drove the query** (verified against the real DB, not assumed): there is no per-episode "watched" flag; a row in `app_episode` *is* a watch instance, and its `item_id` → `app_item.episode_number` gives which episode. Crucially, **episode-numbered `app_item` rows only exist for episodes already watched** — the air-date schedule for *unwatched* episodes lives on `events_event` rows attached to the *season's* `app_item`, with `content_number` standing in for episode number. The query joins in-progress `app_season` → `events_event` (aired, `content_number` not yet in the watched set). First naive version keyed off per-episode items and silently returned nothing.
- **Config:** `WATCHNEXT_DB_PATH` (default `/yamtrack/db/db.sqlite3`), `WATCHNEXT_USERNAME` (optional; defaults to the sole user), `TMDB_API` (optional; see 1b).
- **Phase 1b (BUILT):** episode titles via TMDB (`tmdb.py`). Endpoint `GET /3/tv/{media_id}/season/{n}/episode/{n}`, bearer auth with the v4 read token; `series_id` = `app_item.media_id` when `source='tmdb'`. Best-effort with in-process cache — any failure (no token / network / 404 / rate limit) falls back to `SxxExx`-only labels, never breaks the page. Token lives in a git-ignored `watchnext/.env` (an *account-tied* secret, so unlike Yamtrack's `SECRET` it can't be regenerated on the instance — the same value must exist both places; created directly on the instance, not committed). Compose loads it via optional `env_file` (`required: false`, needs Compose ≥ v2.24). Attribution: footer shows `static/tmdb.svg` + the required "not endorsed or certified by TMDB" notice whenever a token is set.
- **Phase 2 (not built):** mark-as-watched — see read/write note above.
- Full design/status: `~/.claude/plans/cached-skipping-micali.md`.

## Upstream facts (verified 2026-07-06 against github.com/FuzzyGrim/Yamtrack `release` branch, live ghcr.io registry, and GitHub Releases API)

- Image: `ghcr.io/fuzzygrim/yamtrack:<version>`, tagged without a `v` prefix (e.g. `0.25.3`, not `v0.25.3`) — confirmed directly against the ghcr.io tag list. `0.25.3` (published 2026-05-25) is the current latest release; check https://github.com/FuzzyGrim/Yamtrack/releases before bumping.
- Required env var for the Django secret key is exactly `SECRET` (not `SECRET_KEY`).
- Redis connection var is `REDIS_URL`, format `redis://{service}:{port}` — `redis://redis:6379` when Redis is the `redis` service in this same Compose file.
- Volume mount for the SQLite data dir is `./db:/yamtrack/db`.
- Full env var reference: https://fuzzygrim.github.io/Yamtrack/release/env-variables/ (note the `/release/` path segment — the unversioned `/Yamtrack/env-variables/` URL 404s, the docs site is versioned under the branch name). Covers TMDB/MAL/IGDB/etc. API keys, `URLS`/`ALLOWED_HOSTS`/`CSRF` for reverse-proxy setups, Postgres `DB_*` vars, Docker secrets `_FILE` variants, `PUID`/`PGID`, etc.
- Official upstream compose does NOT use `env_file:` — it inlines `SECRET=longstring` directly under `environment:`. This repo intentionally deviates by using `env_file: .env` instead, to keep the secret out of the tracked compose file.

## Gotchas

- `env_file: .env` is required by Compose (not optional) — if `.env` is missing, `docker compose up` fails immediately. Always regenerate it from `.env.example` before first run: `SECRET=$(openssl rand -base64 48)`.
- If adding a reverse proxy in front of this, set `URLS=https://<public-origin>` in `.env` or CSRF/OAuth will break with 403s.
