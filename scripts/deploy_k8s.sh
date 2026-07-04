#!/usr/bin/env bash
# Deploy 3Dorth to a Kubernetes cluster (RKE2 etc.) — GPU-native, SERVER-ONLY (build
# on-cluster with Kaniko, no Mac transfer, no privileged Docker). Needs kubectl access
# and a container registry.
#
#   ./scripts/deploy_k8s.sh --check                       # detect cluster / GPU / registry
#   REGISTRY=ghcr.io/you ./scripts/deploy_k8s.sh --build  # build images on-cluster + push
#   REGISTRY=ghcr.io/you ./scripts/deploy_k8s.sh          # apply manifests + open the tunnel
#   ./scripts/deploy_k8s.sh --down                        # delete everything
set -uo pipefail
cd "$(dirname "$0")/.."

export NAMESPACE="${NAMESPACE:-3dorth}"
REGISTRY="${REGISTRY:-}"
export IMAGE_GPU="${IMAGE_GPU:-${REGISTRY:+$REGISTRY/}3dorth-api-gpu:latest}"
export IMAGE_REACT="${IMAGE_REACT:-${REGISTRY:+$REGISTRY/}3dorth-react:latest}"
export GPU_COUNT="${GPU_COUNT:-1}"
export REACT_MAX_REPLICAS="${REACT_MAX_REPLICAS:-6}"
export API_CPU_REQUEST="${API_CPU_REQUEST:-4}"
export API_MEM_REQUEST="${API_MEM_REQUEST:-8Gi}"
export API_MEM_LIMIT="${API_MEM_LIMIT:-64Gi}"
GIT_REPO="${GIT_REPO:-https://github.com/ArioMoniri/3Dorth.git}"
GIT_REF="${GIT_REF:-refs/heads/main}"
export GIT_CONTEXT="${GIT_CONTEXT:-git://${GIT_REPO#https://}#${GIT_REF}}"
# Compute env (high but safe); override, or `source scripts/dynamic_resources.sh` first.
export THREEDORTH_MAX_SESSIONS="${THREEDORTH_MAX_SESSIONS:-8}"
export THREEDORTH_COMPUTE_CONCURRENCY="${THREEDORTH_COMPUTE_CONCURRENCY:-2}"
export THREEDORTH_MAX_WORK_VOXELS="${THREEDORTH_MAX_WORK_VOXELS:-40000000}"
export THREEDORTH_MAX_ISO_VOXELS="${THREEDORTH_MAX_ISO_VOXELS:-16000000}"
export THREEDORTH_GPU="${THREEDORTH_GPU:-1}"

command -v kubectl >/dev/null 2>&1 || {
  echo "✗ kubectl not found — the Kubernetes path needs cluster access."
  echo "  No cluster access? use the single-pod Docker path: ./scripts/deploy_restricted.sh"
  exit 1; }

_detect_gpu_res() {
  kubectl get nodes -o jsonpath='{range .items[*]}{.status.allocatable}{"\n"}{end}' 2>/dev/null \
    | grep -oE 'nvidia\.com/[a-zA-Z0-9._-]+' | sort -u | head -n1
}
export GPU_RESOURCE="${GPU_RESOURCE:-$(_detect_gpu_res)}"; export GPU_RESOURCE="${GPU_RESOURCE:-nvidia.com/gpu}"

# envsubst if present, else python (expands ${VAR} from the environment)
render() {
  if command -v envsubst >/dev/null 2>&1; then envsubst < "$1"
  else python3 -c 'import os,sys;sys.stdout.write(os.path.expandvars(sys.stdin.read()))' < "$1"; fi
}

case "${1:-}" in
  --check)
    echo "── Kubernetes readiness ─────────────────────────────"
    if kubectl cluster-info >/dev/null 2>&1; then echo "  kubectl        : reachable"; else echo "  kubectl        : NOT reachable"; fi
    echo "  namespace      : $NAMESPACE"
    echo "  registry       : ${REGISTRY:-<unset — set REGISTRY=… to build/deploy>}"
    echo "  GPU resource   : $GPU_RESOURCE"
    echo "  GPU on nodes   :"; kubectl describe nodes 2>/dev/null | grep -oE 'nvidia\.com/[a-zA-Z0-9._-]+' | sort | uniq -c | sed 's/^/      /' || echo "      (none found — GPU won't schedule; app runs CPU-only)"
    echo "  regcred secret :"; kubectl -n "$NAMESPACE" get secret regcred >/dev/null 2>&1 && echo "      present" || echo "      MISSING (needed for Kaniko push — see deploy/k8s/kaniko-build.yaml)"
    echo "  recommendation : $( { kubectl cluster-info >/dev/null 2>&1 && [ -n "$REGISTRY" ]; } && echo 'K8s path OK (--build then deploy)' || echo 'use ./scripts/deploy_restricted.sh (single-pod)')"
    exit 0 ;;
  --down)
    kubectl -n "$NAMESPACE" delete -f <(render deploy/k8s/3dorth.yaml) --ignore-not-found 2>/dev/null || true
    kubectl -n "$NAMESPACE" delete -f <(render deploy/k8s/kaniko-build.yaml) --ignore-not-found 2>/dev/null || true
    echo "✓ deleted."; exit 0 ;;
esac

[ -n "$REGISTRY" ] || [ -n "${IMAGE_GPU_SET:-}" ] || { echo "✗ set REGISTRY=<your-registry> (e.g. ghcr.io/you) so images have a pushable name."; exit 2; }
kubectl get ns "$NAMESPACE" >/dev/null 2>&1 || kubectl create ns "$NAMESPACE"

if [ "${1:-}" = "--build" ]; then
  echo "▶ building images ON THE CLUSTER with Kaniko (pushes to $REGISTRY)…"
  kubectl -n "$NAMESPACE" get secret regcred >/dev/null 2>&1 || {
    echo "✗ registry secret 'regcred' missing in $NAMESPACE. Create it:"
    echo "    kubectl -n $NAMESPACE create secret docker-registry regcred \\"
    echo "      --docker-server=<registry> --docker-username=<user> --docker-password=<token>"; exit 1; }
  kubectl -n "$NAMESPACE" delete job 3dorth-build-gpu 3dorth-build-react --ignore-not-found >/dev/null 2>&1 || true
  render deploy/k8s/kaniko-build.yaml | kubectl -n "$NAMESPACE" apply -f -
  echo "▶ waiting for builds (the CUDA image is large — can take 10-20 min)…"
  kubectl -n "$NAMESPACE" wait --for=condition=complete --timeout=45m job/3dorth-build-gpu job/3dorth-build-react
  echo "✓ images built + pushed."
fi

echo "▶ applying 3Dorth manifests (GPU resource: $GPU_RESOURCE x$GPU_COUNT)…"
render deploy/k8s/3dorth.yaml | kubectl -n "$NAMESPACE" apply -f -
echo "▶ waiting for rollout…"
kubectl -n "$NAMESPACE" rollout status deploy/3dorth-api --timeout=10m
kubectl -n "$NAMESPACE" rollout status deploy/3dorth-react --timeout=5m

echo "✓ 3Dorth is running in namespace '$NAMESPACE'."
echo
echo "▶ expose it with a Cloudflare tunnel (from this pod; outbound-only):"
echo "    kubectl -n $NAMESPACE port-forward svc/3dorth-react 8088:80 >/tmp/pf-react.log 2>&1 &"
echo "    kubectl -n $NAMESPACE port-forward svc/3dorth-trame 8081:8080 >/tmp/pf-trame.log 2>&1 &"
echo "    tmux new -s tunnel './scripts/share.sh 8088 8081'"
echo "    cat outputs/public_urls.json"
