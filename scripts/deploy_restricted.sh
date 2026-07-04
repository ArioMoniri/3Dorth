#!/usr/bin/env bash
# Restricted-server deploy (non-privileged Rancher/RKE2, no systemd, no bridge, no
# sudo): ensure dockerd is up, auto-tune compute to RAM/MIG, clean up stale
# containers, and start the PRE-BUILT stack (images loaded via `docker load`) with
# host networking. Never builds here (builds fail in this container).
#
#   ./scripts/deploy_restricted.sh              # start (default)
#   ./scripts/deploy_restricted.sh --no-build   # explicit; identical (never builds)
#   ./scripts/deploy_restricted.sh --down       # stop the app + remove its containers
#   ./scripts/deploy_restricted.sh --prune      # ALSO prune dangling volumes (destructive)
set -uo pipefail
cd "$(dirname "$0")/.."

COMPOSE="docker compose -p 3dorth -f docker-compose.restricted.yml --profile all"
DOWN=0; PRUNE=0; EXPOSE=0
for a in "$@"; do case "$a" in
  --down)     DOWN=1 ;;
  --prune)    PRUNE=1 ;;
  --expose)   EXPOSE=1 ;;                 # bind 0.0.0.0 (pod-net reachable) instead of tunnel-only
  --no-build) : ;;                       # accepted for clarity; this path never builds
  *) echo "unknown flag: $a  (use --down / --prune / --expose / --no-build)"; exit 2 ;;
esac; done

# Bind mode: STRICT (default) = 127.0.0.1, only the local tunnel reaches the app;
# --expose = 0.0.0.0, reachable on the pod network too.
if [ "$EXPOSE" = 1 ]; then
  export APP_BIND=0.0.0.0 NGINX_LISTEN_ADDR=""
  echo "▶ bind mode: EXPOSED (0.0.0.0 — reachable on the pod network)"
else
  export APP_BIND=127.0.0.1 NGINX_LISTEN_ADDR="127.0.0.1:"
  echo "▶ bind mode: STRICT (127.0.0.1 — only the local Cloudflare tunnel reaches the app)"
fi

# ---- 0. dockerd (restricted mode) -----------------------------------------
./scripts/start_docker_restricted.sh || exit 1

# ---- pick free host ports (some may be taken on this server) --------------
# shellcheck disable=SC1091
. ./scripts/pick_ports.sh

# ---- cleanup: stop the app + remove stale containers (keep volumes) --------
echo "▶ cleaning up any previous 3Dorth containers…"
$COMPOSE down --remove-orphans 2>/dev/null || true
docker rm -f 3dorth-api 3dorth-trame 3dorth-react >/dev/null 2>&1 || true
if [ "$PRUNE" = 1 ]; then
  echo "▶ --prune: removing dangling volumes (explicitly requested)…"
  docker volume prune -f >/dev/null 2>&1 || true
fi
if [ "$DOWN" = 1 ]; then echo "✓ stopped (volumes kept)."; exit 0; fi

# ---- 1. auto-tune compute to this machine ---------------------------------
# shellcheck disable=SC1091
. ./scripts/dynamic_resources.sh

# ---- 2. verify the pre-built images are loaded ----------------------------
missing=""
for img in 3dorth-api:latest 3dorth-trame:latest 3dorth-react:latest; do
  docker image inspect "$img" >/dev/null 2>&1 || missing="$missing $img"
done
if [ -n "$missing" ]; then
  echo "✗ missing image(s):$missing"
  echo "  These are built on ANOTHER machine and loaded here (build fails in this container). On a build box:"
  echo "     docker compose --profile all build"
  echo "     docker save 3dorth-api:latest 3dorth-trame:latest 3dorth-react:latest -o 3dorth-images.tar"
  echo "     scp -P 30405 3dorth-images.tar root@THIS_SERVER:\$PWD/"
  echo "  then here:"
  echo "     docker load -i 3dorth-images.tar && ./scripts/deploy_restricted.sh"
  exit 1
fi

# ---- 3. start (host networking, pre-built images, no build) ---------------
mkdir -p outputs data/raw
echo "▶ starting the stack (host networking, pre-built images, no build)…"
$COMPOSE up -d --no-build --pull never

# ---- 4. wait for the API on its chosen port -------------------------------
printf "▶ waiting for the API on :%s" "$API_PORT"
ok=""
for _ in $(seq 1 80); do
  if curl -fsS -m 3 "http://127.0.0.1:${API_PORT}/api/config" >/dev/null 2>&1; then ok=1; break; fi
  printf "."; sleep 3
done
echo
if [ -z "$ok" ]; then
  echo "✗ API is not answering on :${API_PORT}."
  echo "  logs: $COMPOSE logs api"
  exit 1
fi

# Persist the chosen ports so share.sh / a later shell can pick them up.
printf 'REACT_PORT=%s\nTRAME_PORT=%s\nAPI_PORT=%s\n' "$REACT_PORT" "$TRAME_PORT" "$API_PORT" > outputs/ports.env

echo "✓ 3Dorth is up (host networking, ${APP_BIND} bind):"
echo "    API   http://127.0.0.1:${API_PORT}/docs"
echo "    React http://127.0.0.1:${REACT_PORT}"
echo "    trame http://127.0.0.1:${TRAME_PORT}"
echo
echo "▶ open the public Cloudflare link (outbound-only; no inbound ports needed):"
echo "    tmux new -s tunnel './scripts/share.sh ${REACT_PORT} ${TRAME_PORT}'"
echo "    cat outputs/public_urls.json     # the URL, also shown in the app top bar"
