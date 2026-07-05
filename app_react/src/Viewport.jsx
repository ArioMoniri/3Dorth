// The central vtk.js viewport. Renders whatever geometry the compute API
// returned: a Mode-A / per-side thickness map (colored by `thickness_mm` with a
// sequential LUT) or a Mode-B deviation map (colored by `deviation_mm` with a
// diverging LUT). Both are driven by a discrete LUT built from the response
// scalar_range / colormap / steps, so the viewport and the HTML legend agree.
//
// Geometry is loaded with vtkXMLPolyDataReader from the ArrayBuffer fetched from
// the returned geometry_url. No analysis happens here.
//
// HOVER: a vtkCellPicker fires on mouse-move over the render window. When it
// lands on the surface we read EVERY point_data array's value at the picked
// vertex (not just the active scalar) plus its world position and hand them to
// the parent via `onHover`, which draws an HTML tooltip. In Mode B this lets
// the tooltip show reference thickness, contralateral (target) thickness, the
// signed difference and the signed deviation together — all read straight from
// the already-loaded mesh's point data. This is real picking, not a mock.

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
import vtkPlane from '@kitware/vtk.js/Common/DataModel/Plane';
import vtkDataArray from '@kitware/vtk.js/Common/Core/DataArray';

import { fetchGeometryArrayBuffer } from './api';
import { buildDiscreteLUT } from './colors';

function parseVtp(arrayBuffer) {
  const reader = vtkXMLPolyDataReader.newInstance();
  reader.parseAsArrayBuffer(arrayBuffer);
  return reader.getOutputData(0);
}

// ---- DISPLAY-ONLY colour smoothing --------------------------------------- //
// Build the one-ring vertex adjacency (neighbour index lists) from the triangle
// connectivity, so a scalar can be Laplacian-smoothed along the surface. Cached
// per-geometry on the context (topology is fixed until the mesh URL changes).
function buildVertexAdjacency(polydata) {
  const polys = polydata.getPolys()?.getData();
  const nPts = polydata.getNumberOfPoints();
  const nbr = Array.from({ length: nPts }, () => new Set());
  if (!polys) return nbr.map((s) => [...s]);
  let i = 0;
  while (i < polys.length) {
    const n = polys[i];
    for (let a = 1; a <= n; a += 1) {
      for (let b = a + 1; b <= n; b += 1) {
        const va = polys[i + a];
        const vb = polys[i + b];
        nbr[va].add(vb);
        nbr[vb].add(va);
      }
    }
    i += n + 1;
  }
  return nbr.map((s) => [...s]);
}

// Laplacian smoothing of a per-vertex scalar over the mesh graph. Returns a NEW
// Float32Array — the source array (the honest, computed thickness used for hover
// and every statistic) is never modified. Purely a render-side cosmetic pass.
function laplacianSmoothScalar(values, adjacency, iters, lambda = 0.5) {
  let cur = Float32Array.from(values);
  const n = cur.length;
  for (let it = 0; it < iters; it += 1) {
    const next = new Float32Array(n);
    for (let v = 0; v < n; v += 1) {
      const nb = adjacency[v];
      if (!nb || nb.length === 0) { next[v] = cur[v]; continue; }
      let sum = 0;
      for (let k = 0; k < nb.length; k += 1) sum += cur[nb[k]];
      const avg = sum / nb.length;
      next[v] = cur[v] + lambda * (avg - cur[v]);
    }
    cur = next;
  }
  return cur;
}

// Add/replace a point-data array (used to hold the smoothed DISPLAY scalar so the
// mapper colours by it while hover/stats still read the raw array by its name).
function upsertPointArray(polydata, name, typedValues) {
  const pd = polydata.getPointData();
  const existing = pd.getArrayByName(name);
  if (existing) {
    existing.setData(typedValues);
  } else {
    pd.addArray(vtkDataArray.newInstance({ name, numberOfComponents: 1, values: typedValues }));
  }
}

// Choose the array the mapper should colour by: the smoothed display copy when
// smoothing is on, else the raw scalar. Recomputes the display copy as needed.
function colorArrayForDisplay(ctx, polydata, scalarName, iters, adjKey = 'adjacency') {
  if (!iters || iters <= 0) return scalarName;
  const raw = polydata.getPointData().getArrayByName(scalarName);
  if (!raw) return scalarName;
  if (!ctx[adjKey]) ctx[adjKey] = buildVertexAdjacency(polydata);
  const smoothed = laplacianSmoothScalar(raw.getData(), ctx[adjKey], Math.min(iters, 20));
  const displayName = `${scalarName}__display`;
  upsertPointArray(polydata, displayName, smoothed);
  return displayName;
}

// Flood-fill the connected component that contains `startPid` (via the one-ring
// adjacency) and return its world-space bounds [xmin,xmax,ymin,ymax,zmin,zmax].
// Used by click-to-isolate so clipping snaps to the WHOLE piece you clicked (e.g.
// the humerus, dropping detached fragments) instead of an arbitrary axis box.
function componentBoundsFromPoint(polydata, adjacency, startPid) {
  const n = polydata.getNumberOfPoints();
  if (startPid == null || startPid < 0 || startPid >= n) return null;
  const pts = polydata.getPoints().getData();
  const seen = new Uint8Array(n);
  const stack = [startPid];
  seen[startPid] = 1;
  let xmin = Infinity, xmax = -Infinity, ymin = Infinity, ymax = -Infinity, zmin = Infinity, zmax = -Infinity;
  let count = 0;
  while (stack.length) {
    const v = stack.pop();
    const x = pts[v * 3], y = pts[v * 3 + 1], z = pts[v * 3 + 2];
    if (x < xmin) xmin = x; if (x > xmax) xmax = x;
    if (y < ymin) ymin = y; if (y > ymax) ymax = y;
    if (z < zmin) zmin = z; if (z > zmax) zmax = z;
    count += 1;
    const nb = adjacency[v];
    if (nb) for (let k = 0; k < nb.length; k += 1) {
      const w = nb[k];
      if (!seen[w]) { seen[w] = 1; stack.push(w); }
    }
  }
  return { bounds: [xmin, xmax, ymin, ymax, zmin, zmax], count };
}

// Find the point id of the cell vertex closest to the pick hit. The picker
// gives us a cell id and the world position of the hit; we walk the polys
// connectivity to find that cell's point ids and return whichever is nearest
// the hit position — the vertex the clinician is actually pointing at.
// Returns null if connectivity is unavailable (rare).
function pickedPointId(polydata, cellId, pos) {
  const points = polydata.getPoints().getData();
  const polys = polydata.getPolys()?.getData();
  if (!polys) return null;

  // VTK cell arrays are [n, id0, id1, ..., n, id0, ...]; for triangle meshes n
  // is usually 3.
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
      return bestId;
    }
    idx += n + 1;
    cell += 1;
  }
  return null;
}

// Read a single named point-data scalar at a point id.
function scalarAt(polydata, scalarName, pointId) {
  const scalars = polydata.getPointData().getArrayByName(scalarName);
  if (!scalars) return null;
  return scalars.getData()[pointId];
}

// Read EVERY point_data array's value at a point id, e.g. { thickness_mm: 2.1,
// deviation_mm: -0.4, ... }. Used so a hover can show more than just the active
// scalar (Mode B needs ref/target thickness + diff + deviation together).
function allScalarsAt(polydata, pointId) {
  const pd = polydata.getPointData();
  const out = {};
  const n = pd.getNumberOfArrays();
  for (let i = 0; i < n; i += 1) {
    const arr = pd.getArrayByIndex(i);
    const name = arr?.getName();
    if (!name) continue;
    out[name] = arr.getData()[pointId];
  }
  return out;
}

// `geometry` = { url, scalar, rangeMin, rangeMax, steps, colormap, reverse } or
// null (nothing computed yet).
// `onHover(info|null)` — info = { value, scalars, x, y, z, screenX, screenY }
// while the cursor is over the surface, null when it leaves. `scalars` is every
// point_data array's value at the picked vertex, e.g.
// { thickness_mm } (Mode A) or
// { deviation_mm, ref_thickness_mm, tgt_thickness_mm, thickness_diff_mm } (Mode B).
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
// `onScalarData(values|null)` — fires with the active scalar's full per-vertex
//   typed array (e.g. every thickness_mm or deviation_mm value across the
//   loaded surface) whenever the geometry (re)loads or the active scalar name
//   changes, so the parent can compute a distribution histogram in the browser
//   with no extra API call — the array is already in the parsed polydata.
// `clipBox` — { xmin, xmax, ymin, ymax, zmin, zmax } or null. When set, SIX
//   vtk.js mapper clipping planes hide every fragment outside the box (GPU-side,
//   no geometry copy) — everything OUTSIDE the box disappears from the render.
//   "Reset clip" is just passing null / the full mesh bounds again.
// `onBounds(bounds|null)` — fires with the loaded polydata's bounds
//   [xmin,xmax,ymin,ymax,zmin,zmax] whenever new geometry loads, so the parent
//   can seed the clip-box sliders to the real mesh extent.
// `onVisibleMask(mask|null)` — fires with a Uint8Array (1 = inside the current
//   clip box, 0 = outside), one entry per point in the SAME order as the active
//   scalar array, whenever the geometry or clip box changes. With no clip box
//   active this is null (nothing to mask — "whole" already means everything).
//   Used by the parent to recompute Mean/Median/SD/RMS/Min/Max/Count over just
//   the visible (on-screen) vertices, entirely client-side.
// `secondGeometry` — an OPTIONAL second geometry payload (same shape as
//   `geometry`). When present (the LEFT/RIGHT/BOTH "Both" bilateral view), a
//   SECOND actor is rendered in the same scene, each mesh coloured by its own
//   side's thickness with the identical LUT. Hover picking works across both
//   actors (the picker reads whichever mesh is under the cursor); the camera is
//   framed to include both. Clip / visible-mask / scalar-data reporting stay on
//   the PRIMARY geometry only (Both is a comparison-of-two view, not a clip
//   target). Omit / null for the normal single-mesh view.
export default function Viewport({
  geometry,
  secondGeometry,
  onHover,
  cameraPose,
  onPick,
  marker,
  plane,
  onScalarData,
  clipBox,
  onBounds,
  onVisibleMask,
  colorSmoothIters = 0,
  onPlaneDrag,
}) {
  const containerRef = useRef(null);
  const contextRef = useRef(null);
  const onHoverRef = useRef(onHover);
  onHoverRef.current = onHover;
  const onPickRef = useRef(onPick);
  onPickRef.current = onPick;
  const onPlaneDragRef = useRef(onPlaneDrag);
  onPlaneDragRef.current = onPlaneDrag;
  const onScalarDataRef = useRef(onScalarData);
  onScalarDataRef.current = onScalarData;
  const onBoundsRef = useRef(onBounds);
  onBoundsRef.current = onBounds;
  const onVisibleMaskRef = useRef(onVisibleMask);
  onVisibleMaskRef.current = onVisibleMask;

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
    // bottom-RIGHT so it never collides with the bottom-left legend/stats/histogram card
    orientationWidget.setViewportCorner(
      vtkOrientationMarkerWidget.Corners.BOTTOM_RIGHT,
    );
    orientationWidget.setViewportSize(0.13);

    // A cell picker ray-casts against the surface (robust on thin bone shells);
    // we then read the scalar at the picked cell's nearest vertex. A small
    // tolerance keeps grazing rays landing on the mesh.
    const picker = vtkCellPicker.newInstance();
    picker.setPickFromList(false);
    picker.setTolerance(0.01);

    // ---- clip-box planes (Feature 3: isolate a sub-part) -------------------
    // Six axis-aligned vtk.js clipping planes (+X/-X/+Y/-Y/+Z/-Z half-spaces).
    // Added to the mapper so the GPU discards every fragment outside the box —
    // no geometry copy, works on the existing actor. Kept even when the clip is
    // "off": we just don't add them to the mapper until clipBox is set.
    const clipPlanes = {
      xmin: vtkPlane.newInstance({ normal: [1, 0, 0] }),
      xmax: vtkPlane.newInstance({ normal: [-1, 0, 0] }),
      ymin: vtkPlane.newInstance({ normal: [0, 1, 0] }),
      ymax: vtkPlane.newInstance({ normal: [0, -1, 0] }),
      zmin: vtkPlane.newInstance({ normal: [0, 0, 1] }),
      zmax: vtkPlane.newInstance({ normal: [0, 0, -1] }),
    };

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
      // Optional SECOND mesh (the bilateral "Both" view).
      actor2: null,
      mapper2: null,
      polydata2: null,
      lastUrl2: null,
      scalarName2: null,
      markerActor: null,
      markerSource: null,
      planeActor: null,
      planeSource: null,
      clipPlanes,
      clipActive: false,
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
    // Resolve which of the (up to two) loaded meshes the picker just hit, so a
    // hover/click over the second bilateral mesh reads THAT mesh's scalars.
    const pickedPolydata = (ctx) => {
      const hit = ctx.picker.getActors?.() || [];
      if (ctx.actor2 && hit.includes(ctx.actor2)) {
        return { polydata: ctx.polydata2, scalarName: ctx.scalarName2 };
      }
      return { polydata: ctx.polydata, scalarName: ctx.scalarName };
    };

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
      const { polydata: hitPoly, scalarName: hitScalar } = pickedPolydata(ctx);
      const pointId = hitPoly ? pickedPointId(hitPoly, cellId, pos) : null;
      const value =
        pointId != null ? scalarAt(hitPoly, hitScalar, pointId) : null;
      const scalars = pointId != null ? allScalarsAt(hitPoly, pointId) : {};
      onHoverRef.current?.({
        value,
        scalars,
        x: pos[0],
        y: pos[1],
        z: pos[2],
        screenX: clientX - rect.left,
        screenY: clientY - rect.top,
      });
    };
    // Ray-pick the actor directly under the cursor (used both for surface picking
    // and to detect a grab on the translucent cutting plane).
    const pickActorAt = (clientX, clientY) => {
      const ctx = contextRef.current;
      if (!ctx) return { actor: null, pos: null, cellId: -1 };
      const rect = el.getBoundingClientRect();
      const size = ctx.apiRenderWindow.getSize();
      const ratioX = rect.width ? size[0] / rect.width : 1;
      const ratioY = rect.height ? size[1] / rect.height : 1;
      const x = (clientX - rect.left) * ratioX;
      const y = (rect.height - (clientY - rect.top)) * ratioY;
      ctx.picker.pick([x, y, 0], ctx.renderer);
      const actors = ctx.picker.getActors();
      return {
        actor: actors && actors.length ? actors[0] : null,
        pos: ctx.picker.getPickPosition(),
        cellId: ctx.picker.getCellId(),
      };
    };

    const onMove = (e) => {
      const ctx = contextRef.current;
      // ---- dragging the cutting plane: slide it along its own normal ---------
      if (ctx && ctx.planeDrag) {
        const dyPx = ctx.planeDrag.lastY - e.clientY; // up = positive
        ctx.planeDrag.lastY = e.clientY;
        // world-mm per pixel ≈ plane extent / canvas height, so a full-height drag
        // slides the plane by ~its own size — a natural feel at any zoom.
        const rect = el.getBoundingClientRect();
        const mmPerPx = rect.height ? (ctx.planeDrag.sizeMm || 200) / rect.height : 0.3;
        onPlaneDragRef.current?.(dyPx * mmPerPx);
        onHoverRef.current?.(null);
        return;
      }
      doPick(e.clientX, e.clientY);
    };
    const onLeave = () => onHoverRef.current?.(null);
    el.addEventListener('mousemove', onMove);
    el.addEventListener('mouseleave', onLeave);

    // ---- click picking (surface point -> MPR crosshair) + plane grab --------
    // We only treat it as a "pick" click when the pointer didn't move far
    // between down and up, so orbiting the camera (a drag) never fires a pick.
    let downX = 0;
    let downY = 0;
    let downT = 0;
    const endPlaneDrag = () => {
      const ctx = contextRef.current;
      if (ctx && ctx.planeDrag) {
        // restore the camera interactor style we suspended during the grab.
        if (ctx.planeDrag.style !== undefined) ctx.interactor.setInteractorStyle(ctx.planeDrag.style);
        ctx.planeDrag = null;
        el.style.cursor = '';
      }
    };
    const onDown = (e) => {
      downX = e.clientX;
      downY = e.clientY;
      downT = Date.now();
      const ctx = contextRef.current;
      // Grab the plane only when it's actually shown (oblique mode) and the click
      // lands on it (closest hit). Suspend camera orbit for the duration so the
      // drag slides the plane instead of rotating the scene.
      if (e.button === 0 && ctx && ctx.planeActor && ctx.planeActor.getVisibility()) {
        const hit = pickActorAt(e.clientX, e.clientY);
        if (hit.actor === ctx.planeActor) {
          ctx.planeDrag = {
            lastY: e.clientY,
            sizeMm: ctx.planeSizeMm || 200,
            style: ctx.interactor.getInteractorStyle(),
          };
          ctx.interactor.setInteractorStyle(null);
          el.style.cursor = 'ns-resize';
          e.preventDefault();
        }
      }
    };
    const onUp = (e) => {
      if (e.button !== 0) return;
      const ctx = contextRef.current;
      if (ctx && ctx.planeDrag) { endPlaneDrag(); return; }
      const moved = Math.hypot(e.clientX - downX, e.clientY - downY);
      if (moved > 5 || Date.now() - downT > 500) return; // a drag, not a click
      if (!ctx || !ctx.actor || !ctx.polydata) return;
      const hit = pickActorAt(e.clientX, e.clientY);
      if (!hit.actor || hit.cellId < 0) return;
      // When the click lands on the PRIMARY bone, also report the connected
      // component under the cursor so click-to-isolate can clip to the whole
      // piece (not an axis-box sliver of a diagonal bone).
      let component = null;
      if (hit.actor === ctx.actor) {
        const pid = pickedPointId(ctx.polydata, hit.cellId, hit.pos);
        if (pid != null) {
          if (!ctx.adjacency) ctx.adjacency = buildVertexAdjacency(ctx.polydata);
          component = componentBoundsFromPoint(ctx.polydata, ctx.adjacency, pid);
        }
      }
      onPickRef.current?.([hit.pos[0], hit.pos[1], hit.pos[2]], component);
    };
    el.addEventListener('mousedown', onDown);
    el.addEventListener('mouseup', onUp);
    // Safety: if the mouse is released outside the canvas, still end the grab so
    // camera control is always restored.
    window.addEventListener('mouseup', endPlaneDrag);

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
      window.removeEventListener('mouseup', endPlaneDrag);
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
    if (!ctx || !geometry || !geometry.url) {
      onScalarDataRef.current?.(null);
      return undefined;
    }

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
        ctx.adjacency = null; // topology changed — invalidate the smoothing graph
        // A new geometry means a brand-new vtkMapper instance with no clipping
        // planes yet; the clip-box effect below (keyed partly on geometry.url)
        // re-adds them if a clip is currently active.
        ctx.clipActive = false;
        // Hand the new mesh's real bounds up so the parent can seed the
        // clip-box sliders to the actual extent of THIS geometry.
        onBoundsRef.current?.(polydata.getBounds());
      }
      if (!ctx.mapper) return;
      ctx.scalarName = geometry.scalar;

      // Hand the active scalar's full per-vertex array up to the parent (for
      // the Stats panel histogram) — read straight from the loaded polydata,
      // no new fetch.
      const scalarArr = ctx.polydata?.getPointData().getArrayByName(geometry.scalar);
      onScalarDataRef.current?.(scalarArr ? scalarArr.getData() : null);

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
      // Colour by the smoothed DISPLAY copy when colour smoothing is on; hover +
      // the scalar array handed to the Stats panel still read the raw values.
      ctx.mapper.setColorByArrayName(
        colorArrayForDisplay(ctx, ctx.polydata, geometry.scalar, colorSmoothIters),
      );
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
    colorSmoothIters,
  ]);

  // ---- optional SECOND mesh (bilateral "Both" view) -------------------------
  // Loads/updates a second actor coloured by its own side's thickness with the
  // SAME LUT settings as the primary. When present, the camera is reset to frame
  // BOTH meshes. Removing it (secondGeometry -> null) reverts to a single-mesh
  // scene and re-frames on the primary alone.
  useEffect(() => {
    const ctx = contextRef.current;
    if (!ctx) return undefined;
    let cancelled = false;

    async function rebuild2() {
      const { renderer } = ctx;
      if (!secondGeometry || !secondGeometry.url) {
        // Tear down any existing second actor and re-frame on the primary.
        if (ctx.actor2) {
          renderer.removeActor(ctx.actor2);
          ctx.actor2 = null;
          ctx.mapper2 = null;
          ctx.polydata2 = null;
          ctx.lastUrl2 = null;
          applyCameraPose(ctx, true);
        }
        return;
      }
      const isNew = ctx.lastUrl2 !== secondGeometry.url;
      if (isNew) {
        const buf = await fetchGeometryArrayBuffer(secondGeometry.url);
        if (cancelled) return;
        const polydata = parseVtp(buf);
        if (ctx.actor2) renderer.removeActor(ctx.actor2);
        ctx.mapper2 = vtkMapper.newInstance();
        ctx.actor2 = vtkActor.newInstance();
        ctx.actor2.setMapper(ctx.mapper2);
        ctx.mapper2.setInputData(polydata);
        renderer.addActor(ctx.actor2);
        ctx.polydata2 = polydata;
        ctx.lastUrl2 = secondGeometry.url;
        ctx.adjacency2 = null;
      }
      if (!ctx.mapper2) return;
      ctx.scalarName2 = secondGeometry.scalar;
      const lut = buildDiscreteLUT({
        rangeMin: secondGeometry.rangeMin,
        rangeMax: secondGeometry.rangeMax,
        steps: secondGeometry.steps,
        reverse: secondGeometry.reverse,
        colormap: secondGeometry.colormap,
      });
      ctx.mapper2.setLookupTable(lut);
      ctx.mapper2.setUseLookupTableScalarRange(true);
      ctx.mapper2.setScalarRange(secondGeometry.rangeMin, secondGeometry.rangeMax);
      ctx.mapper2.setColorModeToMapScalars();
      ctx.mapper2.setScalarModeToUsePointFieldData();
      ctx.mapper2.setColorByArrayName(
        colorArrayForDisplay(ctx, ctx.polydata2, secondGeometry.scalar, colorSmoothIters, 'adjacency2'),
      );
      ctx.mapper2.setInterpolateScalarsBeforeMapping(true);
      if (cancelled) return;
      // Frame both meshes together only when the second mesh is (re)loaded.
      if (isNew) applyCameraPose(ctx, true);
      else ctx.renderWindow?.render();
    }

    rebuild2();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    secondGeometry?.url,
    secondGeometry?.scalar,
    secondGeometry?.rangeMin,
    secondGeometry?.rangeMax,
    secondGeometry?.steps,
    secondGeometry?.reverse,
    secondGeometry?.colormap,
    // Re-frame both when the PRIMARY mesh changes underneath a live second mesh.
    geometry?.url,
    colorSmoothIters,
  ]);

  // ---- clip box: move the 6 planes, toggle them on the mapper, recompute the
  // per-vertex visible mask ---------------------------------------------------
  // A point is "inside" the box (visible) when xmin<=x<=xmax (and same for y/z).
  // Each plane's normal points INWARD (e.g. xmin plane has normal +X), so
  // vtk.js clips away everything on the negative side of every plane — i.e.
  // outside the box. The mask uses the identical inequality so the Stats panel
  // sees exactly what the mapper is drawing — never an approximation.
  useEffect(() => {
    const ctx = contextRef.current;
    if (!ctx || !ctx.mapper) return;
    const { mapper, clipPlanes, polydata } = ctx;

    if (!clipBox) {
      if (ctx.clipActive) {
        mapper.removeAllClippingPlanes();
        ctx.clipActive = false;
        ctx.renderWindow?.render();
      }
      onVisibleMaskRef.current?.(null);
      return;
    }

    const { xmin, xmax, ymin, ymax, zmin, zmax } = clipBox;
    clipPlanes.xmin.setOrigin(xmin, 0, 0);
    clipPlanes.xmax.setOrigin(xmax, 0, 0);
    clipPlanes.ymin.setOrigin(0, ymin, 0);
    clipPlanes.ymax.setOrigin(0, ymax, 0);
    clipPlanes.zmin.setOrigin(0, 0, zmin);
    clipPlanes.zmax.setOrigin(0, 0, zmax);

    if (!ctx.clipActive) {
      Object.values(clipPlanes).forEach((p) => mapper.addClippingPlane(p));
      ctx.clipActive = true;
    }
    ctx.renderWindow?.render();

    // Per-vertex visible mask, same order as the point-data arrays.
    if (polydata) {
      const pts = polydata.getPoints().getData();
      const nPts = pts.length / 3;
      const mask = new Uint8Array(nPts);
      for (let i = 0; i < nPts; i += 1) {
        const x = pts[i * 3];
        const y = pts[i * 3 + 1];
        const z = pts[i * 3 + 2];
        mask[i] =
          x >= xmin && x <= xmax && y >= ymin && y <= ymax && z >= zmin && z <= zmax
            ? 1
            : 0;
      }
      onVisibleMaskRef.current?.(mask);
    } else {
      onVisibleMaskRef.current?.(null);
    }
  }, [
    clipBox?.xmin,
    clipBox?.xmax,
    clipBox?.ymin,
    clipBox?.ymax,
    clipBox?.zmin,
    clipBox?.zmax,
    geometry?.url,
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
      ctx.planeSizeMm = plane.sizeMm ?? 200; // for the grab-to-slide sensitivity
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
