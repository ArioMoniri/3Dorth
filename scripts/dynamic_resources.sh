#!/usr/bin/env bash
# Detect RAM (free -g) and NVIDIA MIG VRAM (nvidia-smi) and pick 3Dorth compute
# settings that run HIGH but never max out RAM/VRAM. Robust to nvidia-smi returning
# "[Insufficient Permissions]" instead of numbers. Honours any THREEDORTH_* already
# set. SOURCE this to export the vars (deploy_restricted.sh does), or run it to just
# print. No `set -e` — safe to source.  No sudo.

# ---- RAM: available GB (free -g), fallback to total -----------------------
_ram_gb=0
if command -v free >/dev/null 2>&1; then
  _ram_gb="$(free -g | awk '/^Mem:/{print ($7 != "" ? $7 : $2)}')"
fi
case "${_ram_gb:-}" in ''|*[!0-9]*) _ram_gb=0 ;; esac

# ---- MIG VRAM used/total (MiB) from nvidia-smi table ----------------------
# Example line the H200 MIG prints:  "47575MiB / 71424MiB". Take the first pair.
_mig_used=0; _mig_total=0; _gpu_note="nvidia-smi not present"
if command -v nvidia-smi >/dev/null 2>&1; then
  _pair="$(nvidia-smi 2>/dev/null | grep -oE '[0-9]+MiB / [0-9]+MiB' | head -n1)"
  if [ -n "${_pair:-}" ]; then
    _mig_used="$(printf '%s' "$_pair"  | grep -oE '^[0-9]+')"
    _mig_total="$(printf '%s' "$_pair" | grep -oE '[0-9]+MiB$' | grep -oE '^[0-9]+')"
    _gpu_note="parsed from nvidia-smi table"
  else
    _gpu_note="nvidia-smi returned no numeric memory (e.g. [Insufficient Permissions])"
  fi
fi
case "${_mig_used:-}"  in ''|*[!0-9]*) _mig_used=0  ;; esac
case "${_mig_total:-}" in ''|*[!0-9]*) _mig_total=0 ;; esac
_gpu_free=$(( _mig_total - _mig_used )); [ "$_gpu_free" -lt 0 ] && _gpu_free=0

# ---- policy: RAM tier -> sessions / concurrency / work-voxels -------------
if   [ "$_ram_gb" -gt 800 ]; then _sess=8; _conc=2; _vox=40000000
elif [ "$_ram_gb" -ge 500 ]; then _sess=6; _conc=2; _vox=35000000
elif [ "$_ram_gb" -ge 250 ]; then _sess=4; _conc=1; _vox=25000000
else                              _sess=2; _conc=1; _vox=15000000
fi
# GPU only if we can actually SEE >30 GB of free MIG VRAM; else CPU (the app also
# falls back on its own if CuPy/the device isn't reachable inside the container).
if [ "$_gpu_free" -gt 30000 ]; then _gpu=1; else _gpu=0; fi
_iso=$(( _vox * 2 / 5 ))

# ---- export (never override an explicit preset) ---------------------------
export THREEDORTH_MAX_SESSIONS="${THREEDORTH_MAX_SESSIONS:-$_sess}"
export THREEDORTH_COMPUTE_CONCURRENCY="${THREEDORTH_COMPUTE_CONCURRENCY:-$_conc}"
export THREEDORTH_MAX_WORK_VOXELS="${THREEDORTH_MAX_WORK_VOXELS:-$_vox}"
export THREEDORTH_MAX_ISO_VOXELS="${THREEDORTH_MAX_ISO_VOXELS:-$_iso}"
export THREEDORTH_GPU="${THREEDORTH_GPU:-$_gpu}"

echo "── 3Dorth dynamic resources ─────────────────────────────"
echo "  RAM available      : ${_ram_gb} GB"
echo "  MIG VRAM used/total: ${_mig_used}MiB / ${_mig_total}MiB  (${_gpu_note})"
echo "  MIG VRAM free est. : ${_gpu_free}MiB  -> GPU $([ "$_gpu" = 1 ] && echo 'ENABLED' || echo 'off')"
echo "  selected settings:"
echo "    THREEDORTH_MAX_SESSIONS        = ${THREEDORTH_MAX_SESSIONS}"
echo "    THREEDORTH_COMPUTE_CONCURRENCY = ${THREEDORTH_COMPUTE_CONCURRENCY}"
echo "    THREEDORTH_MAX_WORK_VOXELS     = ${THREEDORTH_MAX_WORK_VOXELS}"
echo "    THREEDORTH_MAX_ISO_VOXELS      = ${THREEDORTH_MAX_ISO_VOXELS}"
echo "    THREEDORTH_GPU                 = ${THREEDORTH_GPU}"
echo "─────────────────────────────────────────────────────────"
