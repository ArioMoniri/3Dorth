// "Statistics & Figures" section — collapsible, sits under the Stats panel.
// Fetches the publication-style matplotlib figures (histogram + per-region
// summary) from POST /api/session/{sid}/figures and renders them as images,
// plus an export control (format checkboxes + DPI) mirroring the existing
// 3D-figure ExportPanel, calling POST /api/session/{sid}/export-figures.
//
// Honesty rail: this is SINGLE-SUBJECT descriptive statistics. The server's
// `note` (always shown) states that scope; `by_region` is included only when
// the data actually supports a per-region breakdown (>=2 segmented regions in
// Mode A) — Mode B / a single region simply omits it rather than fabricating
// a group comparison, and the note explains why.

import { useEffect, useRef, useState } from 'react';

import { fetchFigures, exportFigures } from './api';

const RASTER_FORMATS = ['png', 'tiff', 'jpg'];

const FIGURE_TITLES = {
  histogram: 'Distribution histogram',
  ecdf: 'Cumulative distribution (ECDF)',
  table: 'Descriptive table (Table 1)',
  by_region: 'Per-region summary',
};

export default function StatsFigures({
  sessionId,
  mode, // 'A' | 'B'
  side,
  referenceSide,
  targetSide,
  regionLabel,
  params,
  manualTransform,
  computeSignature, // opaque string — refetch when the computed result changes
  hasResult,
}) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [figures, setFigures] = useState(null); // { name: base64 png }
  const [note, setNote] = useState(null);
  const [stats, setStats] = useState(null); // descriptive stat block from /figures
  const [zoomed, setZoomed] = useState(null); // { name, b64 } shown enlarged in a lightbox

  const [formats, setFormats] = useState(() => new Set(['png']));
  const [dpi, setDpi] = useState(300);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState(null);
  const [exportFiles, setExportFiles] = useState(null);

  // Refetch whenever the panel is opened, or the underlying computed result
  // changes while it's already open. Stale responses (an older session/mode
  // that resolves after a newer request) are dropped via a request-id guard.
  const reqIdRef = useRef(0);
  const fetchArgsRef = useRef(null);

  function buildArgs() {
    return {
      mode,
      side,
      referenceSide,
      targetSide,
      regionLabel,
      params,
      manualTransform,
    };
  }
  fetchArgsRef.current = buildArgs();

  async function loadFigures() {
    if (!sessionId || !hasResult) return;
    const myId = (reqIdRef.current += 1);
    setLoading(true);
    setError(null);
    try {
      const res = await fetchFigures(sessionId, fetchArgsRef.current);
      if (reqIdRef.current !== myId) return;
      setFigures(res.figures || {});
      setNote(res.note || null);
      setStats(res.stats || null);
    } catch (e) {
      if (reqIdRef.current !== myId) return;
      setError(readableError(e));
      setFigures(null);
    } finally {
      if (reqIdRef.current === myId) setLoading(false);
    }
  }

  useEffect(() => {
    if (open) loadFigures();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, sessionId, computeSignature]);

  // A fresh session/result invalidates any previously exported files.
  useEffect(() => {
    setExportFiles(null);
    setExportError(null);
  }, [sessionId, computeSignature]);

  function toggleFormat(f) {
    setFormats((prev) => {
      const next = new Set(prev);
      if (next.has(f)) next.delete(f);
      else next.add(f);
      return next;
    });
  }

  async function runExportFigures() {
    if (!sessionId || formats.size === 0) return;
    setExporting(true);
    setExportError(null);
    setExportFiles(null);
    try {
      const res = await exportFigures(sessionId, {
        ...fetchArgsRef.current,
        formats: [...formats],
        dpi,
      });
      setExportFiles(res.files || {});
      if (res.note) setNote(res.note);
    } catch (e) {
      setExportError(readableError(e));
    } finally {
      setExporting(false);
    }
  }

  return (
    <>
    <details
      className="stats-figures panel-section-details"
      open={open}
      onToggle={(e) => setOpen(e.currentTarget.open)}
    >
      <summary>Statistics &amp; figures</summary>
      <div className="stats-figures-body">
        {!hasResult && (
          <p className="panel-hint">
            Compute a {mode === 'B' ? 'deviation' : 'thickness'} result first,
            then open this section to render figures.
          </p>
        )}

        {hasResult && loading && (
          <p className="panel-hint">Rendering figures…</p>
        )}

        {hasResult && error && <p className="panel-warn">{error}</p>}

        {hasResult && !loading && stats && Number.isFinite(stats.n) && (
          <div className="stats-descriptive">
            <div className="stats-descriptive-title">
              Descriptive statistics (single-subject)
            </div>
            <div className="stats-descriptive-rows">
              <span>n {stats.n}</span>
              <span>
                mean {fmtStat(stats.mean)} ± {fmtStat(stats.sd)}
              </span>
              <span>median {fmtStat(stats.median)}</span>
              <span>IQR {fmtStat(stats.iqr)}</span>
              <span>
                p5 {fmtStat(stats.p5)} · p95 {fmtStat(stats.p95)}
              </span>
              <span>
                min {fmtStat(stats.min)} · max {fmtStat(stats.max)}
              </span>
              <span>RMS {fmtStat(stats.rms)}</span>
              <span>&gt;1 mm {fmtStat(stats.pct_over_1mm)}%</span>
              <span>&gt;2 mm {fmtStat(stats.pct_over_2mm)}%</span>
            </div>
          </div>
        )}

        {hasResult && !loading && figures && (
          <>
            <div className="stats-figures-grid">
              {Object.entries(figures).map(([name, b64]) => (
                <figure key={name} className="stats-figure">
                  <img
                    src={`data:image/png;base64,${b64}`}
                    alt={FIGURE_TITLES[name] || name}
                    title="Click to enlarge"
                    role="button"
                    tabIndex={0}
                    onClick={() => setZoomed({ name, b64 })}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') setZoomed({ name, b64 });
                    }}
                  />
                  <figcaption>{FIGURE_TITLES[name] || name}</figcaption>
                </figure>
              ))}
              {Object.keys(figures).length === 0 && (
                <p className="panel-hint">No figures could be rendered for this result.</p>
              )}
            </div>

            {note && <p className="panel-note stats-figures-note">{note}</p>}

            {/* ---- figure export: format checkboxes + DPI --------------- */}
            <div className="stats-figures-export">
              <div className="export-sub">Export figures</div>
              <div className="format-grid format-grid-3">
                {RASTER_FORMATS.map((f) => (
                  <label key={f} className="format-chip">
                    <input
                      type="checkbox"
                      checked={formats.has(f)}
                      onChange={() => toggleFormat(f)}
                    />
                    <span>{f.toUpperCase()}</span>
                  </label>
                ))}
              </div>

              <label className="ctl ctl-slider export-dpi">
                <span className="ctl-label">
                  Figure DPI <span className="ctl-value">{dpi}</span>
                </span>
                <input
                  type="range"
                  min={72}
                  max={600}
                  step={1}
                  value={dpi}
                  onChange={(e) => setDpi(parseInt(e.target.value, 10))}
                />
              </label>

              <button
                className="apply-btn export-btn"
                disabled={exporting || formats.size === 0}
                onClick={runExportFigures}
              >
                {exporting ? 'Exporting…' : 'Export figures'}
              </button>
              {formats.size === 0 && (
                <p className="panel-hint">Pick at least one format.</p>
              )}
              {exportError && <p className="panel-warn">{exportError}</p>}

              {exportFiles && Object.keys(exportFiles).length > 0 && (
                <div className="export-files">
                  <div className="export-sub">Downloads</div>
                  {Object.entries(exportFiles).map(([key, url]) => (
                    <a
                      key={key}
                      className="export-file"
                      href={url}
                      download
                      target="_blank"
                      rel="noreferrer"
                    >
                      Download {prettyFileKey(key)}
                    </a>
                  ))}
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </details>

    {/* click-to-enlarge lightbox — full figure at readable size, click/Esc to close */}
    {zoomed && (
      <div
        className="figure-lightbox"
        role="dialog"
        aria-modal="true"
        aria-label={`${FIGURE_TITLES[zoomed.name] || zoomed.name} (enlarged)`}
        onClick={() => setZoomed(null)}
        onKeyDown={(e) => { if (e.key === 'Escape') setZoomed(null); }}
        tabIndex={-1}
        ref={(el) => el && el.focus()}
      >
        <div className="figure-lightbox-inner" onClick={(e) => e.stopPropagation()}>
          <button
            className="figure-lightbox-close"
            aria-label="Close"
            onClick={() => setZoomed(null)}
          >
            ×
          </button>
          <img
            src={`data:image/png;base64,${zoomed.b64}`}
            alt={FIGURE_TITLES[zoomed.name] || zoomed.name}
          />
          <div className="figure-lightbox-cap">{FIGURE_TITLES[zoomed.name] || zoomed.name}</div>
        </div>
      </div>
    )}
    </>
  );
}

function fmtStat(v) {
  return Number.isFinite(v) ? Number(v).toFixed(2) : '—';
}

function prettyFileKey(key) {
  // "histogram" -> "Histogram"; "by_region_tiff" -> "By region (TIFF)"
  const m = key.match(/^(.*)_(png|tiff|jpg)$/);
  const base = (m ? m[1] : key).replace(/_/g, ' ');
  const label = base.charAt(0).toUpperCase() + base.slice(1);
  return m ? `${label} (${m[2].toUpperCase()})` : label;
}

function readableError(e) {
  const status = e?.status;
  if (status === 501) return `Not implemented on the server (501): ${e.message}`;
  if (status === 422) return `Invalid request (422): ${e.message}`;
  return e?.message || String(e);
}
