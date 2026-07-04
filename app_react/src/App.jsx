// Frontend 2 root. Mirrors the trame app's layout:
//   top bar (title + Mode A / Mode B toggle)
//   LEFT panel (region show/hide + highlight, then registry-driven params)
//   CENTER vtk.js viewport
//   RIGHT overlay: discrete HTML color legend (Mode A only)
//
// Parity rule: the parameter panel is generated purely by iterating the
// controls returned from /api/parameters. Parameter *values* are seeded from
// the API `defaults` (the paper's values). No parameter list is hardcoded.

import { useEffect, useMemo, useState } from 'react';

import { fetchManifest, fetchParameters } from './api';
import ControlPanel from './ControlPanel';
import Viewport from './Viewport';
import Legend from './Legend';

export default function App() {
  const [manifest, setManifest] = useState(null);
  const [allControls, setAllControls] = useState([]); // full registry (all modes)
  const [defaults, setDefaults] = useState({});
  const [values, setValues] = useState({});
  const [mode, setMode] = useState('A');
  const [error, setError] = useState(null);

  // Region view state (seeded from the manifest once it loads).
  const [regionState, setRegionState] = useState({ visible: [], highlight: null });

  // ---- load registry + manifest --------------------------------------------
  useEffect(() => {
    Promise.all([fetchParameters(), fetchManifest()])
      .then(([params, man]) => {
        setAllControls(params.controls);
        setDefaults(params.defaults);
        setValues(params.defaults); // seed EVERY key from the paper defaults
        setManifest(man);
        setRegionState({
          visible: man.regions.map((r) => r.label),
          highlight: man.thickness.region_label,
        });
      })
      .catch((e) => setError(String(e)));
  }, []);

  // Controls shown for the active mode: keep only params whose mode matches the
  // active mode or that apply to 'both'. (We keep every VALUE in state; we just
  // display the relevant subset — every registry key still has an adjustable
  // control across the two modes.)
  const modeControls = useMemo(
    () => allControls.filter((c) => c.mode === mode || c.mode === 'both'),
    [allControls, mode],
  );

  // Coloring state for the LUT + legend, derived live from the parameter values
  // (falling back to the manifest for the very first paint).
  const coloring = useMemo(() => {
    const cr = manifest?.thickness?.colorbar_range_mm ?? [0.1537, 6.5202];
    return {
      rangeMin: numOr(values.mode_a_range_min, cr[0]),
      rangeMax: numOr(values.mode_a_range_max, cr[1]),
      steps: numOr(values.mode_a_colorbar_steps, manifest?.thickness?.colorbar_steps ?? 7),
      reverse: Boolean(values.mode_a_colormap_reverse),
      colormap: values.mode_a_colormap ?? manifest?.thickness?.colormap ?? 'green_yellow_red',
    };
  }, [values, manifest]);

  const onParamChange = (key, v) => setValues((prev) => ({ ...prev, [key]: v }));
  const resetDefaults = () => setValues(defaults);

  const onToggleRegion = (label) =>
    setRegionState((prev) => ({
      ...prev,
      visible: prev.visible.includes(label)
        ? prev.visible.filter((l) => l !== label)
        : [...prev.visible, label],
    }));
  const onHighlightChange = (label) =>
    setRegionState((prev) => ({ ...prev, highlight: label }));

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

  if (!manifest || allControls.length === 0) {
    return <div className="loading">Loading registry &amp; demo bundle…</div>;
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          3Dorth <span className="brand-sub">React + vtk.js</span>
        </div>
        <div className="topbar-right">
          <span className="bone-series">{manifest.bone_series}</span>
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
          manifest={manifest}
          controls={modeControls}
          values={values}
          onParamChange={onParamChange}
          onReset={resetDefaults}
          regionState={regionState}
          onToggleRegion={onToggleRegion}
          onHighlightChange={onHighlightChange}
        />

        <main className="viewport-wrap">
          <Viewport
            manifest={manifest}
            mode={mode}
            coloring={coloring}
            regionState={regionState}
          />
          {mode === 'A' && (
            <div className="legend-overlay">
              <Legend
                rangeMin={coloring.rangeMin}
                rangeMax={coloring.rangeMax}
                steps={coloring.steps}
                reverse={coloring.reverse}
                colormap={coloring.colormap}
                title="Cortical thickness (mm)"
              />
            </div>
          )}
          {mode === 'B' && (
            <div className="mode-b-note">
              Mode B (two-scan signed deviation) — controls shown; comparison
              geometry is produced by the full pipeline.
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

function numOr(v, fallback) {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}
