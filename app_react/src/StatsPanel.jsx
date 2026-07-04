// Right-side results panel. In Mode A / per-side thickness it prints the
// returned thickness stats (mean / median / SD / min / max). In Mode B deviation
// it prints registration quality (RMS, inlier fraction) and the deviation stats
// (%>1/2 mm, added/removed cc). Values come straight from the compute response.

function n(v, d = 2) {
  return Number.isFinite(v) ? Number(v).toFixed(d) : '—';
}

function Row({ label, value, unit }) {
  return (
    <div className="stat-row">
      <span className="stat-key">{label}</span>
      <span className="stat-val">
        {value}
        {unit ? <span className="stat-unit"> {unit}</span> : null}
      </span>
    </div>
  );
}

export default function StatsPanel({ kind, result }) {
  if (!result) return null;

  if (kind === 'deviation') {
    const s = result.stats || {};
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
          <Row label="Mean" value={n(s.mean)} unit="mm" />
          <Row label="Median" value={n(s.median)} unit="mm" />
          <Row label="SD" value={n(s.sd)} unit="mm" />
          <Row label="RMS" value={n(s.rms)} unit="mm" />
          <Row label="Max +" value={n(s.max_positive)} unit="mm" />
          <Row label="Max −" value={n(s.max_negative)} unit="mm" />
        </div>
        <div className="stats-group">
          <div className="stats-subtitle">Coverage</div>
          <Row label="&gt; 1 mm (+)" value={n(s.pct_over_1mm_pos, 1)} unit="%" />
          <Row label="&gt; 1 mm (−)" value={n(s.pct_over_1mm_neg, 1)} unit="%" />
          <Row label="&gt; 2 mm (+)" value={n(s.pct_over_2mm_pos, 1)} unit="%" />
          <Row label="&gt; 2 mm (−)" value={n(s.pct_over_2mm_neg, 1)} unit="%" />
          <Row label="Added" value={n(s.added_volume_cc)} unit="cc" />
          <Row label="Removed" value={n(s.removed_volume_cc)} unit="cc" />
        </div>
      </div>
    );
  }

  // thickness
  const s = result.stats || {};
  return (
    <div className="stats-card">
      <div className="stats-title">Cortical thickness (mm)</div>
      <div className="stats-group">
        <Row label="Mean" value={n(s.mean)} unit="mm" />
        <Row label="Median" value={n(s.median)} unit="mm" />
        <Row label="SD" value={n(s.sd)} unit="mm" />
        <Row label="RMS" value={n(s.rms)} unit="mm" />
        <Row label="Min" value={n(s.min)} unit="mm" />
        <Row label="Max" value={n(s.max)} unit="mm" />
        <Row label="Vertices" value={s.n?.toLocaleString?.() ?? s.n} />
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
    </div>
  );
}
