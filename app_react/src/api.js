// Thin client for the 3Dorth FastAPI backend. All requests go through the Vite
// dev proxy (/api -> http://localhost:8000). This file contains NO analysis
// logic — it only fetches data the Python `core/` produced.

async function getJSON(url) {
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`GET ${url} -> ${res.status} ${res.statusText}`);
  }
  return res.json();
}

// GET /api/parameters -> { keys, controls, defaults }
export function fetchParameters() {
  return getJSON('/api/parameters');
}

// GET /api/parameters/mode/{A|B} -> { controls }
export function fetchModeControls(mode) {
  return getJSON(`/api/parameters/mode/${mode}`);
}

// GET /api/demo/manifest -> manifest object (see API contract)
export function fetchManifest() {
  return getJSON('/api/demo/manifest');
}

// Static geometry lives under /api/geometry/<file>. We fetch as ArrayBuffer so
// vtkXMLPolyDataReader.parseAsArrayBuffer can consume it.
export async function fetchGeometryArrayBuffer(file) {
  const url = `/api/geometry/${file}`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`GET ${url} -> ${res.status} ${res.statusText}`);
  }
  return res.arrayBuffer();
}
