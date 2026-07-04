#!/usr/bin/env bash
# 3Dorth setup — inspect this server and stand up the best possible deployment.
# Installs what's missing (locally where it can). Works on: full VMs, non-privileged
# Rancher/RKE2 pods, Kubernetes clusters, and bare containers with no Docker at all.
#
#   ./scripts/setup.sh            # interactive menu (recommended path pre-selected)
#   ./scripts/setup.sh --auto     # detect + run the best path, no prompts
#   ./scripts/setup.sh --check    # just print the capability report
#   ./scripts/setup.sh --uninstall# remove the native install (venv/.tools/build)
set -uo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
. ./scripts/_ui.sh

have() { command -v "$1" >/dev/null 2>&1; }
yn() { [ "$1" = yes ] && printf "%syes%s" "$GRN" "$RST" || printf "%sno%s" "$RED" "$RST"; }

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

if   [ "$K8S_OK" = yes ]; then REC=k8s;     REC_TXT="Kubernetes (GPU + autoscale)"
elif [ "$DOCKER_UP" = yes ] || [ "$HAVE_DOCKERD" = yes ]; then REC=docker; REC_TXT="Docker single-pod (restricted)"
else REC=native; REC_TXT="Native (no Docker — installs Python venv / local Node / cloudflared)"; fi

report() {
  banner
  printf "  ${BOLD}Server${RST}   %s   root:%s   %s cores · %s GB RAM\n" "$OS" "$(yn "$IS_ROOT")" "$CORES" "$RAM"
  printf "  ${BOLD}GPU${RST}      %s  ${DIM}(%s)${RST}\n" "$(yn "$GPU")" "$GPU_NAME"
  printf "  ${BOLD}Tools${RST}    docker:%s  dockerd:%s  running:%s  kubectl:%s  cluster:%s\n" "$(yn "$HAVE_DOCKER")" "$(yn "$HAVE_DOCKERD")" "$(yn "$DOCKER_UP")" "$(yn "$HAVE_KUBECTL")" "$(yn "$K8S_OK")"
  printf "           python:%s${DIM}(%s)${RST}  node:%s  cloudflared:%s\n" "$(yn "$HAVE_PY")" "$PYV" "$(yn "$HAVE_NODE")" "$(yn "$HAVE_CF")"
  printf "  ${BOLD}Best fit${RST} ${GRN}→ %s${RST}\n" "$REC_TXT"
}

run_k8s()    { echo; step "Kubernetes path"; ./scripts/deploy_k8s.sh --check
               echo; echo "  then: ${DIM}REGISTRY=<reg>/<you> ./scripts/deploy_k8s.sh --build && REGISTRY=<reg>/<you> ./scripts/deploy_k8s.sh${RST}"; }
run_native() { echo; step "Native (no-Docker) path"; ./scripts/run_native.sh "$@"; }
run_docker() {
  echo; step "Docker single-pod path"
  if [ "$HAVE_DOCKER" = no ] && [ "$HAVE_DOCKERD" = no ]; then
    printf "  Docker isn't installed. Install it now? [y/N] "; read -r a || a=""
    if [ "${a:-}" = y ]; then
      if [ "$IS_ROOT" = yes ]; then curl -fsSL https://get.docker.com | sh; else curl -fsSL https://get.docker.com | sudo sh; fi
    else warn "skipped — falling back to native."; run_native; return; fi
  fi
  ./scripts/deploy_restricted.sh
}
do_uninstall() { echo; step "Uninstall / clean up"; ./scripts/run_native.sh --uninstall
                 [ "$HAVE_DOCKERD" = yes ] && { ./scripts/deploy_restricted.sh --down 2>/dev/null || true; }; }

case "${1:-}" in
  --check)     report; exit 0 ;;
  --uninstall) do_uninstall; exit 0 ;;
  --auto)      report; case "$REC" in k8s) run_k8s ;; docker) run_docker ;; native) run_native ;; esac; exit $? ;;
esac

# ---- interactive menu -----------------------------------------------------
report
echo
echo "  ${BOLD}Choose a deployment${RST} ( ${GRN}${REC}${RST} recommended ):"
echo "    ${BOLD}1${RST}) Kubernetes  — GPU + autoscale, builds on-cluster ${DIM}(needs kubectl + registry)${RST}"
echo "    ${BOLD}2${RST}) Docker      — single-pod, host-networked ${DIM}(needs a runnable dockerd)${RST}"
echo "    ${BOLD}3${RST}) Native      — no Docker; local venv/Node/cloudflared, runs directly"
echo "    ${BOLD}4${RST}) Re-scan     ${BOLD}5${RST}) Uninstall     ${BOLD}6${RST}) Quit"
while true; do
  printf "  ${BOLD}>${RST} select [1-6, Enter=%s]: " "$REC"
  read -r choice || choice=6
  [ -z "$choice" ] && case "$REC" in k8s) choice=1;; docker) choice=2;; native) choice=3;; esac
  case "$choice" in
    1) run_k8s; break ;;
    2) run_docker; break ;;
    3) run_native; break ;;
    4) report; echo ;;
    5) do_uninstall; break ;;
    6|q|Q) echo "  bye."; exit 0 ;;
    *) warn "pick 1-6" ;;
  esac
done
