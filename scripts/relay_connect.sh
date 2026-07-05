#!/usr/bin/env bash
# relay_connect.sh — run on the POD. Keeps 3Dorth reverse-forwarded to your always-on
# relay box (see relay_server.sh) so the public link stays up WITHOUT your laptop.
# Reconnects on drops. The pod dials OUT to the box (443 is safest on locked pods).
#
#   RELAY=user@your-box:443 ./scripts/relay_connect.sh          # app 8000 → box localhost:8000
#   RELAY=user@your-box:443 APP_PORT=8000 REMOTE_PORT=8000 ./scripts/relay_connect.sh
#
# Run it in the background so it survives your SSH session:
#   RELAY=user@your-box:443 nohup ./scripts/relay_connect.sh > outputs/relay.log 2>&1 &
set -uo pipefail
cd "$(dirname "$0")/.." 2>/dev/null || true
# shellcheck disable=SC1091
. ./scripts/_ui.sh 2>/dev/null || { step(){ echo "▶ $*"; }; ok(){ echo "  ✓ $*"; }; warn(){ echo "  ! $*"; }; err(){ echo "  ✗ $*"; }; BOLD=""; RST=""; DIM=""; }

[ -n "${RELAY:-}" ] || { err "set RELAY=user@your-box[:sshport]   (the box running scripts/relay_server.sh)"; exit 2; }
APP_PORT="${APP_PORT:-8000}"; REMOTE_PORT="${REMOTE_PORT:-$APP_PORT}"
spec="$RELAY"; PORT=443; case "$spec" in *:*) PORT="${spec##*:}"; spec="${spec%:*}" ;; esac
case "$PORT" in ''|*[!0-9]*) PORT=443 ;; esac

step "Relay: app :${APP_PORT} → ${BOLD}${spec}${RST} localhost:${REMOTE_PORT} (ssh port ${PORT}). Ctrl-C stops it; the app keeps running."
trap 'echo; ok "relay stopped (the app keeps running)"; exit 0' INT TERM
# Bind the relay box's LOCALHOST (no GatewayPorts needed there); its cloudflared serves it.
while :; do
  ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
      -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20 \
      -R "localhost:${REMOTE_PORT}:127.0.0.1:${APP_PORT}" -p "$PORT" "$spec"
  warn "$(date +%H:%M:%S) relay ssh dropped — reconnecting in 3s"; sleep 3
done
