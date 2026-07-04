// React + vtk.js root for 3Dorth. Layout:
//   top bar (title + Mode A / Mode B toggle)
//   LEFT panel  — scan/upload, side selector, Mode-B sub-toggle, Apply/Recompute,
//                 then the registry-driven parameter panel
//   CENTER      — vtk.js viewport showing the LAST computed geometry
//   RIGHT       — HTML color legend + returned stats
//
// Session model: on mount we POST /api/session and keep session_id + sides. The
// PRIMARY action ("Apply / Recompute" or "Compute deviation") POSTs the CURRENT
// parameter values to /analyze or /compare; the pipeline re-runs with those
// params, so every side-panel control genuinely affects the result. We then load
// the returned geometry_url .vtp and color it from the response
// scalar_range/colormap/steps.
//
// Parity rule: the parameter panel is generated purely by iterating the controls
// returned from /api/parameters. No parameter list is hardcoded.

import { useEffect, useMemo, useState } from 'react';

import {
  fetchParameters,
  createSession,
  uploadZip,
  analyze,
  compare,
} from './api';
import ControlPanel from './ControlPanel';
import Viewport from './Viewport';
import Legend from './Legend';
import StatsPanel from './StatsPanel';

export default function App() {
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

  // Compute state + last results.
  const [computing, setComputing] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [computeError, setComputeError] = useState(null);
  const [geometry, setGeometry] = useState(null); // {url,scalar,rangeMin,...}
  const [thicknessResult, setThicknessResult] = useState(null);
  const [deviationResult, setDeviationResult] = useState(null);

  // ---- load registry + open a session --------------------------------------
  useEffect(() => {
    Promise.all([fetchParameters(), createSession()])
      .then(([params, sess]) => {
        setAllControls(params.controls);
        setDefaults(params.defaults);
        setValues(params.defaults); // seed EVERY key from the paper defaults
        applySession(sess);
      })
      .catch((e) => setError(String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function applySession(sess) {
    setSession(sess);
    const sides = sess.sides || [];
    setSide(sides[0] ?? null);
    setReferenceSide(sides[0] ?? null);
    setTargetSide(sides[1] ?? sides[0] ?? null);
    // A fresh scan invalidates prior geometry/results.
    setGeometry(null);
    setThicknessResult(null);
    setDeviationResult(null);
    setComputeError(null);
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
  const isDeviationView = mode === 'B' && modeBView === 'deviation';

  // If the server dropped our session (e.g. it restarted and lost its in-memory
  // store), transparently open a fresh one and hand back its id so the action
  // can retry once instead of surfacing a 404 to the user.
  async function ensureSession() {
    const fresh = await createSession();
    setSession(fresh);
    return fresh.session_id;
  }

  // ---- primary actions ------------------------------------------------------
  async function runAnalyze() {
    if (!session || !side) return;
    setComputing(true);
    setComputeError(null);
    try {
      let sid = session.session_id;
      let res;
      try {
        res = await analyze(sid, { side, params: values });
      } catch (e) {
        if (e?.status === 404) {
          sid = await ensureSession();
          res = await analyze(sid, { side, params: values });
        } else {
          throw e;
        }
      }
      setThicknessResult(res);
      setGeometry({
        url: res.geometry_url,
        scalar: res.scalar,
        rangeMin: res.scalar_range[0],
        rangeMax: res.scalar_range[1],
        steps: res.steps,
        colormap: res.colormap,
        reverse: Boolean(values.mode_a_colormap_reverse),
      });
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
      const args = { referenceSide, targetSide, params };
      let res;
      try {
        res = await compare(sid, args);
      } catch (e) {
        if (e?.status === 404) {
          sid = await ensureSession();
          res = await compare(sid, args);
        } else {
          throw e;
        }
      }
      setDeviationResult(res);
      setGeometry({
        url: res.geometry_url,
        scalar: res.scalar,
        rangeMin: res.scalar_range[0],
        rangeMax: res.scalar_range[1],
        steps: res.steps,
        colormap: res.colormap,
        reverse: false,
      });
    } catch (e) {
      setComputeError(readableError(e));
    } finally {
      setComputing(false);
    }
  }

  async function onUpload(file) {
    setUploading(true);
    setComputeError(null);
    try {
      const sess = await uploadZip(file);
      applySession(sess);
    } catch (e) {
      setComputeError(`Upload failed: ${readableError(e)}`);
    } finally {
      setUploading(false);
    }
  }

  // Switching to deviation shouldn't leave the thickness result on screen; keep
  // the viewport showing whatever matches the current view.
  useEffect(() => {
    if (isDeviationView) {
      if (deviationResult) {
        setGeometryFromDeviation(deviationResult);
      } else {
        setGeometry(null);
      }
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
        </div>
      </header>

      <div className="body">
        <ControlPanel
          session={session}
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
          onApply={runAnalyze}
          onCompare={runCompare}
          computing={computing}
          onUpload={onUpload}
          uploading={uploading}
        />

        <main className="viewport-wrap">
          <Viewport geometry={geometry} />

          {!geometry && !computing && (
            <div className="viewport-empty">
              <div className="viewport-empty-card">
                <div className="viewport-empty-title">
                  {isDeviationView
                    ? 'No deviation computed yet'
                    : 'No result computed yet'}
                </div>
                <div className="viewport-empty-body">
                  {isDeviationView
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
                  ? 'Registering & comparing the two sides…'
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
