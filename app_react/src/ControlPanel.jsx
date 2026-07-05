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

import ParameterControl from './ParameterControl';
import ExportPanel from './ExportPanel';
import ManualAnchor from './ManualAnchor';
import RegionThumbnails from './RegionThumbnails';

const UPLOAD_ACCEPT = '.zip,.nii,.nii.gz,.stl,.ply,.obj,.vtp';

function prettySide(s) {
  if (!s) return s;
  if (s === 'full') return 'Full';
  if (s === 'mesh') return 'Mesh';
  return s.charAt(0).toUpperCase() + s.slice(1);
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
  const meta = session?.meta ?? {};
  const showDeviation = (mode === 'B' && modeBView === 'deviation') || isMesh;
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
        {isMesh && (
          <p className="panel-note">
            Mesh upload: thickness (Mode A) needs a CT volume, so this session is
            limited to viewing and Mode-B deviation vs another surface.
          </p>
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
              {prettySide(s)}
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
            <p className="panel-hint compare-guide">
              <strong>What to compare.</strong> Deviation compares two bone surfaces of
              the <em>same</em> anatomy — e.g. an operated humerus vs the contralateral
              side. Load a <em>bilateral</em> CT (one scan containing both sides); Mode&nbsp;B
              then aligns and compares Left vs Right. The{' '}
              <b title="Baseline surface. Deviation is signed relative to this one (0 mm).">reference</b>{' '}
              is the baseline; the{' '}
              <b title="Surface measured against the reference. + = target sits outside the reference (bone gained); − = inside (lost).">target</b>{' '}
              is measured against it, so <b>swapping them flips the sign and the
              red/blue colours</b>.
            </p>
            <label className="ctl ctl-enum">
              <span
                className="ctl-label"
                title="Baseline surface — deviation is signed relative to this one (0 mm)"
              >
                Reference side
              </span>
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
              <span
                className="ctl-label"
                title="Surface measured against the reference; + = outside the reference (bone gained)"
              >
                Target side
              </span>
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
