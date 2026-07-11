#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# run_local_example.sh — launch 3Dorth locally on YOUR OWN CT series, bounded so
# it never maxes out RAM/VRAM on a laptop.
#
# It points the demo session at scans you already have under ./data/raw/ (which is
# .gitignored) via the THREEDORTH_DEMO / THREEDORTH_DEMO_FOLLOWUP env overrides —
# so nothing patient-identifying is ever committed. The served UI shows only the
# DICOM SeriesDescription + a PatientID *hash*, never a name.
#
# Usage:
#   scripts/run_local_example.sh                 # auto-discover series under data/raw/
#   scripts/run_local_example.sh BASELINE_DIR [FOLLOWUP_DIR]
#   PORT=8001 scripts/run_local_example.sh       # override the port
#
# BASELINE_DIR / FOLLOWUP_DIR may be a DICOM directory, a .zip, or a .nii/.nii.gz.
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${PORT:-8000}"
BASELINE="${1:-}"
FOLLOWUP="${2:-}"

# Auto-discover: each immediate sub-directory of data/raw/ is treated as one scan
# (ingest recurses past viewer wrappers to the real series). Sorted for stability.
if [[ -z "$BASELINE" ]]; then
  # bash 3.2 (macOS default) has no `mapfile`; build the array portably.
  SCANS=()
  while IFS= read -r _d; do
    [[ -n "$_d" ]] && SCANS+=("$_d")
  done < <(find data/raw -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort)
  if [[ "${#SCANS[@]}" -eq 0 ]]; then
    echo "No scans found under data/raw/. Pass a path explicitly:" >&2
    echo "  scripts/run_local_example.sh /path/to/scanA [/path/to/scanB]" >&2
    exit 1
  fi
  BASELINE="${SCANS[0]}"
  [[ "${#SCANS[@]}" -ge 2 ]] && FOLLOWUP="${SCANS[1]}"
fi

echo "── 3Dorth local example ────────────────────────────────────────────"
echo "baseline : $BASELINE"
if [[ -n "$FOLLOWUP" ]]; then
  echo "follow-up: $FOLLOWUP"
  echo
  echo "NOTE: if your two files are two RECONSTRUCTIONS of the SAME scan session"
  echo "      (e.g. a coronal reformat + an axial bone kernel of one visit), a"
  echo "      cross-series Difference map shows reconstruction noise, NOT real"
  echo "      change. For those, the meaningful comparison is LEFT vs RIGHT:"
  echo "      Colour by → Difference, then 'L vs R within one scan'."
fi
echo "port     : $PORT   (open http://localhost:$PORT/ )"
echo "────────────────────────────────────────────────────────────────────"

export THREEDORTH_DEMO="$BASELINE"
[[ -n "$FOLLOWUP" ]] && export THREEDORTH_DEMO_FOLLOWUP="$FOLLOWUP"

# Bounded so a laptop never runs out of RAM/VRAM: cap the working-voxel budget,
# run one compute at a time, keep few sessions, and limit BLAS/OpenMP threads.
export THREEDORTH_MAX_WORK_VOXELS="${THREEDORTH_MAX_WORK_VOXELS:-2500000}"
export THREEDORTH_COMPUTE_CONCURRENCY="${THREEDORTH_COMPUTE_CONCURRENCY:-1}"
export THREEDORTH_MAX_SESSIONS="${THREEDORTH_MAX_SESSIONS:-2}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-2}"

exec .venv/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port "$PORT"
