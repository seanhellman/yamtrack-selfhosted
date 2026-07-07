# yamtrack-selfhosted

Docker Compose deployment for [Yamtrack](https://github.com/FuzzyGrim/Yamtrack), a self-hosted media tracker (movies, TV, anime, manga, games, books, comics). This repo holds only the deployment config, not the app source.

## Stack

- Yamtrack + Redis, pinned to a specific image version (never `latest`) for reproducible deploys.
- SQLite-backed — the database is a single bind-mounted directory (`./db`), making backup and migration a matter of copying a folder rather than managing a separate database server.
- Runs on Oracle Cloud's Always Free tier (ARM), accessed over [Tailscale](https://tailscale.com/) rather than a public IP — no exposed ports, no VPS bill.
- Secrets are kept out of the tracked compose file via a git-ignored `.env`.

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

This tars up `./db` and drops a timestamped archive in `~/yamtrack-backups/`. The app can stay running while you do this — SQLite handles concurrent reads fine for a personal-scale backup snapshot.

### Restore

1. Stop the stack: `docker compose down`.
2. Move or remove the existing `db/` directory.
3. Extract the backup archive so its contents land at `./db`:
   ```bash
   mkdir -p db
   tar -xzf ~/yamtrack-backups/yamtrack-db-<timestamp>.tar.gz -C db --strip-components=1
   ```
4. Start the stack again: `docker compose up -d`.

## Deploying on Oracle Cloud's Always Free tier

Both `ghcr.io/fuzzygrim/yamtrack` and `redis:8-alpine` publish multi-arch images (amd64 + arm64), so this compose file runs unmodified on Oracle's free ARM shape — no changes needed for the architecture.

1. Sign up at https://www.oracle.com/cloud/free/ (requires a card for identity verification only — a refunded $1 hold, not a charge). Pick a home region with reliable ARM capacity, e.g. `us-ashburn-1` or `us-phoenix-1`; this can't be changed later.
2. Convert the account to Pay-As-You-Go billing. You're still charged nothing as long as usage stays within Always Free limits, but this step is required — it exempts the instance from Oracle's idle-instance reclamation policy, which a low-traffic personal app would otherwise likely trigger.
3. Create a compute instance: shape `VM.Standard.A1.Flex`, Ubuntu image, using the full Always Free allocation (2 OCPU / 12 GB). If instance creation fails with "Out of host capacity," retry, try a different availability domain, or wait — this is a one-time provisioning hiccup, not an ongoing problem once the instance exists.
4. Install Docker and Docker Compose on the instance.
5. Install Tailscale on the instance and join it to your tailnet. Don't open any public inbound ports — access is Tailscale-only.
6. Copy `docker-compose.yml` to the instance, and recreate `.env` there directly (don't transfer the file over an insecure channel).
7. `docker compose up -d`, then reach the app at `http://<tailscale-hostname-or-ip>:8000`.

To migrate existing data rather than starting fresh, stop the stack on the old host, copy the `db/` directory over instead of skipping it, then start the stack on the new host — the same tar-based approach as [Backup / restore](#backup--restore) works for moving between hosts.

## Notes on TV Time migration

This deployment replaces TV Time, which shut down 2026-07-15. Importing prior TV Time history is on hold — Simkl (the import path) has temporarily paused free-tier imports — so the app starts empty and history is backfilled later. Not a functional limitation of this deployment itself.
