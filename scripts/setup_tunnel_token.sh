#!/usr/bin/env bash
# SOURCED by run_native.sh: optionally set up ngrok for a STABLE, no-time-limit public
# link. Does nothing if ngrok is already configured. Provide the token
# non-interactively with NGROK_AUTHTOKEN=… , or it prompts on a terminal. Press Enter
# to skip and use the free Pinggy tunnel (60-min sessions + a visitor splash page).
TOOLS="$(pwd)/.tools"; mkdir -p "$TOOLS"
_ng() { [ -x "$TOOLS/ngrok" ] && echo "$TOOLS/ngrok" || command -v ngrok 2>/dev/null || true; }

NG="$(_ng)"
if [ -n "$NG" ] && "$NG" config check >/dev/null 2>&1; then
  export TUNNEL_PROVIDER="${TUNNEL_PROVIDER:-ngrok}"          # already good -> prefer it
else
  # Some pods allowlist egress and block ngrok's host — don't offer ngrok if we can't
  # even reach its download endpoint (Pinggy will be used instead).
  _ngrok_reachable=1
  if command -v timeout >/dev/null 2>&1; then
    timeout 5 bash -c "exec 3<>/dev/tcp/bin.equinox.io/443" 2>/dev/null || _ngrok_reachable=0
  fi
  TOKEN="${NGROK_AUTHTOKEN:-}"
  if [ -z "$TOKEN" ] && [ "$_ngrok_reachable" = 0 ]; then
    echo "  ${DIM:-}ngrok's host is unreachable from this pod (egress-blocked) — using the free Pinggy tunnel.${RST:-}"
  elif [ -z "$TOKEN" ] && [ -t 0 ]; then
    printf "\n"
    printf "  ${BOLD:-}Public link — token (optional):${RST:-}\n"
    printf "    • ${BOLD:-}Enter${RST:-}  → free ${BOLD:-}Pinggy${RST:-} tunnel (no signup; 60-min sessions + a visitor splash page)\n"
    printf "    • paste a free ${BOLD:-}ngrok${RST:-} authtoken → ${BOLD:-}stable, no time limit, clean URL${RST:-}\n"
    printf "      (get one at ${DIM:-}https://dashboard.ngrok.com${RST:-} → 'Your Authtoken')\n"
    printf "  ngrok authtoken (or Enter to skip): "
    read -r TOKEN || TOKEN=""
  fi
  if [ -n "${TOKEN:-}" ]; then
    if [ -z "$(_ng)" ]; then
      arch=amd64; [ "$(uname -m)" = aarch64 ] && arch=arm64
      echo "  installing ngrok (local, ./.tools)…"
      url="https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-${arch}.tgz"
      if curl -fSL "$url" -o "$TOOLS/ngrok.tgz" 2>"$TOOLS/ngrok.err"; then
        tar xzf "$TOOLS/ngrok.tgz" -C "$TOOLS" 2>>"$TOOLS/ngrok.err" && rm -f "$TOOLS/ngrok.tgz"
        [ -f "$TOOLS/ngrok" ] && chmod +x "$TOOLS/ngrok"
      else
        echo "  ${YEL:-}!${RST:-} ngrok download failed: $(tail -1 "$TOOLS/ngrok.err" 2>/dev/null)"
        echo "     (bin.equinox.io may be blocked on this pod — see the manual step in the README/chat)"
      fi
    fi
    NG="$(_ng)"
    if [ -n "$NG" ] && "$NG" version >/dev/null 2>&1; then
      if "$NG" config add-authtoken "$TOKEN" 2>"$TOOLS/ngrok.err"; then
        export TUNNEL_PROVIDER=ngrok
        echo "  ${GRN:-}✓${RST:-} ngrok configured — stable, no-time-limit link"
      else
        echo "  ${YEL:-}!${RST:-} ngrok token config failed: $(tail -1 "$TOOLS/ngrok.err" 2>/dev/null) — using Pinggy"
      fi
    else
      echo "  ${YEL:-}!${RST:-} ngrok binary not runnable (download/arch issue) — using Pinggy"
    fi
  fi
fi

# ---------------------------------------------------------------------------
# Locked pod? When 7844 + pinggy(443) + serveo/lhr(22) + ngrok are ALL blocked (confirm
# with ./scripts/egress_probe.sh), the public-link paths left are Tailscale Funnel (rides
# 443/DERP — reachable even here) or an SSH relay to a box YOU control. Provide either
# non-interactively via ENV (TS_AUTHKEY=… or SSH_RELAY=user@host:443), or paste it here.
# Enter skips → the app is still reachable with `ssh -L` (see outputs/ssh_access.txt).
if [ "${TUNNEL_PROVIDER:-}" != ngrok ] && [ -z "${TS_AUTHKEY:-}" ] && [ -z "${SSH_RELAY:-}" ] && [ -t 0 ]; then
  printf "\n  ${BOLD:-}Public link on a locked pod — paste one (or Enter to skip → use ssh -L):${RST:-}\n"
  printf "    • ${BOLD:-}Tailscale${RST:-} auth key (${DIM:-}tskey-…${RST:-}) → Funnel over 443 ${BOLD:-}(recommended)${RST:-}\n"
  printf "        ${DIM:-}https://login.tailscale.com/admin/settings/keys${RST:-} — make it Reusable + Ephemeral,\n"
  printf "        then enable ${BOLD:-}HTTPS${RST:-} + ${BOLD:-}Funnel${RST:-} in the admin console (Settings → Features / ACL).\n"
  printf "    • or an ${BOLD:-}SSH relay${RST:-} you control: ${DIM:-}user@host:443${RST:-} (relay needs GatewayPorts clientspecified)\n"
  printf "  paste key / relay: "
  read -r _ans || _ans=""
  case "$_ans" in
    tskey-*) export TS_AUTHKEY="$_ans"; export TUNNEL_PROVIDER=tailscale
             echo "  ${GRN:-}✓${RST:-} Tailscale Funnel selected (the binary auto-installs next)" ;;
    *@*)     export SSH_RELAY="$_ans";  export TUNNEL_PROVIDER=relay
             echo "  ${GRN:-}✓${RST:-} SSH relay selected → ${_ans}" ;;
    "")      echo "  ${DIM:-}skipped — reach the app with ssh -L (outputs/ssh_access.txt)${RST:-}" ;;
    *)       echo "  ${YEL:-}!${RST:-} not a tskey-… key or user@host relay — skipped" ;;
  esac
fi
