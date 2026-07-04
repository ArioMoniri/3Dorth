#!/usr/bin/env bash
# Native run — NO Docker, NO Kubernetes. For bare Ubuntu boxes/containers where
# dockerd won't run. Installs what's missing (apt; uses sudo only if not root),
# builds a venv + the React UI, runs the API (which SERVES the React UI on one port)
# + trame, auto-tunes to RAM/GPU, picks free ports, and opens the Cloudflare tunnel.
#
#   ./scripts/run_native.sh            # install + run + tunnel (strict 127.0.0.1)
#   ./scripts/run_native.sh --expose   # bind 0.0.0.0
#   ./scripts/run_native.sh --no-trame # skip the trame UI
#   ./scripts/run_native.sh --down     # stop everything started here
set -uo pipefail
cd "$(dirname "$0")/.."

SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"
APT="$SUDO apt-get"
have() { command -v "$1" >/dev/null 2>&1; }

WITH_TRAME=1; STRICT=1
for a in "$@"; do case "$a" in
  --no-trame) WITH_TRAME=0 ;;
  --expose)   STRICT=0 ;;
  --down) pkill -f "uvicorn api.main:app" 2>/dev/null; pkill -f "app_trame.app" 2>/dev/null
          pkill -f "cloudflared tunnel" 2>/dev/null; pkill -f "scripts/share.sh" 2>/dev/null
          echo "✓ stopped native 3Dorth."; exit 0 ;;
  *) echo "unknown flag: $a"; exit 2 ;;
esac; done
BIND=127.0.0.1; [ "$STRICT" = 0 ] && BIND=0.0.0.0

# ---- 1. system packages (install what's missing) --------------------------
echo "▶ installing system packages (apt — needs root/sudo)…"
$APT update -y >/dev/null 2>&1 || echo "  (apt update had issues — continuing)"
BASE="python3 python3-venv python3-pip git curl ca-certificates xvfb fonts-dejavu-core \
  libgl1 libglx-mesa0 libgl1-mesa-dri libglu1-mesa libxrender1 libxext6 libsm6 libx11-6 libxt6 libgomp1"
$APT install -y --no-install-recommends $BASE 2>&1 | tail -2 || echo "  (some apt packages failed — continuing)"

# Prefer Python 3.12; else use the system python3 (>=3.11 recommended).
PY=python3
have python3.12 || $APT install -y --no-install-recommends python3.12 python3.12-venv >/dev/null 2>&1 || true
have python3.12 && PY=python3.12
echo "  python: $($PY --version 2>&1)"

# Node.js (for the React build; skipped gracefully if it can't install)
if ! have node; then
  echo "▶ installing Node.js 20 (NodeSource)…"
  curl -fsSL https://deb.nodesource.com/setup_20.x | $SUDO -E bash - >/dev/null 2>&1 || true
  $APT install -y nodejs >/dev/null 2>&1 || echo "  (node install failed — will serve API/docs only)"
fi

# cloudflared (for the public link)
if ! have cloudflared; then
  echo "▶ installing cloudflared…"
  deb="cloudflared-linux-amd64.deb"; [ "$(uname -m)" = "aarch64" ] && deb="cloudflared-linux-arm64.deb"
  curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/$deb" -o /tmp/cf.deb 2>/dev/null \
    && $SUDO dpkg -i /tmp/cf.deb >/dev/null 2>&1 || echo "  (cloudflared install failed — you'll get local access only)"
fi

# ---- 2. python venv + deps ------------------------------------------------
[ -d .venv ] || { echo "▶ creating venv…"; $PY -m venv .venv; }
echo "▶ installing Python deps (open3d/VTK/etc. — a few minutes)…"
.venv/bin/pip install -q --upgrade pip >/dev/null 2>&1 || true
.venv/bin/pip install -q -r requirements.txt

# ---- 3. auto-tune compute (RAM/GPU) ---------------------------------------
# shellcheck disable=SC1091
. ./scripts/dynamic_resources.sh
if [ "${THREEDORTH_GPU:-0}" = 1 ] && have nvidia-smi; then
  echo "▶ GPU on -> installing cupy-cuda12x…"; .venv/bin/pip install -q cupy-cuda12x 2>/dev/null || { echo "  (cupy failed — CPU)"; export THREEDORTH_GPU=0; }
fi

# ---- 4. build the React UI (served by the API on one port) ----------------
if have node && [ -f app_react/package.json ]; then
  echo "▶ building the React UI…"
  ( cd app_react && npm ci --no-audit --no-fund >/dev/null 2>&1 && npm run build >/dev/null 2>&1 ) \
    && export THREEDORTH_STATIC_DIR="$(pwd)/app_react/dist" \
    && echo "  ✓ UI built — the API will serve it" \
    || echo "  (React build failed — API/docs only)"
fi

# ---- 5. pick free ports + run ---------------------------------------------
# shellcheck disable=SC1091
. ./scripts/pick_ports.sh                 # -> API_PORT / TRAME_PORT / REACT_PORT
APP_PORT="$API_PORT"                       # the API serves the UI too => app is on one port
mkdir -p outputs data/raw
echo "▶ starting the app (API + UI) on ${BIND}:${APP_PORT}…"
THREEDORTH_STATIC_DIR="${THREEDORTH_STATIC_DIR:-}" \
  nohup .venv/bin/uvicorn api.main:app --host "$BIND" --port "$APP_PORT" > outputs/api.log 2>&1 &
if [ "$WITH_TRAME" = 1 ]; then
  echo "▶ starting trame on ${BIND}:${TRAME_PORT}…"
  nohup xvfb-run -a .venv/bin/python -m app_trame.app --server --host "$BIND" --port "$TRAME_PORT" --timeout 0 > outputs/trame.log 2>&1 &
fi

printf "▶ waiting for the API"
ok=""
for _ in $(seq 1 60); do
  curl -fsS -m 3 "http://127.0.0.1:${APP_PORT}/api/config" >/dev/null 2>&1 && { ok=1; break; }
  printf "."; sleep 2
done
echo
[ -n "$ok" ] || { echo "✗ the API did not start — last log lines:"; tail -8 outputs/api.log; exit 1; }
echo "✓ 3Dorth (native) is up:"
echo "    app   http://127.0.0.1:${APP_PORT}     (React UI + API; /docs for the API)"
[ "$WITH_TRAME" = 1 ] && echo "    trame http://127.0.0.1:${TRAME_PORT}"

# ---- 6. public tunnel -----------------------------------------------------
printf 'REACT_PORT=%s\nTRAME_PORT=%s\nAPI_PORT=%s\n' "$APP_PORT" "$TRAME_PORT" "$APP_PORT" > outputs/ports.env
if have cloudflared; then
  echo "▶ opening the public Cloudflare link (outbound-only; Ctrl-C stops the tunnel, app keeps running)…"
  exec ./scripts/share.sh "$APP_PORT" "$TRAME_PORT"
else
  echo "  cloudflared not available — reach it locally at http://127.0.0.1:${APP_PORT}"
fi
