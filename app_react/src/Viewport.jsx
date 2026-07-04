// The central vtk.js viewport. Renders whatever geometry the compute API
// returned: a Mode-A / per-side thickness map (colored by `thickness_mm` with a
// sequential LUT) or a Mode-B deviation map (colored by `deviation_mm` with a
// diverging LUT). Both are driven by a discrete LUT built from the response
// scalar_range / colormap / steps, so the viewport and the HTML legend agree.
//
// Geometry is loaded with vtkXMLPolyDataReader from the ArrayBuffer fetched from
// the returned geometry_url. No analysis happens here.

import { useEffect, useRef } from 'react';

import '@kitware/vtk.js/Rendering/Profiles/Geometry';

import vtkGenericRenderWindow from '@kitware/vtk.js/Rendering/Misc/GenericRenderWindow';
import vtkActor from '@kitware/vtk.js/Rendering/Core/Actor';
import vtkMapper from '@kitware/vtk.js/Rendering/Core/Mapper';
import vtkXMLPolyDataReader from '@kitware/vtk.js/IO/XML/XMLPolyDataReader';
import vtkAxesActor from '@kitware/vtk.js/Rendering/Core/AxesActor';
import vtkOrientationMarkerWidget from '@kitware/vtk.js/Interaction/Widgets/OrientationMarkerWidget';

import { fetchGeometryArrayBuffer } from './api';
import { buildDiscreteLUT } from './colors';

function parseVtp(arrayBuffer) {
  const reader = vtkXMLPolyDataReader.newInstance();
  reader.parseAsArrayBuffer(arrayBuffer);
  return reader.getOutputData(0);
}

// `geometry` = { url, scalar, rangeMin, rangeMax, steps, colormap, reverse } or
// null (nothing computed yet).
export default function Viewport({ geometry }) {
  const containerRef = useRef(null);
  const contextRef = useRef(null);

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
      orientationWidget,
      actor: null,
      mapper: null,
      lastUrl: null,
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

  // ---- (re)build the scene whenever the geometry / coloring changes ---------
  useEffect(() => {
    const ctx = contextRef.current;
    if (!ctx || !geometry || !geometry.url) return undefined;

    let cancelled = false;

    async function rebuild() {
      const { renderer, renderWindow } = ctx;

      // Only refetch/parse when the geometry URL actually changes; a pure
      // coloring tweak just rebuilds the LUT.
      const isNewGeometry = ctx.lastUrl !== geometry.url;
      if (isNewGeometry) {
        const buf = await fetchGeometryArrayBuffer(geometry.url);
        if (cancelled) return;
        const polydata = parseVtp(buf);

        if (ctx.actor) renderer.removeActor(ctx.actor);
        ctx.mapper = vtkMapper.newInstance();
        ctx.actor = vtkActor.newInstance();
        ctx.actor.setMapper(ctx.mapper);
        ctx.mapper.setInputData(polydata);
        renderer.addActor(ctx.actor);
        ctx.lastUrl = geometry.url;
      }
      if (!ctx.mapper) return;

      const lut = buildDiscreteLUT({
        rangeMin: geometry.rangeMin,
        rangeMax: geometry.rangeMax,
        steps: geometry.steps,
        reverse: geometry.reverse,
        colormap: geometry.colormap,
      });

      ctx.mapper.setLookupTable(lut);
      ctx.mapper.setUseLookupTableScalarRange(true);
      ctx.mapper.setScalarRange(geometry.rangeMin, geometry.rangeMax);
      ctx.mapper.setColorModeToMapScalars();
      ctx.mapper.setScalarModeToUsePointFieldData();
      ctx.mapper.setColorByArrayName(geometry.scalar);
      ctx.mapper.setInterpolateScalarsBeforeMapping(true);

      if (cancelled) return;
      if (isNewGeometry) renderer.resetCamera();
      renderer.resetCameraClippingRange();
      renderWindow.render();
    }

    rebuild();

    return () => {
      cancelled = true;
    };
  }, [
    geometry?.url,
    geometry?.scalar,
    geometry?.rangeMin,
    geometry?.rangeMax,
    geometry?.steps,
    geometry?.reverse,
    geometry?.colormap,
  ]);

  return (
    <div
      ref={containerRef}
      style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}
    />
  );
}
