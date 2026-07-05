// Feature 3 — "Clip / isolate": a client-side clip box for isolating a
// sub-part of the mesh (e.g. only the proximal humerus where connected-
// components can't separate it from the fused thorax). Everything OUTSIDE
// the adjustable box is hidden in the 3D Viewport via vtk.js mapper clipping
// planes (see Viewport.jsx) — no server recompute, no new geometry fetch.
//
// Six range sliders (xmin/xmax/ymin/ymax/zmin/zmax), seeded to the loaded
// mesh's real bounds (passed down from App via `bounds`, which Viewport reports
// straight from the parsed polydata). "Reset clip" restores the full box
// (= the whole bone, nothing hidden).
//
// This panel only holds UI state; the actual hide/show and the visible-vertex
// stats recompute happen in Viewport + App, both driven by the same box.

function fmt(v) {
  return Number.isFinite(v) ? v.toFixed(1) : '—';
}

function AxisSliders({ axis, label, lo, hi, min, max, onChange }) {
  const step = Math.max((max - min) / 500, 0.01);
  return (
    <div className="clip-axis">
      <div className="clip-axis-label">{label}</div>
      <label className="clip-slider-row">
        <span className="clip-slider-tag">min</span>
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={lo}
          onChange={(e) => {
            const v = Math.min(parseFloat(e.target.value), hi);
            onChange(axis, 'lo', v);
          }}
        />
        <span className="clip-slider-val">{fmt(lo)}</span>
      </label>
      <label className="clip-slider-row">
        <span className="clip-slider-tag">max</span>
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={hi}
          onChange={(e) => {
            const v = Math.max(parseFloat(e.target.value), lo);
            onChange(axis, 'hi', v);
          }}
        />
        <span className="clip-slider-val">{fmt(hi)}</span>
      </label>
    </div>
  );
}

// `bounds` — mesh bounds [xmin,xmax,ymin,ymax,zmin,zmax] from Viewport, or null
//   before anything is loaded.
// `box` — the current clip box { xmin,xmax,ymin,ymax,zmin,zmax } (already
//   clamped to `bounds`), or null when the clip is off (whole mesh shown).
// `enabled` — whether the clip toggle is on.
// `onToggle(enabled)` / `onBoxChange(box)` / `onReset()`.
// `visibleCount` / `totalCount` / `visiblePct` — for the small readout at the
//   top of the panel (also mirrored in the Stats panel's "Visible part" column).
export default function ClipPanel({
  bounds,
  box,
  enabled,
  onToggle,
  onBoxChange,
  onReset,
  canPickIsolate,
  visibleCount,
  totalCount,
  visiblePct,
}) {
  if (!bounds) return null;
  const [bxmin, bxmax, bymin, bymax, bzmin, bzmax] = bounds;
  const active = box || {
    xmin: bxmin,
    xmax: bxmax,
    ymin: bymin,
    ymax: bymax,
    zmin: bzmin,
    zmax: bzmax,
  };

  function set(axis, edge, v) {
    const next = { ...active, [`${axis}${edge === 'lo' ? 'min' : 'max'}`]: v };
    onBoxChange(next);
  }

  return (
    <div className="clip-panel">
      <div className="clip-panel-head">
        <span className="clip-panel-title">Clip / isolate</span>
        <label className="clip-toggle">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => onToggle(e.target.checked)}
          />
          <span>{enabled ? 'On' : 'Off'}</span>
        </label>
      </div>

      {enabled && (
        <>
          {canPickIsolate && (
            <p className="panel-hint clip-hint clip-hint-pick">
              Tip: <strong>click the part you want</strong> on the 3D surface to
              re-centre the box on it — then fine-tune with the sliders.
            </p>
          )}
          <p className="panel-hint clip-hint">
            Shrink the box to isolate a sub-part (e.g. only the proximal
            humerus). Everything outside the box is hidden; statistics for the
            visible part recompute live from the same per-vertex values already
            on the surface — no server call.
          </p>

          <AxisSliders
            axis="x"
            label="X"
            lo={active.xmin}
            hi={active.xmax}
            min={bxmin}
            max={bxmax}
            onChange={set}
          />
          <AxisSliders
            axis="y"
            label="Y"
            lo={active.ymin}
            hi={active.ymax}
            min={bymin}
            max={bymax}
            onChange={set}
          />
          <AxisSliders
            axis="z"
            label="Z"
            lo={active.zmin}
            hi={active.zmax}
            min={bzmin}
            max={bzmax}
            onChange={set}
          />

          <div className="clip-readout">
            <span>
              Visible: <strong>{Number.isFinite(visibleCount) ? visibleCount.toLocaleString() : '—'}</strong>
              {' / '}
              {Number.isFinite(totalCount) ? totalCount.toLocaleString() : '—'}
              {' vertices'}
            </span>
            <span className="clip-readout-pct">
              {Number.isFinite(visiblePct) ? `${visiblePct.toFixed(1)}%` : '—'}
            </span>
          </div>

          <button type="button" className="reset-btn clip-reset-btn" onClick={onReset}>
            Reset clip (show whole bone)
          </button>
        </>
      )}
    </div>
  );
}
