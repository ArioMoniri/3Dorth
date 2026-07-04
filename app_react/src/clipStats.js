// Client-side statistics for the clip-box "Visible part" column (Feature 3).
// Mirrors the shape of the server's stats dict (mean/median/sd/rms/min/max/n)
// so StatsPanel can render a "Visible part (clipped)" column next to "Whole"
// with the SAME Row layout. Computed purely from the per-vertex scalar array
// Viewport already read out of the loaded polydata (`scalarValues`) masked by
// the per-vertex visible mask Viewport computes from the clip box — no
// fabricated numbers, no server round-trip.

// `values` — the full per-vertex scalar array (thickness_mm or deviation_mm).
// `mask` — Uint8Array same length as `values`, 1 = inside the clip box.
// Returns null if there is no usable (finite, masked-in) data.
export function computeMaskedStats(values, mask) {
  if (!values || !mask || values.length === 0) return null;

  const kept = [];
  for (let i = 0; i < values.length; i += 1) {
    if (!mask[i]) continue;
    const v = values[i];
    if (Number.isFinite(v)) kept.push(v);
  }
  const n = kept.length;
  if (n === 0) return { n: 0 };

  let sum = 0;
  let sumSq = 0;
  let min = Infinity;
  let max = -Infinity;
  let maxPositive = -Infinity;
  let maxNegative = Infinity;
  for (let i = 0; i < n; i += 1) {
    const v = kept[i];
    sum += v;
    sumSq += v * v;
    if (v < min) min = v;
    if (v > max) max = v;
    if (v > 0 && v > maxPositive) maxPositive = v;
    if (v < 0 && v < maxNegative) maxNegative = v;
  }
  const mean = sum / n;
  const rms = Math.sqrt(sumSq / n);
  let variance = 0;
  for (let i = 0; i < n; i += 1) {
    const d = kept[i] - mean;
    variance += d * d;
  }
  variance /= n;
  const sd = Math.sqrt(variance);

  const sorted = kept.slice().sort((a, b) => a - b);
  const mid = Math.floor(n / 2);
  const median = n % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];

  // Coverage thresholds (mirrors the server's deviation stats, computed the
  // same way: fraction of vertices beyond +/-1mm and +/-2mm).
  let overPos1 = 0;
  let overNeg1 = 0;
  let overPos2 = 0;
  let overNeg2 = 0;
  for (let i = 0; i < n; i += 1) {
    const v = kept[i];
    if (v > 1) overPos1 += 1;
    if (v < -1) overNeg1 += 1;
    if (v > 2) overPos2 += 1;
    if (v < -2) overNeg2 += 1;
  }

  return {
    n,
    mean,
    median,
    sd,
    rms,
    min,
    max,
    max_positive: Number.isFinite(maxPositive) ? maxPositive : null,
    max_negative: Number.isFinite(maxNegative) ? maxNegative : null,
    pct_over_1mm_pos: (overPos1 / n) * 100,
    pct_over_1mm_neg: (overNeg1 / n) * 100,
    pct_over_2mm_pos: (overPos2 / n) * 100,
    pct_over_2mm_neg: (overNeg2 / n) * 100,
  };
}
