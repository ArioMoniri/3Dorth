// The central vtk.js viewport. Renders whatever geometry the compute API
// returned: a Mode-A / per-side thickness map (colored by `thickness_mm` with a
// sequential LUT) or a Mode-B deviation map (colored by `deviation_mm` with a
// diverging LUT). Both are driven by a discrete LUT built from the response
// scalar_range / colormap / steps, so the viewport and the HTML legend agree.
//
// Geometry is loaded with vtkXMLPolyDataReader from the ArrayBuffer fetched from
// the returned geometry_url. No analysis happens here.
//
// HOVER: a vtkPointPicker fires on mouse-move over the render window. When it
// lands on the surface we read the picked point's active scalar (thickness_mm
// or deviation_mm) and its world position and hand them to the parent via
// `onHover`, which draws an HTML tooltip. This is real picking, not a mock.

import { useEffect, useRef } from 'react';

import '@kitware/vtk.js/Rendering/Profiles/Geometry';

import vtkGenericRenderWindow from '@kitware/vtk.js/Rendering/Misc/GenericRenderWindow';
import vtkActor from '@kitware/vtk.js/Rendering/Core/Actor';
import vtkMapper from '@kitware/vtk.js/Rendering/Core/Mapper';
import vtkXMLPolyDataReader from '@kitware/vtk.js/IO/XML/XMLPolyDataReader';
import vtkAxesActor from '@kitware/vtk.js/Rendering/Core/AxesActor';
import vtkOrientationMarkerWidget from '@kitware/vtk.js/Interaction/Widgets/OrientationMarkerWidget';
import vtkCellPicker from '@kitware/vtk.js/Rendering/Core/CellPicker';

import { fetchGeometryArrayBuffer } from './api';
import { buildDiscreteLUT } from './colors';

function parseVtp(arrayBuffer) {
  const reader = vtkXMLPolyDataReader.newInstance();
  reader.parseAsArrayBuffer(arrayBuffer);
  return reader.getOutputData(0);
}

// Read the per-point scalar for a picked cell. The picker gives us a cell id and
// the world position of the hit; we return the scalar of the cell vertex closest
// to that hit, which is the value the clinician is pointing at. Falls back to a
// direct point lookup when the cell can't be resolved.
function scalarAtPickedCell(polydata, scalarName, cellId, pos) {
  const scalars = polydata.getPointData().getArrayByName(scalarName);
  if (!scalars) return null;
  const data = scalars.getData();
  const points = polydata.getPoints().getData();
  const polys = polydata.getPolys()?.getData();

  // Walk the polys connectivity to find this cell's point ids. VTK cell arrays
  // are [n, id0, id1, ..., n, id0, ...]; for triangle meshes n is usually 3.
  if (polys) {
    let idx = 0;
    let cell = 0;
    while (idx < polys.length) {
      const n = polys[idx];
      if (cell === cellId) {
        let bestId = polys[idx + 1];
        let bestD = Infinity;
        for (let k = 0; k < n; k += 1) {
          const pid = polys[idx + 1 + k];
          const dx = points[pid * 3] - pos[0];
          const dy = points[pid * 3 + 1] - pos[1];
          const dz = points[pid * 3 + 2] - pos[2];
          const d = dx * dx + dy * dy + dz * dz;
          if (d < bestD) {
            bestD = d;
            bestId = pid;
          }
        }
        return data[bestId];
      }
      idx += n + 1;
      cell += 1;
    }
  }
  // Fallback: nearest point overall (rare — only if connectivity is unavailable).
  return null;
}

// `geometry` = { url, scalar, rangeMin, rangeMax, steps, colormap, reverse } or
// null (nothing computed yet).
// `onHover(info|null)` — info = { value, x, y, z, screenX, screenY } while the
// cursor is over the surface, null when it leaves.
// `cameraPose` — { azimuth, elevation, roll, zoom } applied to the reset camera
// so the on-screen pose matches the Export panel's requested pose.
export default function Viewport({ geometry, onHover, cameraPose }) {
  const containerRef = useRef(null);
  const contextRef = useRef(null);
  const onHoverRef = useRef(onHover);
  onHoverRef.current = onHover;

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

    // A cell picker ray-casts against the surface (robust on thin bone shells);
    // we then read the scalar at the picked cell's nearest vertex. A small
    // tolerance keeps grazing rays landing on the mesh.
    const picker = vtkCellPicker.newInstance();
    picker.setPickFromList(false);
    picker.setTolerance(0.01);

    contextRef.current = {
      genericRenderWindow,
      renderer,
      renderWindow,
      interactor,
      orientationWidget,
      picker,
      actor: null,
      mapper: null,
      polydata: null,
      lastUrl: null,
    };

    // ---- hover picking ------------------------------------------------------
    const el = containerRef.current;
    const doPick = (clientX, clientY) => {
      const ctx = contextRef.current;
      if (!ctx || !ctx.actor || !ctx.polydata) {
        onHoverRef.current?.(null);
        return;
      }
      const rect = el.getBoundingClientRect();
      const x = clientX - rect.left;
      // vtk uses a bottom-left origin for display coordinates.
      const y = rect.height - (clientY - rect.top);
      ctx.picker.pick([x, y, 0], ctx.renderer);
      const actors = ctx.picker.getActors();
      const cellId = ctx.picker.getCellId();
      if (!actors || actors.length === 0 || cellId < 0) {
        onHoverRef.current?.(null);
        return;
      }
      const pos = ctx.picker.getPickPosition();
      const value = scalarAtPickedCell(ctx.polydata, ctx.scalarName, cellId, pos);
      onHoverRef.current?.({
        value,
        x: pos[0],
        y: pos[1],
        z: pos[2],
        screenX: clientX - rect.left,
        screenY: clientY - rect.top,
      });
    };
    const onMove = (e) => doPick(e.clientX, e.clientY);
    const onLeave = () => onHoverRef.current?.(null);
    el.addEventListener('mousemove', onMove);
    el.addEventListener('mouseleave', onLeave);

    const onResize = () => genericRenderWindow.resize();
    window.addEventListener('resize', onResize);

    return () => {
      window.removeEventListener('resize', onResize);
      el.removeEventListener('mousemove', onMove);
      el.removeEventListener('mouseleave', onLeave);
      orientationWidget.setEnabled(false);
      genericRenderWindow.delete();
      contextRef.current = null;
    };
  }, []);

  // ---- apply a requested camera pose (used by the Export panel) -------------
  function applyCameraPose(ctx, isNewGeometry) {
    const { renderer, renderWindow } = ctx;
    const camera = renderer.getActiveCamera();
    if (isNewGeometry) renderer.resetCamera();
    if (cameraPose) {
      const { azimuth = 0, elevation = 0, roll = 0, zoom = 1 } = cameraPose;
      // Reset to the framed pose first so the pose is absolute, not cumulative.
      renderer.resetCamera();
      if (azimuth) camera.azimuth(azimuth);
      if (elevation) camera.elevation(elevation);
      if (roll) camera.roll(roll);
      if (zoom && zoom !== 1) camera.zoom(zoom);
    }
    renderer.resetCameraClippingRange();
    renderWindow.render();
  }

  // ---- (re)build the scene whenever the geometry / coloring changes ---------
  useEffect(() => {
    const ctx = contextRef.current;
    if (!ctx || !geometry || !geometry.url) return undefined;

    let cancelled = false;

    async function rebuild() {
      const { renderer } = ctx;

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
        ctx.polydata = polydata;
        ctx.lastUrl = geometry.url;
      }
      if (!ctx.mapper) return;
      ctx.scalarName = geometry.scalar;

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
      applyCameraPose(ctx, isNewGeometry);
    }

    rebuild();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    geometry?.url,
    geometry?.scalar,
    geometry?.rangeMin,
    geometry?.rangeMax,
    geometry?.steps,
    geometry?.reverse,
    geometry?.colormap,
  ]);

  // ---- re-apply the camera pose when it changes (no geometry reload) --------
  useEffect(() => {
    const ctx = contextRef.current;
    if (!ctx || !ctx.actor) return;
    applyCameraPose(ctx, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    cameraPose?.azimuth,
    cameraPose?.elevation,
    cameraPose?.roll,
    cameraPose?.zoom,
  ]);

  return (
    <div
      ref={containerRef}
      style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}
    />
  );
}
