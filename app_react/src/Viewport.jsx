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
import vtkSphereSource from '@kitware/vtk.js/Filters/Sources/SphereSource';
import vtkPlaneSource from '@kitware/vtk.js/Filters/Sources/PlaneSource';

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
// `onPick(worldXyz)` — fires with the picked [x,y,z] world point when the user
//   clicks the surface (used to drive the MPR crosshair via pick-to-slices).
// `marker` — { x, y, z } world position for a small sphere marker (the linked
//   crosshair point), or null to hide it.
// `plane` — { origin:[x,y,z], normal:[x,y,z], sizeMm } for the Phase VII
//   arbitrary-cross-section widget: draws a translucent square plane actor at
//   that origin/normal so the user sees exactly what the 2D oblique reformat
//   is cutting. Omit / null to hide it (unused by the other center views).
export default function Viewport({ geometry, onHover, cameraPose, onPick, marker, plane }) {
  const containerRef = useRef(null);
  const contextRef = useRef(null);
  const onHoverRef = useRef(onHover);
  onHoverRef.current = onHover;
  const onPickRef = useRef(onPick);
  onPickRef.current = onPick;

  // ---- one-time vtk.js setup ------------------------------------------------
  useEffect(() => {
    if (!containerRef.current || contextRef.current) return undefined;

    const genericRenderWindow = vtkGenericRenderWindow.newInstance({
      background: [1, 1, 1],
    });
    genericRenderWindow.setContainer(containerRef.current);
    // Sync the OpenGL view to the container's real (device-pixel) size now, up
    // front. Without this the view stays at its 300×300 default until a stray
    // resize event fires — which both mis-fits the first render and, because the
    // picker scales by getSize(), makes early hover picks land in the wrong place.
    genericRenderWindow.resize();

    const renderer = genericRenderWindow.getRenderer();
    const renderWindow = genericRenderWindow.getRenderWindow();
    const interactor = genericRenderWindow.getInteractor();
    // The OpenGL view renders into a device-pixel backing store; on HiDPI /
    // Retina displays (devicePixelRatio > 1) that is larger than the CSS box.
    // vtkCellPicker.pick() expects DEVICE-pixel display coordinates, so we must
    // scale CSS coordinates by this ratio or every pick lands in the wrong place.
    const apiRenderWindow = genericRenderWindow.getApiSpecificRenderWindow();

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
      apiRenderWindow,
      actor: null,
      mapper: null,
      polydata: null,
      lastUrl: null,
      markerActor: null,
      markerSource: null,
      planeActor: null,
      planeSource: null,
    };

    // ---- linked-crosshair marker (a small red sphere) ----------------------
    // Placed at the picked / crosshair world point so the 3D view shows exactly
    // where the MPR planes intersect. Hidden until there is a marker.
    const markerSource = vtkSphereSource.newInstance({
      radius: 2.0,
      thetaResolution: 16,
      phiResolution: 16,
    });
    const markerMapper = vtkMapper.newInstance();
    markerMapper.setInputConnection(markerSource.getOutputPort());
    const markerActor = vtkActor.newInstance();
    markerActor.setMapper(markerMapper);
    markerActor.getProperty().setColor(0.95, 0.15, 0.15);
    markerActor.getProperty().setAmbient(0.5);
    markerActor.setVisibility(false);
    renderer.addActor(markerActor);
    contextRef.current.markerActor = markerActor;
    contextRef.current.markerSource = markerSource;

    // ---- oblique cutting-plane actor (Phase VII) ---------------------------
    // A translucent square centred at the plane origin, oriented by the plane
    // normal — shows exactly what the 2D oblique panel is sampling. Hidden
    // until a `plane` prop is supplied (only used by the 'oblique' center view).
    const planeSource = vtkPlaneSource.newInstance({ xResolution: 1, yResolution: 1 });
    const planeMapper = vtkMapper.newInstance();
    planeMapper.setInputConnection(planeSource.getOutputPort());
    const planeActor = vtkActor.newInstance();
    planeActor.setMapper(planeMapper);
    planeActor.getProperty().setColor(0.25, 0.55, 0.95);
    planeActor.getProperty().setOpacity(0.35);
    planeActor.getProperty().setAmbient(0.6);
    planeActor.getProperty().setBackfaceCulling(false);
    planeActor.getProperty().setFrontfaceCulling(false);
    planeActor.setVisibility(false);
    renderer.addActor(planeActor);
    contextRef.current.planeActor = planeActor;
    contextRef.current.planeSource = planeSource;

    // ---- hover picking ------------------------------------------------------
    const el = containerRef.current;
    const doPick = (clientX, clientY) => {
      const ctx = contextRef.current;
      if (!ctx || !ctx.actor || !ctx.polydata) {
        onHoverRef.current?.(null);
        return;
      }
      const rect = el.getBoundingClientRect();
      // Scale CSS-pixel cursor coordinates into the render window's device-pixel
      // space (getSize() returns device px). On a 1× display the ratio is 1; on
      // HiDPI it is devicePixelRatio, and without it every pick misses.
      const size = ctx.apiRenderWindow.getSize();
      const ratioX = rect.width ? size[0] / rect.width : 1;
      const ratioY = rect.height ? size[1] / rect.height : 1;
      const x = (clientX - rect.left) * ratioX;
      // vtk uses a bottom-left origin for display coordinates.
      const y = (rect.height - (clientY - rect.top)) * ratioY;
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

    // ---- click picking (surface point -> MPR crosshair) --------------------
    // We only treat it as a "pick" click when the pointer didn't move far
    // between down and up, so orbiting the camera (a drag) never fires a pick.
    let downX = 0;
    let downY = 0;
    let downT = 0;
    const onDown = (e) => {
      downX = e.clientX;
      downY = e.clientY;
      downT = Date.now();
    };
    const onUp = (e) => {
      if (e.button !== 0) return;
      const moved = Math.hypot(e.clientX - downX, e.clientY - downY);
      if (moved > 5 || Date.now() - downT > 500) return; // a drag, not a click
      const ctx = contextRef.current;
      if (!ctx || !ctx.actor || !ctx.polydata) return;
      const rect = el.getBoundingClientRect();
      const size = ctx.apiRenderWindow.getSize();
      const ratioX = rect.width ? size[0] / rect.width : 1;
      const ratioY = rect.height ? size[1] / rect.height : 1;
      const x = (e.clientX - rect.left) * ratioX;
      const y = (rect.height - (e.clientY - rect.top)) * ratioY;
      ctx.picker.pick([x, y, 0], ctx.renderer);
      const actors = ctx.picker.getActors();
      if (!actors || actors.length === 0 || ctx.picker.getCellId() < 0) return;
      const pos = ctx.picker.getPickPosition();
      onPickRef.current?.([pos[0], pos[1], pos[2]]);
    };
    el.addEventListener('mousedown', onDown);
    el.addEventListener('mouseup', onUp);

    const onResize = () => genericRenderWindow.resize();
    window.addEventListener('resize', onResize);
    // A ResizeObserver catches container-only layout changes (panel toggles,
    // flex reflow) that a window 'resize' misses, and fires once as soon as the
    // container has its real size — keeping the render fit and the picker's
    // device-pixel scaling correct without waiting for a stray window resize.
    let resizeObserver = null;
    if (typeof ResizeObserver !== 'undefined') {
      resizeObserver = new ResizeObserver(() => genericRenderWindow.resize());
      resizeObserver.observe(el);
    }

    return () => {
      window.removeEventListener('resize', onResize);
      if (resizeObserver) resizeObserver.disconnect();
      el.removeEventListener('mousemove', onMove);
      el.removeEventListener('mouseleave', onLeave);
      el.removeEventListener('mousedown', onDown);
      el.removeEventListener('mouseup', onUp);
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

  // ---- move / show / hide the crosshair marker -----------------------------
  useEffect(() => {
    const ctx = contextRef.current;
    if (!ctx || !ctx.markerActor) return;
    if (marker && Number.isFinite(marker.x)) {
      // Size the sphere relative to the current mesh so it reads on any scale.
      if (ctx.polydata) {
        const b = ctx.polydata.getBounds();
        const diag = Math.hypot(b[1] - b[0], b[3] - b[2], b[5] - b[4]);
        if (diag > 0) ctx.markerSource.setRadius(diag * 0.012);
      }
      ctx.markerActor.setPosition(marker.x, marker.y, marker.z);
      ctx.markerActor.setVisibility(true);
    } else {
      ctx.markerActor.setVisibility(false);
    }
    ctx.renderWindow?.render();
  }, [marker?.x, marker?.y, marker?.z]);

  // ---- move / show / hide the oblique cutting-plane actor ------------------
  // Builds an in-plane basis (u, v) from the normal the same way the server's
  // plane_basis() does (arbitrary "up" hint, orthogonalised), purely for
  // drawing — the actual 2D reformat's exact basis comes back from the API in
  // its own `meta.u` / `meta.v` and is used by ObliqueView for pixel<->world,
  // never approximated here.
  useEffect(() => {
    const ctx = contextRef.current;
    if (!ctx || !ctx.planeActor || !ctx.planeSource) return;
    if (plane && Array.isArray(plane.origin) && Array.isArray(plane.normal)) {
      const [nx, ny, nz] = plane.normal;
      const nLen = Math.hypot(nx, ny, nz) || 1;
      const n = [nx / nLen, ny / nLen, nz / nLen];
      const upHint = Math.abs(n[2]) < 0.9 ? [0, 0, 1] : [0, 1, 0];
      const dot = n[0] * upHint[0] + n[1] * upHint[1] + n[2] * upHint[2];
      let u = [upHint[0] - dot * n[0], upHint[1] - dot * n[1], upHint[2] - dot * n[2]];
      const uLen = Math.hypot(...u) || 1;
      u = [u[0] / uLen, u[1] / uLen, u[2] / uLen];
      const v = [
        n[1] * u[2] - n[2] * u[1],
        n[2] * u[0] - n[0] * u[2],
        n[0] * u[1] - n[1] * u[0],
      ];
      const half = (plane.sizeMm ?? 200) / 2;
      const [ox, oy, oz] = plane.origin;
      // PlaneSource: origin + point1 (defines one edge) + point2 (defines the
      // other edge); the actor's quad spans origin..point1 x origin..point2.
      ctx.planeSource.setOrigin(ox - u[0] * half - v[0] * half, oy - u[1] * half - v[1] * half, oz - u[2] * half - v[2] * half);
      ctx.planeSource.setPoint1(ox + u[0] * half - v[0] * half, oy + u[1] * half - v[1] * half, oz + u[2] * half - v[2] * half);
      ctx.planeSource.setPoint2(ox - u[0] * half + v[0] * half, oy - u[1] * half + v[1] * half, oz - u[2] * half + v[2] * half);
      ctx.planeActor.setVisibility(true);
    } else {
      ctx.planeActor.setVisibility(false);
    }
    ctx.renderWindow?.render();
  }, [
    plane?.origin?.[0],
    plane?.origin?.[1],
    plane?.origin?.[2],
    plane?.normal?.[0],
    plane?.normal?.[1],
    plane?.normal?.[2],
    plane?.sizeMm,
  ]);

  return (
    <div
      ref={containerRef}
      style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}
    />
  );
}
