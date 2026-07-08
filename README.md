# yamtrack-selfhosted

Docker Compose deployment for [Yamtrack](https://github.com/FuzzyGrim/Yamtrack), a self-hosted media tracker (movies, TV, anime, manga, games, books, comics). This repo holds only the deployment config, not the app source.

## Stack

- Yamtrack + Redis, pinned to a specific image version (never `latest`) for reproducible deploys.
- SQLite-backed — the database is a single bind-mounted directory (`./db`), making backup and migration a matter of copying a folder rather than managing a separate database server.
- Runs on Oracle Cloud's Always Free tier (ARM), accessed exclusively over [Tailscale](https://tailscale.com/) — no public inbound ports, no VPS bill.
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

## Notes on TV Time migration

This deployment replaces TV Time, which shut down 2026-07-15. Importing prior TV Time history is on hold — Simkl (the import path) has temporarily paused free-tier imports — so history is backfilled later. Not a functional limitation of this deployment itself.
