#!/usr/bin/env bash
# egress_probe.sh — find the ONE way out of a locked-down pod.
#
# The 3Dorth public-tunnel problem is really one question: what can this pod actually
# reach outbound? This probes the exact hosts/ports every tunnel provider depends on —
# a raw TCP connect AND a real TLS/HTTP request (TCP-open is necessary but NOT
# sufficient; a firewall can accept SYN and drop the payload) — and prints a clean
# OPEN/BLOCKED table so we stop guessing.
#
#   ./scripts/egress_probe.sh            # probe the standard battery
#   ./scripts/egress_probe.sh --json     # also write outputs/egress_probe.json
#   ./scripts/egress_probe.sh --timeout 6
#
# No secrets, no writes outside outputs/. Read-only network probes. POSIX-ish bash.
set -uo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
. ./scripts/_ui.sh

TMO=5           # per-probe timeout (seconds); short on purpose
WANT_JSON=0
while [ $# -gt 0 ]; do case "$1" in
  --json)      WANT_JSON=1 ;;
  --timeout)   TMO="${2:-5}"; shift ;;
  --timeout=*) TMO="${1#*=}" ;;
  -h|--help)   grep -E '^#( |$)' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  *) err "unknown flag: $1  (use --json / --timeout N)"; exit 2 ;;
esac; shift; done
case "$TMO" in ''|*[!0-9]*) TMO=5 ;; esac

OUT="outputs/egress_probe.json"; mkdir -p outputs

# ---- timeout shim: prefer coreutils `timeout`; else fall back to a bash watchdog ----
# The target pod (Ubuntu) has `timeout`; keep a fallback so the probe still runs on a
# box that doesn't (e.g. a mac dev laptop) without hanging forever.
if command -v timeout >/dev/null 2>&1; then
  _to() { timeout "$1" "${@:2}"; }
else
  _to() {  # $1 seconds, rest = command
    local t="$1"; shift
    "$@" & local p=$!
    ( sleep "$t"; kill -9 "$p" 2>/dev/null ) & local w=$!
    wait "$p" 2>/dev/null; local rc=$?
    kill -9 "$w" 2>/dev/null; wait "$w" 2>/dev/null
    return $rc
  }
fi

# ---- raw TCP connect: does the 3-way handshake complete within TMO? ----
# This is the ONLY thing an SSH control path (pinggy/serveo/lhr) strictly needs to even
# begin. We pick the most reliable connector available, in order:
#   1) nc -z            (purpose-built, honest timeout)
#   2) python3 socket   (bulletproof, resolves + connects with a real timeout)
#   3) bash /dev/tcp    (last resort; note: bash 3.2's /dev/tcp mishandles hostnames,
#                        so we only lean on it where bash >= 4, e.g. the Ubuntu pod)
# Whichever we use, _to bounds the wall-clock so a black-holed SYN can't hang the run.
if command -v nc >/dev/null 2>&1 && nc -h 2>&1 | grep -q -- '-z'; then
  tcp_connect() { _to "$TMO" nc -z -w "$TMO" "$1" "$2" >/dev/null 2>&1; }
elif command -v python3 >/dev/null 2>&1; then
  tcp_connect() {
    _to "$TMO" python3 - "$1" "$2" "$TMO" <<'PY' >/dev/null 2>&1
import socket,sys
h,p,t=sys.argv[1],int(sys.argv[2]),float(sys.argv[3])
s=socket.create_connection((h,p),timeout=t); s.close()
PY
  }
else
  tcp_connect() { _to "$TMO" bash -c "exec 3<>/dev/tcp/$1/$2" 2>/dev/null; }
fi

# ---- real TLS/HTTP request (connect is necessary, not sufficient) ----
# A stateful firewall can complete the handshake then drop the TLS ClientHello / SNI —
# so we insist on getting BYTES BACK, not just an open socket. Uses curl if present
# (best signal: real HTTP code), else openssl s_client for a TLS-only reachability check.
tls_probe() {  # $1 host  $2 port  -> prints a short detail; rc 0 = got a response
  local h="$1" p="$2" code=""
  if command -v curl >/dev/null 2>&1; then
    if [ "$p" = 443 ]; then
      code="$(_to "$TMO" curl -sk -o /dev/null -m "$TMO" -w '%{http_code}' "https://$h:$p/" 2>/dev/null)"
    else
      # non-443: try https first, then plain http on that port
      code="$(_to "$TMO" curl -sk -o /dev/null -m "$TMO" -w '%{http_code}' "https://$h:$p/" 2>/dev/null)"
      if [ -z "$code" ] || [ "$code" = 000 ]; then
        code="$(_to "$TMO" curl -s  -o /dev/null -m "$TMO" -w '%{http_code}' "http://$h:$p/" 2>/dev/null)"
      fi
    fi
    if [ -n "$code" ] && [ "$code" != 000 ]; then printf 'HTTP %s' "$code"; return 0; fi
    printf 'no HTTP reply'; return 1
  elif command -v openssl >/dev/null 2>&1 && [ "$p" = 443 ]; then
    if printf 'Q\n' | _to "$TMO" openssl s_client -connect "$h:$p" -servername "$h" >/dev/null 2>&1; then
      printf 'TLS ok'; return 0
    fi
    printf 'no TLS reply'; return 1
  fi
  printf 'no http client'; return 1
}

# ---- grab an SSH banner: proof the SSH service (not just an open port) answered ----
# Same connector preference as tcp_connect; returns the (sanitised) banner text on stdout.
ssh_banner() {  # $1 host  $2 port
  if command -v python3 >/dev/null 2>&1; then
    _to "$TMO" python3 - "$1" "$2" "$TMO" <<'PY' 2>/dev/null
import socket,sys
h,p,t=sys.argv[1],int(sys.argv[2]),float(sys.argv[3])
s=socket.create_connection((h,p),timeout=t); s.settimeout(t)
try: sys.stdout.write(s.recv(64).decode('latin-1'))
except Exception: pass
finally: s.close()
PY
  else
    _to "$TMO" bash -c "exec 3<>/dev/tcp/$1/$2; head -c 64 <&3" 2>/dev/null
  fi
}

# ---- UDP/QUIC hint for cloudflare's 7844 (best-effort; UDP has no handshake) ----
# We can't truly "connect" UDP, but if a datagram send fails outright that's a strong
# blocked signal; success is only weak evidence (no reply expected). Cloudflare 7844 is
# the known-blocked case on these pods, so we label it explicitly.
udp_hint() {  # $1 host  $2 port
  _to "$TMO" bash -c "exec 3<>/dev/udp/$1/$2 && printf '' >&3" 2>/dev/null
}

# ---- DNS resolution probe (port 53) ----
dns_probe() {  # $1 resolver-or-name
  if command -v getent >/dev/null 2>&1; then
    _to "$TMO" getent hosts "$1" >/dev/null 2>&1 && return 0
  fi
  if command -v nslookup >/dev/null 2>&1; then
    _to "$TMO" nslookup "$1" >/dev/null 2>&1 && return 0
  fi
  # last resort: can we open 53/tcp to a known public resolver?
  tcp_connect 1.1.1.1 53
}

# ---- probe battery -----------------------------------------------------------------
# Each row: label | host | port | kind | why-it-matters
#   kind: tls (443/http provider edge), ssh (SSH control path), quic (cloudflare UDP),
#         raw (plain reachability), dns (name resolution)
PROBES="
a.pinggy.io|a.pinggy.io|443|ssh|Pinggy SSH control path (tunnel.sh: ssh -p 443 a.pinggy.io)
pinggy.link-edge|t.pinggy.link|443|tls|Pinggy PUBLIC edge — what OUTSIDERS load (the self-verify curl target)
cloudflare-7844|region1.v2.argotunnel.com|7844|quic|Cloudflare QUIC/HTTP2 edge — KNOWN blocked on these pods
cloudflare-443|region1.v2.argotunnel.com|443|tls|Cloudflare argotunnel edge over 443 (http2 fallback path)
serveo.net|serveo.net|22|ssh|Serveo SSH reverse-tunnel control path (port 22)
localhost.run|localhost.run|22|ssh|localhost.run / lhr SSH control path (port 22)
bin.equinox.io|bin.equinox.io|443|tls|ngrok DOWNLOAD host — if blocked, ngrok never installs
tailscale-login|login.tailscale.com|443|tls|Tailscale coordination (a real fallback if this alone is open)
1.1.1.1:443|1.1.1.1|443|tls|Cloudflare DNS-over-HTTPS — bare 443 reachability to a well-known IP
example.com:443|example.com|443|tls|Neutral 443 control — proves generic outbound HTTPS works at all
dns-53|1.1.1.1|53|dns|DNS resolution / 53 reachability (nothing works without names)
"

# results collector for the JSON + red-team summary
RES_TMP="$(mktemp 2>/dev/null || echo "outputs/.egress.$$")"
: > "$RES_TMP"
OPEN_443=0; OPEN_SSH=""; CF_QUIC_OPEN=0; CF_443_OPEN=0; PINGGY_CTRL=0; PINGGY_EDGE=0

banner
step "Egress probe — what can THIS pod actually reach? (timeout ${TMO}s/probe)"
printf "  ${DIM}TCP-open is necessary but not sufficient: a firewall can accept the handshake and drop the payload,${RST}\n"
printf "  ${DIM}so every 443/http row also does a real TLS/HTTP request and demands bytes back.${RST}\n\n"

# table header
HFMT="  %-18s %-34s %-6s %-9s %s\n"
printf "${BOLD}${HFMT}${RST}" "TARGET" "HOST" "PORT" "TCP" "TLS/HTTP or NOTE"
printf "  %s\n" "──────────────────────────────────────────────────────────────────────────────────────"

RFMT="  %-18s %-34s %-6s %b%-9s%b %s\n"
while IFS='|' read -r label host port kind why; do
  [ -z "${label:-}" ] && continue
  # --- TCP connect (skip for pure quic/udp rows; UDP has no handshake) ---
  tcp_txt="—"; tcp_open=0
  if [ "$kind" != quic ]; then
    if tcp_connect "$host" "$port"; then tcp_txt="OPEN"; tcp_open=1; else tcp_txt="BLOCKED"; fi
  fi
  # --- second-stage probe depending on kind ---
  note=""; app_ok=0
  case "$kind" in
    tls)
      if [ "$tcp_open" = 1 ]; then note="$(tls_probe "$host" "$port")" && app_ok=1 || :; else note="(tcp blocked)"; fi ;;
    ssh)
      # SSH control path: the tunnel only needs the TCP handshake + an SSH banner. We
      # DON'T need HTTP here. Grab the banner as proof the SSH service answered.
      if [ "$tcp_open" = 1 ]; then
        b="$(ssh_banner "$host" "$port" | tr -d '\r\n' | tr -c 'A-Za-z0-9._ -' ' ')"
        case "$b" in *SSH-*) note="banner: ${b}"; app_ok=1 ;; *) note="open, no SSH banner (proxy/filter?)" ;; esac
      else note="(tcp blocked)"; fi ;;
    quic)
      if udp_hint "$host" "$port"; then tcp_txt="UDP?"; note="datagram sent (no reply expected; usually still blocked)"; else tcp_txt="BLOCKED"; note="UDP send failed — 7844 blocked (expected on these pods)"; fi ;;
    dns)
      if dns_probe example.com; then tcp_txt="OPEN"; note="name resolution works"; app_ok=1; else note="DNS resolution FAILED"; fi ;;
    raw)
      note="" ;;
  esac

  # colourise the TCP/UDP cell
  col="$GRN"; case "$tcp_txt" in BLOCKED) col="$RED" ;; UDP?|"—") col="$YEL" ;; esac
  printf "$RFMT" "$label" "$host" "$port" "$col" "$tcp_txt" "$RST" "$note"

  # record for JSON + summary
  printf '%s|%s|%s|%s|%s|%s|%s\n' "$label" "$host" "$port" "$kind" "$tcp_open" "$app_ok" "$note" >> "$RES_TMP"

  # roll up the decision signals
  case "$label" in
    a.pinggy.io)       [ "$tcp_open" = 1 ] && PINGGY_CTRL=1 ;;
    pinggy.link-edge)  [ "$app_ok" = 1 ]  && PINGGY_EDGE=1 ;;
    cloudflare-7844)   : ;;  # quic handled below
    cloudflare-443)    [ "$app_ok" = 1 ]  && CF_443_OPEN=1 ;;
    serveo.net)        [ "$app_ok" = 1 ]  && OPEN_SSH="$OPEN_SSH serveo.net:22" ;;
    localhost.run)     [ "$app_ok" = 1 ]  && OPEN_SSH="$OPEN_SSH localhost.run:22" ;;
    example.com:443)   [ "$app_ok" = 1 ]  && OPEN_443=1 ;;
    1.1.1.1:443)       [ "$app_ok" = 1 ]  && OPEN_443=1 ;;
  esac
  [ "$label" = a.pinggy.io ] && [ "$app_ok" = 1 ] && OPEN_SSH="$OPEN_SSH a.pinggy.io:443"
done <<EOF
$PROBES
EOF

echo
# ---- verdict ----------------------------------------------------------------------
step "${BOLD}Verdict${RST}"
if [ "$OPEN_443" = 1 ]; then
  ok "Outbound 443 WORKS (generic HTTPS egress is open)."
else
  err "Outbound 443 to neutral hosts FAILED — this pod may have (near-)zero egress. See red-team below."
fi
if [ -n "$OPEN_SSH" ]; then
  ok "SSH tunnel control path(s) reachable:${OPEN_SSH}"
else
  warn "No SSH tunnel control path answered (pinggy 443 / serveo 22 / lhr 22 all blocked)."
fi
if [ "$PINGGY_CTRL" = 1 ] && [ "$PINGGY_EDGE" = 0 ]; then
  warn "Pinggy CONTROL path (a.pinggy.io:443) is OPEN but the PUBLIC edge (*.pinggy.link) is NOT reachable from here."
  warn "→ This is the FALSE-REJECT trap: outsiders CAN load the tunnel, but tunnel.sh's self-curl can't, so it discards a WORKING link."
fi
if [ "$CF_443_OPEN" = 0 ]; then
  warn "Cloudflare edge (7844 QUIC and 443 argotunnel) unreachable — cloudflared can't register. Don't fight it; use an SSH/443 provider."
fi

# ---- ONE-LINE verdict: which path (if any) to actually use ------------------------
echo
if [ "$PINGGY_CTRL" = 1 ]; then
  ok "${BOLD}USE → Pinggy over 443.${RST}  Restart:  TUNNEL_PROVIDER=pinggy ./scripts/tunnel.sh ${APP_PORT:-8000}   (or re-run ./scripts/run_native.sh)"
elif [ -n "$OPEN_SSH" ]; then
  ok "${BOLD}USE → an SSH provider that answered:${RST}${OPEN_SSH}.  Restart:  ./scripts/tunnel.sh ${APP_PORT:-8000}"
elif [ "$OPEN_443" = 1 ]; then
  warn "${BOLD}443 is open but no tunnel provider answered${RST} — set your own relay:  SSH_RELAY=user@host:443 ./scripts/tunnel.sh ${APP_PORT:-8000}  (or Tailscale: TS_AUTHKEY=… )"
else
  err "${BOLD}No usable egress from this pod.${RST}  Reach the app WITHOUT a public tunnel:  ssh -L ${APP_PORT:-8000}:127.0.0.1:${APP_PORT:-8000} -p 30405 root@10.6.110.10   then open http://localhost:${APP_PORT:-8000}  (or expose a cluster Ingress/NodePort)."
fi

# ---- JSON (opt-in; never contains secrets) ----------------------------------------
if [ "$WANT_JSON" = 1 ]; then
  {
    printf '{\n  "updated": "%s",\n  "timeout_s": %s,\n  "probes": [\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$TMO"
    first=1
    while IFS='|' read -r label host port kind tcp app note; do
      [ -z "${label:-}" ] && continue
      [ "$first" = 1 ] || printf ',\n'; first=0
      printf '    {"target":"%s","host":"%s","port":"%s","kind":"%s","tcp_open":%s,"app_ok":%s,"note":"%s"}' \
        "$label" "$host" "$port" "$kind" "$([ "$tcp" = 1 ] && echo true || echo false)" \
        "$([ "$app" = 1 ] && echo true || echo false)" "$(printf '%s' "$note" | sed 's/"/\\"/g')"
    done < "$RES_TMP"
    printf '\n  ],\n'
    printf '  "outbound_443": %s,\n' "$([ "$OPEN_443" = 1 ] && echo true || echo false)"
    printf '  "ssh_control_open": "%s",\n' "$(echo "$OPEN_SSH" | sed 's/^ *//')"
    printf '  "pinggy_false_reject": %s\n' "$([ "$PINGGY_CTRL" = 1 ] && [ "$PINGGY_EDGE" = 0 ] && echo true || echo false)"
    printf '}\n'
  } > "$OUT"
  ok "wrote $OUT"
fi

rm -f "$RES_TMP" 2>/dev/null
exit 0
