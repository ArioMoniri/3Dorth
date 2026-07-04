#!/usr/bin/env bash
# Shared UI helpers for the 3Dorth deploy scripts: colours, the banner, tiny
# log helpers. Sourced by setup.sh and run_native.sh — not run directly.

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  C1=$'\033[38;5;45m'; C2=$'\033[38;5;39m'; C3=$'\033[38;5;33m'
  BOLD=$'\033[1m'; DIM=$'\033[2m'; GRN=$'\033[32m'; YEL=$'\033[33m'; RED=$'\033[31m'; CYN=$'\033[36m'; RST=$'\033[0m'
else
  C1=""; C2=""; C3=""; BOLD=""; DIM=""; GRN=""; YEL=""; RED=""; CYN=""; RST=""
fi

# The figlet renders on any UTF-8 terminal (independent of the server's $LANG); set
# ASCII_BANNER=1 to force the plain fallback on a terminal that can't do box chars.
_utf8() { [ -z "${ASCII_BANNER:-}" ]; }

banner() {
  if _utf8; then
    printf "%s\n" \
"${C1} ██████╗ ██████╗  ██████╗ ██████╗ ████████╗██╗  ██╗" \
"${C1} ╚════██╗██╔══██╗██╔═══██╗██╔══██╗╚══██╔══╝██║  ██║" \
"${C2}  █████╔╝██║  ██║██║   ██║██████╔╝   ██║   ███████║" \
"${C2}  ╚═══██╗██║  ██║██║   ██║██╔══██╗   ██║   ██╔══██║" \
"${C3} ██████╔╝██████╔╝╚██████╔╝██║  ██║   ██║   ██║  ██║" \
"${C3} ╚═════╝ ╚═════╝  ╚═════╝ ╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝${RST}"
  else
    printf "%s\n" "${C1}  3 D o r t h${RST}"
  fi
  printf "${DIM} ────────────────────────────────────────────────────${RST}\n"
  printf "  ${BOLD}3Dorth${RST}${DIM} · quantitative cortical-thickness mapping · deploy${RST}\n\n"
}

# status helpers: ok/warn/err/step  (self-documenting logs the user can act on)
ok()   { printf "  ${GRN}✓${RST} %s\n" "$*"; }
warn() { printf "  ${YEL}!${RST} %s\n" "$*"; }
err()  { printf "  ${RED}✗${RST} %s\n" "$*"; }
step() { printf "${BOLD}▶${RST} %s\n" "$*"; }
