#!/usr/bin/env bash
# Start the Docker daemon inside a NON-PRIVILEGED Rancher/RKE2/containerd container
# (no systemd, no sudo, no bridge, no iptables) — the only mode dockerd can run in
# here. Idempotent: if the daemon already answers, it does nothing.
#
#   ./scripts/start_docker_restricted.sh
set -uo pipefail
cd "$(dirname "$0")/.."

LOG="${DOCKERD_LOG:-$(pwd)/outputs/dockerd.log}"
mkdir -p "$(dirname "$LOG")"

if docker info >/dev/null 2>&1; then
  echo "✓ Docker daemon already running."
  exit 0
fi

if ! command -v dockerd >/dev/null 2>&1; then
  echo "✗ 'dockerd' is not installed on this server (Docker can't run here)."
  echo "  → No-Docker native path:   ./scripts/run_native.sh"
  echo "  → Or auto-pick the best:   ./scripts/setup.sh"
  exit 1
fi

echo "▶ starting dockerd (restricted: vfs storage, no bridge, no iptables) — log: $LOG"
# These are the ONLY flags that work in this non-privileged container. data-root /
# exec-root live under \$HOME so we never touch a path we can't write.
dockerd \
  --iptables=false --ip6tables=false \
  --bridge=none --ip-forward=false --ip-masq=false \
  --storage-driver=vfs \
  --data-root "${DOCKER_DATA_ROOT:-$HOME/.local/share/docker}" \
  --exec-root "${DOCKER_EXEC_ROOT:-$HOME/.local/docker-exec}" \
  >"$LOG" 2>&1 &
DOCKERD_PID=$!
echo "  dockerd pid $DOCKERD_PID"

printf "▶ waiting for the Docker socket"
for _ in $(seq 1 40); do
  if docker info >/dev/null 2>&1; then echo; echo "✓ Docker daemon is up."; exit 0; fi
  if ! kill -0 "$DOCKERD_PID" 2>/dev/null; then
    echo; echo "✗ dockerd exited early — last log lines:"; tail -n 25 "$LOG"; exit 1
  fi
  printf "."; sleep 2
done
echo; echo "✗ dockerd did not become ready in time — last log lines:"; tail -n 25 "$LOG"; exit 1
