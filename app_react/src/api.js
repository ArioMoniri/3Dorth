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
  },
) {
  const body = { mode, params, formats, dpi };
  if (side != null) body.side = side;
  if (referenceSide != null) body.reference_side = referenceSide;
  if (targetSide != null) body.target_side = targetSide;
  if (regionLabel != null) body.region_label = regionLabel;
  if (camera) body.camera = camera;
  if (manualTransform !== undefined) body.manual_transform = manualTransform;
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
