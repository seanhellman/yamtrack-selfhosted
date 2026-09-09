#!/usr/bin/env bash
set -euo pipefail

# Refreshes the live Yamtrack stack from git, then rebuilds and restarts it.
# Run from the Mac; every step happens over SSH.
#
# It runs here rather than on the instance because step 3 replaces the checkout's
# own files — a copy of this script running *there* would be rewritten underneath
# itself mid-pull, and bash reads scripts incrementally.
#
# NEVER run `git clean -fdx` in the remote directory. `.env`, `watchnext/.env`
# and `db/` are gitignored, which is what makes `git pull` and `git reset --hard`
# safe here, and is exactly what makes `clean -fdx` delete the live secret and
# the live database.

cd "$(dirname "$0")"

ORACLE_HOST="ubuntu@martlab"                # stable MagicDNS name (IP is ephemeral)
ORACLE_KEY="$HOME/.ssh/oracle-yamtrack.key"
REMOTE_DIR="/home/ubuntu/yamtrack"
WATCHNEXT_URL="http://localhost:8090/"

# `ubuntu` is uid 1001 and deliberately not in the `docker` group, so compose
# needs sudo. `db/` is owned by opc (uid 1000), which is what `user: "1000:1000"`
# in the compose file matches — don't chown it to make this simpler.
COMPOSE="sudo docker compose"

# Takes one pre-quoted command string, so remote word-splitting is the caller's
# to control rather than an accident of how the arguments happened to be spelled.
# BatchMode keeps a prompt from hanging an unattended run; IdentitiesOnly stops a
# loaded ssh-agent offering other keys first and tripping sshd's auth-attempt cap.
remote() { ssh -o BatchMode=yes -o IdentitiesOnly=yes -i "$ORACLE_KEY" "$ORACLE_HOST" "cd $REMOTE_DIR && $1"; }

# 1) The instance pulls `main` from `wip`, so a commit sitting unpushed on the
#    Mac cannot reach it — and the resulting no-op deploy is indistinguishable
#    from a real one unless you read the printed sha.
git fetch wip main --quiet
if [ -n "$(git rev-list wip/main..main)" ]; then
  echo "Error: local main has commits not pushed to wip." >&2
  echo "Deploying now would ship the previous commit and report success." >&2
  exit 1
fi

# 2) Refuse to deploy over a hand-edit. Untracked files are included: an
#    untracked file at a path an incoming commit adds makes `git pull` abort
#    with its own raw error, which this check exists to pre-empt. (`.env`,
#    `watchnext/.env`, `db/` and `__pycache__/` are gitignored, so they never
#    appear here.)
dirty="$(remote 'git status --porcelain')"
if [ -n "$dirty" ]; then
  echo "Error: $ORACLE_HOST:$REMOTE_DIR has local modifications:" >&2
  echo "$dirty" >&2
  echo "Resolve them on the instance before deploying." >&2
  exit 1
fi

# 3) Fast-forward only. The instance never merges; a diverged checkout is a
#    problem to look at, not one to resolve automatically.
echo "==> Pulling"
previous="$(remote 'git rev-parse HEAD')"
remote 'git pull --ff-only'

# 4) Gate the restart on the committed tests. They exist to catch the Yamtrack
#    schema and TMDB contract drift that a version bump causes, and a deploy is
#    the moment that bump lands. Stdlib-only, no virtualenv; they stub the
#    network and build their own fixture DB, so they never touch the live one.
#
#    A failed gate rolls the checkout back, because the containers are still
#    built from `$previous` — leaving HEAD ahead of them would make `git log -1`
#    lie about what is running, which is the one thing step 7 promises it does.
echo "==> Testing"
if ! remote 'for t in watchnext/tests/test_*.py; do python3 "$t" || exit 1; done'; then
  remote "git reset --hard $previous"
  echo "Error: tests failed; instance rolled back to $previous, nothing restarted." >&2
  exit 1
fi

# 5) Rebuild every buildable service, unconditionally. Docker's layer cache
#    already makes a no-op build cheap; rebuilding only what looks changed is how
#    a deploy silently skips the change you came to ship.
echo "==> Building"
remote "$COMPOSE build"

echo "==> Restarting"
remote "$COMPOSE up -d"

# 6) `up -d` returns once containers are *created*, not once they serve, and
#    `restart: unless-stopped` turns a crash at startup into a silent loop. Poll
#    until Watch Next actually answers, so a broken image fails the deploy rather
#    than being reported as one.
echo "==> Verifying"
if ! remote "for i in \$(seq 1 20); do curl -fsS -o /dev/null $WATCHNEXT_URL && exit 0; sleep 1; done; exit 1"; then
  echo "Error: Watch Next did not answer on $WATCHNEXT_URL after the restart." >&2
  remote "$COMPOSE ps" >&2
  remote "$COMPOSE logs --tail=30 watchnext" >&2
  exit 1
fi

# 7) End by stating what is now running, so the answer to "is the instance on
#    what merged?" is this script's last line rather than a file comparison.
echo
echo "Deployed to $ORACLE_HOST:$REMOTE_DIR —"
remote "git log -1 --format='  %h %s (%ci)'"
