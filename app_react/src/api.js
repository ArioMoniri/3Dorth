// Thin client for the 3Dorth FastAPI backend. All requests go through the Vite
// dev proxy (/api -> http://localhost:8000). This file contains NO analysis
// logic — it only talks to the Python `core/` pipeline.
//
// The compute endpoints (analyze / compare) RE-RUN segmentation + thickness with
// the CURRENT params, so every side-panel parameter genuinely affects the
// result once the UI sends it.

async function getJSON(url) {
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`GET ${url} -> ${res.status} ${res.statusText}`);
  }
  return res.json();
}

// POST a JSON body and return the parsed response. On a non-2xx status we throw
// an Error whose `.status` is the HTTP code and whose message carries the
// server's `detail` (so callers can render 501/422 gracefully).
async function postJSON(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { detail: text };
  }
  if (!res.ok) {
    const detail =
      typeof data?.detail === 'string'
        ? data.detail
        : Array.isArray(data?.detail)
          ? data.detail.map((d) => d.msg || JSON.stringify(d)).join('; ')
          : `${res.status} ${res.statusText}`;
    const err = new Error(detail);
    err.status = res.status;
    err.detail = data?.detail;
    throw err;
  }
  return data;
}

// GET /api/config -> { app, react_url, trame_url, public }
export function fetchConfig() {
  return getJSON('/api/config');
}

// GET /api/session/{sid}/region-thumbnails?side=<side>
//   -> { thumbnails: [ { label, volume_cm3, boneness, thumb: url|null } ] }
// Small per-bone-region renders so the region picker is visual. The compute
// takes ~5-10 s server-side; callers should show a spinner and cache the result
// per (session_id, side).
export function fetchRegionThumbnails(sessionId, side) {
  return getJSON(
    `/api/session/${sessionId}/region-thumbnails?side=${encodeURIComponent(side)}`,
  );
}

// GET /api/parameters -> { keys, controls, defaults }
export function fetchParameters() {
  return getJSON('/api/parameters');
}

// POST /api/session (NO body) -> { session_id, sides, meta, is_bilateral }
export function createSession() {
  return postJSON('/api/session');
}

// POST /api/upload (multipart, field 'file') -> same shape as /session.
// Accepts .zip .nii .nii.gz .stl .ply .obj .vtp. A mesh upload returns
// sides:['mesh'], is_mesh:true; a single-sided scan returns sides:['full'].
export async function uploadFile(file) {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch('/api/upload', { method: 'POST', body: form });
  const text = await res.text();
  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { detail: text };
  }
  if (!res.ok) {
    const detail =
      typeof data?.detail === 'string'
        ? data.detail
        : Array.isArray(data?.detail)
          ? data.detail.map((d) => d.msg || JSON.stringify(d)).join('; ')
          : `${res.status} ${res.statusText}`;
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  return data;
}

// POST /api/session/{sid}/analyze -> thickness result for one side.
export function analyze(sessionId, { side, regionLabel, params }) {
  const body = { side, params };
  if (regionLabel != null) body.region_label = regionLabel;
  return postJSON(`/api/session/${sessionId}/analyze`, body);
}

// POST /api/session/{sid}/compare -> two-side deviation result.
// `manualTransform` is an optional 4x4 row-major list (or null) applied on top
// of the auto registration to manually nudge the target onto the reference.
export function compare(
  sessionId,
  { referenceSide, targetSide, params, manualTransform },
) {
  const body = {
    reference_side: referenceSide,
    target_side: targetSide,
    params,
  };
  if (manualTransform !== undefined) body.manual_transform = manualTransform;
  return postJSON(`/api/session/${sessionId}/compare`, body);
}

// POST /api/session/{sid}/export -> { files:{fmt:url}, mode, scalar }.
// mode 'A' exports a single side's thickness map; mode 'B' a deviation map.
export function exportResult(
  sessionId,
  {
    mode,
    side,
    referenceSide,
    targetSide,
    regionLabel,
    params,
    formats,
    dpi,
    camera,
    manualTransform,
    annotate,
  },
) {
  const body = { mode, params, formats, dpi };
  if (side != null) body.side = side;
  if (referenceSide != null) body.reference_side = referenceSide;
  if (targetSide != null) body.target_side = targetSide;
  if (regionLabel != null) body.region_label = regionLabel;
  if (camera) body.camera = camera;
  if (manualTransform !== undefined) body.manual_transform = manualTransform;
  // Fig-2 measurement overlays for raster/DICOM exports (auto-placed when the
  // value is `true`). Omitted -> plain export.
  if (annotate !== undefined && annotate !== null) body.annotate = annotate;
  return postJSON(`/api/session/${sessionId}/export`, body);
}

// ---- MPR image viewer (slice-on-demand) ----------------------------------
// The volume never leaves the server: the browser only ever pulls small
// windowed PNG slices + tiny geometry JSON. See docs/IMAGING_DESIGN.md.

// GET /api/session/{sid}/volume-info?side=<side>
//   -> { side, shape_zyx, spacing_mm, offset_xyz_mm, origin_mm, extent_mm,
//        hu_range, default_window, default_level, planes, n_slices, orientation }
// Geometry the MPR viewer needs to lay out planes and map the 3D crosshair.
// Cheap, cacheable, no pixels. `side` is optional (defaults server-side to the
// first side of the session).
export function fetchVolumeInfo(sessionId, side) {
  const q = side ? `?side=${encodeURIComponent(side)}` : '';
  return getJSON(`/api/session/${sessionId}/volume-info${q}`);
}

// Build the URL for one windowed, aspect-correct PNG slice. Returned as a plain
// string so it can drop straight into an <img src>. `index` is clamped
// server-side (scrubbing past the end holds the last slice). All planes are
// array-oriented (axial=fix z, coronal=fix y, sagittal=fix x).
export function sliceUrl(
  sessionId,
  { side, plane, index, window, level, maxDim },
) {
  const p = new URLSearchParams();
  p.set('plane', plane);
  p.set('index', String(Math.round(index)));
  if (side) p.set('side', side);
  if (window != null) p.set('window', String(window));
  if (level != null) p.set('level', String(level));
  if (maxDim != null) p.set('max_dim', String(Math.round(maxDim)));
  return `/api/session/${sessionId}/slice?${p.toString()}`;
}

// POST /api/session/{sid}/pick-to-slices { side, world_xyz_mm:[x,y,z] }
//   -> { voxel_ijk:[ix,iy,iz], in_bounds, slices:{axial,coronal,sagittal},
//        world_xyz_mm }
// Maps a 3D world pick (from clicking the mesh) to the three slice indices, so
// clicking the bone moves all three MPR crosshairs. Pure arithmetic on the
// server; shared with the trame path so both frontends stay honest.
export function pickToSlices(sessionId, { side, worldXyz }) {
  const body = { world_xyz_mm: worldXyz };
  if (side) body.side = side;
  return postJSON(`/api/session/${sessionId}/pick-to-slices`, body);
}

// Geometry .vtp files are served at the geometry_url returned by analyze/compare.
// Fetch as an ArrayBuffer so vtkXMLPolyDataReader.parseAsArrayBuffer can consume
// it. geometryUrl already starts with /api/... so it flows through the proxy.
export async function fetchGeometryArrayBuffer(geometryUrl) {
  const res = await fetch(geometryUrl);
  if (!res.ok) {
    throw new Error(`GET ${geometryUrl} -> ${res.status} ${res.statusText}`);
  }
  return res.arrayBuffer();
}

// POST /api/session/{sid}/compare-slice-map
//   body: { reference_side, target_side, world_xyz_mm, params?, manual_transform? }
//   -> { reference:{world_xyz_mm,voxel_ijk,in_bounds,slices}, target:{...same...},
//        registration:{ rms_mm, inlier_fraction, reliable, note } }
// Linked cross-section lookup (Phase IV): maps a crosshair on the reference
// volume to the matching slice on the target volume via the (server-cached)
// registration. `reliable=false` means low overlap — the caller MUST surface
// this (amber banner), never silently trust the returned target slice.
export function compareSliceMap(
  sessionId,
  { referenceSide, targetSide, worldXyz, params, manualTransform },
) {
  const body = {
    reference_side: referenceSide,
    target_side: targetSide,
    world_xyz_mm: worldXyz,
    params: params || {},
  };
  if (manualTransform !== undefined) body.manual_transform = manualTransform;
  return postJSON(`/api/session/${sessionId}/compare-slice-map`, body);
}

// POST /api/session/{sid}/oblique-slice
//   body: { side?, origin_xyz_mm:[x,y,z], normal:[nx,ny,nz], up?:[ux,uy,uz],
//           size_mm?, px_mm?, max_dim?, window?, level? }
//   -> { image_png_base64, meta:{ origin_xyz_mm, normal, u, v, px_mm, size_px,
//        size_mm } }
// Arbitrary (tiltable) cross-section reformat (Phase VII): the volume is
// sampled on the plane (origin + normal); the returned image is that reformat,
// with an EXACT pixel<->world basis in `meta` (see oblique_pixel_to_world /
// world_to_oblique_pixel in core.viz.slice — mirrored client-side in
// obliquePixelToWorld below so a 2D click maps to the exact 3D point).
export function obliqueSlice(
  sessionId,
  { side, originXyz, normal, up, sizeMm, pxMm, window, level, maxDim },
) {
  const body = { origin_xyz_mm: originXyz, normal };
  if (side) body.side = side;
  if (up) body.up = up;
  if (sizeMm != null) body.size_mm = sizeMm;
  if (pxMm != null) body.px_mm = pxMm;
  if (window != null) body.window = window;
  if (level != null) body.level = level;
  if (maxDim != null) body.max_dim = maxDim;
  return postJSON(`/api/session/${sessionId}/oblique-slice`, body);
}

// Exact client-side mirror of core.viz.slice.oblique_pixel_to_world: maps a
// pixel (row, col) on the returned oblique reformat to its 3D world point,
// using ONLY the response's own meta (never approximated / fabricated).
//   world = origin + (col - c0)*px_mm*u + (row - c0)*px_mm*v,  c0 = (size_px-1)/2
export function obliquePixelToWorld(meta, row, col) {
  const { origin_xyz_mm: o, u, v, px_mm: px, size_px: sizePx } = meta;
  const c0 = (sizePx - 1) / 2;
  return [
    o[0] + (col - c0) * px * u[0] + (row - c0) * px * v[0],
    o[1] + (col - c0) * px * u[1] + (row - c0) * px * v[1],
    o[2] + (col - c0) * px * u[2] + (row - c0) * px * v[2],
  ];
}

// POST /api/session/{sid}/oblique-compare
//   body: { reference_side, target_side, origin_xyz_mm:[x,y,z], normal:[nx,ny,nz],
//           up?, size_mm?, px_mm?, max_dim?, window?, level?, params?, manual_transform? }
//   -> { reference:{ image_png_base64, meta }, target:{ image_png_base64, meta },
//        registration:{ rms_mm, inlier_fraction, reliable, note } }
// Two-bone matched oblique (Phase VII compare): ONE reference oblique plane is
// mapped through the cached rigid registration onto the target bone, so BOTH
// boxes show the SAME physical cut. The FIRST call for a (sides,params) pair
// runs the heavy registration (can take ~1-2 min); it is then cached, so moving
// the plane afterwards only re-samples (fast). reliable=false MUST be surfaced
// (amber banner) — never hidden.
export function obliqueCompare(
  sessionId,
  {
    referenceSide,
    targetSide,
    originXyz,
    normal,
    up,
    sizeMm,
    pxMm,
    window,
    level,
    maxDim,
    params,
    manualTransform,
  },
) {
  const body = {
    reference_side: referenceSide,
    target_side: targetSide,
    origin_xyz_mm: originXyz,
    normal,
  };
  if (up) body.up = up;
  if (sizeMm != null) body.size_mm = sizeMm;
  if (pxMm != null) body.px_mm = pxMm;
  if (window != null) body.window = window;
  if (level != null) body.level = level;
  if (maxDim != null) body.max_dim = maxDim;
  if (params !== undefined) body.params = params;
  if (manualTransform !== undefined) body.manual_transform = manualTransform;
  return postJSON(`/api/session/${sessionId}/oblique-compare`, body);
}

// ---- statistics figures (publication-style PNG/TIFF/JPG) ------------------
// POST /api/session/{sid}/figures
//   body: { mode:'A'|'B', side|reference_side/target_side, region_label?,
//           params?, which?:['histogram','by_region'], manual_transform? }
//   -> { figures: { histogram?: base64 png, by_region?: base64 png }, note }
// Reuses the SAME analyze/compare cache the interactive viewer already
// populated, so this never re-runs segmentation/thickness/registration just
// to draw a figure. `note` states the single-subject/descriptive scope and,
// when `by_region` was requested but the data doesn't support it (<2 regions,
// or Mode B), explains why it was omitted — never fabricate groups.
export function fetchFigures(
  sessionId,
  { mode, side, referenceSide, targetSide, regionLabel, params, which, manualTransform },
) {
  const body = { mode, params: params || {} };
  if (side != null) body.side = side;
  if (referenceSide != null) body.reference_side = referenceSide;
  if (targetSide != null) body.target_side = targetSide;
  if (regionLabel != null) body.region_label = regionLabel;
  if (which !== undefined) body.which = which;
  if (manualTransform !== undefined) body.manual_transform = manualTransform;
  return postJSON(`/api/session/${sessionId}/figures`, body);
}

// POST /api/session/{sid}/export-figures -> same body as fetchFigures plus
// { formats:['png','tiff','jpg'], dpi }.
//   -> { files: { histogram|histogram_<fmt>|by_region|by_region_<fmt>: url },
//        mode, scalar, note }
// Each requested figure is written in EVERY requested format (2 figures x 2
// formats = 4 files). When exactly one format is requested the keys are bare
// (`histogram`); with >1 format they are suffixed (`histogram_png`).
export function exportFigures(
  sessionId,
  {
    mode,
    side,
    referenceSide,
    targetSide,
    regionLabel,
    params,
    which,
    manualTransform,
    formats,
    dpi,
  },
) {
  const body = { mode, params: params || {}, formats, dpi };
  if (side != null) body.side = side;
  if (referenceSide != null) body.reference_side = referenceSide;
  if (targetSide != null) body.target_side = targetSide;
  if (regionLabel != null) body.region_label = regionLabel;
  if (which !== undefined) body.which = which;
  if (manualTransform !== undefined) body.manual_transform = manualTransform;
  return postJSON(`/api/session/${sessionId}/export-figures`, body);
}

// GET /api/session/{sid}/model.glb -> binary glTF URL of the most-recently-
// computed surface (thickness or deviation), per-vertex colour baked in. 409
// if nothing has been computed yet. Returned as a plain URL string (like
// sliceUrl) so it can drop straight into a <model-viewer src="..."> — the
// element itself performs the GET.
export function modelGlbUrl(sessionId) {
  return `/api/session/${sessionId}/model.glb`;
}
