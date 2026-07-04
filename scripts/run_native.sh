#!/usr/bin/env bash
# Native run — NO Docker, NO Kubernetes. For bare Ubuntu boxes/containers where
# dockerd won't run. Keeps everything LOCAL for easy removal: a Python venv (.venv),
# a private Node + cloudflared under ./.tools, and only the unavoidable system GL/Xvfb
# libraries via apt (tracked in .tools/apt-installed.txt so --uninstall removes exactly
# those). Self-healing (retries transient failures) and reports every issue at the end.
#
#   ./scripts/run_native.sh            # install (local) + build + run + tunnel  (strict 127.0.0.1)
#   ./scripts/run_native.sh --expose   # bind 0.0.0.0
#   ./scripts/run_native.sh --no-trame # skip the trame UI
#   ./scripts/run_native.sh --down      # stop what this started (keeps installs)
#   ./scripts/run_native.sh --uninstall # stop + remove venv/.tools/build + tracked apt pkgs
set -uo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
. ./scripts/_ui.sh

SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"
APT="$SUDO apt-get"
TOOLS="$(pwd)/.tools"; APT_LOG="$TOOLS/apt-installed.txt"
have() { command -v "$1" >/dev/null 2>&1; }
ISSUES=""
note_issue() { ISSUES="${ISSUES}\n  ${RED}•${RST} $*"; }
retry() { local n="$1"; shift; local i=1; until "$@"; do [ "$i" -ge "$n" ] && return 1; warn "retry $i/$n: $*"; sleep $((i*2)); i=$((i+1)); done; }

WITH_TRAME=1; STRICT=1
for a in "$@"; do case "$a" in
  --no-trame) WITH_TRAME=0 ;;
  --expose)   STRICT=0 ;;
  --down)
    pkill -f "uvicorn api.main:app" 2>/dev/null; pkill -f "app_trame.app" 2>/dev/null
    pkill -f "cloudflared tunnel" 2>/dev/null; pkill -f "scripts/share.sh" 2>/dev/null
    ok "stopped native 3Dorth (installs kept — use --uninstall to remove them)."; exit 0 ;;
  --uninstall)
    banner; step "Uninstalling native 3Dorth (local artefacts + tracked apt packages)…"
    pkill -f "uvicorn api.main:app" 2>/dev/null; pkill -f "app_trame.app" 2>/dev/null
    pkill -f "cloudflared tunnel" 2>/dev/null; pkill -f "scripts/share.sh" 2>/dev/null
    rm -rf .venv "$TOOLS" app_react/dist app_react/node_modules 2>/dev/null && ok "removed .venv, .tools, React build/node_modules"
    if [ -f "$APT_LOG" ]; then :; fi
    if [ -s "$APT_LOG" ]; then
      pkgs="$(tr '\n' ' ' < "$APT_LOG")"
      warn "apt packages this installer added: $pkgs"
      printf "  Remove them too? (they may be shared) [y/N] "; read -r a || a=""
      [ "${a:-}" = y ] && { $APT remove -y $pkgs >/dev/null 2>&1 && ok "apt-removed" || warn "apt remove had issues"; } || warn "kept apt packages"
    fi
    rm -f outputs/public_urls.json outputs/ports.env outputs/api.log outputs/trame.log 2>/dev/null
    ok "done. (uploads under data/raw and outputs kept — delete manually if wanted.)"; exit 0 ;;
  *) err "unknown flag: $a"; exit 2 ;;
esac; done
BIND=127.0.0.1; [ "$STRICT" = 0 ] && BIND=0.0.0.0
mkdir -p "$TOOLS" outputs data/raw
banner

# ---- 1. system libs (only the unavoidable GL/Xvfb; only-missing; tracked) --
step "System libraries (only what VTK/pyvista need; tracked for clean removal)…"
SYS="python3-venv python3-pip git curl ca-certificates xz-utils xvfb fonts-dejavu-core \
  libgl1 libglx-mesa0 libgl1-mesa-dri libglu1-mesa libxrender1 libxext6 libsm6 libx11-6 libxt6 libgomp1"
missing=""
for p in $SYS; do dpkg -s "$p" >/dev/null 2>&1 || missing="$missing $p"; done
if [ -n "$missing" ]; then
  retry 2 $APT update -y >/dev/null 2>&1 || warn "apt update had issues"
  if retry 2 $APT install -y --no-install-recommends $missing >/dev/null 2>&1; then
    for p in $missing; do echo "$p" >> "$APT_LOG"; done
    ok "installed:$missing"
  else
    err "some apt packages failed to install"; note_issue "apt install failed for:$missing (run: $APT install $missing)"
  fi
else
  ok "all system libraries already present"
fi

# ---- 2. Python venv (from the existing python3 >= 3.10 — no global install) -
PY=python3
pv="$($PY -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo 0.0)"
case "$pv" in 3.1[0-9]|3.[2-9]*) : ;; *)
  for alt in python3.12 python3.11 python3.10; do have "$alt" && { PY="$alt"; break; }; done
  pv="$($PY -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo 0.0)"
esac
step "Python venv (.venv) from $PY $pv…"
case "$pv" in 3.1[0-9]|3.[2-9]*) : ;; *) err "Python >= 3.10 required (found $pv)"; note_issue "no Python >= 3.10"; ;; esac
[ -d .venv ] || retry 2 $PY -m venv .venv || { err "venv creation failed"; note_issue "python venv failed (need python3-venv)"; }
retry 2 .venv/bin/pip install -q --upgrade pip >/dev/null 2>&1 || warn "pip self-upgrade skipped"
step "Python dependencies (open3d/VTK/… — a few minutes on first run)…"
if retry 2 .venv/bin/pip install -q -r requirements.txt; then ok "python deps installed"
else err "pip install -r requirements.txt failed"; note_issue "pip failed (arch must be x86-64 for open3d wheels; see outputs, or 'apt install build-essential python3-dev')"; fi

# ---- 3. auto-tune (RAM/GPU) + optional CuPy -------------------------------
# shellcheck disable=SC1091
. ./scripts/dynamic_resources.sh
if [ "${THREEDORTH_GPU:-0}" = 1 ] && have nvidia-smi; then
  step "GPU on -> installing cupy-cuda12x into the venv…"
  .venv/bin/pip install -q cupy-cuda12x >/dev/null 2>&1 && ok "cupy installed" || { warn "cupy failed — CPU fallback"; export THREEDORTH_GPU=0; note_issue "cupy-cuda12x install failed (needs CUDA runtime + device); running CPU"; }
fi

# ---- 4. private Node (./.tools) + build the React UI (served by the API) ---
NODE_V="20.18.1"; arch="x64"; [ "$(uname -m)" = "aarch64" ] && arch="arm64"
if ! have node && [ ! -x "$TOOLS/node/bin/node" ]; then
  step "Node.js $NODE_V (private, under ./.tools — no global install)…"
  url="https://nodejs.org/dist/v${NODE_V}/node-v${NODE_V}-linux-${arch}.tar.gz"
  if retry 2 curl -fsSL "$url" -o "$TOOLS/node.tgz"; then
    mkdir -p "$TOOLS/node"; tar -xzf "$TOOLS/node.tgz" -C "$TOOLS/node" --strip-components=1 && rm -f "$TOOLS/node.tgz" && ok "node ready"
  else warn "node download failed — will serve API/docs only"; note_issue "node download failed (no React UI build)"; fi
fi
[ -x "$TOOLS/node/bin/node" ] && export PATH="$TOOLS/node/bin:$PATH"
if have node && [ -f app_react/package.json ]; then
  step "Building the React UI…"
  if ( cd app_react && retry 2 npm ci --no-audit --no-fund >/dev/null 2>&1 && npm run build >/dev/null 2>&1 ); then
    export THREEDORTH_STATIC_DIR="$(pwd)/app_react/dist"; ok "UI built — the API serves it on one port"
  else warn "React build failed — API/docs only"; note_issue "React build failed (npm)"; fi
fi

# ---- 5. private cloudflared (./.tools) ------------------------------------
CF="cloudflared"
if ! have cloudflared && [ ! -x "$TOOLS/cloudflared" ]; then
  step "cloudflared (private, under ./.tools)…"
  cfarch="amd64"; [ "$(uname -m)" = "aarch64" ] && cfarch="arm64"
  retry 2 curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${cfarch}" -o "$TOOLS/cloudflared" \
    && chmod +x "$TOOLS/cloudflared" && ok "cloudflared ready" || { warn "cloudflared download failed — local access only"; note_issue "cloudflared download failed (no public link)"; }
fi
[ -x "$TOOLS/cloudflared" ] && export PATH="$TOOLS:$PATH"

# ---- 6. pick free ports + run ---------------------------------------------
# shellcheck disable=SC1091
. ./scripts/pick_ports.sh
APP_PORT="$API_PORT"
step "Starting the app (API + UI) on ${BIND}:${APP_PORT}…"
THREEDORTH_STATIC_DIR="${THREEDORTH_STATIC_DIR:-}" \
  nohup .venv/bin/uvicorn api.main:app --host "$BIND" --port "$APP_PORT" > outputs/api.log 2>&1 &
if [ "$WITH_TRAME" = 1 ]; then
  step "Starting trame on ${BIND}:${TRAME_PORT}…"
  nohup xvfb-run -a .venv/bin/python -m app_trame.app --server --host "$BIND" --port "$TRAME_PORT" --timeout 0 > outputs/trame.log 2>&1 &
fi
printf "${BOLD}▶${RST} waiting for the API"
appok=""
for _ in $(seq 1 60); do curl -fsS -m 3 "http://127.0.0.1:${APP_PORT}/api/config" >/dev/null 2>&1 && { appok=1; break; }; printf "."; sleep 2; done; echo
if [ -n "$appok" ]; then
  ok "app up: http://127.0.0.1:${APP_PORT}  (React UI + API; /docs for the API)"
  [ "$WITH_TRAME" = 1 ] && ok "trame:  http://127.0.0.1:${TRAME_PORT}"
else
  err "the API did not start — last log lines:"; tail -8 outputs/api.log; note_issue "API failed to start (see outputs/api.log)"
fi

# ---- 7. issue report ------------------------------------------------------
if [ -n "$ISSUES" ]; then
  echo; printf "${YEL}${BOLD}Some steps had issues:${RST}"; printf "$ISSUES\n"
  echo "  (the app may still run with reduced features; fix the above and re-run.)"
fi

# ---- 8. public tunnel -----------------------------------------------------
printf 'REACT_PORT=%s\nTRAME_PORT=%s\nAPI_PORT=%s\n' "$APP_PORT" "$TRAME_PORT" "$APP_PORT" > outputs/ports.env
[ -n "$appok" ] || exit 1
if have cloudflared; then
  echo; step "Opening the public Cloudflare link (outbound-only; Ctrl-C stops the tunnel, app keeps running)…"
  exec ./scripts/share.sh "$APP_PORT" "$TRAME_PORT"
else
  warn "no cloudflared — reach it locally at http://127.0.0.1:${APP_PORT}"
fi
