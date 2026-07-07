# yamtrack-selfhosted

Self-hosted deployment config for [Yamtrack](https://github.com/FuzzyGrim/Yamtrack) (media tracker). This repo holds only the Docker Compose deployment, not the app source.

Built to migrate off TV Time, which shut down 2026-07-15.

## Locked decisions

- **Deploy:** Docker Compose. Image pinned to a specific version (currently `0.25.3`), never `latest` — so this Mac and any future host run identical builds.
- **DB:** SQLite (default), bind-mounted `./db:/yamtrack/db`. Chosen over Postgres for portability — backup is just copying a folder. Redis is required regardless (broker/cache), run as a separate container.
- **Secrets:** real `SECRET` lives in git-ignored `.env`; committed `.env.example` holds a placeholder. `.gitignore` excludes `.env` and `db/`. Never commit either.

## Deployment phases

- **Phase 2 (current):** hosted on this Mac, LAN-only, machine kept awake. No remote/internet access.
- **Phase 3 (next, active plan):** move to Oracle Cloud's "Always Free" tier — a permanently free ARM VM (`VM.Standard.A1.Flex`, 2 OCPU/12 GB as of the June 2026 limit reduction), reached exclusively via Tailscale (no public inbound ports opened, same security posture as LAN-only). Both `ghcr.io/fuzzygrim/yamtrack:0.25.3` and `redis:8-alpine` are confirmed multi-arch (`linux/amd64` + `linux/arm64` — checked via `docker manifest inspect`), so `docker-compose.yml` runs there unmodified; no image or compose changes needed for the architecture switch itself.
  - Convert the Oracle account to Pay-As-You-Go billing after signup (still $0 as long as usage stays within Always Free limits). This is required, not optional — it's what exempts the instance from Oracle's idle-instance auto-reclamation (instances idle >7 days at <20% CPU/network/memory get reclaimed), which a low-traffic personal app would likely trigger otherwise.
  - Pick a home region with reliable A1 capacity at signup — e.g. `us-ashburn-1` or `us-phoenix-1`. Can't be changed later; busy regions can return "out of host capacity" errors when provisioning the instance (retry/wait, one-time hiccup, not an ongoing issue).
  - Signup requires a card for identity verification ($1 authorization hold, refunded — not a real charge).
- **Phase 4 (optional, no longer the near-term plan):** self-owned refurb mini-PC. Since Phase 3 already solves remote access at $0, this is now optional — worth revisiting only if there's a separate reason to own the hardware, not required for Yamtrack access.

## Migration context (TV Time → Yamtrack)

- Importing TV Time history is **blocked, do not attempt**: Simkl has paused free-tier imports (PRO-only currently). The TV Time export ZIP is safe and does not expire, so the import happens later once Simkl free imports resume or a PRO plan is used.
- The app is intentionally stood up empty for now — absence of data on first run is expected, not a bug.

## Features considered and not adopted (for now)

- **Calendar / iCal subscribe:** explicitly not wanted — release dates should not show up in the personal calendar. Don't reintroduce this.
- **Apprise notifications:** not set up. Apprise has no direct APNs/native-iOS target — it would require a companion app (ntfy, Bark, or Pushover) to get a real iOS push notification, rather than a one-line config. Possible to add later if wanted, but not a current priority — no work has been done toward it.

## Layout

- `docker-compose.yml` — SQLite variant (yamtrack + redis). No Postgres variant in use.
- `.env` — real secrets, gitignored. Contains `SECRET` (Django secret key).
- `.env.example` — committed placeholder template for `.env`.
- `db/` — gitignored, created at runtime by the container (SQLite database + media).
- `backup.sh` — snapshots `db/` to `~/yamtrack-backups/` with a timestamped archive.

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
