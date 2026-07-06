// LEFT panel. Sections, top to bottom:
//   1. Scan / session   — upload a scan or mesh (all formats), show series meta.
//   2. Side & mode       — side selector driven purely from session.sides
//                          (['full'], ['left','right'] or ['mesh']); in Mode B a
//                          sub-toggle between per-side thickness and deviation
//                          (with reference/target selectors + mirror toggle).
//   3. Region            — connected-region selector (from the analyze response).
//   4. Apply / Recompute — the PRIMARY action; sends current params to the
//                          compute API so EVERY parameter genuinely applies.
//   5. Manual anchor     — Mode-B nudge/swap for the deviation registration.
//   6. Export            — formats / DPI / camera pose + download links.
//   7. Parameters        — the registry-driven panel. Controls come from
//                          /api/parameters (subset for the active mode); grouped
//                          by `group`. NOTHING is hardcoded per key.

import { useState } from 'react';

import ParameterControl from './ParameterControl';
import ExportPanel from './ExportPanel';
import ManualAnchor from './ManualAnchor';
import RegionThumbnails from './RegionThumbnails';

const UPLOAD_ACCEPT = '.zip,.nii,.nii.gz,.stl,.ply,.obj,.vtp';

// Label a side key. Later-series sides are namespaced ("s1/left"); when a
// `series` list is supplied we prefix the series name so the user always sees
// WHICH scan a side belongs to (e.g. "follow-up · Left").
function prettySide(s, series) {
  if (!s) return s;
  const sid = s.includes('/') ? s.split('/')[0] : 's0';
  const bare = s.includes('/') ? s.split('/').slice(1).join('/') : s;
  const pretty =
    bare === 'full' ? 'Full' : bare === 'mesh' ? 'Mesh' : bare.charAt(0).toUpperCase() + bare.slice(1);
  const entry = (series || []).find((x) => x.id === sid);
  // Only prefix when there is more than one series to disambiguate.
  if (entry && (series || []).length > 1) return `${entry.name} · ${pretty}`;
  return pretty;
}

export default function ControlPanel({
  session,
  isMesh,
  isSingleSided,
  mode,
  controls,
  values,
  onParamChange,
  onReset,
  // side / sub-mode
  side,
  onSideChange,
  canShowBoth,
  modeBView,
  onModeBViewChange,
  compareMode,
  onCompareModeChange,
  groupInfo,
  groupVisitCount = 0,
  referenceSide,
  targetSide,
  onReferenceSideChange,
  onTargetSideChange,
  mirror,
  onMirrorChange,
  // regions
  regions,
  regionLabel,
  onRegionChange,
  // region thumbnails (visual picker)
  regionThumbs,
  regionThumbsLoading,
  regionThumbsError,
  // actions
  onApply,
  onCompare,
  computing,
  // upload
  onUpload,
  uploading,
  // manual anchor
  nudge,
  onNudgeChange,
  onSwapSides,
  hasDeviationResult,
  isDeviationView,
  // export
  formats,
  onToggleFormat,
  dpi,
  onDpiChange,
  camera,
  onCameraChange,
  onExport,
  exporting,
  exportFiles,
  exportError,
  canExport,
  // Fig-2 annotation overlays (raster export)
  annotateLine,
  onAnnotateLineChange,
  annotateHeight,
  onAnnotateHeightChange,
  annotateApplies,
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
  const series = session?.series ?? [];
  const meta = session?.meta ?? {};

  // Side-key helpers for the comparison controls. A side key is a plain side of
  // the first series ("left") or a namespaced side of a later series ("s1/left").
  const sideNameOf = (k) => (k && k.includes('/') ? k.split('/').slice(1).join('/') : k);
  const seriesIdOf = (k) => (k && k.includes('/') ? k.split('/')[0] : 's0');
  const keyFor = (seriesId, sideName) => {
    const entry = series.find((s) => s.id === seriesId);
    return entry ? entry.sides.find((k) => sideNameOf(k) === sideName) ?? null : null;
  };
  const sideNamesIn = (seriesId) =>
    (series.find((s) => s.id === seriesId)?.sides || []).map(sideNameOf);
  // Set BOTH roles to the same anatomical side across two chosen visits (the
  // standard cross-series comparison: baseline·Left → follow-up·Left).
  const setCrossSeries = (sideName, refSeriesId, tgtSeriesId) => {
    onReferenceSideChange(keyFor(refSeriesId, sideName) || referenceSide);
    onTargetSideChange(keyFor(tgtSeriesId, sideName) || targetSide);
    // Same anatomical side across visits — the two surfaces are NOT mirror images.
    onMirrorChange?.(false);
  };
  const showDeviation = (mode === 'B' && modeBView === 'deviation') || isMesh;
  const primaryBusy = computing || uploading;
  const [showHelp, setShowHelp] = useState(true);

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
            <span className="meta-key">Format</span>
            <span className="meta-val">{meta.format || '—'}</span>
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
              {isMesh
                ? 'Mesh'
                : session?.is_bilateral
                  ? 'Bilateral'
                  : meta.laterality || '—'}
            </span>
          </div>
        </div>
        <label className={`upload-btn${uploading ? ' busy' : ''}`}>
          <input
            type="file"
            accept={UPLOAD_ACCEPT}
            disabled={uploading}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) onUpload(f);
              e.target.value = '';
            }}
          />
          {uploading ? 'Uploading…' : 'Upload scan or mesh'}
        </label>
        <p className="panel-hint upload-hint">
          Volumes (.zip DICOM, .nii, .nii.gz) or meshes (.stl, .ply, .obj, .vtp).
        </p>

        {/* Add-series: append a second/third scan (baseline vs follow-up …) to
            the SAME session so they can be anchored and compared. */}
        {session && (
          <>
            <label className={`add-series-btn${uploading ? ' busy' : ''}`}>
              <input
                type="file"
                accept={UPLOAD_ACCEPT}
                disabled={uploading}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) onUpload(f, true);
                  e.target.value = '';
                }}
              />
              {uploading ? 'Uploading…' : '＋ Add series (baseline / follow-up …)'}
            </label>
            {series.length > 1 && (
              <div className="series-list">
                <div className="series-list-title">
                  {series.length} series loaded — anchored against each other:
                </div>
                {series.map((s) => (
                  <div key={s.id} className="series-row" title={s.name}>
                    <span className="series-tag">{s.id}</span>
                    <span className="series-name">{s.name}</span>
                    <span className="series-sides">
                      {(s.sides || []).map((k) => prettySide(k, null)).join(' · ')}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
        {isMesh && (
          <p className="panel-note">
            Mesh upload: thickness (Mode A) needs a CT volume, so this session is
            limited to viewing and Mode-B deviation vs another surface.
          </p>
        )}

        {/* Comparison roles — visible right after upload, assignable any time. */}
        {!isMesh && sides.length >= 2 && (
          <div className="roles-card">
            <div className="roles-card-title">What to compare (Mode B)</div>

            {series.length > 1 ? (
              (() => {
                const refSideName = sideNameOf(referenceSide);
                const refSeriesId = seriesIdOf(referenceSide);
                const tgtSeriesId = seriesIdOf(targetSide);
                // Sides available in BOTH chosen visits (so same-side is possible).
                const both = sideNamesIn(refSeriesId).filter((n) =>
                  sideNamesIn(tgtSeriesId).includes(n),
                );
                const ordered = ['left', 'right', 'full']
                  .filter((n) => both.includes(n))
                  .concat(both.filter((n) => !['left', 'right', 'full'].includes(n)));
                const activeSide = ordered.includes(refSideName) ? refSideName : (ordered[0] || 'left');
                return (
                  <>
                    <div className="roles-sub">
                      Standard — <b>same side across visits</b> (the article's anchoring)
                    </div>
                    <label className="ctl ctl-enum">
                      <span className="ctl-label">Side to compare</span>
                      <select
                        value={activeSide}
                        onChange={(e) => setCrossSeries(e.target.value, refSeriesId, tgtSeriesId)}
                      >
                        {ordered.map((n) => (
                          <option key={n} value={n}>{cap(n)} ↔ {cap(n)}</option>
                        ))}
                      </select>
                    </label>
                    <div className="roles-visit-row">
                      <label className="ctl ctl-enum">
                        <span className="ctl-label">Reference visit</span>
                        <select
                          value={refSeriesId}
                          onChange={(e) => setCrossSeries(activeSide, e.target.value, tgtSeriesId)}
                        >
                          {series.map((s) => (
                            <option key={s.id} value={s.id}>{s.name}</option>
                          ))}
                        </select>
                      </label>
                      <label className="ctl ctl-enum">
                        <span className="ctl-label">Target visit</span>
                        <select
                          value={tgtSeriesId}
                          onChange={(e) => setCrossSeries(activeSide, refSeriesId, e.target.value)}
                        >
                          {series.map((s) => (
                            <option key={s.id} value={s.id}>{s.name}</option>
                          ))}
                        </select>
                      </label>
                    </div>

                    <div className="roles-sub">Or — <b>left vs right within one scan</b></div>
                    <div className="roles-within-row">
                      {series.map((s) => {
                        const l = s.sides.find((k) => sideNameOf(k) === 'left');
                        const r = s.sides.find((k) => sideNameOf(k) === 'right');
                        if (!l || !r) return null;
                        const on = referenceSide === l && targetSide === r;
                        return (
                          <button
                            key={s.id}
                            type="button"
                            className={`roles-within-btn${on ? ' active' : ''}`}
                            onClick={() => {
                              onReferenceSideChange(l);
                              onTargetSideChange(r);
                              // Left vs Right of ONE scan is contralateral — mirror it.
                              onMirrorChange?.(true);
                            }}
                            title={`Compare Left vs Right within ${s.name} (mirrored contralateral)`}
                          >
                            {s.name}: L vs R
                          </button>
                        );
                      })}
                    </div>
                  </>
                );
              })()
            ) : (
              <>
                <p className="panel-hint roles-hint">
                  Comparing <b>Left vs Right</b> of this one scan. To compare the{' '}
                  <b>same side across visits</b> (before / after), use{' '}
                  <b>＋ Add series</b> above to load a follow-up.
                </p>
                <label className="ctl ctl-enum">
                  <span className="ctl-label">Reference (baseline)</span>
                  <select value={referenceSide ?? ''} onChange={(e) => onReferenceSideChange(e.target.value)}>
                    {sides.map((s) => (<option key={s} value={s}>{prettySide(s, series)}</option>))}
                  </select>
                </label>
                <label className="ctl ctl-enum">
                  <span className="ctl-label">Target (measured)</span>
                  <select value={targetSide ?? ''} onChange={(e) => onTargetSideChange(e.target.value)}>
                    {sides.map((s) => (<option key={s} value={s}>{prettySide(s, series)}</option>))}
                  </select>
                </label>
              </>
            )}

            <button
              type="button"
              className="swap-sides-btn"
              onClick={onSwapSides}
              disabled={!referenceSide || referenceSide === targetSide}
              title="Swap reference and target — flips the deviation sign and the colours"
            >
              ⇄ Swap reference / target
            </button>
            <div className="roles-current">
              Comparing: <strong>{prettySide(targetSide, series)}</strong> against{' '}
              <strong>{prettySide(referenceSide, series)}</strong> (baseline)
              {series.length <= 1 && meta.series ? ` · ${meta.series}` : ''}
            </div>
          </div>
        )}
      </section>

      {/* ---- side & mode --------------------------------------------------- */}
      <section className="panel-section">
        <h2>{isSingleSided ? 'Scan' : 'Side'}</h2>
        <div className="seg-toggle" role="group" aria-label="Scan side">
          {sides.map((s) => (
            <button
              key={s}
              className={side === s ? 'active' : ''}
              onClick={() => onSideChange(s)}
            >
              {prettySide(s, series)}
            </button>
          ))}
          {/* Bilateral scans get a "Both" option that renders left + right
              together (each coloured by its own thickness). Only shown in the
              thickness view (Mode A or Mode-B thickness) — deviation compares a
              single registered surface, so Both is hidden there. */}
          {canShowBoth && !showDeviation && (
            <button
              className={side === 'both' ? 'active' : ''}
              onClick={() => onSideChange('both')}
              title="Show LEFT and RIGHT together, each coloured by its own cortical thickness"
            >
              Both
            </button>
          )}
        </div>
        {side === 'both' && (
          <p className="panel-hint">
            Bilateral view: left and right are rendered together, each coloured
            by its own cortical thickness. The stats, legend and figures below
            describe the <strong>left</strong> side; hover either bone to read
            its thickness. Pick a single side to isolate / clip / pick regions.
          </p>
        )}

        {mode === 'B' && !isMesh && (
          <>
            <h2 className="sub-head">Mode B view</h2>
            <div className="seg-toggle" role="group" aria-label="Mode B view">
              <button
                className={modeBView === 'thickness' ? 'active' : ''}
                onClick={() => onModeBViewChange('thickness')}
                title="Colour each scan by its OWN cortical thickness (not a comparison)"
              >
                Each scan's thickness
              </button>
              <button
                className={modeBView === 'deviation' ? 'active' : ''}
                onClick={() => onModeBViewChange('deviation')}
                title="Colour by the DIFFERENCE between the two anchored surfaces (mm) — this is the comparison"
              >
                Difference between scans
              </button>
            </div>
            <p className="panel-hint" style={{ marginTop: '4px' }}>
              <strong>Difference between scans</strong> is the comparison: red/blue = how far
              the target surface sits outside/inside the reference (mm).{' '}
              <strong>Each scan's thickness</strong> just colours one bone by its own wall
              thickness — not a comparison.
            </p>
          </>
        )}

        {showDeviation && series.length > 1 && (
          <>
            <h2 className="sub-head">Compare</h2>
            <div className="seg-toggle" role="group" aria-label="Comparison mode">
              <button
                className={compareMode !== 'group' ? 'active' : ''}
                onClick={() => onCompareModeChange('pair')}
                title="Compare two surfaces (one pair)"
              >
                One pair
              </button>
              <button
                className={compareMode === 'group' ? 'active' : ''}
                onClick={() => onCompareModeChange('group')}
                title="Overlay ALL visits (same side) and colour one surface by the difference across all of them"
              >
                All visits at once
              </button>
            </div>
            {compareMode === 'group' && (
              <div className="roles-current" style={{ marginTop: '6px' }}>
                Overlaying <strong>{groupVisitCount} visits</strong> (same side). The{' '}
                <strong>latest</strong> surface is coloured by the difference; earlier
                visits are faint ghost shells. Red = excess, green = deficit.
                {groupInfo?.registrations && (
                  <div className="group-reg">
                    {groupInfo.registrations.map((r, i) => (
                      <span key={i} className={`reg-badge${r.reliable ? '' : ' bad'}`}>
                        visit {i}: {r.reliable ? 'aligned' : 'low overlap'}
                        {typeof r.inlier_fraction === 'number'
                          ? ` (${Math.round(r.inlier_fraction * 100)}%)`
                          : ''}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}
          </>
        )}

        {showDeviation && compareMode !== 'group' && (
          <div className="deviation-setup">
            <p className="panel-hint compare-guide">
              <strong>What to compare.</strong>{' '}
              {series.length > 1
                ? 'The standard is the SAME side across visits (e.g. baseline·Left → follow-up·Left). '
                : 'With one scan, Left is compared against Right. '}
              The{' '}
              <b title="Baseline surface. Deviation is signed relative to this one (0 mm).">reference</b>{' '}
              is the baseline; the{' '}
              <b title="Surface measured against the reference. + = target sits outside the reference (bone gained); − = inside (lost).">target</b>{' '}
              is measured against it. Set the pair in the{' '}
              <b>“What to compare”</b> card in the Scan panel above; swapping flips the
              sign and colours.
            </p>
            <div className="roles-current">
              Comparing: <strong>{prettySide(targetSide, series)}</strong> against{' '}
              <strong>{prettySide(referenceSide, series)}</strong> (baseline)
            </div>
            <button
              type="button"
              className="swap-sides-btn"
              onClick={onSwapSides}
              disabled={!referenceSide || referenceSide === targetSide}
              title="Swap reference and target — flips the deviation sign and the red/blue colours, then recomputes"
            >
              ⇄ Swap reference / target
            </button>
            <label className="ctl ctl-bool">
              <span
                className="ctl-label"
                title="Reflect the target across the sagittal (L↔R) plane before aligning — needed when comparing a left bone to a right one"
              >
                Mirror across sagittal plane
              </span>
              <input
                type="checkbox"
                checked={Boolean(mirror)}
                onChange={(e) => onMirrorChange(e.target.checked)}
              />
            </label>
          </div>
        )}
      </section>

      {/* ---- region selector ---------------------------------------------- */}
      {!showDeviation &&
        ((regions && regions.length > 0) ||
          regionThumbsLoading ||
          (regionThumbs && regionThumbs.length > 0) ||
          regionThumbsError) && (
          <section className="panel-section">
            <h2>Region</h2>
            {regions && regions.length > 0 && (
              <label className="ctl ctl-enum">
                <span className="ctl-label">Connected bone region</span>
                <select
                  value={regionLabel ?? ''}
                  onChange={(e) => onRegionChange(parseInt(e.target.value, 10))}
                >
                  {regions.map((r) => (
                    <option key={r.label} value={r.label}>
                      Region {r.label} — {r.volume_cm3.toFixed(1)} cm³
                    </option>
                  ))}
                </select>
              </label>
            )}
            {/* Visual picker: small rendered image per region. Clicking one
                selects that region and recomputes. Loads lazily. */}
            <RegionThumbnails
              thumbs={regionThumbs}
              loading={regionThumbsLoading}
              error={regionThumbsError}
              activeLabel={regionLabel}
              onSelect={onRegionChange}
            />
            <p className="panel-hint">
              Largest connected component is chosen by default. Click a preview
              or use the dropdown to switch — the map recomputes automatically.
            </p>
          </section>
        )}

      {/* ---- primary action ------------------------------------------------ */}
      <section className="panel-section">
        <div className="auto-recompute-row">
          <span className={`auto-dot${computing ? ' busy' : ''}`} />
          <span className="auto-recompute-label">
            {computing ? 'Computing…' : 'Auto-recompute on'}
          </span>
        </div>
        {showDeviation ? (
          <button
            className="apply-btn"
            disabled={primaryBusy || referenceSide === targetSide}
            onClick={onCompare}
          >
            {computing ? 'Computing…' : 'Recompute deviation now'}
          </button>
        ) : (
          <button className="apply-btn" disabled={primaryBusy} onClick={onApply}>
            {computing ? 'Computing…' : 'Recompute now'}
          </button>
        )}
        {showDeviation && referenceSide === targetSide && (
          <p className="panel-warn">
            Pick two different sides to compute a deviation.
          </p>
        )}
        <p className="panel-hint">
          Changes apply automatically: display tweaks (colormap, range, steps)
          re-colour instantly, and pipeline parameters re-run after a short
          pause. This button forces an immediate recompute — it is optional.
        </p>
      </section>

      {/* ---- manual anchor (Mode B deviation) ------------------------------ */}
      {showDeviation && (
        <ManualAnchor
          transform={nudge}
          onChange={onNudgeChange}
          onSwapSides={onSwapSides}
          onApply={onCompare}
          computing={computing}
          hasAutoResult={hasDeviationResult}
        />
      )}

      {/* ---- export -------------------------------------------------------- */}
      <ExportPanel
        formats={formats}
        onToggleFormat={onToggleFormat}
        dpi={dpi}
        onDpiChange={onDpiChange}
        camera={camera}
        onCameraChange={onCameraChange}
        onExport={onExport}
        exporting={exporting}
        files={exportFiles}
        error={exportError}
        canExport={canExport}
        annotateLine={annotateLine}
        onAnnotateLineChange={onAnnotateLineChange}
        annotateHeight={annotateHeight}
        onAnnotateHeightChange={onAnnotateHeightChange}
        annotateApplies={annotateApplies}
        disabledReason={
          canExport
            ? undefined
            : `Compute a ${isDeviationView ? 'deviation' : 'thickness'} result first, then export.`
        }
      />

      {/* ---- registry-driven parameters ----------------------------------- */}
      <section className="panel-section">
        <div className="panel-section-head">
          <h2>Parameters</h2>
          <button
            className="reset-btn"
            onClick={onReset}
            title="Restore defaults"
          >
            Reset to defaults
          </button>
        </div>
        <div className="params-head-row">
          <p className="panel-hint">
            {controls.length} controls for this mode — generated from the registry.
          </p>
          <label className="show-help-toggle" title="Show an explanation under every control">
            <input
              type="checkbox"
              checked={showHelp}
              onChange={(e) => setShowHelp(e.target.checked)}
            />
            <span>Show explanations</span>
          </label>
        </div>
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
                  showHelp={showHelp}
                />
              ))}
            </div>
          </details>
        ))}
      </section>
    </aside>
  );
}
