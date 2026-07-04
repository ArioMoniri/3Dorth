// Small floating tooltip drawn at the cursor while hovering the 3D surface.
// Shows the picked point's scalar value (thickness_mm or deviation_mm, mm), its
// world position, and a short local readout comparing the value to the map's
// mean (from the returned stats). Positioned relative to the viewport so it can
// never fall behind the model.

function fmt(v, d = 2) {
  return Number.isFinite(v) ? Number(v).toFixed(d) : '—';
}

export default function HoverTooltip({ hover, scalar, mean }) {
  if (!hover) return null;
  const isDeviation = scalar === 'deviation_mm';
  const label = isDeviation ? 'Deviation' : 'Thickness';
  const val = hover.value;
  const delta = Number.isFinite(val) && Number.isFinite(mean) ? val - mean : null;

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
      <div className="hover-tip-pos">
        x {fmt(hover.x, 1)} · y {fmt(hover.y, 1)} · z {fmt(hover.z, 1)} mm
      </div>
    </div>
  );
}
