#!/usr/bin/env bash
# Resilient PUBLIC tunnel manager. Instead of fragile pre-probes, it TRIES each provider,
# VERIFIES it actually serves, and keeps the first that works — then holds it alive and
# rewrites the live URL into outputs/public_urls.json (+ the app's top bar). Built for
# egress-restricted pods that allow only one path out.
#
# READY SIGNAL (the crux). cloudflare is "ready" only when its log shows a registered
# edge connection. For SSH-based providers (pinggy/serveo/lhr/relay) the pod often
# CANNOT curl the tunnel's own public edge even when OUTSIDERS can reach it (the pod's
# egress blocks *.pinggy.link/*.serveo.net/*.lhr.life while the ssh control port is
# allowed). So an ssh provider is "ready" when a public URL was EMITTED in its log AND
# the ssh child is still alive. The self-curl is kept only as a BONUS signal to LABEL
# the link "verified"; a failed self-curl NEVER rejects. Run scripts/egress_probe.sh to
# see exactly which paths this pod has.
#
# Order (override with TUNNEL_PROVIDER=ngrok|cloudflare|pinggy|serveo|lhr|relay|tailscale):
#   relay (if SSH_RELAY set) → ngrok (if configured) → cloudflare → pinggy(443) →
#   serveo → localhost.run → tailscale (if TS_AUTHKEY set)
#
# ENV knobs:
#   TUNNEL_PROVIDER  force a single provider (skips auto-selection)
#   SSH_RELAY        user@host[:port] of a box YOU control with open internet + public
#                    sshd (GatewayPorts clientspecified). App is reverse-forwarded there.
#   RELAY_REMOTE_PORT  public port to bind on the relay (default = app port)
#   TS_AUTHKEY       Tailscale auth key (ephemeral recommended) for userspace Funnel.
#   TS_HOSTNAME      node name on the tailnet (default 3dorth-pod)
#   Secrets come from ENV only — never written to the repo or to outputs/.
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

# ---- relay / tailscale config (non-secret host spec parsed here) ------------
RELAY_USER=""; RELAY_HOST=""; RELAY_PORT=22
if [ -n "${SSH_RELAY:-}" ]; then
  _spec="$SSH_RELAY"
  case "$_spec" in *:*) RELAY_PORT="${_spec##*:}"; _spec="${_spec%:*}" ;; esac
  RELAY_USER="${_spec%@*}"; RELAY_HOST="${_spec#*@}"
  case "$RELAY_PORT" in ''|*[!0-9]*) RELAY_PORT=22 ;; esac
fi
RELAY_REMOTE_PORT="${RELAY_REMOTE_PORT:-$APP_PORT}"
TS_HOSTNAME="${TS_HOSTNAME:-3dorth-pod}"
TS_SOCK="$TOOLS/tailscaled.sock"

# Auto-install tailscale (userspace binaries) into ./.tools when a key is provided but
# the binary is missing. pkgs.tailscale.com is plain 443 and reachable even on pods that
# block every SSH-tunnel host — which is exactly when Funnel is the only way out.
ensure_tailscale() {
  [ -n "${TS_AUTHKEY:-}" ] || return 0
  { command -v tailscaled >/dev/null 2>&1 || [ -x "$TOOLS/tailscaled" ]; } && return 0
  local arch=amd64; case "$(uname -m)" in aarch64|arm64) arch=arm64 ;; esac
  local ver; ver="$(curl -fsSL https://pkgs.tailscale.com/stable/ 2>/dev/null \
      | grep -oE "tailscale_[0-9.]+_${arch}\.tgz" | head -1 | sed -E "s/.*_([0-9.]+)_${arch}\.tgz/\1/")"
  [ -n "$ver" ] || ver="1.98.8"
  step "installing tailscale ${ver} (userspace, ./.tools — no root, removable)…"
  mkdir -p "$TOOLS"
  if curl -fSL "https://pkgs.tailscale.com/stable/tailscale_${ver}_${arch}.tgz" -o "$TOOLS/ts.tgz" 2>"$TOOLS/ts.err" \
     && tar xzf "$TOOLS/ts.tgz" -C "$TOOLS" --strip-components=1 \
          "tailscale_${ver}_${arch}/tailscale" "tailscale_${ver}_${arch}/tailscaled" 2>>"$TOOLS/ts.err"; then
    rm -f "$TOOLS/ts.tgz"; chmod +x "$TOOLS/tailscale" "$TOOLS/tailscaled" 2>/dev/null
    export PATH="$TOOLS:$PATH"; ok "tailscale ready"
  else
    warn "tailscale install failed: $(tail -1 "$TOOLS/ts.err" 2>/dev/null) — other providers / ssh -L still apply"
  fi
}

kill_all() {
  pkill -9 -f "cloudflared tunnel --url"        2>/dev/null
  pkill -9 -f "ssh .*a.pinggy.io"               2>/dev/null
  pkill -9 -f "ssh .*serveo.net"                2>/dev/null
  pkill -9 -f "ssh .*localhost.run"             2>/dev/null
  pkill -9 -f "ssh .*-R .*:127.0.0.1:"          2>/dev/null   # SSH_RELAY reverse-forward
  pkill -9 -f "ngrok http"                      2>/dev/null
  if [ -n "${TS_AUTHKEY:-}" ] && [ -S "$TS_SOCK" ]; then
    tailscale --socket="$TS_SOCK" down >/dev/null 2>&1 || true
  fi
  pkill -9 -f "tailscaled .*$TS_SOCK"           2>/dev/null
}
trap 'kill_all; rm -f "$LOGD"/.keep 2>/dev/null; exit 0' INT TERM
kill_all; sleep 1

# --- run one tunnel for a port into a log (blocking; wrapped by keepalive) ---
start_tunnel() {   # $1 prov  $2 port  $3 log
  case "$1" in
    cloudflare) cloudflared tunnel --url "http://127.0.0.1:$2" --protocol http2 --no-autoupdate >>"$3" 2>&1 ;;
    pinggy)     ssh -p 443 -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
                    -o ExitOnForwardFailure=yes -o ConnectTimeout=20 -R0:127.0.0.1:"$2" a.pinggy.io >>"$3" 2>&1 ;;
    serveo)     ssh -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
                    -o ExitOnForwardFailure=yes -o ConnectTimeout=20 -R 80:127.0.0.1:"$2" serveo.net >>"$3" 2>&1 ;;
    lhr)        ssh -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
                    -o ExitOnForwardFailure=yes -o ConnectTimeout=20 -R 80:127.0.0.1:"$2" nokey@localhost.run >>"$3" 2>&1 ;;
    relay)      ssh -N -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
                    -o ExitOnForwardFailure=yes -o ConnectTimeout=20 -o BatchMode=yes \
                    -p "$RELAY_PORT" -R "0.0.0.0:${RELAY_REMOTE_PORT}:127.0.0.1:$2" \
                    "${RELAY_USER}@${RELAY_HOST}" >>"$3" 2>&1 ;;
    ngrok)      ngrok http "$2" --log stdout >>"$3" 2>&1 ;;
    tailscale)  start_tailscale "$2" "$3" ;;
  esac
}

# --- tailscale userspace funnel (unprivileged; rides 443/DERP) ---------------
start_tailscale() {  # $1 port  $2 log
  command -v tailscaled >/dev/null 2>&1 || { echo "tailscaled not installed" >>"$2"; return 1; }
  if [ ! -S "$TS_SOCK" ] || ! tailscale --socket="$TS_SOCK" status >/dev/null 2>&1; then
    tailscaled --tun=userspace-networking --socket="$TS_SOCK" \
               --statedir="$TOOLS/ts-state" >>"$2" 2>&1 &
    sleep 2
    # authkey is redacted in the log; only its presence is noted
    echo "$(date +%H:%M:%S) tailscale up (authkey ***redacted***)" >>"$2"
    tailscale --socket="$TS_SOCK" up --authkey="${TS_AUTHKEY}" \
              --hostname="$TS_HOSTNAME" --accept-routes=false --ssh=false >>"$2" 2>&1
  fi
  tailscale --socket="$TS_SOCK" funnel --bg "$1" >>"$2" 2>&1
  # keep this call blocking-ish so keepalive's loop paces itself
  tailscale --socket="$TS_SOCK" funnel status >>"$2" 2>&1
  sleep 20
}

url_from() {       # $1 prov  $2 log
  case "$1" in
    cloudflare) grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$2" 2>/dev/null | tail -1 ;;
    pinggy)     grep -oiE 'https://[a-z0-9.-]*pinggy[a-z0-9.-]*' "$2" 2>/dev/null | grep -vi dashboard | head -1 ;;
    serveo)     grep -oE 'https://[a-z0-9-]+\.serveo\.net' "$2" 2>/dev/null | tail -1 ;;
    lhr)        grep -oE 'https://[a-z0-9]+\.lhr\.life' "$2" 2>/dev/null | tail -1 ;;
    ngrok)      grep -oE 'https://[-a-z0-9]+\.ngrok[-a-z0-9.]*\.(app|io|dev)' "$2" 2>/dev/null | tail -1 ;;
    tailscale)  grep -oE 'https://[-a-z0-9.]+\.ts\.net[^ ]*' "$2" 2>/dev/null | tail -1 ;;
    relay)      # no scrape-able URL; the public endpoint is on the relay host
                if grep -qi 'remote port forwarding failed\|forwarding request failed' "$2" 2>/dev/null; then
                  echo ""
                else
                  echo "http://${RELAY_HOST}:${RELAY_REMOTE_PORT}"
                fi ;;
  esac
}

# --- is the actual ssh child for a provider still alive? ---------------------
# keepalive()'s $! is the WRAPPER LOOP, not ssh, so we match the real ssh child by its
# argv (port-scoped so a stale different-port ssh can't false-match). Mirrors the exact
# ssh invocations in start_tunnel above.
ssh_alive() {   # $1 prov  $2 port
  case "$1" in
    pinggy) pgrep -f "ssh .*-R0:127.0.0.1:$2 .*a.pinggy.io"            >/dev/null 2>&1 ;;
    serveo) pgrep -f "ssh .*-R 80:127.0.0.1:$2 .*serveo.net"          >/dev/null 2>&1 ;;
    lhr)    pgrep -f "ssh .*-R 80:127.0.0.1:$2 .*localhost.run"        >/dev/null 2>&1 ;;
    relay)  pgrep -f "ssh .*-R 0.0.0.0:${RELAY_REMOTE_PORT}:127.0.0.1:$2" >/dev/null 2>&1 ;;
    *)      return 1 ;;
  esac
}

# --- bonus (never-reject) self-curl: labels the link "verified" if it responds ---
self_reachable() {  # $1 url  -> 0 only on 2xx/3xx (2xx/3xx from THIS pod)
  case "$1" in http*://* ) ;; * ) return 1 ;; esac
  local c; c="$(curl -s -o /dev/null -m 8 -w '%{http_code}' "$1" 2>/dev/null)"
  case "$c" in 2*|3*) return 0 ;; *) return 1 ;; esac
}

# a provider is "ready" — echoes the URL on success, else nothing + non-zero.
# CONTRACT (unchanged): stdout=URL on ready, silent+return 1 otherwise. Runs inside a
# command substitution (subshell), so it must NOT rely on setting parent variables.
ready_url() {      # $1 prov  $2 log  [$3 port]
  local u; u="$(url_from "$1" "$2")"; [ -z "$u" ] && return 1
  case "$1" in
    cloudflare)
      grep -q "Registered tunnel connection" "$2" 2>/dev/null && echo "$u" || return 1 ;;
    ngrok)
      echo "$u" ;;   # ngrok only prints the URL after its edge session is established
    pinggy|serveo|lhr|relay)
      # READY = URL emitted + ssh child alive. curl is NOT a gate here.
      ssh_alive "$1" "${3:-}" && { echo "$u"; return 0; }
      # child not matched by pgrep (rare arg drift) — fall back to a live self-curl
      self_reachable "$u" && { echo "$u"; return 0; }
      return 1 ;;
    tailscale)
      # funnel URL only appears once the DERP/edge mapping is live
      echo "$u" ;;
    *) return 1 ;;
  esac
}
keepalive() {      # $1 prov  $2 port  $3 log  — restarts the tunnel forever
  while :; do : >"$3"; start_tunnel "$1" "$2" "$3"; echo "$(date +%H:%M:%S) $1:$2 exited — restart" >>"$3"; sleep 3; done
}

# candidate providers, in preference order, filtered by what's installed/configured
ensure_tailscale   # fetch tailscale on demand so `command -v tailscaled` below can pass
CANDS=""
if [ -n "${TUNNEL_PROVIDER:-}" ]; then CANDS="$TUNNEL_PROVIDER"; else
  [ -n "${SSH_RELAY:-}" ] && command -v ssh >/dev/null 2>&1 && CANDS="$CANDS relay"
  command -v ngrok       >/dev/null 2>&1 && ngrok config check >/dev/null 2>&1 && CANDS="$CANDS ngrok"
  command -v cloudflared >/dev/null 2>&1 && CANDS="$CANDS cloudflare"
  command -v ssh         >/dev/null 2>&1 && CANDS="$CANDS pinggy serveo lhr"
  [ -n "${TS_AUTHKEY:-}" ] && command -v tailscaled >/dev/null 2>&1 && CANDS="$CANDS tailscale"
fi

PICK=""; APPURL=""
for prov in $CANDS; do
  step "Trying tunnel: ${BOLD}${prov}${RST} (verifying it actually serves)…"
  RLOG="$LOGD/app-$prov.log"; keepalive "$prov" "$APP_PORT" "$RLOG" & KP=$!
  # cloudflare rejects fast (registration); the ssh / tailscale ones need longer to bind
  case "$prov" in cloudflare) tries=9 ;; tailscale) tries=24 ;; *) tries=18 ;; esac
  for _ in $(seq 1 "$tries"); do
    u="$(ready_url "$prov" "$RLOG" "$APP_PORT")" && { PICK="$prov"; APPURL="$u"; break; }
    kill -0 "$KP" 2>/dev/null || break
    sleep 3
  done
  [ -n "$PICK" ] && { ok "${prov} → ${APPURL}"; break; }
  kill "$KP" 2>/dev/null; kill_all; sleep 1; warn "${prov} did not produce a working URL — next"
done

if [ -z "$PICK" ]; then
  err "No public tunnel works from this network (egress may allow none of them)."
  echo
  err "Why each provider failed — last lines of each attempt log:"
  for lg in "$LOGD"/app-*.log; do
    [ -f "$lg" ] || continue
    p="$(basename "$lg" .log)"; p="${p#app-}"
    printf "  ${DIM}── %s ──────────────────────────────────────────${RST}\n" "$p"
    tail -n 15 "$lg" 2>/dev/null | sed 's/^/    /'
  done
  echo
  err "The app is up locally: http://127.0.0.1:${APP_PORT}"
  err "Honest options when the pod has no usable public egress:"
  err "  1) From YOUR machine (inbound SSH already works):"
  err "       ssh -L ${APP_PORT}:127.0.0.1:${APP_PORT} -p 30405 root@10.6.110.10   then open http://localhost:${APP_PORT}"
  err "  2) Reverse-forward to a relay YOU control that has open internet:"
  err "       SSH_RELAY=user@your-host:443 ./scripts/tunnel.sh ${APP_PORT}   (relay needs GatewayPorts clientspecified)"
  err "  3) Expose a cluster Ingress / NodePort via your admin."
  err "  Diagnose exactly what IS reachable:  ./scripts/egress_probe.sh"
  printf '{\n  "react_url": "",\n  "trame_url": "",\n  "self_verified": false,\n  "note": "no public tunnel reachable (egress blocked) — use SSH -L, an SSH_RELAY you control, or a Kubernetes Ingress; run scripts/egress_probe.sh"\n}\n' > "$OUT"
  exit 0
fi

# trame on the same provider (best-effort; ngrok free = one tunnel only; relay/tailscale = single endpoint)
TLOG=""
if [ -n "$TRAME_PORT" ] && [ "$PICK" != ngrok ] && [ "$PICK" != relay ] && [ "$PICK" != tailscale ]; then
  TLOG="$LOGD/trame-$PICK.log"; keepalive "$PICK" "$TRAME_PORT" "$TLOG" &
fi

# publish + keep the URL fresh (rotates on reconnect for the free providers)
last=""
while :; do
  r="$(url_from "$PICK" "$RLOG")"; [ -z "$r" ] && r="$APPURL"
  t=""; [ -n "$TLOG" ] && t="$(url_from "$PICK" "$TLOG")"
  cur="$r|$t"
  if [ "$cur" != "$last" ] && [ -n "$r" ]; then
    # BONUS self-check (never rejects) — purely to LABEL the link honestly.
    if [ "$PICK" = cloudflare ] || [ "$PICK" = ngrok ] || self_reachable "$r"; then
      VERIFIED=true;  NOTE="auto-selected working tunnel (${PICK})"
    else
      VERIFIED=false; NOTE="published unverified (pod egress can't self-check; outsiders may still reach it) — test ${PICK} link from OUTSIDE"
    fi
    cat > "$OUT" <<JSON
{
  "react_url": "${r}",
  "trame_url": "${t}",
  "api_url": "${r}/api",
  "provider": "${PICK}",
  "self_verified": ${VERIFIED},
  "updated": "$(date -u '+%Y-%m-%dT%H:%M:%SZ')",
  "note": "${NOTE}"
}
JSON
    echo
    printf "  ${GRN}${BOLD}APP  ${RST} %s\n" "${r}"
    [ -n "$t" ] && printf "  ${GRN}${BOLD}TRAME${RST} %s\n" "$t"
    if [ "$VERIFIED" = false ]; then
      warn "couldn't self-verify ${r} from this pod (egress blocks the public edge) — open it from another network to confirm"
    fi
    printf "  ${DIM}(also in outputs/public_urls.json and the app's top bar; leave this running)${RST}\n"
    last="$cur"
  fi
  sleep 6
done
