#!/usr/bin/env bash
# serve-public.sh — one command to run 3Dorth publicly on a server.
#
# It (1) auto-tunes the compute budget to this machine, (2) builds + starts the
# Docker stack (API + both UIs), (3) waits until the API is healthy, then (4) opens
# a RESILIENT Cloudflare quick tunnel and prints the public link. The tunnel is
# OUTBOUND-only — no inbound ports need to be opened — so it works on firewalled
# servers, and it exposes only the web app (never SSH/your shell).
#
#   ./serve-public.sh                          # React :8088, trame :8081, auto-tuned
#   BIND_ADDR=127.0.0.1 ./serve-public.sh      # expose ONLY on localhost -> tunnel is the sole way in
#   REACT_HOST_PORT=9090 ./serve-public.sh 9090 8081   # move a clashing host port
#   THREEDORTH_GPU=1 ./serve-public.sh         # CUDA box (CuPy-accelerated)
#
# The public URL is written to outputs/public_urls.json and shown in the app's top
# bar (it polls /api/config). Leave this running; Ctrl-C stops the tunnel — the
# containers keep running (`docker compose --profile all down` to stop them).
set -euo pipefail
cd "$(dirname "$0")"

# HOST ports (also what gets tunnelled). Explicit args/env win; otherwise
# scripts/pick_ports.sh auto-selects FREE ports (some may be taken on the server).
[ -n "${1:-}" ] && REACT_PORT="${REACT_PORT:-$1}"
[ -n "${2:-}" ] && TRAME_PORT="${TRAME_PORT:-$2}"
REACT_PORT="${REACT_PORT:-${REACT_HOST_PORT:-}}"
TRAME_PORT="${TRAME_PORT:-${TRAME_HOST_PORT:-}}"
API_PORT="${API_PORT:-${API_HOST_PORT:-}}"
# shellcheck disable=SC1091
. ./scripts/pick_ports.sh                          # fills any unset with a free port
REACT_HOST_PORT="$REACT_PORT"; TRAME_HOST_PORT="$TRAME_PORT"; API_HOST_PORT="$API_PORT"
BIND_ADDR="${BIND_ADDR:-0.0.0.0}"
export REACT_HOST_PORT TRAME_HOST_PORT API_HOST_PORT BIND_ADDR

# ---- preflight ------------------------------------------------------------
need() { command -v "$1" >/dev/null 2>&1 || { echo "✗ '$1' not found — $2"; exit 1; }; }
need docker "install: curl -fsSL https://get.docker.com | sudo sh"
docker compose version >/dev/null 2>&1 || { echo "✗ the 'docker compose' plugin is missing (install docker-compose-plugin)."; exit 1; }
need cloudflared "install: curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o cf.deb && sudo dpkg -i cf.deb"

# ---- auto-tune the compute budget to this machine (honours anything preset) --
_cores() { nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4; }
_ram_gb() {
  if [ -r /proc/meminfo ]; then awk '/MemTotal/{printf "%d",$2/1024/1024}' /proc/meminfo
  elif command -v sysctl >/dev/null 2>&1; then sysctl -n hw.memsize 2>/dev/null | awk '{printf "%d",$1/1073741824}'
  else echo 8; fi
}
CORES="$(_cores)"; RAM_GB="$(_ram_gb)"; [ "${RAM_GB:-0}" -lt 1 ] && RAM_GB=8
# concurrency ~1 per 4 cores (1..4); voxel budget ~10M/GB (20M..120M); iso = 40% of it;
# sessions ~1 per 3 GB (3..12). More RAM -> finer (slower) compute; less RAM -> coarser/faster.
_conc=$(( CORES/4 )); [ "$_conc" -lt 1 ] && _conc=1; [ "$_conc" -gt 4 ] && _conc=4
_vox=$(( RAM_GB*10000000 )); [ "$_vox" -lt 20000000 ] && _vox=20000000; [ "$_vox" -gt 120000000 ] && _vox=120000000
_iso=$(( _vox*2/5 ))
_sess=$(( RAM_GB/3 )); [ "$_sess" -lt 3 ] && _sess=3; [ "$_sess" -gt 12 ] && _sess=12
export THREEDORTH_COMPUTE_CONCURRENCY="${THREEDORTH_COMPUTE_CONCURRENCY:-$_conc}"
export THREEDORTH_MAX_WORK_VOXELS="${THREEDORTH_MAX_WORK_VOXELS:-$_vox}"
export THREEDORTH_MAX_ISO_VOXELS="${THREEDORTH_MAX_ISO_VOXELS:-$_iso}"
export THREEDORTH_MAX_SESSIONS="${THREEDORTH_MAX_SESSIONS:-$_sess}"
export THREEDORTH_GPU="${THREEDORTH_GPU:-}"

echo "▶ 3Dorth — public serve"
echo "  host   : ${CORES} cores · ${RAM_GB} GB RAM · gpu=${THREEDORTH_GPU:-off}"
echo "  tune   : concurrency=${THREEDORTH_COMPUTE_CONCURRENCY} work_voxels=${THREEDORTH_MAX_WORK_VOXELS} iso_voxels=${THREEDORTH_MAX_ISO_VOXELS} sessions=${THREEDORTH_MAX_SESSIONS}"
echo "  bind   : ${BIND_ADDR} · React:${REACT_HOST_PORT} trame:${TRAME_HOST_PORT} api:${API_HOST_PORT}"

# ---- build + start --------------------------------------------------------
echo "▶ building + starting containers (first build can take a few minutes)…"
docker compose --profile all up -d --build

# ---- wait for the API -----------------------------------------------------
printf "▶ waiting for the API"
ok=""
for _ in $(seq 1 80); do
  if curl -fsS -m 3 "http://127.0.0.1:${API_HOST_PORT}/api/config" >/dev/null 2>&1; then ok=1; break; fi
  printf "."; sleep 3
done
echo
[ -n "$ok" ] || { echo "✗ API did not answer on :${API_HOST_PORT} after ~4 min. Logs: docker compose --profile all logs api"; exit 1; }
echo "✓ API healthy."

# ---- open the resilient Cloudflare tunnel + print the link ----------------
echo "▶ opening a Cloudflare quick tunnel (outbound-only; exposes only the app)…"
echo "  the public link prints below, updates in outputs/public_urls.json, and shows in the app top bar."
echo "  share the React URL. Ctrl-C stops the tunnel; containers keep running."
echo
exec ./scripts/share.sh "$REACT_HOST_PORT" "$TRAME_HOST_PORT"
