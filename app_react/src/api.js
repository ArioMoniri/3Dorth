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

// GET /api/parameters -> { keys, controls, defaults }
export function fetchParameters() {
  return getJSON('/api/parameters');
}

// POST /api/session (NO body) -> { session_id, sides, meta, is_bilateral }
export function createSession() {
  return postJSON('/api/session');
}

// POST /api/upload (multipart, field 'file' = .zip) -> same shape as /session
export async function uploadZip(file) {
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
export function compare(sessionId, { referenceSide, targetSide, params }) {
  return postJSON(`/api/session/${sessionId}/compare`, {
    reference_side: referenceSide,
    target_side: targetSide,
    params,
  });
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
