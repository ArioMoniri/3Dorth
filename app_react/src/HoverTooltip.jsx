// Small floating tooltip drawn at the cursor while hovering the 3D surface.
// Mode A (thickness): shows the picked point's thickness_mm, its world
// position, and a short readout comparing it to the map's mean.
// Mode B (deviation): the /compare mesh carries FOUR point_data arrays at
// every reference vertex (deviation_mm, ref_thickness_mm, tgt_thickness_mm,
// thickness_diff_mm) — Viewport reads all of them at the picked vertex and
// hands them up as `hover.scalars`; this tooltip renders whichever of them
// are present as separate rows (Reference / Target / Difference / Deviation).
// tgt_thickness_mm can be NaN where no contralateral match was found; that
// row renders "—" rather than fabricating a number. Never invents values —
// everything here comes straight from the loaded mesh's point data.

function fmt(v, d = 2) {
  return Number.isFinite(v) ? Number(v).toFixed(d) : '—';
}

function signed(v, d = 2) {
  if (!Number.isFinite(v)) return '—';
  const s = v > 0 ? '+' : v < 0 ? '−' : '';
  return `${s}${fmt(Math.abs(v), d)}`;
}

export default function HoverTooltip({ hover, scalar, mean, scalarNames }) {
  if (!hover) return null;
  const isDeviation = scalar === 'deviation_mm';
  const label = isDeviation ? 'Deviation' : 'Thickness';
  const val = hover.value;
  const delta = Number.isFinite(val) && Number.isFinite(mean) ? val - mean : null;
  const scalars = hover.scalars || {};

  // Which of the four Mode-B arrays are actually present on this mesh? Only
  // render rows for arrays that exist — Mode A meshes simply won't have them.
  const names = scalarNames || Object.keys(scalars);
  const has = (n) => names.includes(n) && n in scalars;
  const showBoneBreakdown =
    isDeviation &&
    (has('ref_thickness_mm') || has('tgt_thickness_mm') || has('thickness_diff_mm'));

  // Keep the tooltip on-screen: flip to the left of the cursor near the right
  // edge (handled with translate); nudge up so it doesn't sit under the pointer.
  const style = {
    left: hover.screenX + 16,
    top: hover.screenY + 16,
  };

  return (
    <div className="hover-tip" style={style} role="status">
      <div className="hover-tip-value">
        {isDeviation && Number.isFinite(val) && val > 0 ? '+' : ''}
        {fmt(val)} <span className="hover-tip-unit">mm</span>
      </div>
      <div className="hover-tip-label">{label}</div>
      <div className="hover-tip-readout">
        {delta != null ? (
          <>
            {delta >= 0 ? '+' : '−'}
            {fmt(Math.abs(delta))} mm vs mean ({fmt(mean)})
          </>
        ) : (
          <>map mean {fmt(mean)} mm</>
        )}
      </div>
      {showBoneBreakdown && (
        <div className="hover-tip-bones">
          {has('ref_thickness_mm') && (
            <div className="hover-tip-row">
              <span>Reference thickness</span>
              <span>{fmt(scalars.ref_thickness_mm)} mm</span>
            </div>
          )}
          {has('tgt_thickness_mm') && (
            <div className="hover-tip-row">
              <span>Target thickness</span>
              <span>{fmt(scalars.tgt_thickness_mm)} mm</span>
            </div>
          )}
          {has('thickness_diff_mm') && (
            <div className="hover-tip-row">
              <span>Difference (ref − tgt)</span>
              <span>{signed(scalars.thickness_diff_mm)} mm</span>
            </div>
          )}
          {has('deviation_mm') && (
            <div className="hover-tip-row">
              <span>Deviation</span>
              <span>{signed(scalars.deviation_mm)} mm</span>
            </div>
          )}
        </div>
      )}
      <div className="hover-tip-pos">
        x {fmt(hover.x, 1)} · y {fmt(hover.y, 1)} · z {fmt(hover.z, 1)} mm
      </div>
    </div>
  );
}
