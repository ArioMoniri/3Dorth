// DraggablePanel — wraps an overlay panel (legend / stats / figures) so the user
// can DRAG it around the screen (grip handle, top-right) and RESIZE it (native
// corner grip). The position is a translate offset from the panel's normal layout
// spot and starts at (0,0), so the default layout is untouched until the user
// moves something; double-clicking the grip snaps it back. Purely presentational.

import { useRef, useState } from 'react';

export default function DraggablePanel({ children, className = '' }) {
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const drag = useRef(null);

  function onDown(e) {
    drag.current = { sx: e.clientX, sy: e.clientY, ox: pos.x, oy: pos.y };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp, { once: true });
    e.preventDefault();
    e.stopPropagation();
  }
  function onMove(e) {
    const d = drag.current;
    if (!d) return;
    setPos({ x: d.ox + (e.clientX - d.sx), y: d.oy + (e.clientY - d.sy) });
  }
  function onUp() {
    drag.current = null;
    window.removeEventListener('pointermove', onMove);
  }

  return (
    <div
      className={`draggable-panel ${className}`}
      // Only apply a transform once actually moved — a transform (even translate(0,0))
      // creates a containing block that would trap the figures' position:fixed lightbox.
      style={pos.x || pos.y ? { transform: `translate(${pos.x}px, ${pos.y}px)` } : undefined}
    >
      <span
        className="drag-handle"
        title="Drag to move · double-click to reset position · drag the corner to resize"
        onPointerDown={onDown}
        onDoubleClick={() => setPos({ x: 0, y: 0 })}
        role="button"
        aria-label="Move panel"
      >
        ⠿
      </span>
      {children}
    </div>
  );
}
