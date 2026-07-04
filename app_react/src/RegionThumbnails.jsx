// Visual region picker. Renders a SMALL rendered image per connected bone
// region (fetched lazily from GET /api/session/{sid}/region-thumbnails) beside
// its label / volume / boneness. Clicking a thumbnail selects that region and
// triggers the normal (debounced) recompute so the map updates.
//
// The text dropdown in ControlPanel keeps working independently — this is an
// ADDITIONAL, visual way to pick the right structure on an uploaded scan.
//
// Thumbnails compute takes ~5-10 s server-side; while pending we show a small
// spinner. A region whose render came back null shows a placeholder chip.

export default function RegionThumbnails({
  thumbs, // [{ label, volume_cm3, boneness, thumb: url|null }] | null
  loading, // bool — server render in progress
  error, // string | null
  activeLabel, // currently selected region label
  onSelect, // (label:int) => void
}) {
  if (loading) {
    return (
      <div className="region-thumbs-status">
        <span className="spinner spinner-inline" />
        <span>Rendering region previews… (~5–10 s)</span>
      </div>
    );
  }
  if (error) {
    return (
      <div className="region-thumbs-status region-thumbs-error">{error}</div>
    );
  }
  if (!thumbs || thumbs.length === 0) return null;

  return (
    <div className="region-thumbs" role="listbox" aria-label="Bone regions">
      {thumbs.map((r) => {
        const active = r.label === activeLabel;
        return (
          <button
            key={r.label}
            type="button"
            role="option"
            aria-selected={active}
            className={`region-thumb${active ? ' active' : ''}`}
            onClick={() => onSelect(r.label)}
            title={`Region ${r.label} — ${r.volume_cm3.toFixed(1)} cm³, boneness ${r.boneness.toFixed(2)}`}
          >
            <span className="region-thumb-img">
              {r.thumb ? (
                <img src={r.thumb} alt={`Region ${r.label} preview`} loading="lazy" />
              ) : (
                <span className="region-thumb-placeholder" aria-hidden="true">
                  no preview
                </span>
              )}
            </span>
            <span className="region-thumb-meta">
              <span className="region-thumb-label">Region {r.label}</span>
              <span className="region-thumb-sub">
                {r.volume_cm3.toFixed(1)} cm³ · bone {r.boneness.toFixed(2)}
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
