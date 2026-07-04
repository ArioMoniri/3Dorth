// Discrete vertical color legend, rendered as a crisp HTML/CSS stepped colorbar
// (NOT a vtkScalarBarActor — those fonts blur and overlap). It uses the SAME
// band construction as the vtk.js LUT (see colors.js) so the viewport and the
// legend can never disagree, and it live-updates whenever the coloring changes.
//
// Two shapes:
//   - sequential (Mode A thickness): low value at the bottom, high at the top.
//   - diverging  (Mode B deviation): symmetric range with 0 (white) at center;
//     the blue_white_red map means negative below, positive above.

import { legendBands, legendBoundaries, fmt4, fmt2 } from './colors';

export default function Legend({
  rangeMin,
  rangeMax,
  steps,
  reverse,
  colormap,
  title,
  diverging = false,
}) {
  const bands = legendBands({ rangeMin, rangeMax, steps, reverse, colormap });
  const boundaries = legendBoundaries({ rangeMin, rangeMax, steps });

  // Draw high value at the top: reverse both the swatch stack and the tick list.
  const swatchesTopFirst = [...bands].reverse();
  const boundariesTopFirst = [...boundaries].reverse();
  const fmt = diverging ? fmt2 : fmt4;

  return (
    <div className="legend">
      <div className="legend-title">{title}</div>
      <div className="legend-grid">
        <div className="legend-swatches">
          {swatchesTopFirst.map((b, i) => (
            <div key={i} className="legend-band" style={{ background: b.css }} />
          ))}
        </div>
        <div className="legend-ticks">
          {boundariesTopFirst.map((v, i) => {
            const atZero =
              diverging && Math.abs(v) < (rangeMax - rangeMin) * 1e-4;
            return (
              <div
                key={i}
                className={`legend-tick${atZero ? ' legend-tick-zero' : ''}`}
              >
                {diverging && v > 5e-3 ? `+${fmt(v)}` : fmt(v)}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
