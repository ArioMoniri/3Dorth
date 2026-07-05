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
  TOKEN="${NGROK_AUTHTOKEN:-}"
  if [ -z "$TOKEN" ] && [ -t 0 ]; then
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
      curl -fsSL "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-${arch}.tgz" -o "$TOOLS/ngrok.tgz" 2>/dev/null \
        && tar xzf "$TOOLS/ngrok.tgz" -C "$TOOLS" 2>/dev/null && rm -f "$TOOLS/ngrok.tgz"
    fi
    NG="$(_ng)"
    if [ -n "$NG" ] && "$NG" config add-authtoken "$TOKEN" >/dev/null 2>&1; then
      export TUNNEL_PROVIDER=ngrok
      echo "  ${GRN:-}✓${RST:-} ngrok configured — using it for a stable, no-time-limit link"
    else
      echo "  ${YEL:-}!${RST:-} ngrok setup failed — falling back to Pinggy"
    fi
  fi
fi
