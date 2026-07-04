// Phase VII UI — arbitrary (tiltable) cross-section reformat, matched to the 3D
// cut at every point.
//
// Plane control (fallback per the task spec — robust and simple): the plane's
// unit NORMAL is derived from two angles (azimuth around Z, elevation from the
// XY plane), and a POSITION slider slides the plane ORIGIN along that normal,
// seeded at the volume centre (from /volume-info's extent_mm). A "Set plane
// centre from 3D pick" affordance lets the user re-anchor the origin to the
// last 3D marker (from Viewport.onPick), so the plane can be moved anywhere,
// not just re-oriented in place.
//
// Two-box matched mode (bilateral, two real volumes): ONE POST /oblique-compare
// per plane change returns BOTH bones' reformats (reference + target) for the
// SAME physical cut (the reference plane mapped through the cached rigid
// registration onto the target). Single-sided / mesh sessions keep the
// original single-box /oblique-slice behavior unchanged.
//
// On any plane change (debounced ~120ms, superseding stale requests the same
// way CompareView does), we fetch the reformat(s) and show the returned PNG(s).
// Each box's `meta` (origin/u/v/px_mm/size_px) gives the EXACT pixel<->world
// map — clicking the reference reformat computes the exact 3D world point via
// obliquePixelToWorld (mirrors core.viz.slice.oblique_pixel_to_world) and hands
// it to the parent so the 3D marker moves there.
//
// Honesty rail: world = idx*spacing + offset, identity direction, ARRAY
// oriented. The plane's tilt is reported in APP-FRAME terms (normal components
// along the array's X/Y/Z axes), never radiological A/P/S/I or laterality.

import { useEffect, useMemo, useRef, useState } from 'react';

import {
  fetchVolumeInfo,
  obliqueSlice,
  obliqueCompare,
  obliquePixelToWorld,
} from './api';

const DEBOUNCE_MS = 120;
const DEG = Math.PI / 180;

// Unit normal from azimuth (around Z, degrees) + elevation (from the XY plane,
// degrees). At azimuth=0, elevation=0 the normal is +X (a "sagittal-like" cut
// in array terms); elevation=90 gives +Z.
function normalFromAngles(azimuthDeg, elevationDeg) {
  const az = azimuthDeg * DEG;
  const el = elevationDeg * DEG;
  const cx = Math.cos(el) * Math.cos(az);
  const cy = Math.cos(el) * Math.sin(az);
  const cz = Math.sin(el);
  const n = Math.hypot(cx, cy, cz) || 1;
  return [cx / n, cy / n, cz / n];
}

function fmt3(v) {
  return `[${v.map((x) => x.toFixed(2)).join(', ')}]`;
}

// `sessionId`, `side` — which volume to slice (single-box fallback mode).
// `pickedWorld` — { x, y, z } | null — last 3D-pick world point (from the
//   Viewport's onSurfacePick via the parent's shared marker state), offered as
//   a "centre plane here" affordance.
// `onPlaneChange({ origin, normal })` — fires whenever the plane moves, so the
//   parent can draw the matching translucent plane actor in the 3D Viewport.
// `onPixelPick(worldXyz)` — fires with the exact 3D world point of a 2D click.
// `compareMode` — when true (bilateral session, two real volumes), render TWO
//   reformat boxes (reference/target) driven by ONE /oblique-compare call per
//   plane change, instead of the single-box /oblique-slice fallback.
// `referenceSide`, `targetSide` — the two volume sides for compareMode.
// `params`, `manualTransform` — forwarded to /oblique-compare so the matched
//   cut uses the SAME registration (params + manual anchor) as Compare/Mode B.
export default function ObliqueView({
  sessionId,
  side,
  pickedWorld,
  onPlaneChange,
  onPixelPick,
  compareMode = false,
  referenceSide,
  targetSide,
  params,
  manualTransform,
}) {
  const [info, setInfo] = useState(null);
  const [infoError, setInfoError] = useState(null);

  const [azimuth, setAzimuth] = useState(0); // degrees, around Z
  const [elevation, setElevation] = useState(0); // degrees, from XY plane
  const [offsetMm, setOffsetMm] = useState(0); // slides origin along the normal
  const [center, setCenter] = useState(null); // [x,y,z] mm — base plane centre

  const [image, setImage] = useState(null); // { url, meta } — single-box mode
  const [loading, setLoading] = useState(false);
  const [sliceError, setSliceError] = useState(null);

  // ---- compare (two-box) mode state ----------------------------------------
  const [refImage, setRefImage] = useState(null); // { url, meta }
  const [tgtImage, setTgtImage] = useState(null); // { url, meta }
  const [registration, setRegistration] = useState(null);
  const [firstCallPending, setFirstCallPending] = useState(false); // registering…

  const debounceRef = useRef(null);
  const requestIdRef = useRef(0);
  const imgBoxRef = useRef(null);
  const imgElRef = useRef(null);
  const [imgRect, setImgRect] = useState(null);

  // Second (target) box's own object-fit rect, since it has independent
  // natural dimensions from the reference box.
  const tgtImgBoxRef = useRef(null);
  const tgtImgElRef = useRef(null);
  const [tgtImgRect, setTgtImgRect] = useState(null);

  // The compare-mode side used for volume-info (seeds plane centre/size) is
  // the reference side — the plane lives in the reference bone's space.
  const infoSide = compareMode ? referenceSide : side;

  // ---- load volume-info once per (session, side): seeds the plane centre and
  // a size_mm that comfortably covers the volume's diagonal.
  useEffect(() => {
    if (!sessionId || !infoSide) {
      setInfo(null);
      return undefined;
    }
    let cancelled = false;
    setInfoError(null);
    fetchVolumeInfo(sessionId, infoSide)
      .then((vi) => {
        if (cancelled) return;
        setInfo(vi);
        const { x, y, z } = vi.extent_mm;
        const mid = [(x[0] + x[1]) / 2, (y[0] + y[1]) / 2, (z[0] + z[1]) / 2];
        setCenter(mid);
        setOffsetMm(0);
        setAzimuth(0);
        setElevation(0);
      })
      .catch((e) => {
        if (!cancelled) setInfoError(String(e?.message || e));
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId, infoSide]);

  const sizeMm = useMemo(() => {
    if (!info) return 220;
    const { x, y, z } = info.extent_mm;
    const diag = Math.hypot(x[1] - x[0], y[1] - y[0], z[1] - z[0]);
    return Math.max(60, Math.min(600, diag * 0.6));
  }, [info]);

  const normal = useMemo(() => normalFromAngles(azimuth, elevation), [azimuth, elevation]);

  // Plane origin: base centre nudged along the normal by `offsetMm`.
  const origin = useMemo(() => {
    if (!center) return null;
    return [
      center[0] + normal[0] * offsetMm,
      center[1] + normal[1] * offsetMm,
      center[2] + normal[2] * offsetMm,
    ];
  }, [center, normal, offsetMm]);

  // Tell the parent (so the 3D Viewport can draw the translucent plane actor)
  // whenever origin/normal actually change.
  useEffect(() => {
    if (!origin) return;
    onPlaneChange?.({ origin, normal, sizeMm });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [origin?.[0], origin?.[1], origin?.[2], normal[0], normal[1], normal[2], sizeMm]);

  // ---- debounced fetch of the reformat whenever the plane moves ------------
  useEffect(() => {
    if (!sessionId || !origin) return undefined;
    if (compareMode && (!referenceSide || !targetSide)) return undefined;
    if (!compareMode && !side) return undefined;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      debounceRef.current = null;
      if (compareMode) fetchCompareReformat();
      else fetchReformat();
    }, DEBOUNCE_MS);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    sessionId,
    side,
    compareMode,
    referenceSide,
    targetSide,
    params,
    manualTransform,
    origin?.[0],
    origin?.[1],
    origin?.[2],
    normal[0],
    normal[1],
    normal[2],
    sizeMm,
  ]);

  async function fetchReformat() {
    if (!origin) return;
    const myId = (requestIdRef.current += 1);
    setLoading(true);
    try {
      const res = await obliqueSlice(sessionId, {
        side,
        originXyz: origin,
        normal,
        sizeMm,
        pxMm: Math.max(0.4, sizeMm / 400),
        maxDim: 420,
      });
      if (requestIdRef.current !== myId) return; // superseded — drop stale
      const url = `data:image/png;base64,${res.image_png_base64}`;
      setImage({ url, meta: res.meta });
      setSliceError(null);
    } catch (e) {
      if (requestIdRef.current !== myId) return;
      setSliceError(e?.message || String(e));
    } finally {
      if (requestIdRef.current === myId) setLoading(false);
    }
  }

  // Two-box matched fetch: ONE /oblique-compare call returns BOTH bones'
  // reformats for the SAME physical cut, plus the registration reliability
  // gate. The very first call for a (sides, params) pair runs the heavy
  // registration (can take ~1-2 min) — `firstCallPending` drives a clear
  // "Registering & sampling both bones…" loading state for that case only;
  // subsequent plane moves just re-sample (fast), so we don't show it again
  // once we already have images.
  async function fetchCompareReformat() {
    if (!origin) return;
    const myId = (requestIdRef.current += 1);
    setLoading(true);
    const isFirstCall = !refImage && !tgtImage;
    if (isFirstCall) setFirstCallPending(true);
    try {
      const res = await obliqueCompare(sessionId, {
        referenceSide,
        targetSide,
        originXyz: origin,
        normal,
        sizeMm,
        pxMm: Math.max(0.4, sizeMm / 400),
        maxDim: 420,
        params,
        manualTransform,
      });
      if (requestIdRef.current !== myId) return; // superseded — drop stale
      setRefImage({
        url: `data:image/png;base64,${res.reference.image_png_base64}`,
        meta: res.reference.meta,
      });
      setTgtImage({
        url: `data:image/png;base64,${res.target.image_png_base64}`,
        meta: res.target.meta,
      });
      setRegistration(res.registration);
      setSliceError(null);
    } catch (e) {
      if (requestIdRef.current !== myId) return;
      setSliceError(e?.message || String(e));
    } finally {
      if (requestIdRef.current === myId) {
        setLoading(false);
        setFirstCallPending(false);
      }
    }
  }

  // A pair (sides, compareMode, session) change invalidates any prior compare
  // images/registration — never let a stale banner or mismatched pair linger.
  useEffect(() => {
    setRefImage(null);
    setTgtImage(null);
    setRegistration(null);
    setSliceError(null);
  }, [sessionId, compareMode, referenceSide, targetSide]);

  // Recompute the displayed image rectangle (object-fit: contain math), same
  // approach as SliceView, so the crosshair + click mapping stay pixel-exact.
  const recalcRect = () => {
    const box = imgBoxRef.current;
    const img = imgElRef.current;
    if (!box || !img) return;
    const bw = box.clientWidth;
    const bh = box.clientHeight;
    const iw = img.naturalWidth;
    const ih = img.naturalHeight;
    if (bw <= 0 || bh <= 0 || iw <= 0 || ih <= 0) return;
    const scale = Math.min(bw / iw, bh / ih);
    const w = iw * scale;
    const h = ih * scale;
    setImgRect({ left: (bw - w) / 2, top: (bh - h) / 2, w, h, iw, ih });
  };

  const recalcTgtRect = () => {
    const box = tgtImgBoxRef.current;
    const img = tgtImgElRef.current;
    if (!box || !img) return;
    const bw = box.clientWidth;
    const bh = box.clientHeight;
    const iw = img.naturalWidth;
    const ih = img.naturalHeight;
    if (bw <= 0 || bh <= 0 || iw <= 0 || ih <= 0) return;
    const scale = Math.min(bw / iw, bh / ih);
    const w = iw * scale;
    const h = ih * scale;
    setTgtImgRect({ left: (bw - w) / 2, top: (bh - h) / 2, w, h, iw, ih });
  };

  useEffect(() => {
    const box = imgBoxRef.current;
    if (!box || typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(recalcRect);
    ro.observe(box);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const box = tgtImgBoxRef.current;
    if (!box || typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(recalcTgtRect);
    ro.observe(box);
    return () => ro.disconnect();
  }, []);

  // Crosshair at the panel centre = plane origin (by construction, the centre
  // pixel of the returned reformat IS meta.origin_xyz_mm).
  const rect = imgRect;
  const tgtRect = tgtImgRect;

  // Reference/single box click -> exact 3D world point via its own meta.
  function onImageClick(e) {
    const activeImage = compareMode ? refImage : image;
    if (!activeImage || !rect || rect.w <= 0 || rect.h <= 0) return;
    const box = imgBoxRef.current;
    const b = box.getBoundingClientRect();
    const fx = (e.clientX - b.left - rect.left) / rect.w;
    const fy = (e.clientY - b.top - rect.top) / rect.h;
    if (fx < 0 || fx > 1 || fy < 0 || fy > 1) return; // clicked the letterbox
    const col = fx * (rect.iw - 1);
    const row = fy * (rect.ih - 1);
    const world = obliquePixelToWorld(activeImage.meta, row, col);
    onPixelPick?.(world);
  }

  // Target box click (compare mode, best-effort): map the click to a world
  // point using the TARGET box's own meta (its plane basis, already mapped
  // through the registration server-side) — this moves the shared 3D marker
  // into the target bone's space. At minimum the box always shows its centre
  // crosshair (= the mapped plane origin) even without a click.
  function onTgtImageClick(e) {
    if (!tgtImage || !tgtRect || tgtRect.w <= 0 || tgtRect.h <= 0) return;
    const box = tgtImgBoxRef.current;
    const b = box.getBoundingClientRect();
    const fx = (e.clientX - b.left - tgtRect.left) / tgtRect.w;
    const fy = (e.clientY - b.top - tgtRect.top) / tgtRect.h;
    if (fx < 0 || fx > 1 || fy < 0 || fy > 1) return;
    const col = fx * (tgtRect.iw - 1);
    const row = fy * (tgtRect.ih - 1);
    const world = obliquePixelToWorld(tgtImage.meta, row, col);
    onPixelPick?.(world);
  }

  function useLastPickAsCentre() {
    if (!pickedWorld) return;
    setCenter([pickedWorld.x, pickedWorld.y, pickedWorld.z]);
    setOffsetMm(0);
  }

  function resetPlane() {
    if (!info) return;
    const { x, y, z } = info.extent_mm;
    setCenter([(x[0] + x[1]) / 2, (y[0] + y[1]) / 2, (z[0] + z[1]) / 2]);
    setOffsetMm(0);
    setAzimuth(0);
    setElevation(0);
  }

  if (infoError) {
    return (
      <div className="mpr-wrap mpr-error oblique-wrap">
        <strong>Could not load volume for the oblique view.</strong> {infoError}
      </div>
    );
  }
  if (!info || !center) {
    return (
      <div className="mpr-wrap mpr-loading oblique-wrap">
        <div className="spinner" />
        <div>Loading volume for the oblique reformat…</div>
      </div>
    );
  }

  // Extent-derived slider range for the position-along-normal offset.
  const { x, y, z } = info.extent_mm;
  const maxOffset = Math.hypot(x[1] - x[0], y[1] - y[0], z[1] - z[0]) / 2;

  const controlsPanel = (
    <div className="oblique-controls">
      <div className="oblique-controls-title">Arbitrary cutting plane</div>
        <label className="oblique-slider-row">
          <span>Azimuth</span>
          <input
            type="range"
            min={-180}
            max={180}
            step={1}
            value={azimuth}
            onChange={(e) => setAzimuth(Number(e.target.value))}
          />
          <span className="oblique-slider-val">{azimuth.toFixed(0)}°</span>
        </label>
        <label className="oblique-slider-row">
          <span>Elevation</span>
          <input
            type="range"
            min={-90}
            max={90}
            step={1}
            value={elevation}
            onChange={(e) => setElevation(Number(e.target.value))}
          />
          <span className="oblique-slider-val">{elevation.toFixed(0)}°</span>
        </label>
        <label className="oblique-slider-row">
          <span>Position</span>
          <input
            type="range"
            min={-maxOffset}
            max={maxOffset}
            step={0.5}
            value={offsetMm}
            onChange={(e) => setOffsetMm(Number(e.target.value))}
          />
          <span className="oblique-slider-val">{offsetMm.toFixed(1)} mm</span>
        </label>
        <div className="oblique-btn-row">
          <button
            type="button"
            className="mpr-wl-reset"
            onClick={useLastPickAsCentre}
            disabled={!pickedWorld}
            title={
              pickedWorld
                ? 'Re-centre the plane on the last 3D-picked point'
                : 'Click the bone surface in the 3D view first'
            }
          >
            Centre on 3D pick
          </button>
          <button type="button" className="mpr-wl-reset" onClick={resetPlane}>
            Reset plane
          </button>
        </div>
        <div className="oblique-readout">
          normal (app-frame X/Y/Z) {fmt3(normal)}
          <br />
          origin (mm) {origin ? fmt3(origin) : '—'}
        </div>
    </div>
  );

  if (compareMode) {
    const showFirstCallBanner = firstCallPending && !refImage && !tgtImage;
    return (
      <div className="mpr-wrap oblique-wrap oblique-compare-wrap">
        {registration && (
          <div
            className={`compare-banner ${registration.reliable ? 'reliable' : 'unreliable'}`}
          >
            {registration.reliable ? (
              <>
                <strong>Registration reliable.</strong> {registration.note} (rms{' '}
                {registration.rms_mm} mm · inlier fraction{' '}
                {registration.inlier_fraction})
              </>
            ) : (
              <>
                <strong>
                  Registration UNRELIABLE — the target box is not a trustworthy match.
                </strong>{' '}
                {registration.note} (rms {registration.rms_mm} mm · inlier fraction{' '}
                {registration.inlier_fraction})
              </>
            )}
          </div>
        )}
        {showFirstCallBanner && (
          <div className="compare-banner pending">
            Registering & sampling both bones… the first match for this pair of
            sides can take ~1–2 minutes; the plane will re-sample quickly after
            that.
          </div>
        )}
        {sliceError && (
          <div className="compare-banner unreliable">
            <strong>Could not fetch the matched reformat.</strong> {sliceError}
          </div>
        )}

        <div className="oblique-compare-grid">
          <div className="compare-pane">
            <div className="compare-pane-label">Reference bone</div>
            <div
              className="mpr-image-box oblique-image-box"
              ref={imgBoxRef}
              onMouseDown={onImageClick}
              title="Click the reformat to move the 3D marker to that exact point"
            >
              {refImage ? (
                <>
                  <img
                    ref={imgElRef}
                    className="mpr-image"
                    src={refImage.url}
                    alt="Reference bone oblique reformat"
                    draggable={false}
                    onLoad={recalcRect}
                  />
                  {rect && (
                    <>
                      <div
                        className="mpr-crosshair-v"
                        style={{ left: `${rect.left + rect.w / 2}px`, top: `${rect.top}px`, height: `${rect.h}px` }}
                      />
                      <div
                        className="mpr-crosshair-h"
                        style={{ top: `${rect.top + rect.h / 2}px`, left: `${rect.left}px`, width: `${rect.w}px` }}
                      />
                      <div
                        className="mpr-crosshair-dot"
                        style={{ left: `${rect.left + rect.w / 2}px`, top: `${rect.top + rect.h / 2}px` }}
                      />
                    </>
                  )}
                </>
              ) : (
                <div className="oblique-empty">
                  {loading ? 'Registering & sampling both bones…' : 'No reformat yet'}
                </div>
              )}
              {loading && refImage && (
                <div className="oblique-loading-badge">Updating…</div>
              )}
            </div>
          </div>

          <div className="compare-pane">
            <div className="compare-pane-label">
              Target bone
              {registration && !registration.reliable && (
                <span className="compare-pane-warn"> · unreliable match</span>
              )}
            </div>
            <div
              className="mpr-image-box oblique-image-box"
              ref={tgtImgBoxRef}
              onMouseDown={onTgtImageClick}
              title="Best-effort click: shows this bone's matched centre crosshair"
            >
              {tgtImage ? (
                <>
                  <img
                    ref={tgtImgElRef}
                    className="mpr-image"
                    src={tgtImage.url}
                    alt="Target bone oblique reformat"
                    draggable={false}
                    onLoad={recalcTgtRect}
                  />
                  {tgtRect && (
                    <>
                      <div
                        className="mpr-crosshair-v"
                        style={{ left: `${tgtRect.left + tgtRect.w / 2}px`, top: `${tgtRect.top}px`, height: `${tgtRect.h}px` }}
                      />
                      <div
                        className="mpr-crosshair-h"
                        style={{ top: `${tgtRect.top + tgtRect.h / 2}px`, left: `${tgtRect.left}px`, width: `${tgtRect.w}px` }}
                      />
                      <div
                        className="mpr-crosshair-dot"
                        style={{ left: `${tgtRect.left + tgtRect.w / 2}px`, top: `${tgtRect.top + tgtRect.h / 2}px` }}
                      />
                    </>
                  )}
                </>
              ) : (
                <div className="oblique-empty">
                  {loading ? 'Registering & sampling both bones…' : 'No reformat yet'}
                </div>
              )}
              {loading && tgtImage && (
                <div className="oblique-loading-badge">Updating…</div>
              )}
            </div>
          </div>
        </div>

        {controlsPanel}

        <div className="mpr-note">
          Array-oriented plane (app-frame X/Y/Z tilt, not verified radiological
          orientation — never A/P/S/I or laterality). ONE movable plane on the
          reference bone is mapped through the cached registration onto the
          target bone. Research / de-identified / not for diagnosis.
        </div>
      </div>
    );
  }

  return (
    <div className="mpr-wrap oblique-wrap">
      {controlsPanel}

      <div
        className="mpr-image-box oblique-image-box"
        ref={imgBoxRef}
        onMouseDown={onImageClick}
        title="Click the reformat to move the 3D marker to that exact point"
      >
        {image ? (
          <>
            <img
              ref={imgElRef}
              className="mpr-image"
              src={image.url}
              alt="Oblique reformat"
              draggable={false}
              onLoad={recalcRect}
            />
            {rect && (
              <>
                <div
                  className="mpr-crosshair-v"
                  style={{ left: `${rect.left + rect.w / 2}px`, top: `${rect.top}px`, height: `${rect.h}px` }}
                />
                <div
                  className="mpr-crosshair-h"
                  style={{ top: `${rect.top + rect.h / 2}px`, left: `${rect.left}px`, width: `${rect.w}px` }}
                />
                <div
                  className="mpr-crosshair-dot"
                  style={{ left: `${rect.left + rect.w / 2}px`, top: `${rect.top + rect.h / 2}px` }}
                />
              </>
            )}
          </>
        ) : (
          <div className="oblique-empty">
            {loading ? 'Sampling the reformat…' : 'No reformat yet'}
          </div>
        )}
        {loading && image && <div className="oblique-loading-badge">Updating…</div>}
      </div>

      {sliceError && (
        <div className="viewport-error oblique-error">
          <strong>Could not fetch the reformat.</strong> {sliceError}
        </div>
      )}

      <div className="mpr-note">
        Array-oriented plane (app-frame X/Y/Z tilt, not verified radiological
        orientation — never A/P/S/I or laterality). Research / de-identified /
        not for diagnosis.
      </div>
    </div>
  );
}
