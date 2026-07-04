"""QA: exercise the trame realtime auto-recompute path headlessly.

Goal (matches the product requirement "all should be computed and any changes
should be reflected in realtime"):

  1. Load the demo scan and run one initial compute so a surface exists.
  2. DEBOUNCE + COALESCE: simulate two quick recompute=True parameter changes in
     rapid succession and assert exactly ONE pipeline compute fires (the earlier
     one is coalesced away by the ~600 ms debounce timer).
  3. SUPERSEDE: assert the monotonic request id advances so an older result can
     never overwrite a newer one.
  4. DISPLAY-ONLY INSTANT: change a colormap (recompute=False) and assert the
     surface recolors WITHOUT any additional pipeline compute.
  5. Render the live viewport to outputs/qa_trame_rt.png.

Runs fully offscreen; it drives the real app module (its scheduler, worker and
scene builders) rather than a reimplementation, so it validates the shipped path.
Does NOT launch the long-running trame server.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pyvista as pv  # noqa: E402

pv.OFF_SCREEN = True

import app_trame.app as app  # noqa: E402

OUT = ROOT / "outputs" / "qa_trame_rt.png"
OUT.parent.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------- #
# Instrument the real compute worker so we can count how many pipeline runs a
# burst of changes actually triggers.
# --------------------------------------------------------------------------- #
_compute_calls = {"n": 0}
_orig_worker = app._compute_worker


def _counting_worker(req_id=None):
    _compute_calls["n"] += 1
    return _orig_worker(req_id)


def _wait_for_computes(expected: int, timeout: float = 120.0) -> None:
    """Block until ``expected`` computes have run AND the last one settled."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        pending = app._DEBOUNCE_TIMER is not None and app._DEBOUNCE_TIMER.is_alive()
        if (_compute_calls["n"] >= expected and not pending
                and app.state.status in ("done", "error")):
            # Small settle so the worker's final state writes land.
            time.sleep(0.2)
            return
        time.sleep(0.1)


def main() -> None:
    app._compute_worker = _counting_worker

    # --- 1. Load the demo and do the first compute (synchronously wait). ------
    if app.DEMO_ZIP is None:
        raise SystemExit("No demo dataset found; cannot run realtime QA.")
    app._load_source(app.DEMO_ZIP, layout="bilateral")
    with app.state:
        app._refresh_session_ui()
    app.state.mode = "A"
    app.state.side = "left"

    # Cancel any debounce armed by the session/selector changes above so the
    # burst test starts from a clean slate.
    if app._DEBOUNCE_TIMER is not None:
        app._DEBOUNCE_TIMER.cancel()

    # Kick the initial compute directly (blocking) so a surface exists.
    _compute_calls["n"] = 0
    req0 = app._next_request_id()
    _counting_worker(req0)
    assert app._LAST_MESH["thickness"] is not None, "initial compute produced no mesh"
    assert _compute_calls["n"] == 1, "expected exactly one initial compute"
    print(f"[1] initial compute OK  (computes={_compute_calls['n']}, "
          f"npoints={app._LAST_MESH['thickness'].n_points})")

    # --- 2. Two quick recompute=True changes -> ONE compute (debounced). ------
    _compute_calls["n"] = 0
    req_before = app._REQ_COUNTER
    # Two rapid changes well inside the debounce window.
    app.schedule_recompute()          # change #1 (e.g. slider drag frame 1)
    time.sleep(0.15)
    app.schedule_recompute()          # change #2 (frame 2) — supersedes the timer
    # Nothing should have fired yet (still within the ~600 ms debounce).
    assert _compute_calls["n"] == 0, (
        f"debounce fired too early: {_compute_calls['n']} computes")
    # Wait past the debounce for the single coalesced compute to run + finish.
    _wait_for_computes(1, timeout=120.0)
    assert _compute_calls["n"] == 1, (
        f"expected exactly ONE coalesced compute, got {_compute_calls['n']}")
    print(f"[2] two quick changes -> ONE compute  (computes={_compute_calls['n']})")

    # --- 3. Supersede: request id advanced monotonically. ---------------------
    assert app._REQ_COUNTER > req_before, "request id did not advance"
    print(f"[3] supersede id advanced  ({req_before} -> {app._REQ_COUNTER})")

    # --- 4. Display-only change recolors instantly, NO pipeline compute. ------
    _compute_calls["n"] = 0
    req_snapshot = app._REQ_COUNTER
    app.state.mode_a_colormap = "viridis"      # recompute=False -> instant path
    app.apply_display_only()
    app.state.mode_a_colorbar_steps = 5
    app.apply_display_only()
    # Give any (wrongly-scheduled) debounce a chance to fire; it must not.
    time.sleep(app.RECOMPUTE_DEBOUNCE_S + 0.3)
    assert _compute_calls["n"] == 0, (
        f"display-only change wrongly triggered {_compute_calls['n']} compute(s)")
    assert app._REQ_COUNTER == req_snapshot, "display-only change bumped request id"
    print("[4] display-only recolor instant, NO compute  "
          f"(computes={_compute_calls['n']}, id stable={app._REQ_COUNTER})")

    # --- 5. Render the live viewport. -----------------------------------------
    app.PLOTTER.screenshot(str(OUT))
    assert OUT.exists() and OUT.stat().st_size > 0, "screenshot not written"
    print(f"[5] rendered live viewport -> {OUT} ({OUT.stat().st_size:,} bytes)")

    print("\nQA PASS: debounced auto-recompute coalesces bursts, supersedes "
          "stale results, and display-only changes stay instant & compute-free.")


if __name__ == "__main__":
    main()
