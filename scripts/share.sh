#!/usr/bin/env bash
# Expose the running 3Dorth UIs publicly via Cloudflare quick tunnels, and KEEP
# THEM ALIVE: if a tunnel drops (laptop sleep/wake, network change, edge reset)
# it is restarted and the NEW public URL is written to outputs/public_urls.json.
# Both UIs poll /api/config, so the in-app Share panel always shows the current
# link in realtime — no manual step after a wake.
#
# Usage:
#   ./scripts/share.sh              # local dev: React :5173, trame :8081
#   ./scripts/share.sh 8088 8081    # custom ports (e.g. Docker)
#
# Quick tunnels are ephemeral (URL changes on restart) and unauthenticated — use
# a named Cloudflare tunnel + Access for anything sensitive. Leave this running.
set -uo pipefail
cd "$(dirname "$0")/.."

REACT_PORT="${1:-5173}"
TRAME_PORT="${2:-8081}"
OUT="outputs/public_urls.json"
mkdir -p outputs
command -v cloudflared >/dev/null || { echo "cloudflared not found. brew install cloudflared"; exit 1; }

RLOG="$(mktemp)"; TLOG="$(mktemp)"

# Keep one port's tunnel alive forever; truncate its log on each (re)start so the
# newest assigned URL is always the last match.
keepalive() {  # $1 = port, $2 = logfile
  while true; do
    : > "$2"
    cloudflared tunnel --url "http://127.0.0.1:$1" --protocol http2 --no-autoupdate >>"$2" 2>&1
    echo "$(date '+%H:%M:%S') tunnel on :$1 exited — restarting in 3s" >&2
    sleep 3
  done
}

keepalive "$REACT_PORT" "$RLOG" & RPID=$!
keepalive "$TRAME_PORT" "$TLOG" & TPID=$!
cleanup() { kill "$RPID" "$TPID" 2>/dev/null; pkill -P "$RPID" 2>/dev/null; pkill -P "$TPID" 2>/dev/null; }
trap cleanup EXIT INT TERM

url_of() { grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" "$1" 2>/dev/null | tail -1; }

echo "Resilient Cloudflare tunnels (React :$REACT_PORT, trame :$TRAME_PORT). Leave running."
last=""
while true; do
  r="$(url_of "$RLOG")"; t="$(url_of "$TLOG")"
  cur="$r|$t"
  if [ "$cur" != "$last" ] && [ -n "$r$t" ]; then
    cat > "$OUT" <<JSON
{
  "react_url": "${r}",
  "trame_url": "${t}",
  "api_url": "${r}/api",
  "updated": "$(date -u '+%Y-%m-%dT%H:%M:%SZ')",
  "note": "Cloudflare quick tunnels - ephemeral, unauthenticated."
}
JSON
    echo "  $(date '+%H:%M:%S')  React: ${r:-<pending>}   trame: ${t:-<pending>}"
    last="$cur"
  fi
  sleep 5
done
