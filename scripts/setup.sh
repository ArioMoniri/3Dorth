#!/usr/bin/env bash
# 3Dorth setup — inspect this server and stand up the best possible deployment.
# Installs what's missing. Works on: full VMs, non-privileged Rancher/RKE2 pods,
# Kubernetes clusters, and bare containers with no Docker at all.
#
#   ./scripts/setup.sh            # interactive menu (recommended path pre-selected)
#   ./scripts/setup.sh --auto     # detect + run the best path, no prompts
#   ./scripts/setup.sh --check    # just print the capability report
set -uo pipefail
cd "$(dirname "$0")/.."

C_B=$'\033[1m'; C_G=$'\033[32m'; C_Y=$'\033[33m'; C_R=$'\033[31m'; C_D=$'\033[2m'; C_0=$'\033[0m'
have() { command -v "$1" >/dev/null 2>&1; }
yn() { [ "$1" = yes ] && printf "%syes%s" "$C_G" "$C_0" || printf "%sno%s" "$C_R" "$C_0"; }

banner() {
  printf '%s' "$C_B"
  cat <<'EOF'
  ┌───────────────────────────────────────────────────────────┐
  │   ____  ____   ___          _   _                          │
  │  |___ \|  _ \ / _ \ _ __ __| |_| |__    cortical thickness │
  │    __) | | | | | | | '__/ _` | __| '_ \    ·  deploy setup │
  │   / __/| |_| | |_| | | | (_| | |_| | | |                   │
  │  |_____|____/ \___/|_|  \__,_|\__|_| |_|                   │
  └───────────────────────────────────────────────────────────┘
EOF
  printf '%s' "$C_0"
}

# ---- detect ---------------------------------------------------------------
OS="$(. /etc/os-release 2>/dev/null; echo "${PRETTY_NAME:-unknown}")"
IS_ROOT=no; [ "$(id -u)" = 0 ] && IS_ROOT=yes
CORES="$(nproc 2>/dev/null || echo '?')"
RAM="$(free -g 2>/dev/null | awk '/^Mem:/{print $2}')"; RAM="${RAM:-?}"
HAVE_DOCKER=no; have docker && HAVE_DOCKER=yes
HAVE_DOCKERD=no; have dockerd && HAVE_DOCKERD=yes
DOCKER_UP=no; have docker && docker info >/dev/null 2>&1 && DOCKER_UP=yes
HAVE_KUBECTL=no; have kubectl && HAVE_KUBECTL=yes
K8S_OK=no; [ "$HAVE_KUBECTL" = yes ] && kubectl cluster-info >/dev/null 2>&1 && K8S_OK=yes
GPU=no; GPU_NAME="none"; if have nvidia-smi; then GPU=yes; GPU_NAME="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)"; GPU_NAME="${GPU_NAME:-detected}"; fi
HAVE_CF=no; have cloudflared && HAVE_CF=yes
HAVE_PY=no; PYV="none"; have python3 && { HAVE_PY=yes; PYV="$(python3 --version 2>&1 | awk '{print $2}')"; }
HAVE_NODE=no; have node && HAVE_NODE=yes

# recommend
if   [ "$K8S_OK" = yes ]; then REC=k8s;     REC_TXT="Kubernetes (GPU + autoscale)"
elif [ "$DOCKER_UP" = yes ] || [ "$HAVE_DOCKERD" = yes ]; then REC=docker; REC_TXT="Docker single-pod (restricted)"
else REC=native; REC_TXT="Native (no Docker — installs Python/Node/cloudflared)"; fi

report() {
  banner
  printf "  %sServer%s   %s   root:%s   %s cores · %s GB RAM\n" "$C_B" "$C_0" "$OS" "$(yn "$IS_ROOT")" "$CORES" "$RAM"
  printf "  %sGPU%s      %s  (%s)\n" "$C_B" "$C_0" "$(yn "$GPU")" "$GPU_NAME"
  printf "  %sTools%s    docker:%s  dockerd:%s  docker-running:%s  kubectl:%s  cluster:%s\n" "$C_B" "$C_0" "$(yn "$HAVE_DOCKER")" "$(yn "$HAVE_DOCKERD")" "$(yn "$DOCKER_UP")" "$(yn "$HAVE_KUBECTL")" "$(yn "$K8S_OK")"
  printf "           python:%s(%s)  node:%s  cloudflared:%s\n" "$(yn "$HAVE_PY")" "$PYV" "$(yn "$HAVE_NODE")" "$(yn "$HAVE_CF")"
  printf "  %sBest fit%s %s→ %s%s\n" "$C_B" "$C_0" "$C_G" "$REC_TXT" "$C_0"
}

run_k8s()     { echo; echo "${C_B}▶ Kubernetes path${C_0}"; ./scripts/deploy_k8s.sh --check; echo; echo "Then: REGISTRY=<reg>/<you> ./scripts/deploy_k8s.sh --build && REGISTRY=<reg>/<you> ./scripts/deploy_k8s.sh"; }
run_docker()  {
  echo; echo "${C_B}▶ Docker single-pod path${C_0}"
  if [ "$HAVE_DOCKER" = no ] && [ "$HAVE_DOCKERD" = no ]; then
    printf "  Docker isn't installed. Install it now? [y/N] "; read -r a || a=""
    if [ "${a:-}" = y ]; then
      if [ "$IS_ROOT" = yes ]; then curl -fsSL https://get.docker.com | sh
      else curl -fsSL https://get.docker.com | sudo sh; fi
    else
      echo "  skipped — falling back to native."; run_native; return
    fi
  fi
  ./scripts/deploy_restricted.sh "$@"
}
run_native()  { echo; echo "${C_B}▶ Native (no-Docker) path${C_0}"; ./scripts/run_native.sh "$@"; }

case "${1:-}" in
  --check) report; exit 0 ;;
  --auto)  report; case "$REC" in k8s) run_k8s ;; docker) run_docker ;; native) run_native ;; esac; exit $? ;;
esac

# ---- interactive menu -----------------------------------------------------
report
echo
echo "  Choose a deployment ( ${C_G}${REC}${C_0} is recommended ):"
echo "    1) Kubernetes  — GPU + autoscale, builds on-cluster (needs kubectl + registry)"
echo "    2) Docker      — single-pod, host-networked (needs a runnable dockerd)"
echo "    3) Native      — no Docker; installs Python/Node/cloudflared and runs directly"
echo "    4) Re-scan server        5) Quit"
while true; do
  printf "  > select [1-5, Enter=%s]: " "$REC"
  read -r choice || choice=5
  [ -z "$choice" ] && case "$REC" in k8s) choice=1;; docker) choice=2;; native) choice=3;; esac
  case "$choice" in
    1) run_k8s; break ;;
    2) run_docker; break ;;
    3) run_native; break ;;
    4) report; echo ;;
    5|q|Q) echo "bye."; exit 0 ;;
    *) echo "  ? pick 1-5" ;;
  esac
done
