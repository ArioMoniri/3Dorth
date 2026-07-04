// Manual anchor controls for Mode B deviation. After an automatic comparison the
// clinician can nudge the target onto the reference: translate x/y/z (mm) and
// rotate about x/y/z (deg). These compose into a single 4x4 row-major transform
// (R then T) sent as `manual_transform` to /compare, applied on top of the auto
// ICP registration. A "swap which side is on top" button flips reference/target.
//
// buildManualTransform() lives here so App and Export share one definition.

export function buildManualTransform({ tx, ty, tz, rx, ry, rz }) {
  const nudged =
    tx || ty || tz || rx || ry || rz;
  if (!nudged) return null; // identity => let the server use auto registration alone

  const d = Math.PI / 180;
  const cx = Math.cos(rx * d);
  const sx = Math.sin(rx * d);
  const cy = Math.cos(ry * d);
  const sy = Math.sin(ry * d);
  const cz = Math.cos(rz * d);
  const sz = Math.sin(rz * d);

  // R = Rz * Ry * Rx (row-major 3x3).
  const r00 = cz * cy;
  const r01 = cz * sy * sx - sz * cx;
  const r02 = cz * sy * cx + sz * sx;
  const r10 = sz * cy;
  const r11 = sz * sy * sx + cz * cx;
  const r12 = sz * sy * cx - cz * sx;
  const r20 = -sy;
  const r21 = cy * sx;
  const r22 = cy * cx;

  // Homogeneous 4x4, row-major, translation in the last column.
  return [
    [r00, r01, r02, tx],
    [r10, r11, r12, ty],
    [r20, r21, r22, tz],
    [0, 0, 0, 1],
  ];
}

export default function ManualAnchor({
  transform,
  onChange,
  onSwapSides,
  onApply,
  computing,
  hasAutoResult,
}) {
  const set = (key, v) => onChange({ ...transform, [key]: v });

  return (
    <section className="panel-section manual-anchor">
      <h2>Manual anchor</h2>
      {!hasAutoResult ? (
        <p className="panel-hint">
          Run “Compute deviation” first, then fine-tune the alignment here.
        </p>
      ) : (
        <>
          <button className="reset-btn swap-btn" onClick={onSwapSides}>
            Swap which side is on top
          </button>

          <div className="anchor-group">
            <div className="export-sub">Translation (mm)</div>
            <div className="anchor-grid">
              <NudgeField label="X" value={transform.tx} onChange={(v) => set('tx', v)} />
              <NudgeField label="Y" value={transform.ty} onChange={(v) => set('ty', v)} />
              <NudgeField label="Z" value={transform.tz} onChange={(v) => set('tz', v)} />
            </div>
          </div>

          <div className="anchor-group">
            <div className="export-sub">Rotation (deg)</div>
            <div className="anchor-grid">
              <NudgeField label="RX" value={transform.rx} onChange={(v) => set('rx', v)} />
              <NudgeField label="RY" value={transform.ry} onChange={(v) => set('ry', v)} />
              <NudgeField label="RZ" value={transform.rz} onChange={(v) => set('rz', v)} />
            </div>
          </div>

          <div className="anchor-actions">
            <button
              className="apply-btn"
              disabled={computing}
              onClick={onApply}
            >
              {computing ? 'Recomputing…' : 'Apply anchor & recompute'}
            </button>
            <button
              className="reset-btn"
              onClick={() =>
                onChange({ tx: 0, ty: 0, tz: 0, rx: 0, ry: 0, rz: 0 })
              }
            >
              Reset nudge
            </button>
          </div>
          <p className="panel-hint">
            Applied on top of the automatic ICP registration.
          </p>
        </>
      )}
    </section>
  );
}

function NudgeField({ label, value, onChange }) {
  return (
    <label className="cam-field">
      <span className="cam-label">{label}</span>
      <input
        type="number"
        value={value}
        step={label.startsWith('R') ? 1 : 0.5}
        onChange={(e) => {
          const v = parseFloat(e.target.value);
          onChange(Number.isFinite(v) ? v : 0);
        }}
      />
    </label>
  );
}
