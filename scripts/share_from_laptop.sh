#!/usr/bin/env bash
# share_from_laptop.sh — RUN THIS ON YOUR LAPTOP (Mac/Linux with normal internet),
# NOT on the pod. When the pod's firewall blocks every public tunnel (Cloudflare 7844,
# pinggy/serveo/lhr, ngrok, even Tailscale DERP) but you can still SSH in, this gives
# outsiders a link anyway:
#
#     pod (locked)  ──SSH -L (the login you already use)──►  your laptop:PORT
#     your laptop   ──Cloudflare quick tunnel (open egress)──►  https://…trycloudflare.com
#
# The pod never opens an outbound tunnel; your laptop relays. Keep this running.
#
#   ./scripts/share_from_laptop.sh
#   SSH_HOST=10.6.110.10 SSH_PORT=30405 SSH_USER=root APP_PORT=8000 ./scripts/share_from_laptop.sh
set -uo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
. ./scripts/_ui.sh 2>/dev/null || { step(){ echo "▶ $*"; }; ok(){ echo "  ✓ $*"; }; warn(){ echo "  ! $*"; }; err(){ echo "  ✗ $*"; }; BOLD=""; RST=""; DIM=""; }

SSH_HOST="${SSH_HOST:-10.6.110.10}"; SSH_PORT="${SSH_PORT:-30405}"; SSH_USER="${SSH_USER:-root}"
APP_PORT="${APP_PORT:-8000}"; TRAME_PORT="${TRAME_PORT:-8081}"
OUT="outputs/public_urls.json"; mkdir -p outputs
LOG="outputs/.laptop-tunnel.log"; : > "$LOG"

banner 2>/dev/null || true
echo "  Relaying the pod's app to THIS laptop, then opening a public link from here."
echo "  ${DIM}The pod stays fully locked; your laptop is only the relay. Ctrl-C stops it.${RST}"
echo

# ---- 0. cloudflared on the laptop (the relay only needs it here) ----------
CF="$(command -v cloudflared || true)"
if [ -z "$CF" ]; then
  if command -v brew >/dev/null 2>&1; then step "installing cloudflared (brew)…"; brew install cloudflared >/dev/null 2>&1 && CF="$(command -v cloudflared || true)"; fi
fi
if [ -z "$CF" ]; then
  err "cloudflared not found on this laptop. Install it, then re-run:"
  err "   macOS:  brew install cloudflared      Linux:  see https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
  exit 1
fi

# ---- 1. tear down any relay we started before (match our exact -L forward) -
cleanup() { pkill -f "ssh .*-L ${APP_PORT}:127.0.0.1:${APP_PORT} .*${SSH_HOST}" 2>/dev/null; [ -n "${CFPID:-}" ] && kill "$CFPID" 2>/dev/null; }
trap 'echo; step "stopping the relay (the pod app keeps running)"; cleanup; exit 0' INT TERM
cleanup; sleep 1

# ---- 2. SSH -L: pull the pod's ports onto localhost (prompts for pw once) --
step "SSH -L to ${BOLD}${SSH_USER}@${SSH_HOST}:${SSH_PORT}${RST} — enter the pod password if asked…"
ssh -f -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ConnectTimeout=20 \
    -L "${APP_PORT}:127.0.0.1:${APP_PORT}" -L "${TRAME_PORT}:127.0.0.1:${TRAME_PORT}" \
    -p "$SSH_PORT" "${SSH_USER}@${SSH_HOST}" \
  || { err "SSH -L failed — check SSH_HOST/SSH_PORT/SSH_USER and that the pod app is up."; exit 1; }

# ---- 3. wait until the pod app answers through the forward ----------------
step "waiting for the pod app on localhost:${APP_PORT}…"
appok=""
for _ in $(seq 1 30); do curl -fsS -m 3 "http://127.0.0.1:${APP_PORT}/api/health" >/dev/null 2>&1 && { appok=1; break; }; sleep 1; done
[ -n "$appok" ] || { err "no app on localhost:${APP_PORT} — is it running on the pod? (curl localhost:8000/api/health there)"; cleanup; exit 1; }
ok "pod app reachable locally"

# ---- 4. public Cloudflare quick tunnel FROM the laptop -------------------
step "opening a public Cloudflare link from your laptop (open egress)…"
"$CF" tunnel --url "http://localhost:${APP_PORT}" --no-autoupdate >>"$LOG" 2>&1 &
CFPID=$!
URL=""
for _ in $(seq 1 30); do
  URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" 2>/dev/null | head -1)"
  [ -n "$URL" ] && break
  kill -0 "$CFPID" 2>/dev/null || break
  sleep 2
done
if [ -z "$URL" ]; then
  err "Cloudflare didn't come up from this laptop either (your network may block 7844 too)."
  err "Last lines:"; tail -n 8 "$LOG" 2>/dev/null | sed 's/^/    /'
  err "Try another provider from the laptop:  TUNNEL_PROVIDER=pinggy ./scripts/tunnel.sh ${APP_PORT}"
  cleanup; exit 1
fi

cat > "$OUT" <<JSON
{
  "react_url": "${URL}",
  "trame_url": "",
  "api_url": "${URL}/api",
  "provider": "laptop-relay+cloudflare",
  "self_verified": true,
  "note": "relayed through your laptop (pod egress blocks all tunnels); keep share_from_laptop.sh running"
}
JSON
echo
ok "${BOLD}PUBLIC LINK:${RST}  ${URL}"
echo "  ${DIM}(React app; also written to outputs/public_urls.json). Trame: use http://localhost:${TRAME_PORT} locally.${RST}"
echo "  ${DIM}Leave this terminal open — closing it drops the relay. Ctrl-C to stop.${RST}"
# keep alive; if cloudflared dies, report it
wait "$CFPID"
warn "cloudflared exited — re-run ./scripts/share_from_laptop.sh"
cleanup
