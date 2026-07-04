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

import { useEffect, useMemo, useState } from 'react';

import {
  fetchConfig,
  fetchParameters,
  createSession,
  uploadFile,
  analyze,
  compare,
  exportResult,
} from './api';
import ControlPanel from './ControlPanel';
import Viewport from './Viewport';
import Legend from './Legend';
import StatsPanel from './StatsPanel';
import ShareSwitch from './ShareSwitch';
import HoverTooltip from './HoverTooltip';
import { buildManualTransform } from './ManualAnchor';

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

  // Manual anchor nudge (Mode B deviation).
  const [nudge, setNudge] = useState(ZERO_NUDGE);

  // Export state.
  const [formats, setFormats] = useState(() => new Set(['png']));
  const [dpi, setDpi] = useState(150);
  const [camera, setCamera] = useState(DEFAULT_CAMERA);
  const [exporting, setExporting] = useState(false);
  const [exportFiles, setExportFiles] = useState(null);
  const [exportError, setExportError] = useState(null);

  // Hover tooltip.
  const [hover, setHover] = useState(null);

  // Compute state + last results.
  const [computing, setComputing] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [computeError, setComputeError] = useState(null);
  const [geometry, setGeometry] = useState(null); // {url,scalar,rangeMin,...}
  const [thicknessResult, setThicknessResult] = useState(null);
  const [deviationResult, setDeviationResult] = useState(null);

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

  function applySession(sess) {
    setSession(sess);
    const sides = sess.sides || [];
    setSide(sides[0] ?? null);
    setReferenceSide(sides[0] ?? null);
    setTargetSide(sides[1] ?? sides[0] ?? null);
    setRegionLabel(null);
    setNudge(ZERO_NUDGE);
    // A mesh session can't produce a thickness map; force Mode B (deviation).
    if (sess.is_mesh || sess.sides?.[0] === 'mesh') {
      setMode('B');
      setModeBView('deviation');
    }
    // A fresh scan invalidates prior geometry/results.
    setGeometry(null);
    setThicknessResult(null);
    setDeviationResult(null);
    setComputeError(null);
    setExportFiles(null);
    setExportError(null);
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

  // Is the current view a deviation view?
  const isDeviationView = (mode === 'B' && modeBView === 'deviation') || isMesh;

  const manualTransform = useMemo(
    () => buildManualTransform(nudge),
    [nudge],
  );

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
  async function runAnalyze() {
    if (!session || !side || isMesh) return;
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
      setThicknessResult(res);
      // Adopt the server's chosen region so the selector reflects reality.
      if (res.region_label != null) setRegionLabel(res.region_label);
      setGeometryFromThickness(res);
    } catch (e) {
      setComputeError(readableError(e));
    } finally {
      setComputing(false);
    }
  }

  async function runCompare() {
    if (!session || referenceSide === targetSide) return;
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
      setDeviationResult(res);
      setGeometryFromDeviation(res);
    } catch (e) {
      setComputeError(readableError(e));
    } finally {
      setComputing(false);
    }
  }

  function swapSides() {
    setReferenceSide(targetSide);
    setTargetSide(referenceSide);
  }

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
      if (exportMode === 'B') {
        args.referenceSide = referenceSide;
        args.targetSide = targetSide;
        args.manualTransform = manualTransform;
      } else {
        args.side = side;
        if (regionLabel != null) args.regionLabel = regionLabel;
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
      if (deviationResult) setGeometryFromDeviation(deviationResult);
      else setGeometry(null);
    } else if (thicknessResult) {
      setGeometryFromThickness(thicknessResult);
    } else {
      setGeometry(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isDeviationView]);

  function setGeometryFromThickness(res) {
    setGeometry({
      url: res.geometry_url,
      scalar: res.scalar,
      rangeMin: res.scalar_range[0],
      rangeMax: res.scalar_range[1],
      steps: res.steps,
      colormap: res.colormap,
      reverse: Boolean(values.mode_a_colormap_reverse),
    });
  }
  function setGeometryFromDeviation(res) {
    setGeometry({
      url: res.geometry_url,
      scalar: res.scalar,
      rangeMin: res.scalar_range[0],
      rangeMax: res.scalar_range[1],
      steps: res.steps,
      colormap: res.colormap,
      reverse: false,
    });
  }

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

  const showDeviationLegend = isDeviationView && deviationResult && geometry;
  const showThicknessLegend = !isDeviationView && thicknessResult && geometry;
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
          canExport={Boolean(geometry)}
        />

        <main className="viewport-wrap">
          <Viewport
            geometry={geometry}
            onHover={setHover}
            cameraPose={camera}
          />

          {geometry && (
            <HoverTooltip
              hover={hover}
              scalar={geometry.scalar}
              mean={activeMean}
            />
          )}

          {!geometry && !computing && (
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
              <Legend
                rangeMin={geometry.rangeMin}
                rangeMax={geometry.rangeMax}
                steps={geometry.steps}
                reverse={geometry.reverse}
                colormap={geometry.colormap}
                title={`Cortical thickness (mm) — ${cap(side)}`}
              />
            )}
            {showDeviationLegend && (
              <Legend
                diverging
                rangeMin={geometry.rangeMin}
                rangeMax={geometry.rangeMax}
                steps={geometry.steps}
                reverse={geometry.reverse}
                colormap={geometry.colormap}
                title={`Signed deviation (mm) — ${cap(targetSide)} vs ${cap(
                  referenceSide,
                )}`}
              />
            )}
            {isDeviationView ? (
              <StatsPanel kind="deviation" result={deviationResult} />
            ) : (
              <StatsPanel kind="thickness" result={thicknessResult} />
            )}
          </div>
        </main>
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
