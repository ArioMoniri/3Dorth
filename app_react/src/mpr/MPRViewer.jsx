// The MPR (multi-planar reformat) viewer: a grid of 3 SliceView panels
// (axial / coronal / sagittal) driven by one shared crosshair {ix,iy,iz} and a
// window/level control. Every panel is a pure function of that state — scrubbing
// one plane moves the crosshair on the other two; clicking inside a panel moves
// the in-plane crosshair and updates the others + the 3D marker.
//
// The volume never ships to the browser: SliceView pulls small windowed PNGs
// from /slice on demand (see docs/IMAGING_DESIGN.md, "slice-on-demand").
//
// Coordinate frame (critical): world = idx*spacing + offset, identity direction.
// Planes are ARRAY-ORIENTED and labeled as such; we never print radiological
// A/P/S/I. A persistent research / de-identified / not-for-diagnosis note stays
// visible at the bottom.

import { useCallback, useEffect, useRef, useState } from 'react';

import { fetchVolumeInfo } from '../api';
import SliceView from './SliceView';

const PLANES = ['axial', 'coronal', 'sagittal'];
const WL_DEBOUNCE_MS = 80;

// Clamp a voxel triple into the volume bounds.
function clampVoxel({ ix, iy, iz }, dims) {
  const c = (v, n) => Math.max(0, Math.min(n - 1, Math.round(v)));
  return {
    ix: c(ix, dims.nx),
    iy: c(iy, dims.ny),
    iz: c(iz, dims.nz),
  };
}

// `side`             — which sub-volume to slice (App's active side).
// `sessionId`        — session to slice from.
// `externalCrosshair`— voxel {ix,iy,iz} pushed in by a 3D pick (or null).
// `onCrosshairChange`— (voxel, worldXyz) => void, so the parent can move the 3D
//                       sphere marker. worldXyz is derived from volume-info.
export default function MPRViewer({
  sessionId,
  side,
  externalCrosshair,
  onCrosshairChange,
}) {
  const [info, setInfo] = useState(null); // volume-info for `side`
  const [infoError, setInfoError] = useState(null);
  const [crosshair, setCrosshair] = useState(null); // { ix, iy, iz }

  // Window/level: `wl` drives the UI slider (instant); `committedWL` is what the
  // slices actually request, updated on an 80ms debounce so a drag coalesces.
  const [wl, setWl] = useState({ window: 1800, level: 400 });
  const [committedWL, setCommittedWL] = useState({ window: 1800, level: 400 });
  const wlTimerRef = useRef(null);

  // Measurement mode (distance / angle) for the 2D slice panels. When on, each
  // SliceView's MeasureOverlay becomes live and click-to-pick is suspended
  // (same gated pattern as the oblique reformat).
  const [measureMode, setMeasureMode] = useState(false);

  const dims = info
    ? { nz: info.shape_zyx[0], ny: info.shape_zyx[1], nx: info.shape_zyx[2] }
    : null;
  const spacing = info?.spacing_mm; // [sx, sy, sz]
  const offset = info?.offset_xyz_mm; // [ox, oy, oz]

  // Report the crosshair (and its world position) up so the parent can place
  // the 3D marker. Kept in a ref so effects don't depend on identity.
  const reportRef = useRef(onCrosshairChange);
  reportRef.current = onCrosshairChange;

  const report = useCallback(
    (vox) => {
      if (!spacing || !offset) return;
      const world = [
        vox.ix * spacing[0] + offset[0],
        vox.iy * spacing[1] + offset[1],
        vox.iz * spacing[2] + offset[2],
      ];
      reportRef.current?.(vox, world);
    },
    [spacing, offset],
  );

  // ---- load volume-info whenever session/side changes ----------------------
  useEffect(() => {
    if (!sessionId || !side) {
      setInfo(null);
      setCrosshair(null);
      return undefined;
    }
    let cancelled = false;
    setInfoError(null);
    fetchVolumeInfo(sessionId, side)
      .then((vi) => {
        if (cancelled) return;
        setInfo(vi);
        // Seed the crosshair at the volume centre and W/L at the bone preset.
        const [nz, ny, nx] = vi.shape_zyx;
        const seed = {
          ix: Math.floor(nx / 2),
          iy: Math.floor(ny / 2),
          iz: Math.floor(nz / 2),
        };
        setCrosshair(seed);
        setWl({ window: vi.default_window, level: vi.default_level });
        setCommittedWL({ window: vi.default_window, level: vi.default_level });
      })
      .catch((e) => {
        if (!cancelled) setInfoError(String(e?.message || e));
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId, side]);

  // ---- adopt an external (3D-pick) crosshair -------------------------------
  useEffect(() => {
    if (!externalCrosshair || !dims) return;
    const v = clampVoxel(externalCrosshair, dims);
    setCrosshair(v);
    // Don't re-report: the pick already told the parent where the marker is.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [externalCrosshair?.ix, externalCrosshair?.iy, externalCrosshair?.iz]);

  // ---- crosshair edits from within the MPR ---------------------------------
  // Scrubbing a plane changes only that plane's index component.
  const onScrub = useCallback(
    (plane, newIndex) => {
      if (!dims) return;
      setCrosshair((prev) => {
        if (!prev) return prev;
        const next = { ...prev };
        if (plane === 'axial') next.iz = newIndex;
        else if (plane === 'coronal') next.iy = newIndex;
        else next.ix = newIndex;
        const v = clampVoxel(next, dims);
        report(v);
        return v;
      });
    },
    [dims, report],
  );

  // An in-plane click sets the two in-plane voxel axes for that plane, keeping
  // the fixed (index) axis unchanged.
  const onInPlanePick = useCallback(
    (plane, colVox, rowVox) => {
      if (!dims) return;
      setCrosshair((prev) => {
        if (!prev) return prev;
        const next = { ...prev };
        if (plane === 'axial') {
          next.ix = colVox; // x
          next.iy = rowVox; // y
        } else if (plane === 'coronal') {
          next.ix = colVox; // x
          next.iz = rowVox; // z
        } else {
          next.iy = colVox; // y
          next.iz = rowVox; // z
        }
        const v = clampVoxel(next, dims);
        report(v);
        return v;
      });
    },
    [dims, report],
  );

  // ---- window/level (debounced ~80ms) --------------------------------------
  function onWLChange(partial) {
    setWl((prev) => {
      const next = { ...prev, ...partial };
      if (wlTimerRef.current) clearTimeout(wlTimerRef.current);
      wlTimerRef.current = setTimeout(() => {
        wlTimerRef.current = null;
        setCommittedWL(next);
      }, WL_DEBOUNCE_MS);
      return next;
    });
  }

  useEffect(
    () => () => {
      if (wlTimerRef.current) clearTimeout(wlTimerRef.current);
    },
    [],
  );

  if (infoError) {
    return (
      <div className="mpr-wrap mpr-error">
        <strong>Could not load volume for images.</strong> {infoError}
      </div>
    );
  }
  if (!info || !crosshair || !dims) {
    return (
      <div className="mpr-wrap mpr-loading">
        <div className="spinner" />
        <div>Loading volume for images…</div>
      </div>
    );
  }

  const [huLo, huHi] = info.hu_range;

  return (
    <div className="mpr-wrap">
      <div className="mpr-grid">
        {PLANES.map((plane) => (
          <SliceView
            key={plane}
            sessionId={sessionId}
            side={side}
            plane={plane}
            dims={dims}
            spacing={spacing}
            crosshair={crosshair}
            window={committedWL.window}
            level={committedWL.level}
            maxDim={512}
            onScrub={onScrub}
            onInPlanePick={onInPlanePick}
            measureMode={measureMode}
          />
        ))}

        {/* Window/level control lives in the 4th grid cell. */}
        <div className="mpr-wl">
          <div className="mpr-wl-title">Window / Level (HU)</div>
          <label className="mpr-wl-row">
            <span>Width</span>
            <input
              type="range"
              min={1}
              max={Math.max(2, huHi - huLo)}
              value={wl.window}
              onChange={(e) => onWLChange({ window: Number(e.target.value) })}
            />
            <span className="mpr-wl-val">{Math.round(wl.window)}</span>
          </label>
          <label className="mpr-wl-row">
            <span>Level</span>
            <input
              type="range"
              min={huLo}
              max={huHi}
              value={wl.level}
              onChange={(e) => onWLChange({ level: Number(e.target.value) })}
            />
            <span className="mpr-wl-val">{Math.round(wl.level)}</span>
          </label>
          <button
            type="button"
            className="mpr-wl-reset"
            onClick={() =>
              onWLChange({
                window: info.default_window,
                level: info.default_level,
              })
            }
          >
            Bone preset
          </button>
          <button
            type="button"
            className={`measure-toggle${measureMode ? ' active' : ''}`}
            onClick={() => setMeasureMode((v) => !v)}
            title="Place distance / angle measurements on the slices (mm from the scan geometry). Click to add points, drag to adjust. Click-to-pick is paused while measuring."
          >
            {measureMode ? '✓ Measuring' : '📏 Measure'}
          </button>
          <div className="mpr-side-tag">
            Side: <strong>{side}</strong> · voxel [{crosshair.ix}, {crosshair.iy},{' '}
            {crosshair.iz}]
          </div>
        </div>
      </div>

      <div className="mpr-note">
        Array-oriented planes (not verified radiological orientation). Research /
        de-identified / not for diagnosis.
      </div>
    </div>
  );
}
