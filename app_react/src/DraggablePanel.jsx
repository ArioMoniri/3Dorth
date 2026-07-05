// DraggablePanel — wraps an overlay panel (legend / stats / figures) so the user
// can DRAG it around the screen (grip handle, top-right) and RESIZE it (native
// corner grip).
//
// Docked (default) the panel sits in the right-overlay column, which scrolls when
// the stack is tall. The moment the user drags it, the panel pops out to
// `position: fixed` at its current on-screen spot and then tracks the pointer — so
// it escapes the column's scroll-clip instead of vanishing when moved past the
// column edge ("legends disappear when dragged"). Double-clicking the grip re-docks
// it. Purely presentational; layout/analysis is untouched until the user moves it.
//
// Note we use position:fixed (not a CSS transform) for the moved state — a
// transform on the wrapper would create a containing block and trap the figures'
// position:fixed lightbox; a fixed ancestor does not.

import { useRef, useState } from 'react';

export default function DraggablePanel({ children, className = '' }) {
  // `fixed` is null while docked; once dragged it holds viewport coords {left, top}.
  const [fixed, setFixed] = useState(null);
  const panelRef = useRef(null);
  const drag = useRef(null);

  function onDown(e) {
    const panel = panelRef.current;
    if (!panel) return;
    // Pin the pop-out to the panel's CURRENT on-screen box so it doesn't jump.
    const r = panel.getBoundingClientRect();
    drag.current = { sx: e.clientX, sy: e.clientY, ox: r.left, oy: r.top };
    setFixed({ left: r.left, top: r.top });
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp, { once: true });
    e.preventDefault();
    e.stopPropagation();
  }
  function onMove(e) {
    const d = drag.current;
    if (!d) return;
    const w = panelRef.current ? panelRef.current.getBoundingClientRect().width : 0;
    // Clamp so the panel stays on-screen and the grip stays graspable.
    const maxLeft = Math.max(8, window.innerWidth - w - 8);
    const left = Math.min(Math.max(d.ox + (e.clientX - d.sx), 8), maxLeft);
    const top = Math.min(Math.max(d.oy + (e.clientY - d.sy), 8), Math.max(8, window.innerHeight - 40));
    setFixed({ left, top });
  }
  function onUp() {
    drag.current = null;
    window.removeEventListener('pointermove', onMove);
  }

  return (
    <div
      ref={panelRef}
      className={`draggable-panel ${fixed ? 'is-floating' : ''} ${className}`}
      style={fixed ? { left: `${fixed.left}px`, top: `${fixed.top}px` } : undefined}
    >
      <span
        className="drag-handle"
        title="Drag to move · double-click to re-dock · drag the corner to resize"
        onPointerDown={onDown}
        onDoubleClick={() => setFixed(null)}
        role="button"
        aria-label="Move panel"
      >
        ⠿
      </span>
      {children}
    </div>
  );
}
