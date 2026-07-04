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

healthy() {  # $1 = url -> 0 if it answers 2xx/3xx
  [ -z "$1" ] && return 1
  local code
  code="$(curl -s -o /dev/null -m 5 -w '%{http_code}' "$1" 2>/dev/null)"
  case "$code" in 2*|3*) return 0 ;; *) return 1 ;; esac
}

# Recycle a tunnel ONLY once its URL has served at least once and then goes dead
# (the sleep/wake / edge-reset case). A brand-new tunnel takes 20-40s to bind at
# the edge (transient 530/000), so we must NOT recycle before it has ever been
# healthy — otherwise we churn URLs forever and it never stabilises.
check_side() {  # $1=url  $2=name  $3=port  ; state vars are namerefs via eval
  local url="$1" name="$2" port="$3"
  local seen_v="${name}_seen" fail_v="${name}_fail" lasturl_v="${name}_lasturl"
  # reset per-side state when the URL changes (a fresh tunnel came up)
  if [ "$url" != "${!lasturl_v}" ]; then
    eval "$seen_v=0; $fail_v=0; $lasturl_v=\"\$url\""
  fi
  [ -z "$url" ] && return
  if healthy "$url"; then
    eval "$seen_v=1; $fail_v=0"
  elif [ "${!seen_v}" = 1 ]; then
    eval "$fail_v=\$(( ${!fail_v} + 1 ))"
    if [ "${!fail_v}" -ge 2 ]; then
      echo "$(date '+%H:%M:%S') $name tunnel URL died ($url) — recycling for a fresh one" >&2
      pkill -f "cloudflared tunnel --url http://127.0.0.1:$port" 2>/dev/null
      eval "$seen_v=0; $fail_v=0"; last=""
    fi
  fi
}

last=""; react_seen=0; react_fail=0; react_lasturl=""
trame_seen=0; trame_fail=0; trame_lasturl=""
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

  check_side "$r" react "$REACT_PORT"
  check_side "$t" trame "$TRAME_PORT"
  sleep 12
done
