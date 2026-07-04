# IMAGING_DESIGN — Technical approach & API contract

**Author:** Marcus Vogel (senior medical-imaging web engineer)
**Scope:** In-panel MPR image viewer, movable cross-section, two-bone compare, and AR — for the existing 3Dorth cortical-thickness app.
**Status:** Design (Phase I gate). Research tool, de-identified only, **not diagnostic**.

This document is deliberately grounded in the code that exists today. Where the plan in `GOAL_IMAGING.md` is under-specified or optimistic, I flag it in **⚠ REALITY** notes rather than paper over it.

---

## 0. What already exists (and why it constrains the design)

I read the core before designing. The load-bearing facts:

- **Session model** (`api/routers/session.py`): an in-memory `SESSIONS[sid]` dict holds
  `{"arr": int16[z,y,x] HU, "spacing": (sx,sy,sz) mm, "meta": {...}, "sides": {...}}`.
  `sides` maps a side name (`"full"`, or `"left"`/`"right"`, or `"mesh"`) to
  `{"arr", "spacing", "offset_xyz", "side"}`. Volumes are int16 (half the RAM of float32) and
  block-downsampled to a voxel budget by `core.resources.downsample_to_budget`. Max 3 sessions,
  oldest evicted (`_evict_old_sessions`).
- **Coordinate convention — THE critical fact.** `core.pipeline` loads via SimpleITK but then
  **keeps only `arr` + `spacing` and throws away the image origin and direction cosines.** Every
  mesh is placed into world mm as:

  ```
  world_xyz = (ix, iy, iz) * (sx, sy, sz)  +  offset_xyz     # analyze_thickness, line ~262
  ```

  i.e. the app's world frame is an **axis-aligned frame with implicit origin (0,0,0) and identity
  direction**, in `(x=col, y=row, z=slice)` order, scaled by spacing. The bilateral split gives the
  `left` side an x-offset (`offset_xyz = (left_lo*sx, 0, 0)`) so both halves share one frame.
  **⚠ This is the frame the crosshair must use.** We do NOT have DICOM patient (LPS) coordinates in
  the session, so the viewer must NOT claim anatomical L/R/A/P/S/I labels beyond the app's own
  `left`/`right` side tags. Fixing that (persisting origin+direction) is optional future work; the
  MPR viewer works correctly without it because slices, the 3D mesh, and the crosshair all live in
  the *same* `voxel*spacing` frame.
- **Registration** (`core/registration/register.py` + `core/pipeline.compare_sides`): Mode B mirrors
  the target side across x, runs FPFH+RANSAC → point-to-plane ICP, and returns a **4×4 homogeneous
  `transform` (list-of-lists) that maps moving(source) points into the reference frame**, plus
  `rms` and `inlier_fraction`. `compare_sides` composes an optional manual 4×4 nudge as `M @ auto`.
  This 4×4 is exactly what Compare needs to put both viewers on the same plane.
- **Export** (`core/export/mesh.py`, `bundle.py`): already writes stl/ply/obj/vtp via `pyvista`
  `.save()`. **No GLB yet.** `export_bundle` takes `formats=(...)` and dispatches by extension — the
  natural insertion point for `"glb"`.
- **Frontends:** React (`app_react`, vtk.js, talks to the HTTP API) and trame (`app_trame`, server-side
  pyvista, calls `core` directly). Parity is enforced by both iterating the parameter registry.
  Neither has any slice/DICOM viewer today.

**Consequence:** the MPR feature is almost entirely additive on the backend (one slice endpoint +
one geometry endpoint reading the volume already in `SESSIONS`), and additive on the frontends (a new
viewer component). It does **not** require re-plumbing compute.

---

## 1. Decision: how the MPR gets its pixels

Three candidate architectures were on the table. Decision matrix, judged against *runs on a modest
laptop and a phone, RAM-bounded, no full-volume browser transfer, honest*:

| Option | Browser RAM | Server RAM | Network | Anisotropy handling | Verdict |
|---|---|---|---|---|---|
| **A. Slice-on-demand PNG** (`GET .../slice → PNG`) | ~1 slice (≤0.5 MB) | volume already resident | ~30–150 KB/slice | server resamples once | **CHOSEN** |
| B. Ship a downsampled `.vti`/vtkjs volume | **whole volume in JS/GPU** (tens–hundreds MB) | serialize+gzip whole volume | 5–50 MB up front | client must resample | Rejected |
| C. Cornerstone (cornerstone3D) | per-slice or per-volume | needs DICOMweb (WADO-RS) or custom loader | — | good, but heavy | Rejected |

**Chosen: (A) slice-on-demand PNG, rendered server-side, one 2D `<canvas>`/`<img>` per plane.**

Justification:

1. **RAM.** The `GOAL` non-negotiable is "no full-volume browser transfer; `core/resources` limits
   still hold." (B) violates this by definition — even a downsampled volume is Nx a single slice and
   lands in JS heap + WebGL texture memory, which is exactly what kills a phone. (A) keeps the browser
   at ~one decoded slice per plane (3 planes ≈ a few hundred KB).
2. **The volume is already server-resident.** `SESSIONS[sid]["arr"]` is an int16 numpy array in
   process. A slice is a single `arr[k]` / `arr[:,k]` / `arr[:,:,k]` view — O(1) allocation, no re-read
   from disk, no new large buffer. Windowing (level/width → 8-bit) is one `np.clip`+scale on a 2D
   array. This is the cheapest possible thing the server can do and it reuses the existing memory
   budget rather than adding to it.
3. **Cornerstone (C) is the wrong tool here.** cornerstone3D is excellent, but its natural feed is
   DICOMweb/WADO. We deliberately are **not** standing up Orthanc/dcm4chee (`GOAL`), and our volume is
   frequently NIfTI or a mesh, not addressable DICOM instances. Wrapping cornerstone around a custom
   slice loader buys us nothing over a plain `<canvas>` blitting our own PNG, and adds a large
   dependency + its own coordinate/metadata model that would fight our `voxel*spacing` frame.
   vtk.js (React) and pyvista (trame) are already in the stack; we render the MPR with what we have.
4. **Honesty / "never fabricate a view."** Server-side rendering from the real `arr` means every pixel
   shown is a real resampled CT value. No interpolation guesses happen in a black-box client volume.

**Server-side vs client-side windowing.** We window on the **server** and return an 8-bit PNG.
Rationale: keeps the browser trivial, keeps int16 HU on the server only, and makes the trame path (no
JS) identical. Cost: a window/level drag re-hits the endpoint. We bound that (see §6): PNGs are tiny,
the slice is cached, and we debounce the drag. If profiling later shows window/level dragging is
janky, the *targeted* upgrade is to return a single-channel 16-bit PNG per slice-index and do the W/L
LUT in a WebGL fragment shader client-side — but that's a Phase-III+ optimization, not the MVP, and it
does not change the endpoint's index semantics.

---

## 2. API contract

All new endpoints are additive under the existing `/api` prefix and read from the in-memory
`SESSIONS`. Nothing here loads a second copy of the volume.

### 2.1 `GET /api/session/{sid}/volume-info`

Geometry the viewer needs to lay out planes and map the 3D crosshair. Cheap, cacheable, no pixels.

**Query:** `side` (optional; default = first side, e.g. `full` / `left` / `right`).

**200 response:**

```jsonc
{
  "side": "left",
  "shape_zyx": [220, 512, 300],           // arr.shape of THIS side's sub-volume
  "spacing_mm": [0.49, 0.49, 0.6],        // (sx, sy, sz) — x=col, y=row, z=slice
  "offset_xyz_mm": [92.4, 0.0, 0.0],      // side["offset_xyz"]; world = idx*spacing + offset
  "origin_mm": [0.0, 0.0, 0.0],           // app world origin (see §0: implicit; direction = identity)
  "extent_mm": {                          // convenience bbox in the app world frame
    "x": [92.4, 239.4], "y": [0.0, 250.9], "z": [0.0, 132.0]
  },
  "hu_range": [-1024, 3071],              // for default window/level UI bounds
  "default_window": 1800, "default_level": 400,   // bone preset
  "planes": ["axial", "coronal", "sagittal"],
  "n_slices": { "axial": 220, "coronal": 512, "sagittal": 300 },
  "is_bilateral": true
}
```

Plane ↔ axis mapping (fixed, documented so the frontend and the crosshair agree):

| Plane | Fixed axis (index varies) | In-plane axes (image cols × rows) | `index` range |
|---|---|---|---|
| `axial` | z (slice) | x × y | `0..shape_zyx[0]-1` |
| `coronal` | y (row) | x × z | `0..shape_zyx[1]-1` |
| `sagittal` | x (col) | y × z | `0..shape_zyx[2]-1` |

⚠ **REALITY:** these are *array-orientation* planes, not guaranteed radiological axial/coronal/sagittal
unless the source was acquired axial+isotropic-ish. The demo shoulder CT is axial, so it's correct
there. The viewer labels them "axial/coronal/sagittal (array orientation)" in a tooltip and never
asserts patient A/P/S/I. This is the honest thing to do given we discarded direction cosines (§0).

### 2.2 `GET /api/session/{sid}/slice` → `image/png`

The MPR pixel source.

**Query params:**

| Param | Type | Default | Meaning |
|---|---|---|---|
| `side` | str | first side | which sub-volume |
| `plane` | `axial\|coronal\|sagittal` | required | slicing plane (see table above) |
| `index` | int | required | slice index along the fixed axis for that plane |
| `window` | float | `default_window` | window width in HU |
| `level` | float | `default_level` | window center in HU |
| `max_dim` | int | 512 | longest output edge in px (server caps; bounds bytes) |
| `overlay` | `none\|bone` | `none` | optional: shade the segmented bone mask on the slice |

**Behaviour (server):**

1. `s = SESSIONS[sid]; sub = s["sides"][side]; arr = sub["arr"]` — already resident.
2. Extract the 2D plane as a **view** (`arr[index]` / `arr[:, index, :]` / `arr[:, :, index]`).
3. **Aspect correction:** scale the 2D array so on-screen pixels are square in mm, using the two
   in-plane spacings (e.g. coronal uses `sx` × `sz`). This is the one place anisotropic slabs matter;
   we resample with `PIL`/`scipy.ndimage.zoom` order-1 to a physically-square grid, then cap the long
   edge at `max_dim`.
4. **Window/level → uint8:** `out = clip((hu - (level - window/2)) / window, 0, 1) * 255`.
5. Encode PNG (grayscale, or RGB if `overlay=bone`), stream with
   `Cache-Control: private, max-age=300` and an `ETag` of `(sid,side,plane,index,window,level,max_dim)`.

**Responses:** `200 image/png`; `404` session/side unknown; `422` bad plane; `416`-style clamp — we
**clamp** `index` into range rather than error (dragging past the end just holds the last slice).

**Why PNG not JPEG:** CT slices have sharp high-contrast bone edges; JPEG ringing there is visually
misleading on a research image. PNG of a windowed 512² grayscale is ~30–120 KB — acceptable.

⚠ **REALITY / bound:** aspect-correct resampling is the only per-slice compute cost. It is a single
2D `zoom` on ≤512² — sub-millisecond to a few ms. It runs **outside** `COMPUTE_SEMAPHORE` (it is not
heavy compute; serializing it behind segmentation would make scrubbing feel broken). But we add a
tiny per-session slice LRU (see §6) so repeated scrubs are free.

### 2.3 `POST /api/session/{sid}/pick-to-slices`

Maps a 3D world pick (from clicking the mesh) to the three slice indices — so clicking the bone moves
all three MPR crosshairs. Pure arithmetic; no compute.

**Body:** `{ "side": "left", "world_xyz_mm": [131.2, 88.0, 40.5] }`

**200:**

```jsonc
{
  "voxel_ijk": [79, 179, 67],                       // rounded (see §3 for the math)
  "in_bounds": true,
  "slices": { "axial": 67, "coronal": 179, "sagittal": 79 },
  "world_xyz_mm": [131.2, 88.0, 40.5]
}
```

The inverse (slice crosshair → 3D marker position) is done **client-side** from `volume-info`
(§3) — no round trip needed for that direction.

### 2.4 `GET /api/session/{sid}/compare-slice-map`

For Compare (Mode B): given a **reference** world point, return the matched **target** slice indices
using the Mode-B registration transform, so both MPR stacks show the same anatomical plane. See §4.

**Query:** `reference_side`, `target_side`, and the same params that drive `compare` (so we reuse the
already-computed transform when available; recompute only if absent).
**Body/params carry** `world_xyz_mm` (a point in the reference frame).

**200:**

```jsonc
{
  "transform_4x4": [[...],[...],[...],[0,0,0,1]],   // moving(target)->reference, from register()
  "reference": { "slices": {"axial":67,"coronal":179,"sagittal":79}, "world_xyz_mm":[...] },
  "target":    { "slices": {"axial":71,"coronal":175,"sagittal":88}, "world_xyz_mm":[...],
                 "in_bounds": true },
  "mirrored": true,                                 // params.mirror_sagittal
  "registration": { "rms": 0.42, "inlier_fraction": 0.97 }
}
```

### 2.5 `GET /api/session/{sid}/model.glb` → `model/gltf-binary`

AR MVP asset. Streams a GLB of the **currently displayed** result mesh (thickness- or deviation-
colored), for `<model-viewer>` / Quick Look / Scene Viewer.

**Query:** the same selector the export endpoint uses (`mode=A|B`, `side` or `reference_side`/
`target_side`, `region_label`, `params` as a JSON string or reuse a cached compute), plus
`draco=0|1` (default 1 = Draco-compress geometry). Implementation reuses `_compute_for_export` then a
new `export_mesh(..., fmt="glb")` path (§5). Response is a single `.glb` with
`Content-Disposition: inline`.

⚠ **REALITY:** iOS Quick Look does **not** accept GLB; it needs **USDZ**. See §5.3 — we add an
optional `.usdz` sibling and let the frontend pick per-platform, or document iOS as "Android AR now,
iOS AR when USDZ lands."

---

## 3. Crosshair ↔ 3-plane coordinate mapping

Everything lives in the app's `voxel*spacing + offset` world frame (§0), so the math is a diagonal
affine — no direction cosines, no matrix inversion surprises.

**World → voxel (used by `pick-to-slices`):**

```
ix = round( (X - offset_x - origin_x) / sx )     # column  -> sagittal index
iy = round( (Y - offset_y - origin_y) / sy )     # row     -> coronal index
iz = round( (Z - offset_z - origin_z) / sz )     # slice   -> axial index
```

`origin = (0,0,0)` today; kept explicit so a future "persist origin/direction" change is a one-line
edit, not a rewrite.

**Voxel → world (used client-side when a slice crosshair is dragged):**

```
X = ix*sx + offset_x ;  Y = iy*sy + offset_y ;  Z = iz*sz + offset_z
```

**Linking behaviour (both frontends):**

- **3D pick → planes.** vtk.js/pyvista already surface the picked world point for the hover tooltip.
  On click we `POST pick-to-slices` (or compute locally from `volume-info`; the endpoint exists mainly
  so the trame server path and the React path share one implementation and stay honest). All three MPR
  panels jump to the returned indices and draw a crosshair at the in-plane `(ix,iy)/(ix,iz)/(iy,iz)`.
- **Slice scrub → 3D.** Scrubbing the axial slider sets `iz`; the other two crosshairs and a small 3D
  sphere marker (`voxel→world`) update. No server call.
- **In-plane click on an MPR → the other two planes + 3D.** A click at pixel `(u,v)` on the axial
  panel yields `(ix,iy)` (undo the aspect scale + `max_dim` scale first), keeps the current `iz`, and
  updates coronal (`iy`), sagittal (`ix`), and the 3D marker.

The crosshair is thus a single shared `{ix, iy, iz}` state; each of the four views (3 MPR + 3D) is a
pure function of it. This is the OHIF-*like* "linked cursor" without OHIF.

---

## 4. Compare: reusing the Mode-B registration for matched cross-sections

Requirement: pick a plane on bone A and show the *same anatomical* plane on bone B.

We already have the transform: `compare_sides` → `register()` returns `T` (4×4) mapping
**moving(target) surface points into the reference frame**, after an optional sagittal mirror of the
target. For the crosshair we need the direction that takes a **reference world point to a target
world point**, then target world → target voxel.

**Pipeline for a reference pick `P_ref` (world, reference side):**

1. We want the target point that lands on `P_ref` after registration. Registration maps
   `target → reference` via `moving' = mirror?(target); P_ref ≈ T · P_moving`. So
   `P_moving = T⁻¹ · P_ref`, then **undo the mirror** (reflect x about the target mesh centroid
   `c`, recorded at compare time): `P_target = mirror⁻¹(P_moving)`. Mirror is its own inverse given
   the same center, so `P_target,x = 2c - P_moving,x`.
2. `P_target` world → target voxel via §3 with the **target** side's spacing/offset.
3. Return both index triples (`compare-slice-map`, §2.4).

**Why this is correct and bounded:** `T` is already computed by the Compare action; we cache it on the
session keyed by `(reference_side, target_side, params-hash)` exactly like the mesh URLs are cached in
`api/routers/session.py`. No new registration runs on a crosshair move — only a 4×4 inverse (trivial)
and a mirror reflection. If Compare hasn't been run for the current params, `compare-slice-map` returns
`409 needs-compare` and the UI prompts "Run Compare first" rather than silently registering (which
would be a slow surprise).

⚠ **REALITY — what "same plane" honestly means.** The two scans are **rigidly** registered, so
"matched cross-section" means *the corresponding rigid-body point*, not a deformably-warped identical
anatomy. If the two bones differ in shape (the whole point of Mode B), the target slice through
`P_target` is the anatomically-closest plane, and any residual is exactly the `deviation_mm` already
shown. We surface `rms`/`inlier_fraction` next to the compare viewer so the user can judge how much to
trust the pairing. We do **not** claim voxel-perfect correspondence.

**Compare UI layout:** two `volume-info`s, two sets of three MPR panels (or a compact "reference axial
| target axial" pair with a plane switcher to save space on a laptop), driven by one shared reference
crosshair; the target crosshair is derived, never independently editable (editing it would break the
"same plane" contract — if the user wants free target scrolling, that's a separate un-linked mode we
can add later).

---

## 5. AR

### 5.1 GLB export path (backend)

Add a `glb` branch to `core/export/mesh.py` and register it in `bundle.py`'s `_MESH` set + the
`session/export` `formats` whitelist, and expose `GET .../model.glb` (§2.5).

**Implementation choice:** `pyvista.PolyData` → glTF. Two viable writers:

- **trimesh** (already a common transitive dep; if not, it's small): `trimesh.Trimesh(vertices, faces,
  vertex_colors=rgba)` → `.export(file, file_type="glb")`. Bakes per-vertex RGBA (from the same
  `_scalar_to_rgb` we already use for ply/obj) so the thickness/deviation coloring survives into AR.
  Supports optional **Draco** compression to shrink the file for a phone download.
- Fallback: VTK's `vtkGLTFExporter` (renders a scene, not a bare mesh — clunkier; needs a render
  window). Prefer trimesh.

```python
# core/export/mesh.py  (sketch)
def _export_glb(pd, out_path, scalar_name, cmap_name, clim, draco=True):
    import trimesh
    faces = pd.faces.reshape(-1, 4)[:, 1:]            # pyvista -> (n,3)
    rgb = _scalar_to_rgb(pd, scalar_name, cmap_name, clim) if scalar_name else None
    mesh = trimesh.Trimesh(vertices=np.asarray(pd.points), faces=faces,
                           vertex_colors=rgb, process=False)
    mesh.export(out_path, file_type="glb")            # Draco via exporter kwargs if available
```

Point/triangle count is already bounded: meshes are decimated in `analyze_thickness`
(`mesh_decimate_fraction`, default 0.3). A shoulder surface after decimation is ~10⁴–10⁵ triangles →
a **few hundred KB–2 MB GLB** — fine for a phone over the existing Cloudflare share. We add a hard
triangle cap in the GLB path (extra decimation if > ~250k tris) so a pathological upload can't produce
a 50 MB AR file.

### 5.2 `<model-viewer>` integration (frontend)

MVP AR is a button, not a renderer we own:

```html
<!-- served from the app; model-viewer is a self-contained web component -->
<model-viewer
   src="/api/session/{sid}/model.glb?mode=A&side=left&params=..."
   ios-src="/api/session/{sid}/model.usdz?..."      <!-- optional, iOS -->
   ar ar-modes="webxr scene-viewer quick-look"
   camera-controls shadow-intensity="1"
   alt="Cortical thickness surface (research, de-identified)">
</model-viewer>
```

- On desktop it's an interactive 3D preview; on a phone the **"View in AR"** glyph appears and hands
  off to **Scene Viewer (Android)** or **Quick Look (iOS)**.
- React: a small `<ARPanel>` that injects the `model-viewer` custom element (loaded as a static ESM
  chunk we vendor — ⚠ CSP/offline note: it must be bundled, not pulled from a CDN, to match the app's
  self-contained posture). trame: an `html.Div` embedding the same web component (trame can host raw
  HTML), pointed at the API's GLB URL. Parity holds because both point at the same endpoint.
- The AR button is shown **only on a result** and labeled with the de-identified/research caveat.

### 5.3 WebXR clipping-plane cross-section — a realistic assessment

`GOAL` Phase VI wants an in-AR clipping plane to cut the bone live. Honest device/browser reality
(as of 2026, and this has been true for years — do not over-promise):

| Capability | Android Chrome (ARCore) | iOS Safari |
|---|---|---|
| `<model-viewer>` place-in-room AR | ✅ Scene Viewer | ✅ Quick Look (**USDZ only, not GLB**) |
| **WebXR `immersive-ar` session** | ✅ supported | ❌ **not supported** (no WebXR AR in Safari) |
| Custom in-session clipping plane | ✅ (we render with three.js/WebGL, apply a clip plane) | ❌ |
| Quick Look custom interaction | ❌ (Quick Look is a closed viewer; no live clip) | ❌ |

**Conclusion / plan:**

- **WebXR clipping cross-section is Android-Chrome-only, prototype-tier.** We implement it as a
  separate `immersive-ar` mode using three.js (WebGL clipping planes are a one-liner:
  `renderer.clippingPlanes = [new THREE.Plane(normal, d)]`), fed the **same GLB** plus a slider that
  moves `d`. On iOS and on non-WebXR Android we **degrade gracefully** to the `<model-viewer>` MVP
  (place-in-room, no live clip) and show a one-line "live cross-section needs Android Chrome / WebXR."
- We **never fabricate**: if `navigator.xr?.isSessionSupported('immersive-ar')` is false, the WebXR
  button is not shown at all. No fake AR, no "AR unavailable but here's a spinning model pretending."
- iOS "cross-section in AR" is effectively **not doable** in the browser without a native app; we say
  so plainly in the UI and this doc. The iOS story is: Quick Look place-in-room via USDZ (if we add
  the USDZ export), otherwise desktop/Android for the clip.

⚠ **REALITY on USDZ:** generating USDZ server-side is non-trivial (needs `usd`/`usd-core` or Apple's
tooling; per-vertex color → USDZ material is fiddly). Recommendation: **ship GLB + Android/desktop AR
in Phase V**, and treat USDZ/iOS-Quick-Look as a **stretch** with its own spike, not a Phase-V blocker.
Don't let iOS AR gate the whole feature.

---

## 6. Keeping RAM/CPU bounded (the non-negotiable)

- **No full-volume transfer.** Only windowed 2D PNGs (§1) and a decimated GLB surface ever leave the
  server. The int16 volume stays in `SESSIONS` under the existing eviction + downsample budget.
- **Slice endpoint is O(1) memory:** a 2D view + one ≤512² uint8 buffer + PNG bytes. It does **not**
  take `COMPUTE_SEMAPHORE` (that's for segmentation/thickness/registration), so scrubbing never
  contends with a heavy compute — but if a heavy compute is running, the slice still just reads `arr`.
- **Per-session slice LRU cache.** Add a tiny `functools.lru_cache`-style cache keyed by
  `(sid, side, plane, index, window, level, max_dim)` holding the encoded PNG bytes (cap ~64 entries ≈
  a few MB/session; evicted with the session). Makes back-and-forth scrubbing and window/level tweaks
  free after first paint. This is the main thing that keeps the UI feeling instant.
- **Debounce window/level drags** on the client (~80 ms) so a drag fires a handful of requests, not
  hundreds. Slice-index scrubbing is fine un-debounced because of the cache.
- **`max_dim` cap** bounds both the resample cost and the PNG bytes regardless of a huge input matrix.
- **Compare caches the transform** (§4) so crosshair moves never re-register.
- **GLB triangle cap** (§5.1) bounds AR file size.

**What will be slow, and the bound:**

| Operation | Cost | Bound |
|---|---|---|
| First paint of a plane | 1 resample + PNG encode (~few ms) | `max_dim` cap; cached after |
| Window/level drag | N slice requests | debounce + LRU |
| Aspect resample on very anisotropic slabs | order-1 `zoom` on ≤512² | tiny; capped by `max_dim` |
| 3D pick → slices | arithmetic | trivial |
| Compare crosshair | 4×4 inverse + mirror | trivial (transform cached) |
| GLB export | decimated mesh → trimesh glb | reuses decimated mesh; tri cap |
| WebXR session | GPU render of one GLB | same mesh as MVP; Android only |

The genuinely heavy things (segmentation, thickness, registration) are **unchanged** and still gated
by `COMPUTE_SEMAPHORE`. The imaging feature adds only light, cacheable work.

---

## 7. Component plan — both frontends (parity)

### 7.1 React (`app_react`, vtk.js + HTTP API)

New components (mirroring the existing panel structure in `App.jsx`):

- **`src/mpr/MprPanel.jsx`** — grid of three `SliceView`s + the linked-crosshair state
  `{side, ix, iy, iz, window, level}`. Fetches `volume-info` once per (session, side).
- **`src/mpr/SliceView.jsx`** — one `<canvas>` (or `<img>`) that requests
  `/api/session/{sid}/slice?...`, draws the returned PNG, overlays a crosshair, handles scrub
  (wheel/slider) and in-plane click → updates shared crosshair. Debounced W/L.
- **`src/mpr/useCrosshair.js`** — the shared `{ix,iy,iz}` reducer + `voxel↔world` helpers from §3.
- **Wire into `Viewport.jsx`:** on mesh click, compute the world point (already available for the hover
  tooltip) → `pick-to-slices` → set crosshair; render a small sphere marker at `voxel→world`.
- **`src/compare/CompareMpr.jsx`** — two `MprPanel`s (reference editable, target derived via
  `compare-slice-map`), shown when Mode B / two sides; surfaces `rms`/`inlier_fraction`.
- **`src/ar/ARPanel.jsx`** — hosts the bundled `<model-viewer>` (GLB URL) + a WebXR button gated on
  `navigator.xr.isSessionSupported('immersive-ar')`; the WebXR path loads a small three.js clip-plane
  viewer. Shows research/de-identified caveat.
- **Layout:** a new **"Images"** tab/toggle in the center pane next to the existing 3D viewport (MPR
  beside the 3D map, per the goal), and an **"AR"** button in the export/pose area of `ControlPanel`.
- **`src/api.js`:** add `fetchVolumeInfo`, `sliceUrl(...)` (returns a URL string for `<img>`/canvas),
  `pickToSlices`, `compareSliceMap`, `glbUrl(...)`.

### 7.2 trame (`app_trame`, server-side pyvista, calls `core` directly)

trame renders server-side, so slices are produced by the **same core slice function** the API calls
(factor the windowing/aspect/encoding into `core/viz/slice.py` so both the FastAPI endpoint and trame
import it — this guarantees parity and one source of truth):

- **`core/viz/slice.py`** (NEW, shared) — `extract_slice(arr, spacing, plane, index) -> 2D`,
  `window_to_uint8(sl, window, level)`, `aspect_resample(sl, sp_a, sp_b, max_dim)`,
  `encode_png(...)`, and `world_to_voxel` / `voxel_to_world`. **Both frontends call this.**
- **trame MPR:** three `v3.VImg` (or a small pyvista 2D plotter) bound to reactive state
  `{ix,iy,iz,window,level}`; the crosshair state lives in trame's shared state; clicking the 3D
  pyvista surface (picking is already wired for the hover tooltip) updates it. A "Cross-section" clip
  actor on the 3D plotter can additionally show the plane in 3D (pyvista `add_mesh_clip_plane` / a plane
  widget) — a nice extra the server path gets cheaply.
- **trame Compare:** reuse `compare_sides`' transform (already available in-process) → the same §4 math
  → two slice stacks side by side.
- **trame AR:** an `html.Div` embedding the bundled `<model-viewer>` pointed at the API GLB URL (trame
  can serve/reference the same asset). WebXR clip is React/three.js-only in the prototype; trame shows
  the MVP place-in-room only. **Parity note:** MPR + compare + AR-MVP reach parity; the WebXR live-clip
  prototype is explicitly a React-only Phase-VI prototype (documented, not hidden), because it's an
  Android-Chrome WebGL session that doesn't fit trame's server-render model. This is the one honest
  parity asterisk.

### 7.3 Parity enforcement

- Add a `test_parity`-style check that both UIs expose: MPR (3 planes), a movable crosshair, compare,
  and an AR-MVP button — driven from a small shared feature manifest, same spirit as the existing
  registry-driven parameter parity.
- Because the slice math lives in `core/viz/slice.py`, a slice at `(plane,index,window,level)` is
  **byte-identical** between the API and trame — the strongest possible parity guarantee.

---

## 8. Risks & honest limitations

- **No patient coordinate frame.** We discarded DICOM origin/direction (§0). Planes are
  array-oriented, not guaranteed radiological. Mitigation: label them as such; optionally persist
  origin/direction later (small change) if true anatomical labeling is needed. **Do not** print A/P/S/I
  we can't back up.
- **iOS AR is limited.** No WebXR in Safari; Quick Look needs USDZ we don't yet generate. Android +
  desktop AR ship first; iOS is a documented follow-up. Don't let it block Phase V.
- **Compare is rigid, not deformable.** "Matched plane" = corresponding rigid point; residual = the
  `deviation_mm` we already show. We surface `rms`/`inlier_fraction`; we don't claim exact anatomy.
- **Window/level server round-trips** could feel laggy on a slow tunnel. Mitigated by LRU + debounce;
  the escalation path (16-bit slice + client WebGL LUT) is defined but deferred.
- **Not diagnostic, de-identified only** — reasserted in the viewer UI, unchanged.

---

## 9. Phase mapping (matches `GOAL_IMAGING.md` gates)

| Phase | This doc | Concrete deliverables |
|---|---|---|
| II — Slice backend | §2.1–2.3, §6 | `core/viz/slice.py`; `volume-info`, `slice`, `pick-to-slices`; slice LRU; tests for plane/index/window correctness + memory |
| III — MPR viewer (both UIs) | §3, §7 | React `MprPanel`/`SliceView`/`useCrosshair`; trame MPR; linked crosshair; parity test |
| IV — Compare | §2.4, §4 | `compare-slice-map`; React `CompareMpr` + trame equivalent; matched-plane test using the demo bilateral scan |
| V — AR MVP | §2.5, §5.1–5.2 | `glb` in `core/export/mesh.py`+`bundle.py`; `model.glb` endpoint; `<model-viewer>` in both UIs |
| VI — AR/WebXR prototype | §5.3, §7.2 | React three.js `immersive-ar` clip-plane viewer, Android-Chrome only, graceful degradation elsewhere |
