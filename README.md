# 3Dorth — 3D cortical bone mapping and comparison from CT

3Dorth measures cortical (wall) thickness across a bone surface from a CT scan
and renders it as a colored 3D map, and it compares two bones (for example an
operated shoulder against the contralateral side) as a signed millimetric
surface-deviation map. It reproduces the cortical-thickness pipeline from Guo et
al. 2022 with open-source tools and generalizes it: it loads whatever bone is in
the scan, lets you filter and select regions after loading, and exposes the
anatomy-specific choices as controls rather than hard-coding them.

The immediate motivation is a clinical question — does anchor/tendon-repair
surgery cause long-term bony remodeling in the proximal humerus? — but nothing
in the tool is specific to the humerus.

> Research tooling, not a clinical diagnostic. Every output is de-identified.

## What it does

- **Mode A — cortical thickness (single scan).** Segment bone (Hounsfield
  window), compute per-surface cortical thickness in millimetres, and render it
  with the paper's discrete green→red colorbar. Point/line and height
  measurement tools reproduce the figures in the source paper.
- **Mode B — two-scan / two-side comparison.** Reconstruct both bones,
  auto-register (with an optional sagittal mirror for left/right), and compute a
  signed surface deviation (bone gain vs loss) with per-region statistics.

Everything configurable lives in one parameter registry
([`core/parameters.py`](core/parameters.py)); the defaults reproduce the paper.
Both frontends build their control panels from that registry, so the two UIs
always expose the same knobs.

## One-line deploy (server)

Docker and the Compose plugin are the only prerequisites.

```bash
git clone https://github.com/ArioMoniri/3Dorth.git && cd 3Dorth && ./deploy.sh
```

That builds the images and starts the API plus both frontends:

| Service | URL |
|---|---|
| React UI | `http://<server>:8088` |
| trame UI | `http://<server>:8081` |
| API + docs | `http://<server>:8000/docs` |

No patient data is baked into the image — upload a CT `.zip` in the UI to begin.
`./run.sh react` or `./run.sh trame` start only one frontend; `./run.sh down`
stops everything. Behind a reverse proxy, keep the WebSocket upgrade headers and
long read timeouts already set in [`deploy/nginx.conf`](deploy/nginx.conf), and
allow ~300 MB uploads. A machine with 8 GB RAM is comfortable; volumes and
meshes are held in memory during compute.

## Run locally (development)

```bash
uv venv --python 3.12 .venv
uv pip install -r requirements.txt
make test            # 80+ tests
python scripts/watchdog.py   # independent verification, should be GREEN

# then, in three terminals:
.venv/bin/python -m uvicorn api.main:app --port 8000        # API
cd app_react && npm install && npm run dev                  # React on :5173
.venv/bin/python -m app_trame.app --server --port 8081 --timeout 0   # trame
```

Python 3.12 is required (the imaging stack — SimpleITK, VTK, open3d — has no
wheels for 3.13/3.14 yet).

## The two frontends — which one should I use?

Both do the same analysis; they differ in where the rendering happens.

- **trame** (`app_trame/`, trame + pyvista) renders server-side with VTK and
  calls the Python core directly. It is the quickest to stand up, needs no
  Node build, and is a good fit for internal/research use on one machine.
- **React + vtk.js** (`app_react/`, Vite SPA) renders in the browser and talks
  to the FastAPI backend. It is more work to build but scales to many users and
  is easier to embed or customize.

If you just want to look at your data, use trame. If you are deploying for a
group or embedding the viewer elsewhere, use React.

## Method and reproduced defaults

Segmentation and thickness follow **Guo et al. 2022, *Eur J Med Res* 27:102**
(3D cortical bone mapping of the proximal-humerus surgical neck). The full
mapping of each default to the paper is in [`docs/METHOD.md`](docs/METHOD.md);
the headline values, all confirmed against the source:

| Parameter | Default | From the paper |
|---|---|---|
| HU threshold | 226–1600 | bone lower/upper bound |
| Cortical thickness clamp | 0.33–10 mm | min/max wall thickness |
| Thickness method | local thickness (Hildebrand–Rüegsegger) | = 3-Matic wall thickness |
| Colorbar | green→red, 7 steps, 0.1537–6.5202 mm | Fig. 2 legend |
| Sampling line | 3 points below the lesser tuberosity | Fig. 2A |

Local thickness is the largest-inscribed-sphere thickness of the segmented
cortical mask. A second method — two-surface ray casting — is implemented as a
cross-check; on a hollow-shell phantom the two agree, and on the real proximal
humerus the local-thickness whole-surface mean (~2.8 mm) sits inside the paper's
Table-1 range (2.1–2.85 mm). The two diverge in dense subcortical trabecular
bone, which is expected and is why density-deconvolution methods (Treece/Poole)
are noted as future work rather than used as the primary measure.

Mode B signed distance uses the convention **positive = target surface outside
the reference** (bone gain); the sign is verified on concentric-sphere phantoms
before any real result is reported.

## Usage

1. **Load.** Open a frontend and upload a CT `.zip` (the sample archives wrap a
   Weasis viewer around a `dicom/` folder — the ingest recurses past it), or use
   the bundled demo scan when running locally. The ingest reports geometry,
   laterality, and hardware, and splits a bilateral scan into left/right sides.
2. **Mode A.** Pick a side, adjust any parameters (they default to the paper's
   values), and Apply — the server re-segments and recomputes the thickness map.
   Use the region toggles to hide non-bone (table, contralateral structures) and
   the line/height tools to reproduce the paper's measurements.
3. **Mode B.** Choose a reference and target side, enable the sagittal mirror for
   a left/right comparison, and compute the signed-deviation map. The panel
   reports registration RMS, the deviation statistics, and the percent of surface
   beyond 1 mm and 2 mm split by sign.

## Parameters

All 28 parameters are listed with ranges and units in
[`core/parameters.py`](core/parameters.py) and surfaced identically in both UIs.
The active set is written to [`config.yaml`](config.yaml) so a run is
reproducible; re-running from a saved `config.yaml` reproduces the numbers.

## Feature parity

Analysis logic lives only in `core/`; the API and both UIs are thin. Any new
configurable knob is added once to the registry and appears in both frontends
automatically. `tests/unit/test_parity.py` fails the build if the two UIs ever
expose a different parameter set. See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Limitations

- **A single subject supports description, not causal inference.** Left/right
  differences in one person conflate surgical change with normal
  dominant-arm asymmetry.
- **Segmentation and registration carry uncertainty.** A bone that is fused to
  neighbouring structures in the scan (e.g. an adducted humerus against the
  ribcage) needs manual region selection or clipping to isolate before Mode B is
  meaningful; auto-isolation can pick the wrong structure.
- **CT cannot see radiolucent hardware.** Bioabsorbable/PEEK suture anchors do
  not appear, so the operated side cannot always be inferred from the scan.
- **Metal artifact.** Dense hardware above the metal cutoff is masked and
  reported, but streak artifact can still affect nearby thresholding.
- Not a clinical diagnostic.

## Screenshots

_Add screenshots of the thickness map, region view, and Mode B deviation here._

## Contributing & changelog

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the parity rule and workflow, and
[`CHANGELOG.md`](CHANGELOG.md) for the release history. Bug reports and feature
requests use the templates under `.github/ISSUE_TEMPLATE/`.

## License

Apache License 2.0 — © 2026 Ariorad Moniri. See [`LICENSE`](LICENSE) and
[`NOTICE`](NOTICE).
