// Discrete green -> yellow -> red lookup table, matching the trame frontend and
// the paper (Guo et al. 2022, Fig. 2). The three anchor colors are the ones
// specified in the build brief; other colormaps degrade gracefully to the same
// green->yellow->red anchors (the demo scan only ships the default map).

import vtkColorTransferFunction from '@kitware/vtk.js/Rendering/Core/ColorTransferFunction';

// Anchor stops as normalized RGB. Green -> Yellow -> Red.
const GYR = [
  [10 / 255, 143 / 255, 46 / 255], // #0a8f2e green
  [230 / 255, 230 / 255, 0 / 255], // #e6e600 yellow
  [230 / 255, 0 / 255, 0 / 255], // #e60000 red
];

// Linear interpolation between the three GYR anchors at parameter t in [0,1].
function gyrColorAt(t) {
  const x = Math.min(1, Math.max(0, t));
  if (x <= 0.5) {
    const u = x / 0.5;
    return lerp3(GYR[0], GYR[1], u);
  }
  const u = (x - 0.5) / 0.5;
  return lerp3(GYR[1], GYR[2], u);
}

function lerp3(a, b, u) {
  return [a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u, a[2] + (b[2] - a[2]) * u];
}

// `steps` is the number of legend TICK LABELS (= band boundaries), matching the
// paper Fig. 2 / trame `n_labels`. There is therefore one fewer color band than
// labels: bandCount = steps - 1. For the defaults (steps=7) this yields the 7
// boundary labels 0.1537..6.5202 and 6 discrete color bands.
function bandCount(steps) {
  return Math.max(1, Math.round(steps) - 1);
}

// Build a piecewise-CONSTANT color transfer function with `bandCount(steps)`
// flat bands across [rangeMin, rangeMax]. Constant bands are produced by placing
// two nodes with the same color at each band's edges, so vtk.js does not
// interpolate across a band. `reverse` flips the color order (matches
// mode_a_colormap_reverse).
export function buildDiscreteLUT({ rangeMin, rangeMax, steps, reverse = false }) {
  const ctf = vtkColorTransferFunction.newInstance();
  ctf.removeAllPoints();

  const n = bandCount(steps);
  const span = rangeMax - rangeMin || 1;
  const eps = span * 1e-6;

  for (let i = 0; i < n; i += 1) {
    // Sample the color at the band center on the continuous GYR ramp.
    let tCenter = (i + 0.5) / n;
    if (reverse) tCenter = 1 - tCenter;
    const [r, g, b] = gyrColorAt(tCenter);

    const lo = rangeMin + (span * i) / n;
    const hi = rangeMin + (span * (i + 1)) / n;
    // Two nodes with identical color -> flat band, no cross-band interpolation.
    ctf.addRGBPoint(lo, r, g, b);
    ctf.addRGBPoint(hi - eps, r, g, b);
  }
  ctf.setMappingRange(rangeMin, rangeMax);
  ctf.build();
  return ctf;
}

// The list of {color, lo, hi} bands, used by the HTML legend so it matches the
// vtk LUT exactly.
export function legendBands({ rangeMin, rangeMax, steps, reverse = false }) {
  const n = bandCount(steps);
  const span = rangeMax - rangeMin || 1;
  const bands = [];
  for (let i = 0; i < n; i += 1) {
    let tCenter = (i + 0.5) / n;
    if (reverse) tCenter = 1 - tCenter;
    const [r, g, b] = gyrColorAt(tCenter);
    bands.push({
      css: `rgb(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)})`,
      lo: rangeMin + (span * i) / n,
      hi: rangeMin + (span * (i + 1)) / n,
    });
  }
  return bands;
}

// The `steps` boundary/tick values across [rangeMin, rangeMax] (one per label,
// = bandCount+1 = steps). For the paper defaults (0.1537..6.5202, steps=7) this
// is exactly: 0.1537, 1.2148, 2.2759, 3.3370, 4.3980, 5.4591, 6.5202.
export function legendBoundaries({ rangeMin, rangeMax, steps }) {
  const n = bandCount(steps); // n bands -> n+1 = steps boundaries
  const span = rangeMax - rangeMin;
  const out = [];
  for (let i = 0; i <= n; i += 1) {
    out.push(rangeMin + (span * i) / n);
  }
  return out;
}

// Format a value to 4 decimals using round-half-up with a tiny bias, so binary
// floating-point representation error doesn't drop a trailing half-digit (e.g.
// the boundary 3.33695 formats as "3.3370", not "3.3369"). This reproduces the
// article's tabulated legend values exactly.
export function fmt4(value) {
  const rounded = Math.floor(value * 1e4 + 0.5 + 1e-6) / 1e4;
  return rounded.toFixed(4);
}

export const NEUTRAL_HEX = '#3a3f7a';
export const HIGHLIGHT_HEX = '#ff8c1a';

// vtk.js setColor takes normalized RGB.
export function hexToRgb01(hex) {
  const h = hex.replace('#', '');
  return [
    parseInt(h.slice(0, 2), 16) / 255,
    parseInt(h.slice(2, 4), 16) / 255,
    parseInt(h.slice(4, 6), 16) / 255,
  ];
}
