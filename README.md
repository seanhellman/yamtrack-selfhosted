# yamtrack-selfhosted

Docker Compose deployment for [Yamtrack](https://github.com/FuzzyGrim/Yamtrack), a self-hosted media tracker (movies, TV, anime, manga, games, books, comics). This repo holds only the deployment config, not the app source.

Built to replace TV Time, which shut down 2026-07-15.

## What this is

- A pinned-version, SQLite-backed Yamtrack + Redis stack, run via `docker compose`.
- Currently hosted on a local Mac, LAN-only (Phase 2). A move to a dedicated mini-PC with Tailscale for remote access is planned but deferred (Phase 3) — see below.
- Started **empty**. TV Time history import is deliberately not part of this setup yet (see [Migration status](#migration-status)).

## Prerequisites

- Docker and Docker Compose (`docker compose`, not the legacy `docker-compose`).
- `openssl` (to generate the Django secret key).

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

## Migration status

Importing TV Time history is **blocked for now**: Simkl has paused free-tier imports (PRO-only currently). The TV Time export ZIP doesn't expire, so this is just deferred, not lost — it'll be imported once Simkl free imports resume or a PRO plan is used. Until then, the app runs empty and entries are added manually or via other supported [import sources](https://fuzzygrim.github.io/Yamtrack/release/media-imports/).

## Phase 3 (deferred): migrating to a dedicated host

Currently deferred because a suitable refurb mini-PC is more expensive than justified right now (RAM prices). When that changes:

1. On the new host, install Docker and Docker Compose.
2. Copy `docker-compose.yml` and the entire `db/` directory to the new machine (same relative layout).
3. Recreate `.env` on the new host (from `.env.example` plus the real `SECRET` — do not reuse the old `.env` file over an insecure channel; copy it directly or regenerate).
4. Install [Tailscale](https://tailscale.com/) on the new host and join it to your tailnet, for remote access without a VPS or public port exposure.
5. `docker compose up -d` on the new host; verify data is intact before decommissioning the old one.
6. If exposing Yamtrack beyond the tailnet later, set `URLS` in `.env` per the [env var docs](https://fuzzygrim.github.io/Yamtrack/release/env-variables/) — not needed for LAN/Tailscale-only access.
