// Right-side results panel. In Mode A / per-side thickness it prints the
// returned thickness stats (mean / median / SD / min / max). In Mode B deviation
// it prints registration quality (RMS, inlier fraction) and the deviation stats
// (%>1/2 mm, added/removed cc). Values come straight from the compute response.
//
// It also draws a compact distribution histogram of the ACTIVE per-vertex
// scalar (thickness_mm in Mode A, deviation_mm in Mode B), binned entirely in
// the browser from the array Viewport read out of the loaded polydata
// (`scalarValues`, passed down from App) — no server call, no fabricated
// numbers. Recomputes whenever the map changes (new geometry -> new array).
//
// FEATURE 3 (clip / isolate): when a clip box is active, `clipStats` carries
// the SAME stat shape (mean/median/sd/rms/min/max/n/...) computed client-side
// over only the vertices inside the box (see App.jsx + clipStats.js). Every
// Row then renders a second "Visible part (clipped)" value next to "Whole" so
// the user can see seen-on-screen vs total at a glance. The histogram overlays
// the visible-part distribution on top of the whole-mesh one.

function n(v, d = 2) {
  return Number.isFinite(v) ? Number(v).toFixed(d) : '—';
}

// `clipValue` — when provided (clip active), renders a second column next to
// the "Whole" value labelled from the clip stats, so the two are directly
// comparable in one row.
function Row({ label, value, unit, clipValue }) {
  const showClip = clipValue !== undefined;
  return (
    <div className={`stat-row${showClip ? ' stat-row-split' : ''}`}>
      <span className="stat-key">{label}</span>
      <span className="stat-val">
        {value}
        {unit ? <span className="stat-unit"> {unit}</span> : null}
      </span>
      {showClip && (
        <span className="stat-val stat-val-clip">
          {clipValue}
          {unit ? <span className="stat-unit"> {unit}</span> : null}
        </span>
      )}
    </div>
  );
}

// Column headers shown once above a group of split rows, so "Whole" vs
// "Visible part (clipped)" is labelled rather than implied.
function SplitHead({ visiblePct, visibleCount, totalCount }) {
  return (
    <div className="stat-row stat-row-split stat-row-head">
      <span className="stat-key" />
      <span className="stat-col-head">Whole</span>
      <span className="stat-col-head stat-col-head-clip">
        Visible part (clipped)
        {Number.isFinite(visiblePct) && (
          <span className="stat-col-head-sub">
            {' '}
            ({Number.isFinite(visibleCount) ? visibleCount.toLocaleString() : '—'}
            {' / '}
            {Number.isFinite(totalCount) ? totalCount.toLocaleString() : '—'}
            {' · '}
            {visiblePct.toFixed(1)}%)
          </span>
        )}
      </span>
    </div>
  );
}

const HIST_BINS = 28;
const HIST_W = 210;
const HIST_H = 84;
const HIST_PAD_L = 4;
const HIST_PAD_R = 4;
const HIST_PAD_TOP = 6;
const HIST_AXIS_H = 16;

// Bin a finite-valued array into HIST_BINS equal-width buckets over [min,max].
function binValues(values, min, range) {
  const bins = new Array(HIST_BINS).fill(0);
  if (!values) return bins;
  for (let i = 0; i < values.length; i += 1) {
    const v = values[i];
    if (!Number.isFinite(v)) continue;
    let b = Math.floor(((v - min) / range) * HIST_BINS);
    if (b < 0) b = 0;
    if (b >= HIST_BINS) b = HIST_BINS - 1;
    bins[b] += 1;
  }
  return bins;
}

// Bin a finite-valued typed/plain array into HIST_BINS equal-width buckets and
// render an inline SVG bar chart, with a marker line at the mean and mm-labeled
// axis ticks at min/max. Returns null (renders nothing) when there is no usable
// data yet, so it simply doesn't appear rather than showing a fake chart.
//
// `overlayValues` (Feature 3, optional) — the SAME per-vertex array but masked
// to only the vertices inside the current clip box (visible part). When given,
// its bars are drawn on top of the whole-mesh bars (same bin edges, so the two
// distributions are directly comparable) in a contrasting colour.
function Histogram({ values, mean, unit = 'mm', title, overlayValues, overlayMean }) {
  if (!values || values.length === 0) return null;

  let min = Infinity;
  let max = -Infinity;
  let count = 0;
  for (let i = 0; i < values.length; i += 1) {
    const v = values[i];
    if (!Number.isFinite(v)) continue;
    if (v < min) min = v;
    if (v > max) max = v;
    count += 1;
  }
  if (count === 0 || !Number.isFinite(min) || !Number.isFinite(max)) return null;

  let range = max - min;
  if (range <= 0) range = 1; // degenerate (all-equal) — still draw a single bar

  const bins = binValues(values, min, range);
  const overlayBins = overlayValues ? binValues(overlayValues, min, range) : null;
  const maxCount = Math.max(...bins, ...(overlayBins || [0]), 1);

  const plotW = HIST_W - HIST_PAD_L - HIST_PAD_R;
  const plotH = HIST_H - HIST_PAD_TOP - HIST_AXIS_H;
  const barW = plotW / HIST_BINS;
  const meanFrac = Number.isFinite(mean) ? (mean - min) / range : null;
  const overlayMeanFrac = Number.isFinite(overlayMean) ? (overlayMean - min) / range : null;

  return (
    <div className="stats-hist">
      {title && <div className="stats-subtitle">{title}</div>}
      <svg
        viewBox={`0 0 ${HIST_W} ${HIST_H}`}
        className="stats-hist-svg"
        role="img"
        aria-label={`Distribution histogram, ${count} vertices, range ${n(min)} to ${n(max)} ${unit}`}
      >
        {bins.map((c, i) => {
          const h = (c / maxCount) * plotH;
          const x = HIST_PAD_L + i * barW;
          const y = HIST_PAD_TOP + (plotH - h);
          return (
            <rect
              key={i}
              x={x + 0.5}
              y={y}
              width={Math.max(barW - 1, 0.5)}
              height={h}
              className="stats-hist-bar"
            />
          );
        })}
        {overlayBins &&
          overlayBins.map((c, i) => {
            if (c === 0) return null;
            const h = (c / maxCount) * plotH;
            const x = HIST_PAD_L + i * barW;
            const y = HIST_PAD_TOP + (plotH - h);
            return (
              <rect
                key={`ov-${i}`}
                x={x + 0.5}
                y={y}
                width={Math.max(barW - 1, 0.5)}
                height={h}
                className="stats-hist-bar-overlay"
              />
            );
          })}
        {overlayMeanFrac != null && overlayMeanFrac >= 0 && overlayMeanFrac <= 1 && (
          <line
            x1={HIST_PAD_L + overlayMeanFrac * plotW}
            x2={HIST_PAD_L + overlayMeanFrac * plotW}
            y1={HIST_PAD_TOP}
            y2={HIST_PAD_TOP + plotH}
            className="stats-hist-mean-overlay"
          />
        )}
        {meanFrac != null && meanFrac >= 0 && meanFrac <= 1 && (
          <line
            x1={HIST_PAD_L + meanFrac * plotW}
            x2={HIST_PAD_L + meanFrac * plotW}
            y1={HIST_PAD_TOP}
            y2={HIST_PAD_TOP + plotH}
            className="stats-hist-mean"
          />
        )}
        <text x={HIST_PAD_L} y={HIST_H - 3} className="stats-hist-label">
          {n(min, 1)}
        </text>
        <text
          x={HIST_W - HIST_PAD_R}
          y={HIST_H - 3}
          textAnchor="end"
          className="stats-hist-label"
        >
          {n(max, 1)} {unit}
        </text>
      </svg>
    </div>
  );
}

// `clipStats` — the client-side stat dict computed over only the vertices
// inside the current clip box (see App.jsx + clipStats.js), or null when the
// clip is off. When present, every relevant Row gains a "Visible part
// (clipped)" column next to "Whole", and the histogram overlays the masked
// distribution on the whole-mesh one. `visibleCount`/`totalCount`/`visiblePct`
// label that column with the actual vertex counts.
export default function StatsPanel({
  kind,
  result,
  scalarValues,
  unit = 'mm',
  clipStats,
  visibleMask,
  visibleCount,
  totalCount,
  visiblePct,
}) {
  if (!result) return null;

  const hasClip = Boolean(clipStats);

  if (kind === 'deviation') {
    const s = result.stats || {};
    const cs = clipStats || {};
    const reg = result.registration || {};
    return (
      <div className="stats-card">
        <div className="stats-title">Deviation (mm)</div>
        <div className="stats-group">
          <div className="stats-subtitle">Registration</div>
          <Row label="ICP RMS" value={n(reg.rms, 3)} unit="mm" />
          <Row label="Inlier fraction" value={n(reg.inlier_fraction * 100, 1)} unit="%" />
        </div>
        <div className="stats-group">
          <div className="stats-subtitle">Signed deviation</div>
          {hasClip && (
            <SplitHead
              visiblePct={visiblePct}
              visibleCount={visibleCount}
              totalCount={totalCount}
            />
          )}
          <Row label="Mean" value={n(s.mean)} unit="mm" clipValue={hasClip ? n(cs.mean) : undefined} />
          <Row label="Median" value={n(s.median)} unit="mm" clipValue={hasClip ? n(cs.median) : undefined} />
          <Row label="SD" value={n(s.sd)} unit="mm" clipValue={hasClip ? n(cs.sd) : undefined} />
          <Row label="RMS" value={n(s.rms)} unit="mm" clipValue={hasClip ? n(cs.rms) : undefined} />
          <Row label="Max +" value={n(s.max_positive)} unit="mm" clipValue={hasClip ? n(cs.max_positive) : undefined} />
          <Row label="Max −" value={n(s.max_negative)} unit="mm" clipValue={hasClip ? n(cs.max_negative) : undefined} />
          {hasClip && (
            <Row label="Vertices" value={s.n?.toLocaleString?.() ?? s.n ?? '—'} clipValue={cs.n?.toLocaleString?.() ?? cs.n ?? '—'} />
          )}
        </div>
        <div className="stats-group">
          <div className="stats-subtitle">Coverage</div>
          <Row label="&gt; 1 mm (+)" value={n(s.pct_over_1mm_pos, 1)} unit="%" clipValue={hasClip ? n(cs.pct_over_1mm_pos, 1) : undefined} />
          <Row label="&gt; 1 mm (−)" value={n(s.pct_over_1mm_neg, 1)} unit="%" clipValue={hasClip ? n(cs.pct_over_1mm_neg, 1) : undefined} />
          <Row label="&gt; 2 mm (+)" value={n(s.pct_over_2mm_pos, 1)} unit="%" clipValue={hasClip ? n(cs.pct_over_2mm_pos, 1) : undefined} />
          <Row label="&gt; 2 mm (−)" value={n(s.pct_over_2mm_neg, 1)} unit="%" clipValue={hasClip ? n(cs.pct_over_2mm_neg, 1) : undefined} />
          <Row label="Added" value={n(s.added_volume_cc)} unit="cc" />
          <Row label="Removed" value={n(s.removed_volume_cc)} unit="cc" />
        </div>
        <div className="stats-group">
          <Histogram
            values={scalarValues}
            mean={s.mean}
            unit={unit}
            title={
              hasClip
                ? 'Deviation distribution — whole vs visible part (clipped)'
                : 'Deviation distribution (all vertices)'
            }
            overlayValues={hasClip ? maskedValues(scalarValues, visibleMask) : null}
            overlayMean={hasClip ? cs.mean : null}
          />
          {hasClip && <HistLegend />}
        </div>
      </div>
    );
  }

  // thickness
  const s = result.stats || {};
  const cs = clipStats || {};
  return (
    <div className="stats-card">
      <div className="stats-title">Cortical thickness (mm)</div>
      <div className="stats-group">
        {hasClip && (
          <SplitHead
            visiblePct={visiblePct}
            visibleCount={visibleCount}
            totalCount={totalCount}
          />
        )}
        <Row label="Mean" value={n(s.mean)} unit="mm" clipValue={hasClip ? n(cs.mean) : undefined} />
        <Row label="Median" value={n(s.median)} unit="mm" clipValue={hasClip ? n(cs.median) : undefined} />
        <Row label="SD" value={n(s.sd)} unit="mm" clipValue={hasClip ? n(cs.sd) : undefined} />
        <Row label="RMS" value={n(s.rms)} unit="mm" clipValue={hasClip ? n(cs.rms) : undefined} />
        <Row label="Min" value={n(s.min)} unit="mm" clipValue={hasClip ? n(cs.min) : undefined} />
        <Row label="Max" value={n(s.max)} unit="mm" clipValue={hasClip ? n(cs.max) : undefined} />
        <Row
          label="Vertices"
          value={s.n?.toLocaleString?.() ?? s.n}
          clipValue={hasClip ? (cs.n?.toLocaleString?.() ?? cs.n ?? '—') : undefined}
        />
      </div>
      {Number.isFinite(result.metal_fraction) && (
        <div className="stats-group">
          <Row
            label="Metal fraction"
            value={n(result.metal_fraction * 100, 3)}
            unit="%"
          />
        </div>
      )}
      <div className="stats-group">
        <Histogram
          values={scalarValues}
          mean={s.mean}
          unit={unit}
          title={
            hasClip
              ? 'Thickness distribution — whole vs visible part (clipped)'
              : 'Thickness distribution (all vertices)'
          }
          overlayValues={hasClip ? maskedValues(scalarValues, visibleMask) : null}
          overlayMean={hasClip ? cs.mean : null}
        />
        {hasClip && <HistLegend />}
      </div>
    </div>
  );
}

// Build the masked subset array for the overlay histogram bars. `mask` is the
// Uint8Array App threaded through; if absent (older caller shape) the overlay
// simply doesn't render — never fabricate a distribution.
function maskedValues(values, mask) {
  if (!values || !mask) return null;
  const out = [];
  for (let i = 0; i < values.length; i += 1) {
    if (mask[i]) out.push(values[i]);
  }
  return out;
}

function HistLegend() {
  return (
    <div className="stats-hist-legend">
      <span className="stats-hist-legend-item">
        <span className="stats-hist-legend-swatch stats-hist-legend-whole" /> Whole
      </span>
      <span className="stats-hist-legend-item">
        <span className="stats-hist-legend-swatch stats-hist-legend-clip" /> Visible part
      </span>
    </div>
  );
}
