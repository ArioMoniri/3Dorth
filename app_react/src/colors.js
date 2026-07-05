// Discrete color lookup tables + HTML-legend band construction, shared so the
// vtk.js viewport and the HTML legend can never disagree. Supports the registry
// colormaps (Mode A sequential green->yellow->red et al., Mode B diverging
// blue-white-red et al.); an unknown name degrades to green->yellow->red.

import vtkColorTransferFunction from '@kitware/vtk.js/Rendering/Core/ColorTransferFunction';

// Anchor stops (hex) per registry colormap name. Piecewise-linear between them.
const COLORMAP_HEX = {
  green_yellow_red: ['#0a8f2e', '#e6e600', '#e60000'],
  viridis: ['#440154', '#3b528b', '#21918c', '#5ec962', '#fde725'],
  plasma: ['#0d0887', '#7e03a8', '#cc4778', '#f89540', '#f0f921'],
  inferno: ['#000004', '#57106e', '#bc3754', '#f98e09', '#fcffa4'],
  magma: ['#000004', '#51127c', '#b63679', '#fb8861', '#fcfdbf'],
  turbo: ['#30123b', '#28bceb', '#a2fc3c', '#fb8022', '#7a0403'],
  cividis: ['#00204d', '#414d6b', '#7c7b78', '#bcaf6f', '#ffea46'],
  // diverging (Mode B): low (negative = target INSIDE reference = bone lost)
  // -> white (0 = no change) -> high (positive = OUTSIDE = bone gained)
  blue_white_red: ['#2166ac', '#f7f7f7', '#b2182b'],
  green_white_red: ['#1a9850', '#f7f7f7', '#d73027'],
  coolwarm: ['#3b4cc0', '#dddddd', '#b40426'],
  RdBu_r: ['#053061', '#f7f7f7', '#67001f'],
  seismic: ['#00004c', '#ffffff', '#7f0000'],
  bwr: ['#0000ff', '#ffffff', '#ff0000'],
};

// The low / mid / high anchor colours (as CSS hex) of a colormap — used to draw
// the deviation legend's plain-language explanation so the swatches always match
// whatever diverging map is active.
export function colormapEndpoints(colormap) {
  const hex = COLORMAP_HEX[colormap] || COLORMAP_HEX.blue_white_red;
  return { low: hex[0], mid: hex[Math.floor(hex.length / 2)], high: hex[hex.length - 1] };
}

function anchorsFor(colormap) {
  const hex = COLORMAP_HEX[colormap] || COLORMAP_HEX.green_yellow_red;
  return hex.map(hexToRgb01);
}

function lerp3(a, b, u) {
  return [a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u, a[2] + (b[2] - a[2]) * u];
}

// Piecewise-linear color at t in [0,1] across N anchor stops.
function colorAt(anchors, t) {
  const x = Math.min(1, Math.max(0, t));
  const seg = anchors.length - 1;
  const f = x * seg;
  const i = Math.min(seg - 1, Math.floor(f));
  return lerp3(anchors[i], anchors[i + 1], f - i);
}

// `steps` = number of legend TICK LABELS (= band boundaries); bandCount = steps-1.
function bandCount(steps) {
  return Math.max(1, Math.round(steps) - 1);
}

// Piecewise-CONSTANT color transfer function with bandCount(steps) flat bands.
export function buildDiscreteLUT({ rangeMin, rangeMax, steps, reverse = false, colormap = 'green_yellow_red' }) {
  const ctf = vtkColorTransferFunction.newInstance();
  ctf.removeAllPoints();
  const anchors = anchorsFor(colormap);
  const n = bandCount(steps);
  const span = rangeMax - rangeMin || 1;
  const eps = span * 1e-6;

  for (let i = 0; i < n; i += 1) {
    let tCenter = (i + 0.5) / n;
    if (reverse) tCenter = 1 - tCenter;
    const [r, g, b] = colorAt(anchors, tCenter);
    const lo = rangeMin + (span * i) / n;
    const hi = rangeMin + (span * (i + 1)) / n;
    ctf.addRGBPoint(lo, r, g, b);
    ctf.addRGBPoint(hi - eps, r, g, b);
  }
  ctf.setMappingRange(rangeMin, rangeMax);
  ctf.build();
  return ctf;
}

// {css, lo, hi} bands for the HTML legend — must match buildDiscreteLUT exactly.
export function legendBands({ rangeMin, rangeMax, steps, reverse = false, colormap = 'green_yellow_red' }) {
  const anchors = anchorsFor(colormap);
  const n = bandCount(steps);
  const span = rangeMax - rangeMin || 1;
  const bands = [];
  for (let i = 0; i < n; i += 1) {
    let tCenter = (i + 0.5) / n;
    if (reverse) tCenter = 1 - tCenter;
    const [r, g, b] = colorAt(anchors, tCenter);
    bands.push({
      css: `rgb(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)})`,
      lo: rangeMin + (span * i) / n,
      hi: rangeMin + (span * (i + 1)) / n,
    });
  }
  return bands;
}

// The `steps` boundary/tick values across [rangeMin, rangeMax].
export function legendBoundaries({ rangeMin, rangeMax, steps }) {
  const n = bandCount(steps);
  const span = rangeMax - rangeMin;
  const out = [];
  for (let i = 0; i <= n; i += 1) out.push(rangeMin + (span * i) / n);
  return out;
}

// 2-decimal formatter for the diverging (deviation) legend.
export function fmt2(value) {
  const v = Math.abs(value) < 5e-3 ? 0 : value;
  return v.toFixed(2);
}

// 4-decimal round-half-up (reproduces the article's tabulated legend values).
export function fmt4(value) {
  const rounded = Math.floor(value * 1e4 + 0.5 + 1e-6) / 1e4;
  return rounded.toFixed(4);
}

export const NEUTRAL_HEX = '#3a3f7a';
export const HIGHLIGHT_HEX = '#ff8c1a';

export function hexToRgb01(hex) {
  const h = hex.replace('#', '');
  return [
    parseInt(h.slice(0, 2), 16) / 255,
    parseInt(h.slice(2, 4), 16) / 255,
    parseInt(h.slice(4, 6), 16) / 255,
  ];
}
