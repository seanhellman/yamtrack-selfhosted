# yamtrack-selfhosted

Docker Compose deployment for [Yamtrack](https://github.com/FuzzyGrim/Yamtrack), a self-hosted media tracker (movies, TV, anime, manga, games, books, comics). This repo holds only the deployment config, not the app source.

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
   docker compose up -d
   ```
5. Open http://localhost:8000 and create your account.

The SQLite database and media files persist in `./db`, bind-mounted into the container. `db/` is git-ignored — back it up as a plain folder (see below).

### Upgrading the image version

The image is pinned in `docker-compose.yml` (e.g. `ghcr.io/fuzzygrim/yamtrack:0.25.3`), not `latest`, so upgrades are deliberate. To bump it:

1. Check https://github.com/FuzzyGrim/Yamtrack/releases for the new version number (ghcr.io tags drop the `v` prefix, e.g. release `v0.25.3` → image tag `0.25.3`).
2. Update the tag in `docker-compose.yml`.
3. `docker compose up -d` to pull and recreate the container.

## Backup / restore

### Backup

```bash
./backup.sh
```

Pulls `db.sqlite3` from the live host over SSH/Tailscale and drops a timestamped archive in `~/yamtrack-backups/`. The app can stay running while you do this — SQLite handles concurrent reads fine for a personal-scale backup snapshot.

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

Both `ghcr.io/fuzzygrim/yamtrack` and `redis:8-alpine` publish multi-arch images (amd64 + arm64), so this compose file runs unmodified on Oracle's free ARM shape — confirmed via `docker manifest inspect`, no changes needed for the architecture.

1. Sign up at https://www.oracle.com/cloud/free/ (requires a card for identity verification only — a refunded $1 hold, not a charge). Pick a home region with reliable ARM capacity, e.g. `us-ashburn-1` or `us-phoenix-1`; this can't be changed later.
2. **Set up a Budget Alert** (Billing → Budgets) for a small threshold, e.g. $0.01, before provisioning anything. An email tripwire that fires on any actual or forecasted spend, so a mistake surfaces immediately instead of on a bill.
3. Convert the account to Pay-As-You-Go billing. You're still charged nothing as long as usage stays within Always Free limits, but this step is required — it exempts the instance from Oracle's idle-instance reclamation policy, which a low-traffic personal app would otherwise likely trigger.
4. Create a compute instance:
   - Shape `VM.Standard.A1.Flex`, sliders set to 2 OCPU / 12 GB (the full Always Free allocation) — the console flags this "Always Free-eligible" when configured correctly.
   - Image: the **aarch64-suffixed** Ubuntu build (e.g. "Canonical Ubuntu 24.04 Minimal aarch64"). The non-suffixed image is amd64 and will be rejected as incompatible with this ARM shape.
   - If creation fails with "Out of host capacity," retry, try a different availability domain, or wait — a one-time provisioning hiccup, not an ongoing problem once the instance exists.
   - The "View estimated cost" button may show a non-zero figure (commonly the boot volume, priced at list rate) — a known display quirk, not a real charge, as long as your config stays within the Always Free shape/storage limits above.
   - If the "Automatically assign public IPv4 address" toggle is stuck disabled even with a public subnet selected, create the instance anyway, then attach an ephemeral public IP afterward via Instance → Networking → VNIC → IP Addresses → Edit → Public IP Type → Ephemeral Public IP.
5. Install Docker and Docker Compose on the instance.
6. Install Tailscale on the instance and join it to your tailnet.
7. Copy `docker-compose.yml` to the instance, and recreate `.env` there directly (don't transfer the file over an insecure channel).
8. `docker compose up -d`, then reach the app at `http://<tailscale-hostname>:8000` (Tailscale's MagicDNS gives you a memorable hostname automatically — no need to remember an IP).
9. Once Tailscale access is confirmed working, close public exposure: delete the default security list's SSH (port 22) ingress rule from `0.0.0.0/0`. **Do not detach the instance's public IP itself to do this** — OCI's public-subnet networking model requires the instance to hold a public IP for outbound internet access too (no default NAT like AWS), so removing it kills outbound connectivity entirely, including Tailscale's own connection to its coordination servers. Closing the security list rule achieves the same goal (no public inbound access) without that side effect, since Tailscale traffic doesn't traverse the normal VCN ingress path anyway.

To migrate existing data rather than starting fresh, stop the stack on the old host, copy the `db/` directory over instead of skipping it, then start the stack on the new host — the same tar-based approach as [Backup / restore](#backup--restore) works for moving between hosts.

### Access from other devices

Install Tailscale on any device you want access from (Mac, iPhone, etc.) and sign in with the same account — MagicDNS makes the instance reachable by hostname from all of them automatically, no per-device configuration needed.

## Watch Next companion app

Yamtrack's Home page lists shows that are *in progress*, but doesn't surface a plain "here are the aired episodes you haven't watched yet" list (the thing TV Time did well). `watchnext/` is a small, self-contained companion app that fills that gap — a separate container in this same compose stack, not a fork or modification of Yamtrack.

- **Read-only.** It opens Yamtrack's own SQLite DB and runs `SELECT`s only. Because Yamtrack's DB is in WAL mode, the container mounts `./db` read/write (a WAL reader must be able to update the `-shm`/`-wal` sidecars) and runs as uid/gid `1000` (the DB files' owner), but write protection is enforced at the SQLite engine level via `PRAGMA query_only = ON` — any write is rejected with `SQLITE_READONLY`. It never modifies your data.
- **What it shows:** for each in-progress season, the earliest aired episode you haven't watched, with a `+N` count of how many more are backed up behind it, sorted soonest-aired-first, badged `PREMIERE` (season openers) or `NEW`.
- **Episode titles (optional):** with a TMDB API token configured (see below), each row also shows the episode's real title (e.g. `S05E01 · First Light`). Without a token it degrades gracefully to number-only labels.
- **Access:** served on port `8090`, reached over Tailscale exactly like Yamtrack itself — e.g. `http://<tailscale-hostname>:8090`. No new public exposure.

### Episode titles via TMDB (optional)

Yamtrack only stores full per-episode metadata (including the title) once an episode is watched, so unwatched "watch next" episodes have no local title. The app can fetch it from [TMDB](https://www.themoviedb.org/) on demand.

- Get a free **API Read Access Token** at https://www.themoviedb.org/settings/api (personal use).
- Create `watchnext/.env` from the template and add your token:
  ```bash
  cp watchnext/.env.example watchnext/.env   # then edit TMDB_API=...
  ```
  This file is git-ignored. The compose service loads it via `env_file` (marked optional — the app runs fine without it).
- Lookups are best-effort and cached in-process: any failure (no token, network error, rate limit, 404) falls back to the `SxxExx` label and never breaks the page. Only `tmdb`-source shows are looked up.
- **Attribution:** per TMDB's terms, when a token is configured the page footer shows the TMDB logo (`watchnext/static/tmdb.svg`) and the required notice. This product uses the TMDB API but is not endorsed or certified by TMDB.

It's built and started as part of the normal `docker compose up -d`. To (re)build and start just this service:

```bash
docker compose up -d --build watchnext
```

### Local development

The app can be run against a copy of the DB without Docker:

```bash
cd watchnext
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
WATCHNEXT_DB_PATH=/path/to/a/copy/of/db.sqlite3 \
  waitress-serve --host=127.0.0.1 --port=8090 app:app
```

Then open http://localhost:8090. Point `WATCHNEXT_DB_PATH` at a *copy* of the DB (e.g. one produced by `./backup.sh`) rather than a live production file. `WATCHNEXT_USERNAME` can be set to pick a specific Yamtrack user; if unset, it uses the single user in the DB (the expected case here). Set `TMDB_API` to also exercise episode-title lookups locally.

### Planned phases (not yet built)

- **Phase 2 — mark as watched:** a checkmark on each card that marks the episode watched. This will POST to Yamtrack's *own* endpoint (authenticating as you), so Yamtrack's cascading status logic runs correctly — rather than writing to the DB directly.

## Notes on TV Time migration

This deployment replaces TV Time, which shut down 2026-07-15. Importing prior TV Time history is on hold — Simkl (the import path) has temporarily paused free-tier imports — so history is backfilled later. Not a functional limitation of this deployment itself.
