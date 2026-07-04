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

_kill_running() {
  pkill -f "uvicorn api.main:app" 2>/dev/null; pkill -f "app_trame.app" 2>/dev/null
  pkill -f "cloudflared tunnel" 2>/dev/null; pkill -f "scripts/share.sh" 2>/dev/null; sleep 1
}

WITH_TRAME=1; STRICT=1; RESTART=0
for a in "$@"; do case "$a" in
  --no-trame) WITH_TRAME=0 ;;
  --expose)   STRICT=0 ;;
  --restart)  RESTART=1 ;;   # stop what's running, then bring it back up (installs reused)
  --down)
    _kill_running
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
[ "$RESTART" = 1 ] && { step "Restart: stopping the running instance…"; _kill_running; ok "stopped; bringing it back up (installs reused)"; }

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

# ---- 2. Python 3.12 + deps via uv (self-contained, LOCAL under ./.tools) ---
# The frozen requirements need Python >= 3.11 (e.g. contourpy 1.3.3), so we do NOT
# rely on the system python (this server is 3.10). uv fetches a standalone CPython
# into ./.tools (removable) and installs fast. Falls back to a system python3 >= 3.11.
export UV_INSTALL_DIR="$TOOLS" UV_PYTHON_INSTALL_DIR="$TOOLS/python" UV_CACHE_DIR="$TOOLS/uv-cache" UV_NO_MODIFY_PATH=1
UVBIN=""
UV="$TOOLS/uv"
[ -x "$UV" ] || { have uv && UV="$(command -v uv)"; }
if [ ! -x "$UV" ]; then
  step "Installing uv (self-contained Python + fast installer → ./.tools)…"
  retry 2 sh -c "curl -LsSf https://astral.sh/uv/install.sh | sh" >/dev/null 2>&1 || note_issue "uv install failed (network?)"
  [ -x "$TOOLS/uv" ] && UV="$TOOLS/uv"
fi
if [ -x "$UV" ]; then
  UVBIN="$UV"
  step "Python 3.12 venv via uv…"
  retry 2 "$UVBIN" venv --python 3.12 .venv >/dev/null 2>&1 || { err "uv venv failed"; note_issue "uv venv --python 3.12 failed"; }
  step "Python dependencies (open3d/VTK/… via uv — a few minutes first run)…"
  if retry 2 "$UVBIN" pip install --python .venv/bin/python -r requirements.txt; then ok "python deps installed (Python 3.12)"
  else err "dependency install failed"; note_issue "uv pip install failed (arch must be x86-64 for open3d wheels)"; fi
else
  warn "uv unavailable — trying a system python3 >= 3.11"
  PY=python3; for alt in python3.12 python3.11; do have "$alt" && { PY="$alt"; break; }; done
  pv="$($PY -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo 0.0)"
  step "Python venv from $PY $pv…"
  [ -d .venv ] || retry 2 $PY -m venv .venv || note_issue "python venv failed (need python3-venv)"
  retry 2 .venv/bin/pip install -q --upgrade pip >/dev/null 2>&1 || true
  if retry 2 .venv/bin/pip install -q -r requirements.txt; then ok "python deps installed"
  else err "pip failed — deps need Python >= 3.11 (system is $pv). Install uv (curl -LsSf https://astral.sh/uv/install.sh | sh) and re-run."; note_issue "python deps need >=3.11; system is $pv and uv wasn't available"; fi
fi
# install into the .venv with whichever tool we have
pipinstall() { if [ -n "$UVBIN" ]; then "$UVBIN" pip install --python .venv/bin/python "$@"; else .venv/bin/pip install -q "$@"; fi; }

# ---- 3. auto-tune (RAM/GPU) + optional CuPy -------------------------------
# shellcheck disable=SC1091
. ./scripts/dynamic_resources.sh
if [ "${THREEDORTH_GPU:-0}" = 1 ] && have nvidia-smi; then
  step "GPU on -> installing cupy-cuda12x into the venv…"
  pipinstall cupy-cuda12x >/dev/null 2>&1 && ok "cupy installed" || { warn "cupy failed — CPU fallback"; export THREEDORTH_GPU=0; note_issue "cupy-cuda12x install failed (needs CUDA runtime + device); running CPU"; }
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
  step "Building the React UI (log: outputs/react-build.log)…"
  # --legacy-peer-deps avoids ERESOLVE peer conflicts (three / model-viewer vs React);
  # raise the Node heap for vite; keep the full log for diagnosis.
  if ( cd app_react && export NODE_OPTIONS="--max-old-space-size=4096"
       { retry 2 npm ci --no-audit --no-fund --legacy-peer-deps \
         || retry 2 npm install --no-audit --no-fund --legacy-peer-deps; } \
       && npm run build ) > outputs/react-build.log 2>&1; then
    export THREEDORTH_STATIC_DIR="$(pwd)/app_react/dist"; ok "UI built — the API serves it on one port"
  else
    warn "React build failed (see outputs/react-build.log) — serving API/docs only"
    note_issue "React build failed — last lines: $(tail -3 outputs/react-build.log 2>/dev/null | tr '\n' ' ')"
  fi
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
