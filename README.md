# yamtrack-selfhosted

Docker Compose deployment for [Yamtrack](https://github.com/FuzzyGrim/Yamtrack), a self-hosted media tracker (movies, TV, anime, manga, games, books, comics), built to replace TV Time. This repo holds only the deployment config, not the app source.

## Stack

- Yamtrack + Redis, pinned to a specific image version (never `latest`) for reproducible deploys.
- SQLite-backed — the database is a single bind-mounted directory (`./db`), making backup and migration a matter of copying a folder rather than managing a separate database server.
- Runs on Oracle Cloud's Always Free tier (ARM), accessed exclusively over [Tailscale](https://tailscale.com/) — no public inbound ports, no VPS bill.
- Secrets are kept out of the tracked compose file via a git-ignored `.env`.
- Ships with a small **"Watch Next" companion app** (`watchnext/`) — a separate service that reads Yamtrack's DB to show a TV Time-style list of aired-but-unwatched episodes. See [Watch Next companion app](#watch-next-companion-app).

## Prerequisites

- Docker and Docker Compose (`docker compose`, not the legacy `docker-compose`).
- `openssl` (to generate the Django secret key).
- An [Oracle Cloud](https://www.oracle.com/cloud/free/) account and [Tailscale](https://tailscale.com/) if deploying remotely (see below). Neither is needed to run this locally.

## Setup

1. Clone this repo and `cd` into it.
2. Create your `.env` from the template:
   ```bash
   cp .env.example .env
   ```
3. Generate a real secret and put it in `.env`:
   ```bash
   SECRET=$(openssl rand -base64 48)
   ```
   Edit `.env` so the `SECRET=` line contains that value. Never commit `.env`.
4. Start the stack:
   ```bash
   docker compose up -d --wait
   ```
   `--wait` blocks until the app is healthy, which the next step needs.
5. Create your account. Sign-up is closed (`REGISTRATION=False` in
   `docker-compose.yml`), so make the user directly:
   ```bash
   docker compose exec --user abc yamtrack python manage.py createsuperuser
   ```
6. Open http://localhost:8000 and log in.

The SQLite database and media files persist in `./db`, bind-mounted into the container. `db/` is git-ignored — back it up as a plain folder (see below).

### Upgrading the image version

The image is pinned in `docker-compose.yml` (e.g. `ghcr.io/fuzzygrim/yamtrack:0.25.3`), not `latest`, so upgrades are deliberate. To bump it:

1. Check https://github.com/FuzzyGrim/Yamtrack/releases for the new version number (ghcr.io tags drop the `v` prefix, e.g. release `v0.25.3` → image tag `0.25.3`).
2. Update the tag in `docker-compose.yml`.
3. `docker compose up -d` to pull and recreate the container.
4. Run the Watch Next query tests — see [Tests](#tests). Yamtrack's schema is what that app reads, so a bump can silently change its results.

## Backup / restore

### Backup

```bash
./backup.sh
```

Takes a **transactionally consistent** snapshot of the live DB over SSH/Tailscale and drops a timestamped archive in `~/yamtrack-backups/`, verified with `PRAGMA integrity_check`. The app can stay running. The DB is WAL-mode, so this uses SQLite's online backup API rather than copying the file — a plain `scp` would silently miss transactions still sitting in the `-wal` sidecar.

Runs are manual; scheduling them is not built yet.

### Restore

1. Stop the stack on the host you're restoring to: `docker compose down`.
2. Move or remove the existing `db/` directory on that host.
3. Extract the backup archive so its contents land at `./db`:
   ```bash
   mkdir -p db
   tar -xzf ~/yamtrack-backups/yamtrack-db-<timestamp>.tar.gz -C db --strip-components=1
   ```
   If restoring onto a remote host rather than locally, copy the extracted `db/db.sqlite3` there first (e.g. `scp`) before starting the stack.
4. Start the stack again: `docker compose up -d`.

## Deploying on Oracle Cloud's Always Free tier

Both `ghcr.io/fuzzygrim/yamtrack` and `redis:8-alpine` publish multi-arch images (amd64 + arm64), so this compose file runs unmodified on Oracle's free ARM shape.

1. Sign up at https://www.oracle.com/cloud/free/ (requires a card for identity verification only — a refunded $1 hold, not a charge). Pick a home region with reliable ARM capacity, e.g. `us-ashburn-1` or `us-phoenix-1`; this can't be changed later.
2. **Set up a Budget Alert** (Billing → Budgets) for a small threshold, e.g. $0.01, before provisioning anything. An email tripwire that fires on any actual or forecasted spend, so a mistake surfaces immediately instead of on a bill.
3. Convert the account to Pay-As-You-Go billing. You're still charged nothing as long as usage stays within Always Free limits, but this step is required — it exempts the instance from Oracle's idle-instance reclamation policy, which a low-traffic personal app would otherwise likely trigger.
4. Create a compute instance: shape `VM.Standard.A1.Flex` at 2 OCPU / 12 GB (the full Always Free allocation), running the **aarch64-suffixed** Ubuntu image. The console's create-instance flow has several traps here, from the non-obvious location of the shape sliders to a misleading cost estimate — [ADR-0002](docs/adr/0002-oracle-always-free-over-owned-hardware.md) lists each one and its workaround.
5. Install Docker and Docker Compose on the instance.
6. Install Tailscale on the instance and join it to your tailnet.
7. Clone this repo onto the instance — `docker-compose.yml` alone is not enough, since `build: ./watchnext` needs the whole `watchnext/` directory. Recreate `.env` there directly (don't transfer the file over an insecure channel).
8. On the instance, `docker compose up -d --wait`, then create your account with the `createsuperuser` command from [Setup](#setup). Reach the app at `http://<tailscale-hostname>:8000` (Tailscale's MagicDNS gives you a memorable hostname automatically — no need to remember an IP).
9. Once Tailscale access is confirmed working, close public exposure: delete the default security list's SSH (port 22) ingress rule from `0.0.0.0/0`. **Do not detach the instance's public IP to do this** — it is also the outbound path (OCI has no default NAT), so removing it kills outbound connectivity entirely, Tailscale included. Deleting the ingress rule closes public access without that side effect.

To migrate existing data rather than starting fresh, stop the stack on the old host, copy the `db/` directory over instead of skipping it, then start the stack on the new host — the same tar-based approach as [Backup / restore](#backup--restore) works for moving between hosts.

### Updating the instance

```bash
./deploy.sh
```

Pulls on the instance, runs the Watch Next tests there, rebuilds, restarts, and waits for the app to answer before reporting success — then prints the deployed commit, so `git log -1` on the instance answers "is it running what merged?". It refuses to run over unpushed local commits or a hand-edited instance checkout, and rolls the checkout back if a test fails.

### Access from other devices

Install Tailscale on any device you want access from (Mac, iPhone, etc.) and sign in with the same account — MagicDNS makes the instance reachable by hostname from all of them automatically, no per-device configuration needed.

## Watch Next companion app

Yamtrack's Home page lists shows that are *in progress*, but doesn't surface a plain "here are the aired episodes you haven't watched yet" list (the thing TV Time did well). `watchnext/` is a small, self-contained companion app that fills that gap — a separate container in this same compose stack, not a fork or modification of Yamtrack.

- **What it shows:** for each in-progress season, the earliest aired episode you haven't watched, with a `+N` count of how many more are backed up behind it, sorted soonest-aired-first, badged `PREMIERE` (season openers), `FINALE` / `SERIES FINALE` (season closers) or `NEW`.
- **Access:** served on port `8090`, reached over Tailscale exactly like Yamtrack itself — e.g. `http://<tailscale-hostname>:8090`. No new public exposure.
- **Episode titles and finale badges (optional):** with a TMDB API token configured (see below), each row also shows the episode's real title (e.g. `S05E01 · First Light`), and a season's last episode is badged `FINALE` — `SERIES FINALE` on the last episode a show that has ended will ever air. Without a token it degrades gracefully to number-only labels and a `NEW` badge.
- **Mark as watched (optional):** with Yamtrack credentials configured (see below), each card gets a checkmark that marks that episode watched and drops it off the list.
- **Reads the DB directly; never writes it.** Writes are rejected by SQLite itself, and the mark-watched action goes through Yamtrack's own HTTP endpoint rather than the database — so the read-only invariant holds even with marking enabled. → [ADR-0004](docs/adr/0004-read-write-mount-with-query-only.md)

It's built and started as part of the normal `docker compose up -d`. To (re)build and start just this service:

```bash
docker compose up -d --build watchnext
```

### Episode titles via TMDB (optional)

Yamtrack only stores full per-episode metadata (including the title) once an episode is watched, so unwatched "watch next" episodes have no local title. The app can fetch it from [TMDB](https://www.themoviedb.org/) on demand.

- Get a free **API Read Access Token** at https://www.themoviedb.org/settings/api (personal use).
- Create `watchnext/.env` from the template and add your token:
  ```bash
  cp watchnext/.env.example watchnext/.env   # then edit TMDB_API=...
  ```
  This file is git-ignored. The compose service loads it via `env_file` (marked optional — the app runs fine without it).
- Lookups are best-effort: any failure (no token, network error, rate limit, 404) falls back to the `SxxExx` label and never breaks the page. Only `tmdb`-source shows are looked up.
- **Attribution:** per TMDB's terms, when a token is configured the page footer shows the TMDB logo (`watchnext/static/tmdb.svg`) and the required notice. This product uses the TMDB API but is not endorsed or certified by TMDB.

### Mark as watched (optional)

Set `YAMTRACK_PASSWORD` in `watchnext/.env` to enable a checkmark on each card. Clicking it marks that episode watched, then the list re-renders (the episode drops off, or the next outstanding one for that show takes its place). It posts to the same endpoint Yamtrack's own UI uses, so Yamtrack's status cascade — episode → season → show auto-completion — runs normally. → [ADR-0005](docs/adr/0005-mark-watched-via-episode-save.md)

- **Config** (all in the git-ignored `watchnext/.env`):
  - `YAMTRACK_PASSWORD` — your Yamtrack password. Required to show the checkmark; if unset, the feature is simply hidden.
  - `YAMTRACK_USERNAME` — optional; defaults to the sole user in the DB.
  - `YAMTRACK_URL` — optional; defaults to `http://yamtrack:8000` (the compose service name).
- **Don't reuse that password elsewhere.** Enabling this stores it on the instance — git-ignored and Tailscale-only, but stored.
- **Resilience:** the session is reused across marks and silently re-established if it expires; any failure (bad credentials, Yamtrack unreachable) surfaces as an error banner and never crashes the page.

### Local development

The app can be run against a copy of the DB without Docker:

```bash
cd watchnext
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
WATCHNEXT_DB_PATH=/path/to/a/copy/of/db.sqlite3 \
  waitress-serve --host=127.0.0.1 --port=8090 app:app
```

Then open http://localhost:8090. Point `WATCHNEXT_DB_PATH` at a *copy* of the DB (e.g. one produced by `./backup.sh`) rather than a live production file. `WATCHNEXT_USERNAME` picks a specific Yamtrack user; if unset, it uses the single user in the DB. Set `TMDB_API` to also exercise episode-title lookups locally. To exercise mark-watched safely, point `YAMTRACK_URL` at a throwaway Yamtrack running against a *copy* of the DB rather than your live instance.

### Tests

```bash
python3 watchnext/tests/test_queries.py
python3 watchnext/tests/test_tmdb.py
```

Self-contained (stdlib only, builds its own fixture DB, stubs the network — no live DB, no venv). `test_queries.py` asserts the outstanding-episodes query's edge cases (gap handling, aired/status filters, badges, ordering, multi-season, empty). `test_tmdb.py` asserts the TMDB lookup — titles, the finale flag, and the fallback to a plain `SxxExx` label and an unchanged badge whenever TMDB is missing, slow, or failing.

## What it doesn't do

- **Watch Next lists TV only.** Yamtrack tracks movies, anime, manga, games, books, and comics too; the companion app's query covers TV seasons and episodes, and ignores the rest.
- **No calendar or iCal feed** of upcoming release dates.
- **No notifications** of any kind.
- **No public exposure, and no support for adding it.** There is no reverse proxy, TLS, or certificate setup here — access is over Tailscale. Putting a proxy in front requires setting `URLS` in `.env`, or CSRF and OAuth fail with 403s.
- **Single-user by default.** Watch Next resolves the sole Yamtrack user automatically; with more than one, `WATCHNEXT_USERNAME` has to name the target.
