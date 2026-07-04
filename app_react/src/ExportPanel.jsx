// Export controls. The user picks one or more formats, a DPI for raster output,
// and a camera pose (azimuth / elevation / roll / zoom). On "Export" we POST the
// CURRENT mode + side(s) + params + camera to /api/session/{sid}/export and list
// each returned file as a real download link.
//
// The camera pose is shared with the live viewport (via onCameraChange) so the
// on-screen view matches what will be rendered into the PNG/TIFF/JPG.

const RASTER = new Set(['png', 'tiff', 'jpg']);
const ALL_FORMATS = ['png', 'tiff', 'jpg', 'stl', 'ply', 'obj', 'vtp', 'dicom'];

export default function ExportPanel({
  formats,
  onToggleFormat,
  dpi,
  onDpiChange,
  camera,
  onCameraChange,
  onExport,
  exporting,
  files,
  error,
  canExport,
  disabledReason,
}) {
  const anyRaster = [...formats].some((f) => RASTER.has(f));

  const setCam = (key, v) => onCameraChange({ ...camera, [key]: v });

  return (
    <section className="panel-section export-panel">
      <h2>Export</h2>

      <div className="export-group">
        <div className="export-sub">Formats</div>
        <div className="format-grid">
          {ALL_FORMATS.map((f) => (
            <label key={f} className="format-chip">
              <input
                type="checkbox"
                checked={formats.has(f)}
                onChange={() => onToggleFormat(f)}
              />
              <span>{f.toUpperCase()}</span>
            </label>
          ))}
        </div>
      </div>

      {anyRaster && (
        <label className="ctl ctl-slider export-dpi">
          <span className="ctl-label">
            Raster DPI <span className="ctl-value">{dpi}</span>
          </span>
          <input
            type="range"
            min={72}
            max={600}
            step={1}
            value={dpi}
            onChange={(e) => onDpiChange(parseInt(e.target.value, 10))}
          />
        </label>
      )}

      <div className="export-group">
        <div className="export-sub">Camera pose</div>
        <div className="camera-grid">
          <CamField
            label="Azimuth°"
            value={camera.azimuth}
            min={-180}
            max={180}
            onChange={(v) => setCam('azimuth', v)}
          />
          <CamField
            label="Elevation°"
            value={camera.elevation}
            min={-90}
            max={90}
            onChange={(v) => setCam('elevation', v)}
          />
          <CamField
            label="Roll°"
            value={camera.roll}
            min={-180}
            max={180}
            onChange={(v) => setCam('roll', v)}
          />
          <CamField
            label="Zoom"
            value={camera.zoom}
            min={0.2}
            max={4}
            step={0.05}
            onChange={(v) => setCam('zoom', v)}
          />
        </div>
      </div>

      <button
        className="apply-btn export-btn"
        disabled={!canExport || exporting || formats.size === 0}
        onClick={onExport}
        title={!canExport ? disabledReason : undefined}
      >
        {exporting ? 'Exporting…' : 'Export'}
      </button>

      {!canExport && disabledReason && (
        <p className="panel-hint">{disabledReason}</p>
      )}
      {formats.size === 0 && canExport && (
        <p className="panel-hint">Pick at least one format.</p>
      )}
      {error && <p className="panel-warn">{error}</p>}

      {files && Object.keys(files).length > 0 && (
        <div className="export-files">
          <div className="export-sub">Downloads</div>
          {Object.entries(files).map(([fmt, url]) => (
            <a
              key={fmt}
              className="export-file"
              href={url}
              download
              target="_blank"
              rel="noreferrer"
            >
              Download {fmt.toUpperCase()}
            </a>
          ))}
        </div>
      )}
    </section>
  );
}

function CamField({ label, value, min, max, step = 1, onChange }) {
  return (
    <label className="cam-field">
      <span className="cam-label">{label}</span>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(e) => {
          const v = parseFloat(e.target.value);
          onChange(Number.isFinite(v) ? v : 0);
        }}
      />
    </label>
  );
}
