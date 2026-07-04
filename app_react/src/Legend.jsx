// Discrete vertical color legend for the Mode-A thickness map, rendered as a
// crisp HTML/CSS stepped colorbar (NOT a vtkScalarBarActor — those fonts blur
// and overlap). It uses the SAME band construction as the vtk.js LUT
// (see colors.js) so the viewport and the legend can never disagree, and it
// live-updates whenever the coloring controls change (colormap anchors, range
// min/max, steps, reverse).
//
// Layout: high value at the top, green at the bottom -> red at the top, with
// the `steps` boundary values labelled to 4 decimals alongside the swatch edges.

import { legendBands, legendBoundaries, fmt4 } from './colors';

export default function Legend({ rangeMin, rangeMax, steps, reverse, title }) {
  const bands = legendBands({ rangeMin, rangeMax, steps, reverse });
  const boundaries = legendBoundaries({ rangeMin, rangeMax, steps });

  // Draw high value at the top: reverse both the swatch stack and the tick list.
  const swatchesTopFirst = [...bands].reverse();
  const boundariesTopFirst = [...boundaries].reverse();

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
          {boundariesTopFirst.map((v, i) => (
            <div key={i} className="legend-tick">
              {fmt4(v)}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
