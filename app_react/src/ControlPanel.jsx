// LEFT panel. Two sections:
//   1. Region layers  — show/hide checkboxes (from the manifest) + highlight
//      selector. These drive the region view.
//   2. Parameters     — the registry-driven panel. Controls come from
//      /api/parameters (subset for the active mode); we group them by `group`
//      and render each with <ParameterControl>. NOTHING is hardcoded per key.

import ParameterControl from './ParameterControl';

export default function ControlPanel({
  manifest,
  controls,
  values,
  onParamChange,
  onReset,
  regionState,
  onToggleRegion,
  onHighlightChange,
}) {
  // Group controls by their `group` field, preserving first-seen order.
  const groups = [];
  const byGroup = new Map();
  controls.forEach((spec) => {
    if (!byGroup.has(spec.group)) {
      byGroup.set(spec.group, []);
      groups.push(spec.group);
    }
    byGroup.get(spec.group).push(spec);
  });

  return (
    <aside className="panel">
      <section className="panel-section">
        <h2>Layers / regions</h2>
        <div className="region-list">
          {manifest.regions.map((r) => (
            <label key={r.label} className="region-item" title={`${r.n_points} points`}>
              <input
                type="checkbox"
                checked={regionState.visible.includes(r.label)}
                onChange={() => onToggleRegion(r.label)}
              />
              <span>
                Region {r.label} ({r.volume_cm3} cm³)
                {r.is_humerus ? ' — humerus' : ''}
              </span>
            </label>
          ))}
        </div>
        <label className="ctl ctl-enum">
          <span className="ctl-label">Highlight region</span>
          <select
            value={String(regionState.highlight)}
            onChange={(e) => onHighlightChange(Number(e.target.value))}
          >
            {manifest.regions.map((r) => (
              <option key={r.label} value={r.label}>
                Region {r.label}
                {r.is_humerus ? ' (humerus)' : ''}
              </option>
            ))}
          </select>
        </label>
      </section>

      <section className="panel-section">
        <div className="panel-section-head">
          <h2>Parameters</h2>
          <button className="reset-btn" onClick={onReset} title="Restore paper defaults">
            Reset to paper defaults
          </button>
        </div>
        <p className="panel-hint">
          {controls.length} controls (Mode {'A'}/{'B'} subset) — generated from
          the registry.
        </p>
        {groups.map((group) => (
          <details key={group} open className="param-group">
            <summary>{group}</summary>
            <div className="param-group-body">
              {byGroup.get(group).map((spec) => (
                <ParameterControl
                  key={spec.key}
                  spec={spec}
                  value={values[spec.key]}
                  onChange={(v) => onParamChange(spec.key, v)}
                />
              ))}
            </div>
          </details>
        ))}
      </section>
    </aside>
  );
}
