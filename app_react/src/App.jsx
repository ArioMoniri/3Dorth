// React + vtk.js root for 3Dorth. Layout:
//   top bar (title + Mode A / Mode B toggle + Share / Switch-UI controls)
//   LEFT panel  — scan/upload, side selector, Mode-B sub-toggle, region selector,
//                 Apply/Recompute, manual anchor (Mode B), export, then the
//                 registry-driven parameter panel
//   CENTER      — vtk.js viewport showing the LAST computed geometry, with a
//                 hover tooltip reading the picked point's scalar
//   RIGHT       — HTML color legend + returned stats
//
// Session model: on mount we GET /api/config, GET /api/parameters and POST
// /api/session. The side selector is driven purely from session.sides, so a
// single-sided scan (['full']), a bilateral scan (['left','right']) and a mesh
// upload (['mesh']) all render correctly without assuming humerus/bilateral.
//
// Parity rule: the parameter panel is generated purely by iterating the controls
// returned from /api/parameters. No parameter list is hardcoded.

import { useEffect, useMemo, useRef, useState } from 'react';

import {
  fetchConfig,
  fetchParameters,
  createSession,
  uploadFile,
  analyze,
  compare,
  exportResult,
  fetchRegionThumbnails,
  pickToSlices,
} from './api';
import ControlPanel from './ControlPanel';
import Viewport from './Viewport';
import MPRViewer from './mpr/MPRViewer';
import CompareView from './CompareView';
import ObliqueView from './ObliqueView';
import ArModal from './ArModal';
import Legend from './Legend';
import StatsPanel from './StatsPanel';
import StatsFigures from './StatsFigures';
import DraggablePanel from './DraggablePanel';
import ShareSwitch from './ShareSwitch';
import HoverTooltip from './HoverTooltip';
import ClipPanel from './ClipPanel';
import { buildManualTransform } from './ManualAnchor';
import { computeMaskedStats } from './clipStats';

const ZERO_NUDGE = { tx: 0, ty: 0, tz: 0, rx: 0, ry: 0, rz: 0 };
const DEFAULT_CAMERA = { azimuth: 0, elevation: 0, roll: 0, zoom: 1 };

export default function App() {
  const [config, setConfig] = useState(null);
  const [session, setSession] = useState(null);
  const [allControls, setAllControls] = useState([]); // full registry (all modes)
  const [defaults, setDefaults] = useState({});
  const [values, setValues] = useState({});
  const [mode, setMode] = useState('A');
  const [modeBView, setModeBView] = useState('thickness'); // 'thickness' | 'deviation'
  const [error, setError] = useState(null);

  // Side selection + deviation reference/target.
  const [side, setSide] = useState(null);
  const [referenceSide, setReferenceSide] = useState(null);
  const [targetSide, setTargetSide] = useState(null);
  const [mirror, setMirror] = useState(true);

  // Region selection (analyze returns the list of connected regions).
  const [regionLabel, setRegionLabel] = useState(null);

  // Region thumbnails (visual picker). Fetched lazily and cached per
  // (session_id, side) so switching side / re-opening doesn't re-render.
  const [regionThumbs, setRegionThumbs] = useState(null);
  const [regionThumbsLoading, setRegionThumbsLoading] = useState(false);
  const [regionThumbsError, setRegionThumbsError] = useState(null);
  const thumbCacheRef = useRef(new Map()); // key `${sid}|${side}` -> thumbnails[]

  // Manual anchor nudge (Mode B deviation).
  const [nudge, setNudge] = useState(ZERO_NUDGE);

  // Export state.
  const [formats, setFormats] = useState(() => new Set(['png']));
  const [dpi, setDpi] = useState(150);
  // Fig-2 measurement annotations for the RASTER export (auto-placed at the
  // surgical-neck / lesser-tuberosity base). Sampled thickness is read off the
  // computed scalar server-side (never fabricated); the annotated figure is
  // descriptive / single-subject.
  const [annotateLine, setAnnotateLine] = useState(false);
  const [annotateHeight, setAnnotateHeight] = useState(false);
  const [camera, setCamera] = useState(DEFAULT_CAMERA);
  const [exporting, setExporting] = useState(false);
  const [exportFiles, setExportFiles] = useState(null);
  const [exportError, setExportError] = useState(null);

  // Hover tooltip.
  const [hover, setHover] = useState(null);

  // The active scalar's full per-vertex array (thickness_mm or deviation_mm),
  // read straight from the loaded polydata by Viewport — powers the Stats
  // panel distribution histogram with no extra API call.
  const [scalarValues, setScalarValues] = useState(null);

  // ---- clip / isolate (Feature 3) -------------------------------------------
  // `meshBounds` — [xmin,xmax,ymin,ymax,zmin,zmax] of the CURRENTLY loaded
  // geometry, reported by Viewport straight from the parsed polydata.
  // `clipEnabled` — the toggle. `clipBox` — the adjustable box (same 6-tuple
  // shape as an object); null while the toggle is off (whole mesh visible).
  // `visibleMask` — Uint8Array (1 = inside the box), reported by Viewport, same
  // order as `scalarValues` — lets us recompute stats for just the seen part.
  const [meshBounds, setMeshBounds] = useState(null);
  const [clipEnabled, setClipEnabled] = useState(false);
  const [clipBox, setClipBox] = useState(null);
  const [visibleMask, setVisibleMask] = useState(null);

  // ---- MPR image viewer -----------------------------------------------------
  // Center-area toggle between the 3D map, the linked MPR slices, the linked
  // compare cross-sections (Phase IV), and the arbitrary oblique cross-section
  // (Phase VII).
  const [centerView, setCenterView] = useState('map'); // 'map' | 'images' | 'compare' | 'oblique'
  // AR / 3D modal (Phase V).
  const [arOpen, setArOpen] = useState(false);
  // A 3D-pick crosshair pushed into the MPR (voxel {ix,iy,iz}); bumped so the
  // MPR adopts it even when the same voxel is picked twice.
  const [pickedCrosshair, setPickedCrosshair] = useState(null);
  // World point of the linked crosshair -> the 3D sphere marker. Set both by a
  // 3D pick and by MPR scrubbing/clicking (voxel->world from volume-info).
  const [marker, setMarker] = useState(null); // { x, y, z } | null
  // The current oblique plane { origin:[x,y,z], normal:[x,y,z], sizeMm } pushed
  // up by ObliqueView so the 3D Viewport can draw the matching translucent cut.
  const [obliquePlane, setObliquePlane] = useState(null);
  // Grab-to-slide: the 3D Viewport reports incremental drags of the cutting plane
  // (mm along its normal); ObliqueView consumes each (seq-keyed) nudge to move the
  // plane, so dragging the blue plane == the Position slider.
  const [planeNudge, setPlaneNudge] = useState(null);
  const planeNudgeSeqRef = useRef(0);

  // Compute state + last results.
  const [computing, setComputing] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [computeError, setComputeError] = useState(null);
  // `geometry` holds ONLY the server-computed geometry payload (url + scalar
  // array name). The DISPLAY-ONLY coloring (colormap / range / steps / reverse)
  // is layered on top client-side in `displayGeometry` (see below), so changing
  // a display param re-colours instantly with NO server round-trip.
  const [geometry, setGeometry] = useState(null); // {url, scalar}
  const [thicknessResult, setThicknessResult] = useState(null);
  const [deviationResult, setDeviationResult] = useState(null);
  // The bilateral "Both" view: when side === 'both' we compute BOTH sides and
  // render two meshes together. `secondGeometry` holds the SECOND side's server
  // geometry payload (colored client-side in `secondDisplayGeometry`).
  const [secondGeometry, setSecondGeometry] = useState(null); // {url, scalar} | null

  // Monotonic request-id guard: every compute bumps this; a response is applied
  // only if it is still the latest request when it resolves, so a slow older
  // compute can never clobber a newer one (supersede in-flight/pending).
  const requestIdRef = useRef(0);
  // Debounce timer for auto-recompute.
  const debounceRef = useRef(null);
  // Skip the very first auto-recompute pass (nothing computed yet on mount /
  // right after a session swap — the user hasn't asked for anything).
  const autoReadyRef = useRef(false);

  // ---- load config + registry + open a session -----------------------------
  useEffect(() => {
    Promise.all([fetchConfig(), fetchParameters(), createSession()])
      .then(([cfg, params, sess]) => {
        setConfig(cfg);
        setAllControls(params.controls);
        setDefaults(params.defaults);
        setValues(params.defaults); // seed EVERY key from the paper defaults
        applySession(sess);
      })
      .catch((e) => setError(String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const isMesh = Boolean(session?.is_mesh) || session?.sides?.[0] === 'mesh';
  const isSingleSided = session?.sides?.length === 1 && !isMesh;
  // Bilateral "Both" view: render left + right together. Only offered when the
  // scan actually has both sides (a real bilateral volume, not a mesh).
  const canShowBoth =
    !isMesh &&
    Boolean(session?.is_bilateral) &&
    (session?.sides || []).includes('left') &&
    (session?.sides || []).includes('right');
  const isBoth = side === 'both';
  // Wherever a CONCRETE side is needed (MPR, region thumbnails, pick-to-slices),
  // 'both' falls back to the primary (left) side.
  const effectiveSide = isBoth ? 'left' : side;
  // Phase IV compare view needs TWO real volume sides (left+right), not a mesh.
  const canCompareSides =
    !isMesh &&
    Boolean(session?.is_bilateral) &&
    (session?.sides || []).includes('left') &&
    (session?.sides || []).includes('right');

  function applySession(sess) {
    setSession(sess);
    const sides = sess.sides || [];
    setSide(sides[0] ?? null);
    setReferenceSide(sides[0] ?? null);
    setTargetSide(sides[1] ?? sides[0] ?? null);
    setRegionLabel(null);
    setNudge(ZERO_NUDGE);
    // A new scan invalidates any cached region previews.
    thumbCacheRef.current = new Map();
    setRegionThumbs(null);
    setRegionThumbsLoading(false);
    setRegionThumbsError(null);
    // A mesh session can't produce a thickness map; force Mode B (deviation).
    if (sess.is_mesh || sess.sides?.[0] === 'mesh') {
      setMode('B');
      setModeBView('deviation');
    }
    // A fresh scan invalidates prior geometry/results.
    setGeometry(null);
    setSecondGeometry(null);
    setThicknessResult(null);
    setDeviationResult(null);
    setComputeError(null);
    setExportFiles(null);
    setExportError(null);
    setMarker(null);
    setObliquePlane(null);
    setScalarValues(null);
    // A fresh scan/mesh invalidates the previous clip box (different geometry
    // extent) — the "Reset clip" bounds re-seed from the new mesh's own bounds
    // once Viewport reports them.
    setMeshBounds(null);
    setClipEnabled(false);
    setClipBox(null);
    setVisibleMask(null);
  }

  // Controls shown for the active mode (mode-specific + 'both'). We keep EVERY
  // value in state; we just display the subset relevant to the active mode.
  const modeControls = useMemo(
    () => allControls.filter((c) => c.mode === mode || c.mode === 'both'),
    [allControls, mode],
  );

  const onParamChange = (key, v) =>
    setValues((prev) => ({ ...prev, [key]: v }));
  const resetDefaults = () => setValues(defaults);

  // Keys whose change REQUIRES re-running the pipeline. Taken straight from the
  // registry's `recompute` flag (parity: nothing hardcoded). Display-only keys
  // (recompute=false: colormap / range / steps / reverse / standardized_view)
  // are deliberately excluded so they never trigger a server call.
  const recomputeKeys = useMemo(
    () => allControls.filter((c) => c.recompute).map((c) => c.key),
    [allControls],
  );

  // A stable signature of everything that affects the COMPUTED result: the
  // recompute=true param values for the active mode, plus the side / mode /
  // Mode-B view / reference & target sides / mirror / manual-anchor transform.
  // When this string changes, an auto-recompute is scheduled (debounced). It is
  // intentionally independent of every display-only param.
  const manualTransform = useMemo(
    () => buildManualTransform(nudge),
    [nudge],
  );

  const computeSignature = useMemo(() => {
    const relevant = {};
    recomputeKeys.forEach((k) => {
      relevant[k] = values[k];
    });
    return JSON.stringify({
      mode,
      modeBView,
      side,
      referenceSide,
      targetSide,
      mirror,
      isMesh,
      manualTransform,
      // Selecting a different region (via the dropdown OR a thumbnail) must
      // re-run analyze so the map switches to that structure. Only affects
      // Mode A thickness (deviation ignores region_label).
      regionLabel,
      params: relevant,
    });
  }, [
    recomputeKeys,
    values,
    mode,
    modeBView,
    side,
    referenceSide,
    targetSide,
    mirror,
    isMesh,
    manualTransform,
    regionLabel,
  ]);

  // Is the current view a deviation view?
  const isDeviationView = (mode === 'B' && modeBView === 'deviation') || isMesh;

  // If the server dropped our session (it restarted / evicted our id), open a
  // fresh one and ADOPT it: its sides may differ from the old session's, so we
  // reset the side selector and return the fresh session for the retry to read
  // a valid side from. Returns { sessionId, sides }.
  async function ensureSession() {
    const fresh = await createSession();
    applySession(fresh);
    return fresh;
  }

  // ---- primary actions ------------------------------------------------------
  // Both compute actions are guarded by a monotonic request id. On entry each
  // bumps `requestIdRef` and captures its own `myId`; after every await it checks
  // `requestIdRef.current === myId` before mutating any state, so a stale (older
  // or superseded) response can never overwrite a newer one. `computing` is only
  // cleared by the request that is still the latest, so the indicator reflects
  // the in-flight compute, not a stale one that just resolved.
  async function runAnalyze() {
    if (!session || !side || isMesh) return;
    // The bilateral "Both" view has its own (two-compute) path.
    if (isBoth) return runAnalyzeBoth();
    const myId = (requestIdRef.current += 1);
    setComputing(true);
    setComputeError(null);
    try {
      let sid = session.session_id;
      const args = { side, params: values, regionLabel };
      let res;
      try {
        res = await analyze(sid, args);
      } catch (e) {
        if (e?.status === 404) {
          if (requestIdRef.current !== myId) return;
          const fresh = await ensureSession();
          sid = fresh.session_id;
          // The fresh session may expose different sides; pick a valid one.
          const validSide = fresh.sides?.includes(side)
            ? side
            : fresh.sides?.[0];
          res = await analyze(sid, { ...args, side: validSide });
        } else {
          throw e;
        }
      }
      if (requestIdRef.current !== myId) return; // superseded — drop stale result
      setThicknessResult(res);
      setSecondGeometry(null); // single-side view — no second mesh
      // Adopt the server's chosen region so the selector reflects reality.
      // Use the functional form and only change when it actually differs, so
      // adopting the auto-picked region does NOT spuriously bump the compute
      // signature (which now includes regionLabel) and cause a redundant run.
      if (res.region_label != null) {
        setRegionLabel((prev) => (prev === res.region_label ? prev : res.region_label));
      }
      setGeometryFromThickness(res);
    } catch (e) {
      if (requestIdRef.current === myId) setComputeError(readableError(e));
    } finally {
      if (requestIdRef.current === myId) setComputing(false);
    }
  }

  // Bilateral "Both": run analyze for LEFT then RIGHT (whole bone each — the
  // region selector is hidden in Both, so no region_label is sent) and render
  // the two thickness meshes together. The primary result (left) drives the
  // stats / legend / figures exactly like a single side; the right side is
  // rendered as the second mesh. Guarded by the same request-id supersede rule.
  async function runAnalyzeBoth() {
    const myId = (requestIdRef.current += 1);
    setComputing(true);
    setComputeError(null);
    try {
      let sid = session.session_id;
      const call = (s, side_) => analyze(s, { side: side_, params: values });
      let left;
      let right;
      try {
        [left, right] = await Promise.all([call(sid, 'left'), call(sid, 'right')]);
      } catch (e) {
        if (e?.status === 404) {
          if (requestIdRef.current !== myId) return;
          const fresh = await ensureSession();
          sid = fresh.session_id;
          [left, right] = await Promise.all([call(sid, 'left'), call(sid, 'right')]);
        } else {
          throw e;
        }
      }
      if (requestIdRef.current !== myId) return; // superseded — drop stale result
      setThicknessResult(left);
      setGeometry({ url: left.geometry_url, scalar: left.scalar });
      setSecondGeometry({ url: right.geometry_url, scalar: right.scalar });
    } catch (e) {
      if (requestIdRef.current === myId) setComputeError(readableError(e));
    } finally {
      if (requestIdRef.current === myId) setComputing(false);
    }
  }

  async function runCompare() {
    if (!session || referenceSide === targetSide) return;
    const myId = (requestIdRef.current += 1);
    setComputing(true);
    setComputeError(null);
    try {
      const params = { ...values, mirror_sagittal: mirror };
      let sid = session.session_id;
      const args = { referenceSide, targetSide, params, manualTransform };
      let res;
      try {
        res = await compare(sid, args);
      } catch (e) {
        if (e?.status === 404) {
          if (requestIdRef.current !== myId) return;
          const fresh = await ensureSession();
          sid = fresh.session_id;
          const sides = fresh.sides || [];
          const ref = sides.includes(referenceSide) ? referenceSide : sides[0];
          const tgt = sides.includes(targetSide)
            ? targetSide
            : sides[1] ?? sides[0];
          res = await compare(sid, { ...args, referenceSide: ref, targetSide: tgt });
        } else {
          throw e;
        }
      }
      if (requestIdRef.current !== myId) return; // superseded — drop stale result
      setDeviationResult(res);
      setSecondGeometry(null); // deviation is a single registered surface
      setGeometryFromDeviation(res);
    } catch (e) {
      if (requestIdRef.current === myId) setComputeError(readableError(e));
    } finally {
      if (requestIdRef.current === myId) setComputing(false);
    }
  }

  function swapSides() {
    setReferenceSide(targetSide);
    setTargetSide(referenceSide);
  }

  // The side the MPR slices. A deviation view shows the reference side's volume
  // (the frame the picks live in); otherwise the selected analyze side. A mesh
  // upload has no volume to slice.
  const mprSide = isMesh ? null : isDeviationView ? referenceSide : effectiveSide;

  // ---- 3D pick -> MPR crosshair --------------------------------------------
  // Clicking the mesh surface hands us a world point; we POST pick-to-slices to
  // convert it to voxel indices (the SAME arithmetic the trame path uses), push
  // that crosshair into the MPR, place the 3D marker, and reveal the images.
  const pickSeqRef = useRef(0);
  async function onSurfacePick(worldXyz) {
    // Clip / isolate: when the clip box is on (single side only), clicking the
    // surface RE-CENTRES the box on the picked part so you can "click the bit you
    // want" instead of nudging six sliders. Keeps the box's current size if you
    // already shrank it; otherwise seeds a sensible sub-region around the pick.
    // Done FIRST so it works even for mesh uploads (no MPR side) — the guard below
    // only gates the MPR crosshair round-trip, not the clip.
    if (clipEnabled && !isBoth && meshBounds) {
      const nextBox = clipBoxFromPick(worldXyz);
      if (nextBox) setClipBox(nextBox);
    }
    // Show the marker at the exact picked point (no round-trip lag).
    setMarker({ x: worldXyz[0], y: worldXyz[1], z: worldXyz[2] });
    if (!session || !mprSide) return;
    try {
      const res = await pickToSlices(session.session_id, {
        side: mprSide,
        worldXyz,
      });
      const ijk = res.voxel_ijk;
      // Bump a sequence field so an identical voxel still triggers the MPR's
      // adopt effect (which keys on ix/iy/iz).
      pickSeqRef.current += 1;
      setPickedCrosshair({
        ix: ijk[0],
        iy: ijk[1],
        iz: ijk[2],
        _seq: pickSeqRef.current,
      });
    } catch {
      // Session may have been evicted; a subsequent compute re-opens one. The
      // marker still shows the picked point, so the click isn't silently lost.
    }
  }

  // MPR scrub/click -> move the 3D marker (voxel already converted to world by
  // the MPR from volume-info, so no server round-trip).
  const onMprCrosshair = (_vox, world) => {
    setMarker({ x: world[0], y: world[1], z: world[2] });
  };

  // Oblique 2D panel click -> move the 3D marker (world point computed
  // CLIENT-SIDE, exactly, from the returned oblique-slice meta — see
  // ObliqueView/obliquePixelToWorld — no server round-trip needed).
  const onObliquePixelPick = (world) => {
    setMarker({ x: world[0], y: world[1], z: world[2] });
  };

  // Run whichever compute matches the current view, if its preconditions hold.
  // Deviation view -> compare (needs two distinct sides); otherwise -> analyze
  // (needs a side, non-mesh). Returns true if a compute was actually started.
  function runActiveCompute() {
    if (isDeviationView) {
      if (!session || referenceSide === targetSide) return false;
      runCompare();
      return true;
    }
    if (!session || !side || isMesh) return false;
    runAnalyze();
    return true;
  }

  // Keep a ref to the latest action so the debounce effect can call it without
  // depending on the function's changing identity (which would re-fire the
  // effect on every render). The effect depends ONLY on `computeSignature`.
  const runActiveComputeRef = useRef(runActiveCompute);
  runActiveComputeRef.current = runActiveCompute;

  // ---- debounced AUTO-RECOMPUTE --------------------------------------------
  // Whenever the compute signature changes (a recompute=true param, side, mode,
  // Mode-B view, reference/target side, mirror, or the manual-anchor transform),
  // wait ~600 ms after the LAST change and then fire exactly one compute. Rapid
  // changes (dragging a slider) coalesce into a single request; the request-id
  // guard inside runAnalyze/runCompare supersedes any older in-flight compute so
  // a stale response can never clobber the latest. Display-only param changes do
  // not appear in the signature, so they never reach here.
  useEffect(() => {
    // Skip the initial pass: on mount / right after a session swap there is
    // nothing to recompute until the signature actually changes.
    if (!autoReadyRef.current) {
      autoReadyRef.current = true;
      return undefined;
    }
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      debounceRef.current = null;
      runActiveComputeRef.current();
    }, 600);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [computeSignature]);

  async function onUpload(file) {
    setUploading(true);
    setComputeError(null);
    try {
      const sess = await uploadFile(file);
      applySession(sess);
    } catch (e) {
      setComputeError(`Upload failed: ${readableError(e)}`);
    } finally {
      setUploading(false);
    }
  }

  // ---- region thumbnails (visual picker) -----------------------------------
  // Lazily fetch the per-region rendered previews for (session, side) and cache
  // them. The server render takes ~5-10 s; we show a spinner while it runs and
  // never re-fetch a cached (session_id, side) pair.
  async function loadRegionThumbnails(sid, activeSide) {
    if (!sid || !activeSide) return;
    const cacheKey = `${sid}|${activeSide}`;
    const cached = thumbCacheRef.current.get(cacheKey);
    if (cached) {
      setRegionThumbs(cached);
      setRegionThumbsLoading(false);
      setRegionThumbsError(null);
      return;
    }
    setRegionThumbsLoading(true);
    setRegionThumbsError(null);
    setRegionThumbs(null);
    try {
      const res = await fetchRegionThumbnails(sid, activeSide);
      const thumbs = res.thumbnails || [];
      thumbCacheRef.current.set(cacheKey, thumbs);
      // Guard against a session/side swap while this was in flight.
      if (session?.session_id === sid && side === activeSide) {
        setRegionThumbs(thumbs);
      }
    } catch (e) {
      if (session?.session_id === sid && side === activeSide) {
        setRegionThumbsError(readableError(e));
      }
    } finally {
      if (session?.session_id === sid && side === activeSide) {
        setRegionThumbsLoading(false);
      }
    }
  }

  // Trigger the lazy thumbnail load right after the first analyze for the active
  // side has produced a result (a mesh/volume side with regions). Deviation and
  // mesh sessions have no per-region volume previews, so we skip them. A cached
  // (session, side) pair resolves instantly from loadRegionThumbnails.
  useEffect(() => {
    if (isDeviationView || isMesh) return;
    // The 'both' view hides the region picker (whole-bone per side), so skip
    // the (slow) per-region preview render there.
    if (isBoth) return;
    if (!session?.session_id || !side) return;
    if (!thicknessResult) return; // wait for the first analyze on this side
    loadRegionThumbnails(session.session_id, side);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.session_id, side, isDeviationView, isMesh, isBoth, Boolean(thicknessResult)]);

  // ---- realtime public-URL polling -----------------------------------------
  // Poll GET /api/config every ~6 s so the Share panel reflects a tunnel that
  // scripts/share.sh (re)starts after sleep/wake — without a page reload. Only
  // update state when something actually changed to avoid needless re-renders.
  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const cfg = await fetchConfig();
        if (cancelled) return;
        setConfig((prev) => {
          if (
            prev &&
            prev.public === cfg.public &&
            prev.react_url === cfg.react_url &&
            prev.trame_url === cfg.trame_url
          ) {
            return prev; // unchanged — keep the same reference
          }
          return cfg;
        });
      } catch {
        // Transient failure (server restarting) — keep the last known config.
      }
    };
    const id = setInterval(tick, 6000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  // ---- export ---------------------------------------------------------------
  function toggleFormat(f) {
    setFormats((prev) => {
      const next = new Set(prev);
      if (next.has(f)) next.delete(f);
      else next.add(f);
      return next;
    });
  }

  async function runExport() {
    if (!session || formats.size === 0) return;
    setExporting(true);
    setExportError(null);
    setExportFiles(null);
    try {
      const exportMode = isDeviationView ? 'B' : 'A';
      const params =
        exportMode === 'B' ? { ...values, mirror_sagittal: mirror } : values;
      const args = {
        mode: exportMode,
        params,
        formats: [...formats],
        dpi,
        camera,
      };
      // Fig-2 overlays (auto-placed). Only send fields that are enabled; omit
      // `annotate` entirely when neither is on (backward-compatible plain export).
      if (annotateLine || annotateHeight) {
        const annotate = {};
        if (annotateLine) annotate.sampling_line = true;
        if (annotateHeight) annotate.height = true;
        args.annotate = annotate;
      }
      if (exportMode === 'B') {
        args.referenceSide = referenceSide;
        args.targetSide = targetSide;
        args.manualTransform = manualTransform;
      } else {
        // Raster/mesh export renders ONE surface; in the bilateral 'both' view
        // we export the primary (left) side. (The two-mesh scene is a live
        // viewing aid; a combined figure export is out of scope for the API.)
        args.side = effectiveSide;
        if (!isBoth && regionLabel != null) args.regionLabel = regionLabel;
      }
      let sid = session.session_id;
      let res;
      try {
        res = await exportResult(sid, args);
      } catch (e) {
        if (e?.status === 404) {
          const fresh = await ensureSession();
          sid = fresh.session_id;
          const sides = fresh.sides || [];
          const retry = { ...args };
          if (exportMode === 'B') {
            retry.referenceSide = sides.includes(referenceSide)
              ? referenceSide
              : sides[0];
            retry.targetSide = sides.includes(targetSide)
              ? targetSide
              : sides[1] ?? sides[0];
          } else {
            retry.side = sides.includes(side) ? side : sides[0];
          }
          res = await exportResult(sid, retry);
        } else {
          throw e;
        }
      }
      setExportFiles(res.files || {});
    } catch (e) {
      setExportError(readableError(e));
    } finally {
      setExporting(false);
    }
  }

  // Keep the viewport showing whatever matches the current view.
  useEffect(() => {
    if (isDeviationView) {
      setSecondGeometry(null); // deviation never shows a second mesh
      if (deviationResult) setGeometryFromDeviation(deviationResult);
      else setGeometry(null);
    } else if (thicknessResult && !isBoth) {
      // Single-side thickness: restore its geometry. In the 'both' view the
      // debounced auto-recompute (or the primary button) repopulates both
      // meshes, so we leave the two geometries in place here.
      setSecondGeometry(null);
      setGeometryFromThickness(thicknessResult);
    } else if (!thicknessResult) {
      setGeometry(null);
      setSecondGeometry(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isDeviationView]);

  // Store ONLY the geometry payload (mesh url + scalar array name). The coloring
  // is derived from the current display params in `displayGeometry`, so a
  // colormap / range / steps / reverse change re-colours instantly client-side.
  function setGeometryFromThickness(res) {
    setGeometry({ url: res.geometry_url, scalar: res.scalar });
  }
  function setGeometryFromDeviation(res) {
    setGeometry({ url: res.geometry_url, scalar: res.scalar });
  }

  // ---- clip / isolate (Feature 3) -------------------------------------------
  // Viewport reports the freshly-loaded polydata's real bounds every time the
  // geometry URL changes (a recompute always produces a new mesh). We track
  // the bounds so ClipPanel can seed its sliders, and if a clip box is already
  // active we RE-SEED it to the new mesh's bounds too (a stale box from a
  // previous, differently-sized mesh would clip nonsensically).
  const lastBoundsUrlRef = useRef(null);
  function onViewportBounds(b) {
    if (!b) return;
    const [xmin, xmax, ymin, ymax, zmin, zmax] = b;
    setMeshBounds(b);
    if (lastBoundsUrlRef.current !== geometry?.url) {
      lastBoundsUrlRef.current = geometry?.url;
      if (clipEnabled) {
        setClipBox({ xmin, xmax, ymin, ymax, zmin, zmax });
      }
    }
  }

  function onToggleClip(next) {
    setClipEnabled(next);
    if (next && meshBounds) {
      const [xmin, xmax, ymin, ymax, zmin, zmax] = meshBounds;
      setClipBox((prev) => prev || { xmin, xmax, ymin, ymax, zmin, zmax });
    } else if (!next) {
      setClipBox(null);
      setVisibleMask(null);
    }
  }

  function onResetClip() {
    if (!meshBounds) return;
    const [xmin, xmax, ymin, ymax, zmin, zmax] = meshBounds;
    setClipBox({ xmin, xmax, ymin, ymax, zmin, zmax });
  }

  // Build a clip box centred on a picked world point. Preserves the current box
  // SIZE per axis if the user already shrank it (so "click to reposition" keeps
  // the isolation size); otherwise seeds a default sub-region (40% of each axis
  // extent) around the pick. Always clamped to the real mesh bounds.
  function clipBoxFromPick(worldXyz) {
    if (!meshBounds) return null;
    const [xmin, xmax, ymin, ymax, zmin, zmax] = meshBounds;
    const lo = [xmin, ymin, zmin];
    const hi = [xmax, ymax, zmax];
    const DEFAULT_FRAC = 0.4;
    const cur = clipBox;
    // Is the current box effectively "the whole mesh" (nothing isolated yet)?
    const eps = 1e-3;
    const full =
      !cur ||
      (cur.xmin <= xmin + eps && cur.xmax >= xmax - eps &&
        cur.ymin <= ymin + eps && cur.ymax >= ymax - eps &&
        cur.zmin <= zmin + eps && cur.zmax >= zmax - eps);
    const curHalf = cur
      ? [(cur.xmax - cur.xmin) / 2, (cur.ymax - cur.ymin) / 2, (cur.zmax - cur.zmin) / 2]
      : [0, 0, 0];
    const out = {};
    const keys = ['x', 'y', 'z'];
    for (let a = 0; a < 3; a += 1) {
      const ext = hi[a] - lo[a];
      const half = full ? (ext * DEFAULT_FRAC) / 2 : curHalf[a];
      let cmin = worldXyz[a] - half;
      let cmax = worldXyz[a] + half;
      // Clamp to bounds, keeping the box on-mesh.
      if (cmin < lo[a]) { cmin = lo[a]; cmax = Math.min(hi[a], lo[a] + 2 * half); }
      if (cmax > hi[a]) { cmax = hi[a]; cmin = Math.max(lo[a], hi[a] - 2 * half); }
      out[`${keys[a]}min`] = cmin;
      out[`${keys[a]}max`] = cmax;
    }
    return out;
  }

  const totalVertexCount = scalarValues ? scalarValues.length : null;
  const visibleVertexCount = useMemo(() => {
    if (!visibleMask) return null;
    let c = 0;
    for (let i = 0; i < visibleMask.length; i += 1) if (visibleMask[i]) c += 1;
    return c;
  }, [visibleMask]);
  const visiblePct =
    Number.isFinite(visibleVertexCount) && Number.isFinite(totalVertexCount) && totalVertexCount > 0
      ? (visibleVertexCount / totalVertexCount) * 100
      : null;

  // The "Visible part (clipped)" stats block: same shape as the server's stats
  // dict, computed client-side over ONLY the vertices inside the current clip
  // box, from the same per-vertex scalar array already on the loaded surface.
  const clipStats = useMemo(() => {
    if (!clipEnabled || !clipBox || !visibleMask || !scalarValues) return null;
    return computeMaskedStats(scalarValues, visibleMask);
  }, [clipEnabled, clipBox, visibleMask, scalarValues]);

  // Layer the DISPLAY-ONLY coloring (recompute=false params) on top of the
  // server geometry, replicating the server's own scalar_range / steps math
  // (see api/routers/session.py) so the client-side legend and LUT match a
  // recompute exactly — but WITHOUT a server call. Changing any of these keys
  // re-derives this memo synchronously; Viewport + Legend read from it and
  // re-colour instantly.
  const displayGeometry = useMemo(() => {
    if (!geometry) return null;
    if (isDeviationView) {
      const center = Number(values.mode_b_center ?? 0);
      const abs = Number(values.mode_b_range_abs ?? 1);
      return {
        url: geometry.url,
        scalar: geometry.scalar,
        rangeMin: center - abs,
        rangeMax: center + abs,
        steps: Number(values.mode_b_colorbar_steps ?? 11),
        colormap: values.mode_b_colormap ?? 'blue_white_red',
        reverse: false,
      };
    }
    return {
      url: geometry.url,
      scalar: geometry.scalar,
      rangeMin: Number(values.mode_a_range_min ?? 0),
      rangeMax: Number(values.mode_a_range_max ?? 1),
      steps: Number(values.mode_a_colorbar_steps ?? 11),
      colormap: values.mode_a_colormap ?? 'green_yellow_red',
      reverse: Boolean(values.mode_a_colormap_reverse),
    };
  }, [
    geometry,
    isDeviationView,
    values.mode_a_range_min,
    values.mode_a_range_max,
    values.mode_a_colorbar_steps,
    values.mode_a_colormap,
    values.mode_a_colormap_reverse,
    values.mode_b_center,
    values.mode_b_range_abs,
    values.mode_b_colorbar_steps,
    values.mode_b_colormap,
  ]);

  // Coloring for the SECOND bilateral mesh — always a Mode-A thickness surface,
  // sharing the exact display params (colormap / range / steps / reverse) as the
  // primary so both sides read on one legend. Null unless the Both view is live.
  const secondDisplayGeometry = useMemo(() => {
    if (!secondGeometry || isDeviationView) return null;
    return {
      url: secondGeometry.url,
      scalar: secondGeometry.scalar,
      rangeMin: Number(values.mode_a_range_min ?? 0),
      rangeMax: Number(values.mode_a_range_max ?? 1),
      steps: Number(values.mode_a_colorbar_steps ?? 11),
      colormap: values.mode_a_colormap ?? 'green_yellow_red',
      reverse: Boolean(values.mode_a_colormap_reverse),
    };
  }, [
    secondGeometry,
    isDeviationView,
    values.mode_a_range_min,
    values.mode_a_range_max,
    values.mode_a_colorbar_steps,
    values.mode_a_colormap,
    values.mode_a_colormap_reverse,
  ]);

  if (error) {
    return (
      <div className="fatal">
        <h1>Could not reach the 3Dorth API</h1>
        <p>{error}</p>
        <p>
          Start it with:{' '}
          <code>.venv/bin/python -m uvicorn api.main:app --port 8000</code>
        </p>
      </div>
    );
  }

  if (!session || allControls.length === 0) {
    return <div className="loading">Loading registry &amp; opening session…</div>;
  }

  const showDeviationLegend =
    isDeviationView && deviationResult && displayGeometry;
  const showThicknessLegend =
    !isDeviationView && thicknessResult && displayGeometry;
  const activeResult = isDeviationView ? deviationResult : thicknessResult;
  const activeMean = activeResult?.stats?.mean;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          3Dorth <span className="brand-sub">React + vtk.js</span>
        </div>
        <div className="topbar-right">
          <span className="bone-series" title={session.meta?.series}>
            {session.meta?.series}
          </span>
          {!isMesh && (
            <div className="mode-toggle" role="group" aria-label="Analysis mode">
              {['A', 'B'].map((m) => (
                <button
                  key={m}
                  className={mode === m ? 'active' : ''}
                  onClick={() => setMode(m)}
                >
                  Mode {m}
                </button>
              ))}
            </div>
          )}
          <ShareSwitch config={config} />
        </div>
      </header>

      <div className="body">
        <ControlPanel
          session={session}
          isMesh={isMesh}
          isSingleSided={isSingleSided}
          mode={mode}
          controls={modeControls}
          values={values}
          onParamChange={onParamChange}
          onReset={resetDefaults}
          side={side}
          onSideChange={setSide}
          canShowBoth={canShowBoth}
          modeBView={modeBView}
          onModeBViewChange={setModeBView}
          referenceSide={referenceSide}
          targetSide={targetSide}
          onReferenceSideChange={setReferenceSide}
          onTargetSideChange={setTargetSide}
          mirror={mirror}
          onMirrorChange={setMirror}
          regions={thicknessResult?.regions || null}
          regionLabel={regionLabel}
          onRegionChange={setRegionLabel}
          regionThumbs={regionThumbs}
          regionThumbsLoading={regionThumbsLoading}
          regionThumbsError={regionThumbsError}
          onApply={runAnalyze}
          onCompare={runCompare}
          computing={computing}
          onUpload={onUpload}
          uploading={uploading}
          // manual anchor
          nudge={nudge}
          onNudgeChange={setNudge}
          onSwapSides={swapSides}
          hasDeviationResult={Boolean(deviationResult)}
          isDeviationView={isDeviationView}
          // export
          formats={formats}
          onToggleFormat={toggleFormat}
          dpi={dpi}
          onDpiChange={setDpi}
          camera={camera}
          onCameraChange={setCamera}
          onExport={runExport}
          exporting={exporting}
          exportFiles={exportFiles}
          exportError={exportError}
          canExport={Boolean(displayGeometry)}
          annotateLine={annotateLine}
          onAnnotateLineChange={setAnnotateLine}
          annotateHeight={annotateHeight}
          onAnnotateHeightChange={setAnnotateHeight}
          annotateApplies={!isDeviationView}
        />

        <main
          className={`center${
            centerView === 'images' || centerView === 'oblique' ? ' center-split' : ''
          }${centerView === 'compare' ? ' center-compare' : ''}`}
        >
          <div className="center-toolbar">
            <div className="center-toggle" role="group" aria-label="Center view">
              <button
                className={centerView === 'map' ? 'active' : ''}
                onClick={() => setCenterView('map')}
              >
                3D map
              </button>
              <button
                className={centerView === 'images' ? 'active' : ''}
                onClick={() => setCenterView('images')}
                disabled={isMesh}
                title={
                  isMesh
                    ? 'A mesh upload has no volume to slice'
                    : 'Show the linked MPR slices beside the map'
                }
              >
                Images (MPR)
              </button>
              <button
                className={centerView === 'compare' ? 'active' : ''}
                onClick={() => setCenterView('compare')}
                disabled={!canCompareSides}
                title={
                  canCompareSides
                    ? 'Linked cross-sections between the reference and target volumes'
                    : 'Needs a bilateral session with both left and right volumes'
                }
              >
                Compare
              </button>
              <button
                className={centerView === 'oblique' ? 'active' : ''}
                onClick={() => setCenterView('oblique')}
                disabled={!mprSide}
                title={
                  mprSide
                    ? 'Arbitrary tiltable cutting plane, matched live to a 2D reformat'
                    : 'A mesh upload has no volume to slice'
                }
              >
                Oblique
              </button>
            </div>
            <button
              type="button"
              className={`clip-toggle-btn${clipEnabled ? ' active' : ''}`}
              onClick={() => onToggleClip(!clipEnabled)}
              disabled={!displayGeometry || centerView !== 'map' || isBoth}
              title={
                isBoth
                  ? 'Clip is unavailable in the bilateral “Both” view — pick a single side to isolate a sub-part'
                  : displayGeometry
                    ? 'Isolate a sub-part with an adjustable clip box; stats recompute for the visible part'
                    : 'Compute a thickness or deviation map first'
              }
            >
              {clipEnabled ? 'Clip: On' : 'Clip / isolate'}
            </button>
            <button
              type="button"
              className="ar-launch-btn"
              onClick={() => setArOpen(true)}
              disabled={!displayGeometry}
              title={
                displayGeometry
                  ? 'View the computed surface in 3D / AR'
                  : 'Compute a thickness or deviation map first'
              }
            >
              View in AR
            </button>
          </div>

          <div className="center-body">
        {centerView === 'compare' ? (
          canCompareSides ? (
            <CompareView
              sessionId={session.session_id}
              referenceSide={referenceSide}
              targetSide={targetSide}
              params={values}
              manualTransform={manualTransform}
            />
          ) : (
            <div className="mpr-wrap mpr-empty">
              <div className="mpr-empty-title">Compare needs two volumes</div>
              <div className="mpr-empty-body">
                This session does not expose both a left and a right volume —
                the linked compare view needs a bilateral scan.
              </div>
            </div>
          )
        ) : (
          <>
        <div className="viewport-wrap">
          <Viewport
            geometry={displayGeometry}
            secondGeometry={secondDisplayGeometry}
            onHover={setHover}
            cameraPose={camera}
            onPick={onSurfacePick}
            marker={marker}
            plane={centerView === 'oblique' ? obliquePlane : null}
            onScalarData={setScalarValues}
            clipBox={clipEnabled && !isBoth ? clipBox : null}
            onBounds={onViewportBounds}
            onVisibleMask={setVisibleMask}
            colorSmoothIters={Number(values?.color_smooth_iters) || 0}
            onPlaneDrag={
              centerView === 'oblique'
                ? (d) => setPlaneNudge({ d, seq: (planeNudgeSeqRef.current += 1) })
                : undefined
            }
          />

          {displayGeometry && (
            <HoverTooltip
              hover={hover}
              scalar={displayGeometry.scalar}
              mean={activeMean}
              scalarNames={isDeviationView ? deviationResult?.hover_scalars : null}
            />
          )}

          {clipEnabled && displayGeometry && (
            <div className="left-overlay">
              <DraggablePanel className="dp-clip">
                <ClipPanel
                  bounds={meshBounds}
                  box={clipBox}
                  enabled={clipEnabled}
                  onToggle={onToggleClip}
                  onBoxChange={setClipBox}
                  onReset={onResetClip}
                  canPickIsolate={!isBoth}
                  visibleCount={visibleVertexCount}
                  totalCount={totalVertexCount}
                  visiblePct={visiblePct}
                />
              </DraggablePanel>
            </div>
          )}

          {!displayGeometry && !computing && (
            <div className="viewport-empty">
              <div className="viewport-empty-card">
                <div className="viewport-empty-title">
                  {isDeviationView
                    ? 'No deviation computed yet'
                    : 'No result computed yet'}
                </div>
                <div className="viewport-empty-body">
                  {isMesh
                    ? 'This is a mesh upload — pick two sides / anchor and press “Compute deviation”.'
                    : isDeviationView
                      ? 'Choose reference & target sides, then press “Compute deviation”.'
                      : 'Choose a side and press “Apply / Recompute”.'}
                </div>
              </div>
            </div>
          )}

          {computing && (
            <div className="viewport-loading">
              <div className="spinner" />
              <div className="viewport-loading-text">
                {isDeviationView
                  ? 'Registering & comparing the two surfaces…'
                  : 'Re-running segmentation & thickness…'}
              </div>
              <div className="viewport-loading-sub">This takes ~5–20 s.</div>
            </div>
          )}

          {computeError && (
            <div className="viewport-error">
              <strong>Could not compute.</strong> {computeError}
            </div>
          )}

          <div className="right-overlay">
            {showThicknessLegend && (
              <DraggablePanel className="dp-legend">
                <Legend
                  rangeMin={displayGeometry.rangeMin}
                  rangeMax={displayGeometry.rangeMax}
                  steps={displayGeometry.steps}
                  reverse={displayGeometry.reverse}
                  colormap={displayGeometry.colormap}
                  title={`Cortical thickness (mm) — ${
                    isBoth ? 'Left + Right' : cap(side)
                  }`}
                />
              </DraggablePanel>
            )}
            {showDeviationLegend && (
              <DraggablePanel className="dp-legend">
                <Legend
                  diverging
                  rangeMin={displayGeometry.rangeMin}
                  rangeMax={displayGeometry.rangeMax}
                  steps={displayGeometry.steps}
                  reverse={displayGeometry.reverse}
                  colormap={displayGeometry.colormap}
                  title={`Signed deviation (mm) — ${cap(targetSide)} vs ${cap(
                    referenceSide,
                  )}`}
                />
              </DraggablePanel>
            )}
            <DraggablePanel className="dp-stats">
              {isDeviationView ? (
                <StatsPanel
                  kind="deviation"
                  result={deviationResult}
                  scalarValues={scalarValues}
                  unit="mm"
                  clipStats={clipStats}
                  visibleMask={visibleMask}
                  visibleCount={visibleVertexCount}
                  totalCount={totalVertexCount}
                  visiblePct={visiblePct}
                />
              ) : (
                <StatsPanel
                  kind="thickness"
                  result={thicknessResult}
                  scalarValues={scalarValues}
                  unit="mm"
                  clipStats={clipStats}
                  visibleMask={visibleMask}
                  visibleCount={visibleVertexCount}
                  totalCount={totalVertexCount}
                  visiblePct={visiblePct}
                />
              )}
            </DraggablePanel>
            {displayGeometry && (
              <DraggablePanel className="dp-figures">
              <StatsFigures
                sessionId={session.session_id}
                mode={isDeviationView ? 'B' : 'A'}
                side={isDeviationView ? side : effectiveSide}
                referenceSide={isDeviationView ? referenceSide : undefined}
                targetSide={isDeviationView ? targetSide : undefined}
                regionLabel={!isDeviationView && !isBoth ? regionLabel : undefined}
                params={
                  isDeviationView ? { ...values, mirror_sagittal: mirror } : values
                }
                manualTransform={isDeviationView ? manualTransform : undefined}
                computeSignature={computeSignature}
                hasResult={Boolean(activeResult)}
              />
              </DraggablePanel>
            )}
          </div>
        </div>

          {centerView === 'images' && (
            <div className="mpr-column">
              {mprSide ? (
                <MPRViewer
                  sessionId={session.session_id}
                  side={mprSide}
                  externalCrosshair={pickedCrosshair}
                  onCrosshairChange={onMprCrosshair}
                />
              ) : (
                <div className="mpr-wrap mpr-empty">
                  <div className="mpr-empty-title">No volume to slice</div>
                  <div className="mpr-empty-body">
                    This session is a mesh upload — the MPR viewer needs a CT
                    volume. Load a scan to see linked slices.
                  </div>
                </div>
              )}
            </div>
          )}

          {centerView === 'oblique' && (
            <div className="mpr-column">
              {mprSide ? (
                <ObliqueView
                  sessionId={session.session_id}
                  side={mprSide}
                  pickedWorld={marker}
                  planeNudge={planeNudge}
                  onPlaneChange={setObliquePlane}
                  onPixelPick={onObliquePixelPick}
                  // Two-box matched compare ONLY when actually comparing (Mode B /
                  // deviation). In Mode A the user is analysing ONE side, so show that
                  // side's single cross-section — not a forced (often unreliable) match.
                  compareMode={isDeviationView && canCompareSides}
                  referenceSide={referenceSide}
                  targetSide={targetSide}
                  params={values}
                  manualTransform={manualTransform}
                />
              ) : (
                <div className="mpr-wrap mpr-empty">
                  <div className="mpr-empty-title">No volume to slice</div>
                  <div className="mpr-empty-body">
                    This session is a mesh upload — the oblique reformat needs
                    a CT volume. Load a scan to see the matched cross-section.
                  </div>
                </div>
              )}
            </div>
          )}
          </>
        )}
          </div>
        </main>

        {arOpen && (
          <ArModal sessionId={session.session_id} onClose={() => setArOpen(false)} />
        )}
      </div>
    </div>
  );
}

function cap(s) {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}

function readableError(e) {
  const status = e?.status;
  if (status === 501) {
    return `Not implemented on the server (501): ${e.message}`;
  }
  if (status === 422) {
    return `Invalid request (422): ${e.message}`;
  }
  return e?.message || String(e);
}
