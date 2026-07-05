#!/usr/bin/env bash
# Resilient PUBLIC tunnel manager. Instead of fragile pre-probes, it TRIES each provider,
# VERIFIES it actually serves (registered / responds 2xx-3xx), and keeps the first that
# works — then holds it alive and rewrites the live URL into outputs/public_urls.json
# (+ the app's top bar). Built for egress-restricted pods that allow only one path out.
#
# Order (override with TUNNEL_PROVIDER=ngrok|cloudflare|pinggy|lhr):
#   ngrok (if configured) → cloudflare (only if it truly registers) → pinggy(443) → localhost.run
#
#   ./scripts/tunnel.sh <app_port> [trame_port]
# Kills any previous tunnel; Ctrl-C stops it (the app keeps running).
set -uo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
. ./scripts/_ui.sh

APP_PORT="${1:-8000}"; TRAME_PORT="${2:-}"
OUT="outputs/public_urls.json"; mkdir -p outputs
TOOLS="$(pwd)/.tools"; [ -d "$TOOLS" ] && export PATH="$TOOLS:$PATH"
LOGD="$(pwd)/outputs/.tunnel"; mkdir -p "$LOGD"

kill_all() {
  pkill -9 -f "cloudflared tunnel --url" 2>/dev/null
  pkill -9 -f "ssh .*a.pinggy.io"        2>/dev/null
  pkill -9 -f "ssh .*localhost.run"      2>/dev/null
  pkill -9 -f "ngrok http"               2>/dev/null
}
trap 'kill_all; rm -f "$LOGD"/.keep 2>/dev/null; exit 0' INT TERM
kill_all; sleep 1

# --- run one tunnel for a port into a log (blocking; wrapped by keepalive) ---
start_tunnel() {   # $1 prov  $2 port  $3 log
  case "$1" in
    cloudflare) cloudflared tunnel --url "http://127.0.0.1:$2" --protocol http2 --no-autoupdate >>"$3" 2>&1 ;;
    pinggy)     ssh -p 443 -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
                    -o ExitOnForwardFailure=yes -o ConnectTimeout=20 -R0:127.0.0.1:"$2" a.pinggy.io >>"$3" 2>&1 ;;
    lhr)        ssh -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -o ConnectTimeout=20 \
                    -R 80:127.0.0.1:"$2" nokey@localhost.run >>"$3" 2>&1 ;;
    ngrok)      ngrok http "$2" --log stdout >>"$3" 2>&1 ;;
  esac
}
url_from() {       # $1 prov  $2 log
  case "$1" in
    cloudflare) grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$2" 2>/dev/null | tail -1 ;;
    pinggy)     grep -oiE 'https://[a-z0-9.-]*pinggy[a-z0-9.-]*' "$2" 2>/dev/null | grep -vi dashboard | head -1 ;;
    lhr)        grep -oE 'https://[a-z0-9]+\.lhr\.life' "$2" 2>/dev/null | tail -1 ;;
    ngrok)      grep -oE 'https://[-a-z0-9]+\.ngrok[-a-z0-9.]*\.(app|io|dev)' "$2" 2>/dev/null | tail -1 ;;
  esac
}
# a provider is "ready" only if its tunnel truly works — echoes the URL, else nothing
ready_url() {      # $1 prov  $2 log
  local u; u="$(url_from "$1" "$2")"; [ -z "$u" ] && return 1
  if [ "$1" = cloudflare ]; then
    grep -q "Registered tunnel connection" "$2" 2>/dev/null && echo "$u" || return 1
  else
    local code; code="$(curl -s -o /dev/null -m 12 -w '%{http_code}' "$u" 2>/dev/null)"
    case "$code" in 2*|3*) echo "$u" ;; *) return 1 ;; esac
  fi
}
keepalive() {      # $1 prov  $2 port  $3 log  — restarts the tunnel forever
  while :; do : >"$3"; start_tunnel "$1" "$2" "$3"; echo "$(date +%H:%M:%S) $1:$2 exited — restart" >>"$3"; sleep 3; done
}

# candidate providers, in preference order, filtered by what's installed
CANDS=""
if [ -n "${TUNNEL_PROVIDER:-}" ]; then CANDS="$TUNNEL_PROVIDER"; else
  command -v ngrok       >/dev/null 2>&1 && ngrok config check >/dev/null 2>&1 && CANDS="$CANDS ngrok"
  command -v cloudflared >/dev/null 2>&1 && CANDS="$CANDS cloudflare"
  command -v ssh         >/dev/null 2>&1 && CANDS="$CANDS pinggy lhr"
fi

PICK=""; APPURL=""
for prov in $CANDS; do
  step "Trying tunnel: ${BOLD}${prov}${RST} (verifying it actually serves)…"
  RLOG="$LOGD/app-$prov.log"; keepalive "$prov" "$APP_PORT" "$RLOG" & KP=$!
  # cloudflare rejects fast (registration); the 443 SSH ones need a bit longer to bind
  [ "$prov" = cloudflare ] && tries=9 || tries=18
  for _ in $(seq 1 "$tries"); do
    u="$(ready_url "$prov" "$RLOG")" && { PICK="$prov"; APPURL="$u"; break; }
    kill -0 "$KP" 2>/dev/null || break
    sleep 3
  done
  [ -n "$PICK" ] && { ok "${prov} works → ${APPURL}"; break; }
  kill "$KP" 2>/dev/null; kill_all; sleep 1; warn "${prov} did not produce a working URL — next"
done

if [ -z "$PICK" ]; then
  err "No public tunnel works from this network (egress may allow none of them)."
  err "The app is up locally: http://127.0.0.1:${APP_PORT}"
  err "Reach it without a public link:  ssh -L ${APP_PORT}:127.0.0.1:${APP_PORT} -p <ssh-port> <user>@<host>  then open http://localhost:${APP_PORT}"
  printf '{\n  "react_url": "",\n  "trame_url": "",\n  "note": "no public tunnel reachable (egress blocked) — use SSH -L or a Kubernetes Ingress"\n}\n' > "$OUT"
  exit 0
fi

# trame on the same provider (best-effort; ngrok free = one tunnel only)
TLOG=""
if [ -n "$TRAME_PORT" ] && [ "$PICK" != ngrok ]; then TLOG="$LOGD/trame-$PICK.log"; keepalive "$PICK" "$TRAME_PORT" "$TLOG" & fi

# publish + keep the URL fresh (rotates on reconnect for the free providers)
last=""
while :; do
  r="$(url_from "$PICK" "$RLOG")"; [ -z "$r" ] && r="$APPURL"
  t=""; [ -n "$TLOG" ] && t="$(url_from "$PICK" "$TLOG")"
  cur="$r|$t"
  if [ "$cur" != "$last" ] && [ -n "$r" ]; then
    cat > "$OUT" <<JSON
{
  "react_url": "${r}",
  "trame_url": "${t}",
  "api_url": "${r}/api",
  "provider": "${PICK}",
  "updated": "$(date -u '+%Y-%m-%dT%H:%M:%SZ')",
  "note": "auto-selected working tunnel (${PICK})"
}
JSON
    echo
    printf "  ${GRN}${BOLD}APP  ${RST} %s\n" "${r}"
    [ -n "$t" ] && printf "  ${GRN}${BOLD}TRAME${RST} %s\n" "$t"
    printf "  ${DIM}(also in outputs/public_urls.json and the app's top bar; leave this running)${RST}\n"
    last="$cur"
  fi
  sleep 6
done
