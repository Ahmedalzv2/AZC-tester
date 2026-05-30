#!/usr/bin/env bash
# Auto-update the deployed AZC Tester to the latest pushed commit.
#
# Pulls the deploy branch and rebuilds the container only when the remote has
# actually moved, so it is safe to run on a tight cron/timer. The gallant
# deploy bakes code into the image (no live /root volume), so a rebuild is
# required to pick up new commits — this script does exactly that.
#
# Usage (env-overridable):
#   APP_DIR=/root/apps/backtest-lab-gallant \
#   BRANCH=claude/gallant-pasteur-7G4Of \
#   COMPOSE_FILE=docker-compose.gallant.yml \
#   scripts/update.sh
set -euo pipefail

APP_DIR="${APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
BRANCH="${BRANCH:-claude/gallant-pasteur-7G4Of}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.gallant.yml}"
LOG="${LOG:-/var/log/azc-tester-update.log}"

log() { echo "[$(date -u +%FT%TZ)] $*" | tee -a "$LOG"; }

cd "$APP_DIR"

git fetch origin "$BRANCH" --quiet
LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse "origin/$BRANCH")"

if [ "$LOCAL" = "$REMOTE" ]; then
  exit 0  # already current — nothing to do, stay quiet for cron
fi

log "update: $LOCAL -> $REMOTE on $BRANCH"
# Hard-reset to the pushed tip: deploys track the branch, not local edits.
git reset --hard "origin/$BRANCH" --quiet

if [ -f "$COMPOSE_FILE" ]; then
  docker compose -f "$COMPOSE_FILE" up -d --build 2>&1 | tee -a "$LOG"
else
  docker compose up -d --build 2>&1 | tee -a "$LOG"
fi
log "update: rebuilt and restarted"
