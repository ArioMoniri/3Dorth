#!/usr/bin/env bash
# Expose the running 3Dorth UIs publicly via Cloudflare quick tunnels and record
# the URLs so the app can show them (in-UI share panel + "switch UI" button).
#
# Usage:
#   ./scripts/share.sh              # local dev: React :5173, trame :8081
#   ./scripts/share.sh 8088 8081    # custom React/trame ports (e.g. Docker)
#
# Requires cloudflared (https://developers.cloudflare.com/cloudflare-one/) and
# the servers already running. Quick tunnels are ephemeral (new URL each run)
# and unauthenticated — anyone with the URL can reach the app; use a named
# tunnel + Access for anything sensitive.
set -euo pipefail
cd "$(dirname "$0")/.."

REACT_PORT="${1:-5173}"
TRAME_PORT="${2:-8081}"
OUT="outputs/public_urls.json"
mkdir -p outputs
command -v cloudflared >/dev/null || { echo "cloudflared not found. brew install cloudflared"; exit 1; }

RLOG=$(mktemp); TLOG=$(mktemp)
echo "Starting Cloudflare tunnels (React :$REACT_PORT, trame :$TRAME_PORT)..."
cloudflared tunnel --url "http://127.0.0.1:${REACT_PORT}" --protocol http2 --no-autoupdate >"$RLOG" 2>&1 &
RPID=$!
cloudflared tunnel --url "http://127.0.0.1:${TRAME_PORT}" --protocol http2 --no-autoupdate >"$TLOG" 2>&1 &
TPID=$!
trap 'kill $RPID $TPID 2>/dev/null || true' EXIT

get_url() { grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" "$1" 2>/dev/null | head -1; }
RURL=""; TURL=""
for _ in $(seq 1 30); do
  RURL=$(get_url "$RLOG"); TURL=$(get_url "$TLOG")
  [ -n "$RURL" ] && [ -n "$TURL" ] && break
  sleep 2
done

cat > "$OUT" <<JSON
{
  "react_url": "${RURL}",
  "trame_url": "${TURL}",
  "api_url": "${RURL}/api",
  "note": "Cloudflare quick tunnels — ephemeral, unauthenticated."
}
JSON

echo
echo "  React UI : ${RURL:-<pending>}"
echo "  trame UI : ${TURL:-<pending>}"
echo "  (URLs written to $OUT and shown in the app's Share panel)"
echo "  Quick tunnels can take up to ~1 min to become reachable; Ctrl-C to stop."
wait
