#!/usr/bin/env bash
# tunnel_menu.sh — interactive public-link chooser.
#
# Probes what THIS pod can actually reach, shows every provider with a live
# ✓reachable / ✗blocked status, lets you PICK one, prompts for whatever that
# choice needs (Tailscale key / SSH relay / ngrok token), then launches the
# tunnel. Run it after the app is up (it reads the app port from
# outputs/ports.env, default 8000).
#
#   ./scripts/tunnel_menu.sh                 # probe → menu → prompt → launch
#   ./scripts/tunnel_menu.sh 8000 8081       # force the app/trame ports
#
# Everything it starts is the SAME verified scripts/tunnel.sh underneath; this
# only handles the "which one + what input" question interactively.
set -uo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
. ./scripts/_ui.sh
TOOLS="$(pwd)/.tools"; [ -d "$TOOLS" ] && export PATH="$TOOLS:$PATH"

# ---- app ports (from the running instance) --------------------------------
APP_PORT="${1:-}"; TRAME_PORT="${2:-}"
if [ -z "$APP_PORT" ] && [ -f outputs/ports.env ]; then
  while IFS='=' read -r k v; do case "$k" in
    API_PORT) APP_PORT="${APP_PORT:-$v}" ;; TRAME_PORT) TRAME_PORT="${TRAME_PORT:-$v}" ;;
  esac; done < outputs/ports.env
fi
APP_PORT="${APP_PORT:-8000}"; TRAME_PORT="${TRAME_PORT:-8081}"

# ---- must be interactive to choose + prompt -------------------------------
if [ ! -t 0 ]; then
  err "tunnel_menu.sh needs an interactive terminal (you're piping / nohup-ing stdin)."
  err "Run it directly in your SSH session:   ./scripts/tunnel_menu.sh"
  err "…or go non-interactive with env, e.g.:  TS_AUTHKEY=tskey-… ./scripts/tunnel.sh ${APP_PORT} ${TRAME_PORT}"
  exit 2
fi

# ---- timeout shim + TCP connect (mirrors egress_probe.sh) -----------------
if command -v timeout >/dev/null 2>&1; then _to() { timeout "$1" "${@:2}"; }
else _to() { local t="$1"; shift; "$@" & local p=$!; ( sleep "$t"; kill -9 "$p" 2>/dev/null ) & local w=$!;
             wait "$p" 2>/dev/null; local rc=$?; kill -9 "$w" 2>/dev/null; wait "$w" 2>/dev/null; return $rc; }; fi
if command -v nc >/dev/null 2>&1 && nc -h 2>&1 | grep -q -- '-z'; then
  tcp() { _to 4 nc -z -w 4 "$1" "$2" >/dev/null 2>&1; }
elif command -v python3 >/dev/null 2>&1; then
  tcp() { _to 4 python3 - "$1" "$2" <<'PY' >/dev/null 2>&1
import socket,sys
socket.create_connection((sys.argv[1],int(sys.argv[2])),timeout=4).close()
PY
  }
else tcp() { _to 4 bash -c "exec 3<>/dev/tcp/$1/$2" 2>/dev/null; }; fi

# ---- probe the paths each provider depends on -----------------------------
banner
step "Probing what this pod can reach (a few seconds)…"
probe() { printf "  %-26s" "$1"; if tcp "$2" "$3"; then printf "${GRN}reachable${RST}\n"; return 0; else printf "${RED}blocked${RST}\n"; return 1; fi; }
# Tailscale Funnel needs BOTH the control plane AND a DERP relay (443). login alone
# being reachable is the trap: control connects, then Funnel can't serve (no DERP).
TS_CTRL=0; probe "tailscale control:443"   login.tailscale.com 443 && TS_CTRL=1
TS_DERP=0; probe "tailscale DERP:443"      derp1.tailscale.com 443 && TS_DERP=1
TS_OK=0; [ "$TS_CTRL" = 1 ] && [ "$TS_DERP" = 1 ] && TS_OK=1
TS_NOTE="recommended here; prompts for a free auth key (auto-installs)"
[ "$TS_CTRL" = 1 ] && [ "$TS_DERP" = 0 ] && TS_NOTE="control OK but DERP blocked — Funnel can't serve from here"
NET443=0;  probe "generic 443 (relay)"     example.com         443 && NET443=1
NGROK_OK=0;probe "ngrok host:443"          bin.equinox.io      443 && NGROK_OK=1
PINGGY_OK=0;probe "a.pinggy.io:443"        a.pinggy.io         443 && PINGGY_OK=1
SERVEO_OK=0;probe "serveo.net:22"          serveo.net          22  && SERVEO_OK=1
LHR_OK=0;  probe "localhost.run:22"        localhost.run       22  && LHR_OK=1
CF_OK=0;   probe "cloudflare:7844"         region1.v2.argotunnel.com 7844 && CF_OK=1
NGROK_CFG=0; command -v ngrok >/dev/null 2>&1 && ngrok config check >/dev/null 2>&1 && NGROK_CFG=1

# ---- render the menu ------------------------------------------------------
row() { # $1 num  $2 name  $3 ok(0/1)  $4 note   (mark padded by hand so multibyte/ANSI don't skew it)
  local mark; [ "$3" = 1 ] && mark="${GRN}✓ reachable${RST}" || mark="${RED}✗ blocked  ${RST}"
  printf "   ${BOLD}[%s]${RST} %-18s  %b  ${DIM}%s${RST}\n" "$1" "$2" "$mark" "$4"
}
echo
step "${BOLD}Choose a public-link method${RST} (✓ = your pod can reach it):"
echo
row 1 "Tailscale Funnel" "$TS_OK"     "$TS_NOTE"
row 2 "SSH relay (yours)" "$NET443"   "prompts for user@host:443 of a box YOU control"
row 3 "ngrok"            "$NGROK_OK"  "$([ "$NGROK_CFG" = 1 ] && echo 'already configured' || echo 'prompts for an authtoken')"
row 4 "Pinggy (443)"     "$PINGGY_OK" "no signup; 60-min sessions"
row 5 "serveo (22)"      "$SERVEO_OK" "no signup"
row 6 "Cloudflare"       "$CF_OK"     "needs port 7844 (usually blocked on pods)"
printf "   ${BOLD}[0]${RST} %-18s  %-11s  ${DIM}%s${RST}\n" "ssh -L only" "" "no public link — just print the SSH command"
echo
printf "  ${DIM}Everything above ✗? Two relay options (the pod can't tunnel, so the link comes from elsewhere):${RST}\n"
printf "    ${BOLD}·${RST} laptop (quick, needs it left on):  ${BOLD}./scripts/share_from_laptop.sh${RST} ${DIM}— run ON YOUR LAPTOP${RST}\n"
printf "    ${BOLD}·${RST} always-on box (laptop-free):       ${BOLD}./scripts/relay_server.sh${RST} ${DIM}on a VPS, then RELAY=… ./scripts/relay_connect.sh here${RST}\n"
echo
# recommend the best reachable option
REC=0
if [ "$TS_OK" = 1 ]; then REC=1; elif [ "$NET443" = 1 ]; then REC=2
elif [ "$PINGGY_OK" = 1 ]; then REC=4; elif [ "$SERVEO_OK" = 1 ]; then REC=5
elif [ "$CF_OK" = 1 ]; then REC=6; fi
printf "  choice [${BOLD}%s${RST}]: " "$REC"
read -r CH || CH=""
[ -z "$CH" ] && CH="$REC"

# ---- act on the choice ----------------------------------------------------
launch() { echo; step "Launching tunnel (${1})… Ctrl-C stops the tunnel; the app keeps running."; exec ./scripts/tunnel.sh "$APP_PORT" "$TRAME_PORT"; }

case "$CH" in
  1)  [ "$TS_OK" = 1 ] || warn "Tailscale login looked blocked — trying anyway (DERP may still work)."
      printf "\n  Get a key: ${DIM}https://login.tailscale.com/admin/settings/keys${RST} (Reusable + Ephemeral),\n"
      printf "  then enable ${BOLD}HTTPS${RST} + ${BOLD}Funnel${RST} in the admin console.\n"
      printf "  paste Tailscale auth key (tskey-…): "
      read -r K || K=""
      case "$K" in tskey-*) export TS_AUTHKEY="$K" TUNNEL_PROVIDER=tailscale; launch tailscale ;;
                   *) err "not a tskey-… key — aborting."; exit 1 ;; esac ;;
  2)  [ "$NET443" = 1 ] || warn "generic 443 looked blocked — a relay may still work if its host is allowed."
      printf "\n  Your relay's sshd needs:  ${BOLD}GatewayPorts clientspecified${RST}  (in /etc/ssh/sshd_config).\n"
      printf "  relay (user@host or user@host:443): "
      read -r R || R=""
      case "$R" in *@*) export SSH_RELAY="$R" TUNNEL_PROVIDER=relay; launch "relay → $R" ;;
                   *) err "not a user@host relay — aborting."; exit 1 ;; esac ;;
  3)  printf "\n  ngrok authtoken (${DIM}https://dashboard.ngrok.com${RST} → Your Authtoken)"
      [ "$NGROK_CFG" = 1 ] && printf " ${DIM}(Enter to reuse the configured one)${RST}"
      printf ": "
      read -r T || T=""
      [ -n "$T" ] && export NGROK_AUTHTOKEN="$T"
      export TUNNEL_PROVIDER=ngrok
      # reuse the token installer (installs ngrok + adds the token) then launch
      # shellcheck disable=SC1091
      . ./scripts/setup_tunnel_token.sh
      launch ngrok ;;
  4)  export TUNNEL_PROVIDER=pinggy;     launch pinggy ;;
  5)  export TUNNEL_PROVIDER=serveo;     launch serveo ;;
  6)  export TUNNEL_PROVIDER=cloudflare; launch cloudflare ;;
  0)  SSHFWD="-L ${APP_PORT}:127.0.0.1:${APP_PORT} -L ${TRAME_PORT}:127.0.0.1:${TRAME_PORT}"
      printf 'ssh %s -p <ssh-port> <user>@<host>\n' "$SSHFWD" > outputs/ssh_access.txt
      echo; ok "No public link — reach it from your machine with one SSH hop:"
      printf "    ${BOLD}ssh %s -p <ssh-port> <user>@<host>${RST}\n" "$SSHFWD"
      printf "    then open  ${BOLD}http://localhost:${APP_PORT}${RST}  (React)  ·  ${BOLD}http://localhost:${TRAME_PORT}${RST}  (trame)\n"
      ok "(saved to outputs/ssh_access.txt)"; exit 0 ;;
  *)  err "invalid choice: $CH"; exit 2 ;;
esac
