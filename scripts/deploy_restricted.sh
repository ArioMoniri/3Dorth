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
DOWN=0; PRUNE=0
for a in "$@"; do case "$a" in
  --down)     DOWN=1 ;;
  --prune)    PRUNE=1 ;;
  --no-build) : ;;                       # accepted for clarity; this path never builds
  *) echo "unknown flag: $a  (use --down / --prune / --no-build)"; exit 2 ;;
esac; done

# ---- 0. dockerd (restricted mode) -----------------------------------------
./scripts/start_docker_restricted.sh || exit 1

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

# ---- 4. wait for the API on :8000 -----------------------------------------
printf "▶ waiting for the API on :8000"
ok=""
for _ in $(seq 1 80); do
  if curl -fsS -m 3 "http://127.0.0.1:8000/api/config" >/dev/null 2>&1; then ok=1; break; fi
  printf "."; sleep 3
done
echo
if [ -z "$ok" ]; then
  echo "✗ API is not answering on :8000."
  echo "  logs: $COMPOSE logs api"
  exit 1
fi

echo "✓ 3Dorth is up (host networking):"
echo "    API   http://127.0.0.1:8000/docs"
echo "    React http://127.0.0.1:8088"
echo "    trame http://127.0.0.1:8081"
echo
echo "▶ open the public Cloudflare link (outbound-only; no inbound ports needed):"
echo "    tmux new -s tunnel './scripts/share.sh 8088 8081'"
echo "    cat outputs/public_urls.json     # the URL, also shown in the app top bar"
