#!/usr/bin/env bash
# relay_server.sh — run on a SMALL ALWAYS-ON box so the public link lives WITHOUT your
# laptop. A $0 free-tier VM works (Oracle Cloud Always Free, GCP e2-micro, a cheap VPS).
#
#     pod (locked) ──ssh -R localhost:PORT (over 443)──► THIS box ──cloudflared──► https://…
#
# THIS box needs only: sshd reachable on a port your pod can dial OUT to (443 is safest —
# locked pods usually allow generic 443) + outbound 443 for cloudflared. No inbound app
# port, no domain, no GatewayPorts (the pod binds THIS box's localhost). Always-on.
#
#   ./scripts/relay_server.sh              # serve localhost:8000 publicly, print the pod command
#   ./scripts/relay_server.sh 8000
#
# Leave it running (tmux / nohup / a systemd unit). It reconnects cloudflared on drops.
set -uo pipefail
cd "$(dirname "$0")/.." 2>/dev/null || true
# shellcheck disable=SC1091
. ./scripts/_ui.sh 2>/dev/null || { banner(){ :; }; step(){ echo "▶ $*"; }; ok(){ echo "  ✓ $*"; }; warn(){ echo "  ! $*"; }; err(){ echo "  ✗ $*"; }; BOLD=""; RST=""; DIM=""; }
PORT="${1:-8000}"
TOOLS="$(pwd)/.tools"; mkdir -p "$TOOLS" 2>/dev/null || { TOOLS="$HOME/.3dorth-tools"; mkdir -p "$TOOLS"; }
LOG="$(mktemp 2>/dev/null || echo /tmp/3dorth-relay.$$)"; : > "$LOG"

banner 2>/dev/null || true
# public IP + the ssh port your pod should dial
PUBIP="$(curl -fsS -m 5 https://api.ipify.org 2>/dev/null || curl -fsS -m 5 https://ifconfig.me 2>/dev/null || echo '<this-box-public-ip>')"
SSHP="$( { grep -hoiE '^[[:space:]]*Port[[:space:]]+[0-9]+' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/*.conf 2>/dev/null; } | grep -oE '[0-9]+' | sort -u | tr '\n' ',' | sed 's/,$//')"
[ -z "$SSHP" ] && SSHP=22
ME="$(id -un)@${PUBIP}"

# ---- cloudflared (local, no root) -----------------------------------------
CF="$(command -v cloudflared || true)"
if [ -z "$CF" ] && [ -x "$TOOLS/cloudflared" ]; then CF="$TOOLS/cloudflared"; fi
if [ -z "$CF" ]; then
  step "installing cloudflared (local, ./.tools)…"
  arch=amd64; case "$(uname -m)" in aarch64|arm64) arch=arm64 ;; esac
  if curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${arch}" -o "$TOOLS/cloudflared" 2>/dev/null; then
    chmod +x "$TOOLS/cloudflared"; CF="$TOOLS/cloudflared"; ok "cloudflared ready"
  else err "cloudflared install failed — install it manually, then re-run."; exit 1; fi
fi

# ---- make sure the pod can DIAL IN: sshd should listen on 443 -------------
# Locked pods often allow only outbound 443. If this box's sshd isn't on 443, tell the
# user exactly how to add it (keeping 22). Offer to do it when we're root.
if ! printf '%s' ",$SSHP," | grep -q ',443,'; then
  warn "This box's sshd listens on: ${BOLD}${SSHP}${RST} — but a locked pod usually can dial OUT only on 443."
  if [ "$(id -u)" = 0 ]; then
    printf "  Add 'Port 443' to sshd now (keeps %s)? [y/N] " "$SSHP"; read -r a || a=""
    if [ "${a:-}" = y ] || [ "${a:-}" = Y ]; then
      printf 'Port 443\n' > /etc/ssh/sshd_config.d/3dorth-relay.conf 2>/dev/null || printf '\nPort 443\n' >> /etc/ssh/sshd_config
      (systemctl restart ssh 2>/dev/null || systemctl restart sshd 2>/dev/null || service ssh restart 2>/dev/null) \
        && { ok "sshd now also on 443"; SSHP="${SSHP},443"; } || warn "couldn't restart sshd — do it manually"
    fi
  else
    warn "As root on this box:  echo 'Port 443' | sudo tee /etc/ssh/sshd_config.d/3dorth-relay.conf && sudo systemctl restart ssh"
    warn "(also open inbound 443 in the box's cloud firewall/security-group)"
  fi
fi
DIAL=443; printf '%s' ",$SSHP," | grep -q ',443,' || DIAL="${SSHP%%,*}"

step "Relay front door on ${BOLD}$(hostname 2>/dev/null || echo this-box)${RST} → serving localhost:${PORT}"
echo
ok "① On the POD, keep its app forwarded here (reconnects on drop):"
printf "     ${BOLD}RELAY=%s:%s ./scripts/relay_connect.sh %s${RST}\n" "$ME" "$DIAL" "$PORT"
printf "     ${DIM}raw equivalent:  ssh -N -R localhost:%s:127.0.0.1:8000 -p %s %s${RST}\n" "$PORT" "$DIAL" "$ME"
echo
ok "② This box then publishes it. Leave this running (tmux/nohup/systemd):"
echo

# ---- keepalive cloudflared -------------------------------------------------
trap 'echo; step "relay stopped"; pkill -P $$ 2>/dev/null; exit 0' INT TERM
last=""
while :; do
  : > "$LOG"
  "$CF" tunnel --url "http://localhost:${PORT}" --no-autoupdate >>"$LOG" 2>&1 &
  cfpid=$!
  url=""
  for _ in $(seq 1 30); do
    url="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" 2>/dev/null | head -1)"
    [ -n "$url" ] && break
    kill -0 "$cfpid" 2>/dev/null || break
    sleep 2
  done
  if [ -n "$url" ] && [ "$url" != "$last" ]; then
    ok "${BOLD}PUBLIC LINK → ${url}${RST}   ${DIM}(share this; live while this box runs)${RST}"
    last="$url"
  elif [ -z "$url" ]; then
    warn "cloudflared didn't produce a URL — last lines:"; tail -n 6 "$LOG" | sed 's/^/    /'
  fi
  wait "$cfpid" 2>/dev/null
  warn "cloudflared dropped — restarting in 3s"; sleep 3
done
