#!/bin/bash
# Deploy amp-watchdog to dev server (LXC <dashboard-dev>, dashboard-dev)
#
# Usage: ./scripts/deploy.sh
#
# Prerequisites:
#   - SSH access to dev Proxmox host (<dev-proxmox>)
#   - LXC <dashboard-dev> running with Docker
#   - First deploy only: create /opt/amp-watchdog and /opt/appdata/amp-watchdog
#     in the LXC and place a filled .env at /opt/amp-watchdog/.env

set -e

PROXMOX_HOST="${PROXMOX_HOST:?set PROXMOX_HOST, e.g. root@<dev-proxmox> (values: homeserver configs/dev/services/<app>/README.md)}"
LXC_ID="${LXC_ID:?set LXC_ID of the dev container (see homeserver dev service README)}"
REMOTE_PATH="/opt/amp-watchdog"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== amp-watchdog Deploy ==="
echo "Source: $PROJECT_DIR"
echo "Target: LXC $LXC_ID at $REMOTE_PATH"
echo ""

echo "[1/4] Creating tarball..."
TARBALL="/tmp/amp-watchdog-deploy.tar.gz"
cd "$PROJECT_DIR"
tar -czf "$TARBALL" \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='.venv' \
    --exclude='*.pyc' \
    --exclude='.pytest_cache' \
    --exclude='data' \
    --exclude='.env' \
    .

echo "[2/4] Copying to Proxmox host..."
scp "$TARBALL" "$PROXMOX_HOST:/tmp/"

echo "[3/4] Extracting in LXC (preserves .env)..."
ssh "$PROXMOX_HOST" "pct push $LXC_ID $TARBALL /tmp/amp-watchdog-deploy.tar.gz"
ssh "$PROXMOX_HOST" "pct exec $LXC_ID -- bash -c 'mkdir -p $REMOTE_PATH && cd $REMOTE_PATH && find . -mindepth 1 -maxdepth 1 ! -name .env -exec rm -rf {} + && tar -xzf /tmp/amp-watchdog-deploy.tar.gz && rm /tmp/amp-watchdog-deploy.tar.gz'"

echo "[4/4] Rebuilding container..."
ssh "$PROXMOX_HOST" "pct exec $LXC_ID -- bash -c 'cd $REMOTE_PATH && docker compose up -d --build'"

rm -f "$TARBALL"

echo ""
echo "=== Deploy Complete ==="
echo "Dashboard:  http://<container-ip>:${DASHBOARD_PORT:-8200}"
echo "Check logs: ssh $PROXMOX_HOST \"pct exec $LXC_ID -- docker logs amp-watchdog -f\""
