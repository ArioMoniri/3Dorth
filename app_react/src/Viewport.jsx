// The central vtk.js viewport. Renders either the Mode-A thickness map
// (thickness.vtp colored by the `thickness_mm` point scalar with a discrete
// green->yellow->red LUT + vertical scalar bar) or the region view (one actor
// per region_<label>.vtp, highlighted region orange, rest neutral).
//
// Geometry is loaded with vtkXMLPolyDataReader from the ArrayBuffer fetched
// from /api/geometry/*.vtp. No analysis happens here — colors and ranges come
// straight from the manifest / registry defaults.

import { useEffect, useRef } from 'react';

import '@kitware/vtk.js/Rendering/Profiles/Geometry';

import vtkGenericRenderWindow from '@kitware/vtk.js/Rendering/Misc/GenericRenderWindow';
import vtkActor from '@kitware/vtk.js/Rendering/Core/Actor';
import vtkMapper from '@kitware/vtk.js/Rendering/Core/Mapper';
import vtkXMLPolyDataReader from '@kitware/vtk.js/IO/XML/XMLPolyDataReader';
import vtkAxesActor from '@kitware/vtk.js/Rendering/Core/AxesActor';
import vtkOrientationMarkerWidget from '@kitware/vtk.js/Interaction/Widgets/OrientationMarkerWidget';

import { fetchGeometryArrayBuffer } from './api';
import { buildDiscreteLUT, hexToRgb01, NEUTRAL_HEX, HIGHLIGHT_HEX } from './colors';

// Parse a .vtp ArrayBuffer into a vtkPolyData.
function parseVtp(arrayBuffer) {
  const reader = vtkXMLPolyDataReader.newInstance();
  reader.parseAsArrayBuffer(arrayBuffer);
  return reader.getOutputData(0);
}

export default function Viewport({ manifest, mode, coloring, regionState }) {
  const containerRef = useRef(null);
  const contextRef = useRef(null); // holds vtk objects across renders
  // Cache parsed polydata so we don't re-fetch/parse the (large) .vtp on every
  // parameter tweak.
  const geometryCacheRef = useRef({ thickness: null, regions: {} });

  // ---- one-time vtk.js setup ------------------------------------------------
  useEffect(() => {
    if (!containerRef.current || contextRef.current) return undefined;

    const genericRenderWindow = vtkGenericRenderWindow.newInstance({
      background: [1, 1, 1],
    });
    genericRenderWindow.setContainer(containerRef.current);

    const renderer = genericRenderWindow.getRenderer();
    const renderWindow = genericRenderWindow.getRenderWindow();
    const interactor = genericRenderWindow.getInteractor();

    // Orientation axes marker (bottom-left corner). The color legend is a crisp
    // HTML overlay (see Legend.jsx), NOT a vtkScalarBarActor, so we keep the 3D
    // viewport clean: bone + orientation axes only.
    const axes = vtkAxesActor.newInstance();
    const orientationWidget = vtkOrientationMarkerWidget.newInstance({
      actor: axes,
      interactor,
    });
    orientationWidget.setEnabled(true);
    orientationWidget.setViewportCorner(
      vtkOrientationMarkerWidget.Corners.BOTTOM_LEFT,
    );
    orientationWidget.setViewportSize(0.15);

    contextRef.current = {
      genericRenderWindow,
      renderer,
      renderWindow,
      interactor,
      orientationWidget,
      thicknessActor: null,
      thicknessMapper: null,
      lut: null,
      regionActors: {}, // label -> { actor, mapper }
    };

    const onResize = () => genericRenderWindow.resize();
    window.addEventListener('resize', onResize);

    return () => {
      window.removeEventListener('resize', onResize);
      orientationWidget.setEnabled(false);
      genericRenderWindow.delete();
      contextRef.current = null;
    };
  }, []);

  // ---- (re)build the scene whenever inputs change ---------------------------
  useEffect(() => {
    const ctx = contextRef.current;
    if (!ctx || !manifest) return;

    let cancelled = false;

    async function rebuild() {
      const { renderer, renderWindow } = ctx;

      // Clear existing actors from the renderer (keep vtk objects for reuse).
      if (ctx.thicknessActor) renderer.removeActor(ctx.thicknessActor);
      Object.values(ctx.regionActors).forEach(({ actor }) => renderer.removeActor(actor));

      if (mode === 'A') {
        await renderThickness(ctx, cancelledRef(() => cancelled), manifest, coloring, geometryCacheRef);
      } else {
        await renderRegions(ctx, cancelledRef(() => cancelled), manifest, regionState, geometryCacheRef);
      }

      if (cancelled) return;
      renderer.resetCameraClippingRange();
      renderWindow.render();
    }

    // First build should frame the data; later rebuilds keep the camera.
    const firstBuild = !ctx.hasBuilt;
    rebuild().then(() => {
      if (cancelled || !contextRef.current) return;
      if (firstBuild) {
        ctx.renderer.resetCamera();
        ctx.renderWindow.render();
        ctx.hasBuilt = true;
      }
    });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    manifest,
    mode,
    coloring.rangeMin,
    coloring.rangeMax,
    coloring.steps,
    coloring.reverse,
    regionState.visible.join(','),
    regionState.highlight,
  ]);

  return (
    <div
      ref={containerRef}
      style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}
    />
  );
}

// Small helper so the async closures read whether the effect was cancelled.
function cancelledRef(getter) {
  return getter;
}

// ---- Mode A: thickness map ---------------------------------------------------
async function renderThickness(ctx, isCancelled, manifest, coloring, geometryCacheRef) {
  const { renderer } = ctx;
  const th = manifest.thickness;

  // Load + cache the thickness polydata.
  if (!geometryCacheRef.current.thickness) {
    const buf = await fetchGeometryArrayBuffer(th.file);
    if (isCancelled()) return;
    geometryCacheRef.current.thickness = parseVtp(buf);
  }
  const polydata = geometryCacheRef.current.thickness;

  // Build (or rebuild) the discrete LUT for the current coloring state.
  const lut = buildDiscreteLUT({
    rangeMin: coloring.rangeMin,
    rangeMax: coloring.rangeMax,
    steps: coloring.steps,
    reverse: coloring.reverse,
  });
  ctx.lut = lut;

  if (!ctx.thicknessMapper) {
    ctx.thicknessMapper = vtkMapper.newInstance();
    ctx.thicknessActor = vtkActor.newInstance();
    ctx.thicknessActor.setMapper(ctx.thicknessMapper);
  }
  const mapper = ctx.thicknessMapper;
  mapper.setInputData(polydata);
  mapper.setLookupTable(lut);
  mapper.setUseLookupTableScalarRange(true);
  mapper.setScalarRange(coloring.rangeMin, coloring.rangeMax);
  mapper.setColorModeToMapScalars();
  mapper.setScalarModeToUsePointFieldData();
  mapper.setColorByArrayName(th.scalar); // "thickness_mm"
  mapper.setInterpolateScalarsBeforeMapping(true);

  renderer.addActor(ctx.thicknessActor);
}

// ---- Region view -------------------------------------------------------------
async function renderRegions(ctx, isCancelled, manifest, regionState, geometryCacheRef) {
  const { renderer } = ctx;

  await Promise.all(
    manifest.regions.map(async (r) => {
      const key = String(r.label);
      if (!geometryCacheRef.current.regions[key]) {
        const buf = await fetchGeometryArrayBuffer(r.file);
        if (isCancelled()) return;
        geometryCacheRef.current.regions[key] = parseVtp(buf);
      }
    }),
  );
  if (isCancelled()) return;

  manifest.regions.forEach((r) => {
    const key = String(r.label);
    const polydata = geometryCacheRef.current.regions[key];
    if (!polydata || polydata.getNumberOfPoints() === 0) return;

    if (!ctx.regionActors[key]) {
      const mapper = vtkMapper.newInstance();
      mapper.setInputData(polydata);
      mapper.setScalarVisibility(false); // solid color, no scalars
      const actor = vtkActor.newInstance();
      actor.setMapper(mapper);
      ctx.regionActors[key] = { actor, mapper };
    }

    const { actor } = ctx.regionActors[key];
    const isVisible = regionState.visible.includes(r.label);
    actor.setVisibility(isVisible);
    const isHighlight = String(regionState.highlight) === key;
    actor.getProperty().setColor(...hexToRgb01(isHighlight ? HIGHLIGHT_HEX : NEUTRAL_HEX));

    if (isVisible) renderer.addActor(actor);
  });
}
