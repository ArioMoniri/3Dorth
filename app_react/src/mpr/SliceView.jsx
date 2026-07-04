// One MPR plane panel: a windowed PNG slice (real CT pixels from /slice), a
// crosshair overlay at the in-plane voxel, and scrubbing via a slider + mouse
// wheel. Clicking inside the image moves the in-plane crosshair (and, through
// the parent, the other two planes + the 3D marker).
//
// The <img> pixels are aspect-corrected server-side (physically-square), so its
// natural size may differ from the raw slice dims. We map voxel <-> pixel using
// the plane's in-plane voxel extents (nCols x nRows) against the rendered box,
// which stays correct regardless of the server's max_dim scaling.
//
// Plane <-> axis (fixed; see docs/IMAGING_DESIGN_technical.md §2.1):
//   axial    : fix z (index=iz)  cols=x(ix)  rows=y(iy)
//   coronal  : fix y (index=iy)  cols=x(ix)  rows=z(iz)
//   sagittal : fix x (index=ix)  cols=y(iy)  rows=z(iz)

import { useEffect, useRef, useState } from 'react';

import { sliceUrl } from '../api';

// Per-plane: which crosshair voxel component is the slice INDEX, and which two
// are the in-plane (col, row) axes. Values name the key in {ix,iy,iz}.
const PLANE_MAP = {
  axial: { index: 'iz', col: 'ix', row: 'iy', nCol: 'nx', nRow: 'ny' },
  coronal: { index: 'iy', col: 'ix', row: 'iz', nCol: 'nx', nRow: 'nz' },
  sagittal: { index: 'ix', col: 'iy', row: 'iz', nCol: 'ny', nRow: 'nz' },
};

// Friendly labels — always tagged "(array orientation)": these are
// array-oriented planes, NOT verified radiological axial/coronal/sagittal, so
// we never assert patient A/P/S/I. See docs/IMAGING_DESIGN.md.
const PLANE_LABEL = {
  axial: 'Axial',
  coronal: 'Coronal',
  sagittal: 'Sagittal',
};

export default function SliceView({
  sessionId,
  side,
  plane,
  dims, // { nx, ny, nz }
  crosshair, // { ix, iy, iz }
  window: win,
  level,
  maxDim = 512,
  onScrub, // (plane, newIndex) => void
  onInPlanePick, // (plane, col, row) => void  (voxel coords)
}) {
  const boxRef = useRef(null);
  const imgRef = useRef(null);
  // The rendered image rectangle inside the box, accounting for object-fit:
  // contain letterboxing, so the crosshair overlay and click-mapping stay
  // pixel-accurate rather than assuming the image fills the whole box.
  const [imgRect, setImgRect] = useState(null); // { left, top, w, h } in box px

  const map = PLANE_MAP[plane];
  const idx = crosshair[map.index];
  const nIndex = dims[
    plane === 'axial' ? 'nz' : plane === 'coronal' ? 'ny' : 'nx'
  ];
  const nCol = dims[map.nCol];
  const nRow = dims[map.nRow];
  const col = crosshair[map.col];
  const row = crosshair[map.row];

  const src = sliceUrl(sessionId, {
    side,
    plane,
    index: idx,
    window: win,
    level,
    maxDim,
  });

  // Recompute the displayed image rectangle whenever the box or image size
  // changes. object-fit: contain centres the image and letterboxes the shorter
  // axis; we mirror that math so the crosshair sits on the real pixels and a
  // click on the letterbox maps to the nearest edge voxel rather than drifting.
  const recalcRect = () => {
    const box = boxRef.current;
    const img = imgRef.current;
    if (!box || !img) return;
    const bw = box.clientWidth;
    const bh = box.clientHeight;
    const iw = img.naturalWidth || nCol;
    const ih = img.naturalHeight || nRow;
    if (bw <= 0 || bh <= 0 || iw <= 0 || ih <= 0) return;
    const scale = Math.min(bw / iw, bh / ih);
    const w = iw * scale;
    const h = ih * scale;
    setImgRect({ left: (bw - w) / 2, top: (bh - h) / 2, w, h });
  };

  useEffect(() => {
    recalcRect();
    const box = boxRef.current;
    if (!box || typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(recalcRect);
    ro.observe(box);
    return () => ro.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nCol, nRow]);

  // Crosshair pixel position within the displayed image rect. +0.5 centres on
  // the voxel; falls back to box centre until the rect is known.
  const rect = imgRect || { left: 0, top: 0, w: 0, h: 0 };
  const leftPx = rect.left + (nCol > 1 ? (col + 0.5) / nCol : 0.5) * rect.w;
  const topPx = rect.top + (nRow > 1 ? (row + 0.5) / nRow : 0.5) * rect.h;

  function pickFromEvent(e) {
    const box = boxRef.current;
    if (!box || !imgRect || imgRect.w <= 0 || imgRect.h <= 0) return;
    const b = box.getBoundingClientRect();
    // Cursor position relative to the displayed image rect.
    const fx = (e.clientX - b.left - imgRect.left) / imgRect.w;
    const fy = (e.clientY - b.top - imgRect.top) / imgRect.h;
    const c = Math.max(0, Math.min(nCol - 1, Math.floor(fx * nCol)));
    const r = Math.max(0, Math.min(nRow - 1, Math.floor(fy * nRow)));
    onInPlanePick?.(plane, c, r);
  }

  function onWheel(e) {
    e.preventDefault();
    const step = e.deltaY > 0 ? 1 : -1;
    onScrub?.(plane, idx + step);
  }

  return (
    <div className="mpr-panel">
      <div className="mpr-panel-head">
        <span className="mpr-plane-name">{PLANE_LABEL[plane]}</span>
        <span className="mpr-array-tag" title="Array-oriented plane, not verified radiological orientation; no patient A/P/S/I is asserted.">
          (array orientation)
        </span>
        <span className="mpr-idx">
          {idx + 1} / {nIndex}
        </span>
      </div>

      <div
        className="mpr-image-box"
        ref={boxRef}
        onWheel={onWheel}
        onMouseDown={pickFromEvent}
        title="Scroll to scrub · click to move crosshair"
      >
        <img
          ref={imgRef}
          className="mpr-image"
          src={src}
          alt={`${plane} slice ${idx}`}
          draggable={false}
          onLoad={recalcRect}
        />
        {/* crosshair overlay — lines span only the displayed image rect so they
            never bleed into the letterbox. */}
        {imgRect && (
          <>
            <div
              className="mpr-crosshair-v"
              style={{
                left: `${leftPx}px`,
                top: `${rect.top}px`,
                height: `${rect.h}px`,
              }}
            />
            <div
              className="mpr-crosshair-h"
              style={{
                top: `${topPx}px`,
                left: `${rect.left}px`,
                width: `${rect.w}px`,
              }}
            />
            <div
              className="mpr-crosshair-dot"
              style={{ left: `${leftPx}px`, top: `${topPx}px` }}
            />
          </>
        )}
      </div>

      <input
        className="mpr-scrub"
        type="range"
        min={0}
        max={Math.max(0, nIndex - 1)}
        value={idx}
        onChange={(e) => onScrub?.(plane, Number(e.target.value))}
        aria-label={`${plane} slice index`}
      />
    </div>
  );
}
