// MeasureOverlay — on-image measurement tools for the 2D CT reformats (MPR /
// oblique). It draws an SVG over an image box and lets the user place & drag:
//   • distance  — 2 points, length in mm (use it as a ruler, a cortical-thickness
//                 caliper, or a Fig-2B "height" line — the label is chosen by `unitLabel`)
//   • angle     — 3 points, degrees at the middle vertex
// Points are stored in NORMALISED image coordinates [0..1] so they stay anchored to
// the anatomy under object-fit: contain (same rect math the crosshairs use). mm come
// from the reformat's physical span (`sizeMm` = px_mm × size_px; the reformat grid is
// square, so mm is isotropic). The overlay is INERT (pointer-events: none, nothing
// captured) unless `active` is true, so it can never interfere with click-to-pick.
//
// Export: `exportWithMeasures(imgEl, filename)` composites the underlying reformat
// image + the measurements onto a canvas and downloads a PNG — the measurements are
// "burned into" the exported image, as requested.

import { useCallback, useMemo, useRef, useState } from 'react';

let _uid = 0;
const nextId = () => `m${(_uid += 1)}`;

// Normalised (unitless) point distance — used for the angle tool, which is
// scale-free in the SQUARE-pixel image space the reformats are rendered in.
function dist2d(a, b) {
  return Math.hypot(a.nx - b.nx, a.ny - b.ny);
}

// Physical distance in mm between two normalised points, given the image's
// physical span along each axis. For a square reformat spanX === spanY === the
// oblique `sizeMm`; for an MPR slice the two in-plane axes can differ, so we
// scale each normalised delta by its own axis span (never assume square).
function distMm(a, b, spanXMm, spanYMm) {
  if (!Number.isFinite(spanXMm) || !Number.isFinite(spanYMm)) return null;
  const dx = (a.nx - b.nx) * spanXMm;
  const dy = (a.ny - b.ny) * spanYMm;
  return Math.hypot(dx, dy);
}

// angle at p1 (degrees) between p0 and p2, in normalised (square) space
function angleDeg(p0, p1, p2) {
  const a = [p0.nx - p1.nx, p0.ny - p1.ny];
  const b = [p2.nx - p1.nx, p2.ny - p1.ny];
  const dot = a[0] * b[0] + a[1] * b[1];
  const m = Math.hypot(...a) * Math.hypot(...b);
  if (m < 1e-9) return 0;
  return (Math.acos(Math.max(-1, Math.min(1, dot / m))) * 180) / Math.PI;
}

export default function MeasureOverlay({
  rect,          // { left, top, w, h } of the displayed image within the box (px)
  sizeMm,        // physical span of a SQUARE reformat (mm); used when spanX/Y omitted
  spanXMm,       // physical width of the image in mm (defaults to sizeMm — square)
  spanYMm,       // physical height of the image in mm (defaults to sizeMm — square)
  active,        // measure mode on/off — when off the overlay is fully inert
  unitLabel = 'distance', // label for the distance tool ("thickness" / "height" / "distance")
  measures,
  onChange,      // (measures) => void  — lift state so export can read it
}) {
  const [tool, setTool] = useState('distance'); // 'distance' | 'angle'
  const [pending, setPending] = useState(null); // partially-placed measure
  const dragRef = useRef(null); // { id, ptIdx }
  const svgRef = useRef(null);

  const set = useCallback((next) => onChange?.(next), [onChange]);

  // screen(px) <-> normalised image coords
  const toNorm = useCallback(
    (clientX, clientY) => {
      if (!rect || rect.w <= 0 || rect.h <= 0) return null;
      const svg = svgRef.current;
      const box = svg ? svg.getBoundingClientRect() : { left: 0, top: 0 };
      const x = clientX - box.left - rect.left;
      const y = clientY - box.top - rect.top;
      return { nx: Math.max(0, Math.min(1, x / rect.w)), ny: Math.max(0, Math.min(1, y / rect.h)) };
    },
    [rect],
  );
  const toPx = useCallback(
    (p) => (rect ? { x: rect.left + p.nx * rect.w, y: rect.top + p.ny * rect.h } : { x: 0, y: 0 }),
    [rect],
  );
  // Physical spans: default to the square `sizeMm` for both axes (oblique
  // reformats are square); MPR slices pass explicit per-axis spans.
  const spanX = Number.isFinite(spanXMm) ? spanXMm : sizeMm;
  const spanY = Number.isFinite(spanYMm) ? spanYMm : sizeMm;

  function onDown(e) {
    if (!active || !rect) return;
    const p = toNorm(e.clientX, e.clientY);
    if (!p) return;
    const need = tool === 'angle' ? 3 : 2;
    const cur = pending ? pending.pts : [];
    const pts = [...cur, p];
    if (pts.length >= need) {
      set([...(measures || []), { id: nextId(), type: tool, unitLabel, pts }]);
      setPending(null);
    } else {
      setPending({ type: tool, pts });
    }
  }

  function startDrag(id, ptIdx, e) {
    if (!active) return;
    e.stopPropagation();
    dragRef.current = { id, ptIdx };
    window.addEventListener('pointermove', onDragMove);
    window.addEventListener('pointerup', endDrag, { once: true });
  }
  function onDragMove(e) {
    const d = dragRef.current;
    if (!d) return;
    const p = toNorm(e.clientX, e.clientY);
    if (!p) return;
    set(
      (measures || []).map((m) =>
        m.id === d.id ? { ...m, pts: m.pts.map((pt, i) => (i === d.ptIdx ? p : pt)) } : m,
      ),
    );
  }
  function endDrag() {
    dragRef.current = null;
    window.removeEventListener('pointermove', onDragMove);
  }

  const rendered = useMemo(() => {
    const all = [...(measures || [])];
    if (pending) all.push({ id: '__pending', type: pending.type, unitLabel, pts: pending.pts, pending: true });
    return all;
  }, [measures, pending, unitLabel]);

  if (!rect) return null;

  return (
    <svg
      ref={svgRef}
      className={`measure-overlay${active ? ' active' : ''}`}
      style={{ position: 'absolute', inset: 0, pointerEvents: active ? 'auto' : 'none' }}
      onPointerDown={onDown}
    >
      {rendered.map((m) => {
        const px = m.pts.map(toPx);
        const stroke = m.pending ? '#ffd24a' : '#28e0c8';
        const line =
          px.length >= 2 ? (
            <polyline
              points={px.map((p) => `${p.x},${p.y}`).join(' ')}
              fill="none"
              stroke={stroke}
              strokeWidth={1.6}
            />
          ) : null;
        let label = null;
        if (m.type === 'angle' && m.pts.length === 3) {
          const val = angleDeg(m.pts[0], m.pts[1], m.pts[2]);
          label = { at: px[1], text: `${val.toFixed(1)}°` };
        } else if (m.type === 'distance' && m.pts.length === 2) {
          const d = distMm(m.pts[0], m.pts[1], spanX, spanY);
          const mid = { x: (px[0].x + px[1].x) / 2, y: (px[0].y + px[1].y) / 2 };
          label = { at: mid, text: d == null ? '—' : `${d.toFixed(2)} mm` };
        }
        return (
          <g key={m.id}>
            {line}
            {px.map((p, i) => (
              <circle
                key={i}
                cx={p.x}
                cy={p.y}
                r={5}
                fill={stroke}
                stroke="#0b0f18"
                strokeWidth={1.2}
                style={{ cursor: active ? 'grab' : 'default' }}
                onPointerDown={(e) => !m.pending && startDrag(m.id, i, e)}
              />
            ))}
            {label && (
              <g transform={`translate(${label.at.x + 8}, ${label.at.y - 8})`}>
                <rect x={-3} y={-12} width={label.text.length * 7.2 + 8} height={17} rx={3} fill="rgba(8,12,20,0.82)" />
                <text x={1} y={1} fill="#eafffb" fontSize={12} fontFamily="ui-monospace, monospace">
                  {`${m.unitLabel === 'distance' ? '' : m.unitLabel + ' '}${label.text}`}
                </text>
              </g>
            )}
          </g>
        );
      })}
      {active && (
        <foreignObject x={6} y={6} width={230} height={30} style={{ pointerEvents: 'auto' }}>
          <div className="measure-toolbar" xmlns="http://www.w3.org/1999/xhtml">
            {['distance', 'angle'].map((t) => (
              <button
                key={t}
                type="button"
                className={tool === t ? 'active' : ''}
                onClick={() => { setTool(t); setPending(null); }}
                title={t === 'angle' ? '3 points → angle' : `2 points → ${unitLabel} in mm`}
              >
                {t === 'angle' ? '∠ angle' : `↔ ${unitLabel}`}
              </button>
            ))}
            <button type="button" onClick={() => { set([]); setPending(null); }} title="Clear all">
              ✕ clear
            </button>
          </div>
        </foreignObject>
      )}
    </svg>
  );
}

// Composite the reformat <img> + the measurements onto a canvas and download a
// PNG. `sizeMm` is the SQUARE span; pass `spans = {x, y}` for a non-square MPR
// slice so the burned-in mm labels match the on-screen ones exactly.
export function exportWithMeasures(
  imgEl, measures, sizeMm, unitLabel, filename = 'measured.png', spans = null,
) {
  const spanX = spans && Number.isFinite(spans.x) ? spans.x : sizeMm;
  const spanY = spans && Number.isFinite(spans.y) ? spans.y : sizeMm;
  if (!imgEl || !imgEl.naturalWidth) return;
  const W = imgEl.naturalWidth;
  const H = imgEl.naturalHeight;
  const cv = document.createElement('canvas');
  cv.width = W;
  cv.height = H;
  const ctx = cv.getContext('2d');
  ctx.drawImage(imgEl, 0, 0, W, H);
  ctx.lineWidth = Math.max(1.5, W / 400);
  ctx.font = `${Math.max(12, W / 46)}px ui-monospace, monospace`;
  const P = (p) => ({ x: p.nx * W, y: p.ny * H });
  for (const m of measures || []) {
    const px = m.pts.map(P);
    ctx.strokeStyle = '#28e0c8';
    ctx.fillStyle = '#28e0c8';
    ctx.beginPath();
    px.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
    ctx.stroke();
    px.forEach((p) => { ctx.beginPath(); ctx.arc(p.x, p.y, ctx.lineWidth * 2.4, 0, 2 * Math.PI); ctx.fill(); });
    let text = null;
    let at = null;
    if (m.type === 'angle' && px.length === 3) {
      text = `${angleDeg(m.pts[0], m.pts[1], m.pts[2]).toFixed(1)}°`;
      at = px[1];
    } else if (m.type === 'distance' && px.length === 2) {
      const d = distMm(m.pts[0], m.pts[1], spanX, spanY);
      text = `${(m.unitLabel === 'distance' ? '' : m.unitLabel + ' ')}${(d ?? 0).toFixed(2)} mm`;
      at = { x: (px[0].x + px[1].x) / 2, y: (px[0].y + px[1].y) / 2 };
    }
    if (text && at) {
      ctx.fillStyle = 'rgba(8,12,20,0.82)';
      const tw = ctx.measureText(text).width;
      ctx.fillRect(at.x + 8, at.y - 20, tw + 10, 22);
      ctx.fillStyle = '#eafffb';
      ctx.fillText(text, at.x + 13, at.y - 4);
    }
  }
  cv.toBlob((blob) => {
    if (!blob) return;
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }, 'image/png');
}
