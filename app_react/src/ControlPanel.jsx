// LEFT panel. Sections, top to bottom:
//   1. Scan / session   — upload a bilateral .zip, show series meta.
//   2. Side & mode       — Left/Right side selector; in Mode B a sub-toggle
//                          between per-side thickness and two-side deviation
//                          (with reference/target selectors + mirror toggle).
//   3. Apply / Recompute — the PRIMARY action; sends current params to the
//                          compute API so EVERY parameter genuinely applies.
//   4. Parameters        — the registry-driven panel. Controls come from
//                          /api/parameters (subset for the active mode); grouped
//                          by `group` and rendered with <ParameterControl>.
//                          NOTHING is hardcoded per key.

import ParameterControl from './ParameterControl';

function prettySide(s) {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}

export default function ControlPanel({
  session,
  mode,
  controls,
  values,
  onParamChange,
  onReset,
  // side / sub-mode
  side,
  onSideChange,
  modeBView,
  onModeBViewChange,
  referenceSide,
  targetSide,
  onReferenceSideChange,
  onTargetSideChange,
  mirror,
  onMirrorChange,
  // actions
  onApply,
  onCompare,
  computing,
  // upload
  onUpload,
  uploading,
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

  const sides = session?.sides ?? [];
  const meta = session?.meta ?? {};
  const showDeviation = mode === 'B' && modeBView === 'deviation';
  const primaryBusy = computing || uploading;

  return (
    <aside className="panel">
      {/* ---- scan / session ------------------------------------------------ */}
      <section className="panel-section">
        <h2>Scan</h2>
        <div className="meta-block">
          <div className="meta-row">
            <span className="meta-key">Series</span>
            <span className="meta-val" title={meta.series}>
              {meta.series || '—'}
            </span>
          </div>
          <div className="meta-row">
            <span className="meta-key">Spacing</span>
            <span className="meta-val">
              {meta.spacing_mm ? meta.spacing_mm.join(' × ') + ' mm' : '—'}
            </span>
          </div>
          <div className="meta-row">
            <span className="meta-key">Laterality</span>
            <span className="meta-val">
              {session?.is_bilateral ? 'Bilateral' : meta.laterality || '—'}
            </span>
          </div>
        </div>
        <label className={`upload-btn${uploading ? ' busy' : ''}`}>
          <input
            type="file"
            accept=".zip"
            disabled={uploading}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) onUpload(f);
              e.target.value = '';
            }}
          />
          {uploading ? 'Uploading…' : 'Upload bilateral scan (.zip)'}
        </label>
      </section>

      {/* ---- side & mode --------------------------------------------------- */}
      <section className="panel-section">
        <h2>Side</h2>
        <div className="seg-toggle" role="group" aria-label="Scan side">
          {sides.map((s) => (
            <button
              key={s}
              className={side === s ? 'active' : ''}
              onClick={() => onSideChange(s)}
            >
              {prettySide(s)}
            </button>
          ))}
        </div>

        {mode === 'B' && (
          <>
            <h2 className="sub-head">Mode B view</h2>
            <div className="seg-toggle" role="group" aria-label="Mode B view">
              <button
                className={modeBView === 'thickness' ? 'active' : ''}
                onClick={() => onModeBViewChange('thickness')}
              >
                Per-side thickness
              </button>
              <button
                className={modeBView === 'deviation' ? 'active' : ''}
                onClick={() => onModeBViewChange('deviation')}
              >
                Deviation
              </button>
            </div>
          </>
        )}

        {showDeviation && (
          <div className="deviation-setup">
            <label className="ctl ctl-enum">
              <span className="ctl-label">Reference side</span>
              <select
                value={referenceSide}
                onChange={(e) => onReferenceSideChange(e.target.value)}
              >
                {sides.map((s) => (
                  <option key={s} value={s}>
                    {prettySide(s)}
                  </option>
                ))}
              </select>
            </label>
            <label className="ctl ctl-enum">
              <span className="ctl-label">Target side</span>
              <select
                value={targetSide}
                onChange={(e) => onTargetSideChange(e.target.value)}
              >
                {sides.map((s) => (
                  <option key={s} value={s}>
                    {prettySide(s)}
                  </option>
                ))}
              </select>
            </label>
            <label className="ctl ctl-bool">
              <span className="ctl-label">Mirror across sagittal plane</span>
              <input
                type="checkbox"
                checked={Boolean(mirror)}
                onChange={(e) => onMirrorChange(e.target.checked)}
              />
            </label>
          </div>
        )}
      </section>

      {/* ---- primary action ------------------------------------------------ */}
      <section className="panel-section">
        {showDeviation ? (
          <button
            className="apply-btn"
            disabled={primaryBusy || referenceSide === targetSide}
            onClick={onCompare}
          >
            {computing ? 'Computing…' : 'Compute deviation'}
          </button>
        ) : (
          <button className="apply-btn" disabled={primaryBusy} onClick={onApply}>
            {computing ? 'Computing…' : 'Apply / Recompute'}
          </button>
        )}
        {showDeviation && referenceSide === targetSide && (
          <p className="panel-warn">
            Pick two different sides to compute a deviation.
          </p>
        )}
        <p className="panel-hint">
          Recompute re-runs segmentation &amp; thickness with the current
          parameters, so every control below affects the result.
        </p>
      </section>

      {/* ---- registry-driven parameters ----------------------------------- */}
      <section className="panel-section">
        <div className="panel-section-head">
          <h2>Parameters</h2>
          <button
            className="reset-btn"
            onClick={onReset}
            title="Restore paper defaults"
          >
            Reset to paper defaults
          </button>
        </div>
        <p className="panel-hint">
          {controls.length} controls for this mode — generated from the registry.
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
