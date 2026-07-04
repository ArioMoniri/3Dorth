#!/usr/bin/env bash
# Resilient PUBLIC tunnel manager. AUTO-DETECTS which tunnel actually works from this
# network and keeps a fresh public link in outputs/public_urls.json (+ the app top bar).
#
# Cloudflare quick tunnels need port 7844 (frequently firewalled — e.g. RKE2 pods);
# Pinggy and ngrok ride port 443, which is almost always open. Order (override with
# TUNNEL_PROVIDER=cloudflare|pinggy|ngrok|off):
#   cloudflare (if 7844 reachable) → pinggy (if 443 reachable) → ngrok (if authtoken) → off
#
#   ./scripts/tunnel.sh <app_port> [trame_port]
# Kills any previous tunnel first; keeps URLs alive across drops; Ctrl-C stops it
# (the app keeps running).
set -uo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
. ./scripts/_ui.sh

APP_PORT="${1:-8000}"; TRAME_PORT="${2:-}"
OUT="outputs/public_urls.json"; mkdir -p outputs
TOOLS="$(pwd)/.tools"; [ -x "$TOOLS/cloudflared" ] && export PATH="$TOOLS:$PATH"
LOGD="$(mktemp -d)"; trap 'kill_prev; rm -rf "$LOGD"' EXIT INT TERM

kill_prev() {
  pkill -f "cloudflared tunnel --url"          2>/dev/null
  pkill -f "R0:127.0.0.1:.*a.pinggy.io"        2>/dev/null
  pkill -f "ngrok http"                        2>/dev/null
}

_tcp_open() {  # host port -> 0 if a TCP connect succeeds within 6s
  if command -v timeout >/dev/null 2>&1; then timeout 6 bash -c "exec 3<>/dev/tcp/$1/$2" 2>/dev/null
  else (exec 3<>/dev/tcp/$1/$2) 2>/dev/null; fi
}

detect_provider() {
  [ -n "${TUNNEL_PROVIDER:-}" ] && { echo "$TUNNEL_PROVIDER"; return; }
  if command -v cloudflared >/dev/null 2>&1 && _tcp_open region1.v2.argotunnel.com 7844; then echo cloudflare; return; fi
  if command -v ssh >/dev/null 2>&1 && _tcp_open a.pinggy.io 443; then echo pinggy; return; fi
  if command -v ngrok >/dev/null 2>&1 && ngrok config check >/dev/null 2>&1; then echo ngrok; return; fi
  if command -v cloudflared >/dev/null 2>&1; then echo cloudflare; return; fi   # last resort: try anyway
  echo off
}

# keepalive loop for one tunnel: (provider, port, logfile). Restarts on exit.
serve_one() {
  local prov="$1" port="$2" log="$3"
  while :; do
    : > "$log"
    case "$prov" in
      cloudflare) cloudflared tunnel --url "http://127.0.0.1:$port" --protocol http2 --no-autoupdate >>"$log" 2>&1 ;;
      pinggy)     ssh -p 443 -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
                      -o ExitOnForwardFailure=yes -o ConnectTimeout=15 -R0:127.0.0.1:"$port" a.pinggy.io >>"$log" 2>&1 ;;
      ngrok)      ngrok http "$port" --log stdout >>"$log" 2>&1 ;;
    esac
    echo "$(date '+%H:%M:%S') tunnel on :$port exited — restarting" >>"$log"
    sleep 3
  done
}

url_from() {  # extract the current public URL from a provider's log
  local prov="$1" log="$2"
  case "$prov" in
    cloudflare) grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$log" 2>/dev/null | tail -1 ;;
    pinggy)     grep -oE 'https://[-a-z0-9]+\.(a\.)?(free\.)?pinggy\.(link|online|io)' "$log" 2>/dev/null | tail -1 ;;
    ngrok)      grep -oE 'https://[-a-z0-9]+\.ngrok[-a-z0-9.]*\.(app|io|dev)' "$log" 2>/dev/null | tail -1 ;;
  esac
}

kill_prev; sleep 1
PROV="$(detect_provider)"
case "$PROV" in
  off)
    warn "No public tunnel works from here (7844 blocked, 443 has no pinggy/ngrok)."
    warn "App is local only: http://127.0.0.1:$APP_PORT  (or: ssh -L $APP_PORT:127.0.0.1:$APP_PORT ...)"
    printf '{\n  "react_url": "",\n  "trame_url": "",\n  "note": "no public tunnel available (egress blocked); use SSH -L or a Service/Ingress"\n}\n' > "$OUT"
    exit 0 ;;
esac
step "Public tunnel provider: ${BOLD}${PROV}${RST}  (cloudflare needs 7844; pinggy/ngrok use 443)"

RLOG="$LOGD/app.log"; serve_one "$PROV" "$APP_PORT" "$RLOG" &
if [ -n "$TRAME_PORT" ] && [ "$PROV" != ngrok ]; then   # ngrok free = 1 tunnel; app only
  TLOG="$LOGD/trame.log"; serve_one "$PROV" "$TRAME_PORT" "$TLOG" &
fi

ok "waiting for the public URL (a few seconds)…"
last=""
while :; do
  r="$(url_from "$PROV" "$RLOG")"
  t=""; [ -n "${TLOG:-}" ] && t="$(url_from "$PROV" "$TLOG")"
  cur="$r|$t"
  if [ "$cur" != "$last" ] && [ -n "$r" ]; then
    cat > "$OUT" <<JSON
{
  "react_url": "${r}",
  "trame_url": "${t}",
  "api_url": "${r}/api",
  "provider": "${PROV}",
  "updated": "$(date -u '+%Y-%m-%dT%H:%M:%SZ')",
  "note": "auto-selected tunnel (${PROV}); ephemeral + unauthenticated"
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
