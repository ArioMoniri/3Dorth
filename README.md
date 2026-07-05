<p align="center">
  <img src="docs/assets/header.svg" alt="3Dorth — cortical bone mapping from CT" width="100%">
</p>

# 3Dorth — cortical bone mapping from CT

3Dorth reads a CT scan of a bone, measures how thick the cortex (the hard outer
wall) is across the whole surface, and paints that thickness onto a 3D model you
can rotate. It can also line up two bones — an operated shoulder against the
healthy other side, say — and show where bone has been added or lost, in
millimetres.

It reproduces the cortical-thickness method from **Guo et al. 2022** (proximal
humerus) and generalises it: it loads whatever bone is in the scan and puts the
anatomy-specific choices on sliders instead of hard-coding them.

The question behind it is clinical — does suture-anchor repair change the bone of
the proximal humerus over the years? — but nothing in the tool is humerus-only.

> Research tool, not a diagnostic. Every output is de-identified.

## What you get

![3Dorth React UI — cortical thickness of a proximal humerus, with the side
selector, export/pose panel, and live controls](docs/assets/ui_react_thickness.png)
<sub>The React frontend on the bundled de-identified demo. The trame frontend
exposes the identical feature set.</sub>

| Mode A — cortical thickness | Mode B — left/right deviation |
|---|---|
| ![Thickness map](docs/assets/phase2_thickness.png) | ![Signed deviation map](docs/assets/qa_trame_rework_deviation.png) |
| One scan. Green = thin wall, red = thick, in mm. | Two sides registered; red = bone gained, blue = lost. |

![Cortical thickness on the bundled demo at native resolution — the auto-isolated
proximal humerus with a smooth reconstructed surface and the Fig-2 colorbar](docs/assets/demo_best_thickness.png)
<sub>Live output on the de-identified demo at <b>native 0.977 mm</b> (keep
<code>THREEDORTH_MAX_WORK_VOXELS</code> above the scan's voxel count so it isn't
downsampled). At full resolution the glenohumeral gap resolves, so the app
<b>auto-isolates the proximal humerus</b> as its own connected component, and the
display-only reconstruction (supersample → windowed-sinc → pyacvd isotropic remesh) gives
a smooth, evenly-triangulated shell — the paper's Fig-2 look, in ~18&nbsp;s / ~1.7&nbsp;GB
on a laptop. Cortical thickness is computed on the raw mask (the scalar is re-sampled onto
the remeshed surface, not recomputed).</sub>

- **Mode A** segments the bone from its CT density, computes wall thickness at
  every surface point, and colours it with the paper's green→red scale.
- **Mode B** rebuilds two bone surfaces, aligns them (with an optional left/right
  mirror), and reports a signed surface deviation with per-region statistics. The
  two surfaces can be the **Left and Right of one scan**, or the **same side of two
  different scans** — load a **baseline and a follow-up** (or several visits) into
  one session and compare them: the standard is to anchor each series' Left to the
  others' Left and Right to Right, and you choose which pair to view. Reference and
  target are swappable at upload **and** afterwards (swapping flips the sign and the
  red/green colours), and every panel labels which series·side it is showing.

Everything is interactive and applies in real time:

- **Load** a DICOM `.zip`, NIfTI, or a surface mesh — or use the bundled
  de-identified demo. A bilateral scan splits into Left/Right; pick a **region**
  by its thumbnail, or view **Left, Right, or both sides together (Bilateral)** —
  the bilateral view loads the **whole bone of each side** (every connected piece,
  not just the largest).
- **Add more series to compare across visits** — after the first upload, use
  **＋ Add series** to load a second (or third) scan into the *same* session. Each
  series keeps its own Left/Right; the panel lists every loaded series and lets you
  assign the reference and target from any series·side. The bundled demo ships with
  a baseline and a **de-identified synthetic follow-up** so Mode B's baseline→follow-up
  comparison works out of the box. (Real second-patient data is never bundled; the
  follow-up is derived from the de-identified demo by `scripts/make_multi_demo.py`.)
- **Isolate a bone by clicking it** — turn on **Clip / isolate**, tick *Load whole
  bone (all pieces)*, then **click a piece** on the 3D surface: everything not
  connected to it is hidden, leaving just that bone (e.g. the humerus). *Reset
  clip* restores it; a per-axis clip box trims further. (Pieces that are fused in
  the segmentation are one connected part — raise the HU threshold to separate
  them.)
- **Every parameter applies automatically** — colour/range/steps re-colour
  instantly, segmentation/thickness parameters re-run after a short pause (no
  Apply click needed).
- **Hover** the surface for the per-point value; **export** PNG/TIFF (with a DPI),
  STL/PLY/OBJ/VTP, or DICOM with a camera pose; **Mode B** adds a manual-anchor
  nudge and a reference/target swap.
- **Statistics & figures** — a collapsible section renders **article-quality** plots
  (distribution histogram + KDE, a cumulative **ECDF**, a **Table-1** descriptive panel,
  and a per-region box/summary when the data supports it) with rich stats (percentiles,
  IQR, %>1/2 mm), exported as **PNG/TIFF/JPG at a chosen DPI**, at parity in both UIs
  (single-subject/descriptive, labelled as such).
- **Measure on the CT images** — distance / angle tools on the 2D reformats (**MPR,
  oblique, and the two-bone compare panes**; mm read from the scan geometry), exported
  *burned into* the PNG. Click a figure to enlarge, and **drag/resize every overlay
  panel** — legend, stats, figures, the clip box, and the cutting-plane controls —
  anywhere on screen (drag pops it out to float; double-click the grip to re-dock).
- **Smooth, publication surfaces — all adjustable from both UIs** — a display-only
  **surface reconstruction** (`raw` / `smooth` / `wrap`): supersample resamples the
  voxel staircase away, windowed-sinc removes residual steps, and a **pyacvd isotropic
  remesh** yields a clean, watertight, evenly-triangulated shell (the Mimics/3-matic
  look). Tune it from the **Meshing** group: **surface (tissue) smoothing**,
  supersample, hole-fill, and **surface quality** (remesh triangle density), plus a
  **colour smoothing** knob that smooths the *displayed* green→red gradient. All of
  these are **display-only** — cortical thickness stays computed on the raw mask and
  every statistic is unchanged (the scalar is re-sampled onto the remeshed surface).
  The coloured bone + the discrete Fig-2 colorbar — with optional, **adjustably-placed
  sampling-line / height-bracket** annotations — export as PNG/TIFF at any DPI (the
  paper's Fig-2 A/B layout).
- **Share** a public link — a resilient tunnel that **auto-selects whatever works from
  your network** (Cloudflare / Pinggy / Tailscale Funnel / serveo / your own relay) and
  survives sleep/wake — and **switch between the two UIs** from either one.

### See the images, not just the surface

Beside the 3D map, an image viewer slices the actual CT — the volume never leaves
the server (it streams small windowed PNGs on demand, so RAM stays bounded).

![Arbitrary oblique cross-section — a tiltable cutting plane through the 3D
thickness map with its matched 2D reformat](docs/assets/ui_react_oblique.png)
<sub>A freely tiltable cutting plane (left) and its live 2D reformat (right),
matched at every point — click the reformat and the 3D marker lands exactly there.</sub>

- **MPR** — axial / coronal / sagittal panels with a linked crosshair; click the
  3D bone and all three slices jump to that point, scrub a slice and the 3D marker
  follows.
- **Oblique / any cross-section** — tilt a cutting plane to *any* orientation —
  **adjust its size, drag the blue plane in 3D to slide it along its normal, or click
  a bone point to re-centre it** — and the 2D reformat is matched to the 3D cut **at
  every point** (click the reformat, the 3D marker lands exactly there).
- **Two-bone cross-section** — one movable plane, both bones' 2D CT shown as two
  boxes above the plane controls (the reference plane is mapped onto the other bone
  through the registration, so it's the *same* physical cut):

  ![Two-bone oblique cross-section — Reference bone and Target bone reformats as
  two boxes above the movable cutting-plane controls](docs/assets/ui_react_oblique_compare.png)

- **Compare** two registered sides' matched cross-sections side by side — and the
  linkage is **gated on registration quality**: a low-overlap alignment (e.g. a
  thorax-fused bone) is flagged unreliable, never silently trusted.
- **AR / 3D** — view the coloured bone in-browser (`<model-viewer>`), launch native
  AR on Android (glTF/Scene Viewer), or scrub a clipping-plane cross-section in a
  three.js view with a real WebXR session where the device supports it.

Every image panel is labelled **array-oriented** (the app frame is
`world = index × spacing + offset`, identity direction — the DICOM origin/direction
are not carried through), so it never claims a radiological A/P/S/I orientation, and
the research / de-identified / not-for-diagnosis caveat stays visible.

## Get it running

**Not sure what your server supports? Let it decide.** `./scripts/setup.sh` inspects
the box (root? docker? dockerd? kubectl+cluster? GPU? python/node/cloudflared?),
recommends the best path, **installs what's missing**, and runs it — a colored menu
with the right option pre-selected:

```bash
git clone https://github.com/ArioMoniri/3Dorth.git ~/3dorth && cd ~/3dorth
./scripts/setup.sh            # interactive; or --auto to just do it, --check to only inspect
```

```
 ██████╗ ██████╗  ██████╗ ██████╗ ████████╗██╗  ██╗
 ╚════██╗██╔══██╗██╔═══██╗██╔══██╗╚══██╔══╝██║  ██║
  █████╔╝██║  ██║██║   ██║██████╔╝   ██║   ███████║
  ╚═══██╗██║  ██║██║   ██║██╔══██╗   ██║   ██╔══██║
 ██████╔╝██████╔╝╚██████╔╝██║  ██║   ██║   ██║  ██║
 ╚═════╝ ╚═════╝  ╚═════╝ ╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝
  Best fit → Native (no Docker — installs Python venv / local Node / cloudflared)
    1) Kubernetes   2) Docker   3) Native   4) Re-scan   5) Uninstall   6) Quit
```

It picks between four paths (all end in one public link — an auto-selected tunnel, no inbound port needed):
- **Kubernetes** (`deploy_k8s.sh`) — GPU + autoscale, builds on-cluster.
- **Docker single-pod** (`deploy_restricted.sh`) — for non-privileged RKE2 pods.
- **Native, no Docker** (`run_native.sh`) — for bare containers where `dockerd` won't
  run. Keeps everything **local for easy removal**: it fetches a self-contained
  **Python 3.12 via `uv`** (the frozen deps need ≥3.11, so it doesn't rely on the
  system python) plus a private Node + cloudflared — all under **`./.tools`** + a
  **`.venv`** — and only the unavoidable system GL/Xvfb libraries via `apt` (tracked so
  uninstall removes exactly those). Installs are **self-healing** (retries) and every
  issue is reported at the end. The API serves the React UI on one port (no nginx).
  Remove it all with `./scripts/setup.sh --uninstall`.
- **Normal Docker** (`serve-public.sh` / `deploy.sh`) — a plain VM with Docker.

**The public link auto-heals.** `scripts/tunnel.sh` (run for you at the end) *tries and
verifies* each provider and keeps the first that actually serves in
`outputs/public_urls.json` + the app's top bar: **relay** (if you set `SSH_RELAY`) →
**ngrok** → **Cloudflare** (if 7844/443 edge is open) → **Pinggy** (443) → **serveo**
(22) → **localhost.run** (22) → **Tailscale Funnel** (if you set `TS_AUTHKEY`). For
SSH-based providers it accepts the link as soon as the SSH child is up and a URL is
emitted — it does **not** reject a working tunnel just because the locked pod can't
`curl` its own public edge (a link it can't self-verify is still published, flagged
`self_verified:false`).

**Egress-locked pod? Diagnose first, don't guess.**

```bash
./scripts/tunnel_menu.sh           # INTERACTIVE picker: probes what THIS pod can reach,
                                   # shows each provider ✓reachable/✗blocked, you choose one,
                                   # it prompts for whatever that needs (key/relay/token)
./scripts/egress_probe.sh          # or just the raw OPEN/BLOCKED table + a "USE →" verdict
                                   # (detects the Pinggy false-reject trap: control open, edge blocked)
```

`run_native.sh` launches the menu automatically when run in an interactive shell (a
`nohup`/CI run with no TTY falls back to auto-selection from ENV instead).

Read the verdict. Some pods block **everything** a public tunnel needs — not just the
SSH-tunnel hosts, but Cloudflare's 7844 edge **and** Tailscale's DERP relays (the control
plane connects, then Funnel can't serve). When only *generic* outbound 443 works, the pod
**cannot open any tunnel itself** — the link has to come from somewhere always-on. Four
ways, from zero-setup to proper:

**① Relay through your laptop (zero setup — but the link dies when the laptop sleeps).**
Your laptop already reaches the pod and has open internet, so let it relay. Run **on your
laptop, not the pod**:

```bash
./scripts/share_from_laptop.sh                 # defaults to 30405@10.6.110.10, port 8000
```

It `ssh -L`s the pod's app onto the laptop, opens a Cloudflare tunnel **from the laptop**,
and prints a `https://…trycloudflare.com` link. Keep the terminal open (it's the relay).

**② Always-on relay box — laptop-free.** A $0 free-tier VM (Oracle Cloud Always Free,
GCP e2-micro, any cheap VPS) becomes a permanent front door. The pod reverse-forwards to
it over 443; the box publishes it with its own Cloudflare tunnel. No open app port, no
domain, no laptop:

```bash
# on the ALWAYS-ON box (installs cloudflared; prints the exact pod command; leave running):
./scripts/relay_server.sh 8000
# on the POD (reconnects on drops; background it so it outlives your SSH session):
RELAY=user@your-box:443 nohup ./scripts/relay_connect.sh > outputs/relay.log 2>&1 &
```

**③ A box you control, via the built-in providers.** If egress reaches
`login.tailscale.com` **and** a DERP relay, Tailscale Funnel works; otherwise reverse-forward
to any 443 host you own. `run_native.sh`/`tunnel_menu.sh` **prompt** for it, or via ENV:

```bash
TS_AUTHKEY=tskey-xxxx ./scripts/tunnel.sh 8000 8081     # Funnel → https://<host>.<tailnet>.ts.net
SSH_RELAY=user@your-host:443 ./scripts/tunnel.sh 8000   # → http://<host>:8000 (sshd: GatewayPorts clientspecified)
```

**④ The proper way on a cluster — ask your admin (or apply it) for an Ingress/NodePort.**
[`deploy/k8s/ingress.yaml`](deploy/k8s/ingress.yaml) exposes the `3dorth-react` Service at
a real hostname over HTTPS (or a NodePort) — always on, no tunnel, no relay. This is the
right answer for a Kubernetes deployment; the tunnels above are for when you can't get it.

Other knobs (secrets from ENV only, never written to the repo):
`TUNNEL_PROVIDER=pinggy|serveo|cloudflare|relay|tailscale` forces one;
`RELAY_REMOTE_PORT` / `TS_HOSTNAME` fine-tune the relay/Funnel endpoints.
**Always-works fallback** (no public egress needed) — one SSH hop from your machine; the
exact command (with the real ports) is printed at startup and saved to
`outputs/ssh_access.txt`:

```bash
ssh -L 8000:127.0.0.1:8000 -L 8081:127.0.0.1:8081 -p <ssh-port> <user>@<host>
# then open http://localhost:8000 (React) and http://localhost:8081 (trame)
```

Lifecycle:

```bash
./scripts/setup.sh --restart     # kill previous + bring it back up (reuses installs)
./scripts/setup.sh --update      # git pull + restart
./scripts/setup.sh --kill        # stop the app + tunnel
./scripts/setup.sh --uninstall   # remove the local install (.venv/.tools/build)
cat outputs/public_urls.json     # the current public link, any time
```

If you already know you have Docker + Compose:

```bash
git clone https://github.com/ArioMoniri/3Dorth.git && cd 3Dorth && ./deploy.sh
```

That builds everything and starts the API plus both frontends:

| Service | URL |
|---|---|
| React UI | `http://<server>:8088` |
| trame UI | `http://<server>:8081` |
| API + docs | `http://<server>:8000/docs` |

No patient data is in the image — upload a CT `.zip` in the UI to start.
`./run.sh react` or `./run.sh trame` bring up just one frontend; `./run.sh down`
stops everything.

**Public server, one command.** On a firewalled Ubuntu box, `./serve-public.sh`
auto-tunes the compute budget to the machine (cores/RAM), builds and starts the
stack, waits until the API is healthy, then opens a resilient Cloudflare tunnel and
prints the public link — **outbound-only, so no inbound ports need opening, and the
link exposes only the app (never SSH/your shell)**. Move a clashing host port with
`REACT_HOST_PORT=9090 ./serve-public.sh 9090`, expose only via the tunnel with
`BIND_ADDR=127.0.0.1 ./serve-public.sh`, or use a GPU with `THREEDORTH_GPU=1`. See
the current link anytime with `cat outputs/public_urls.json`.

**Share an already-running stack.** `./scripts/share.sh` opens
public Cloudflare tunnels to both UIs and writes the URLs so the in-app Share
panel picks them up. It stays running and **keeps the tunnels alive across
laptop sleep/wake and network drops** — on a wake it restarts them and rewrites
the URL, and the Share panel polls `/api/config`, so the link updates live with
no manual step. The URLs are ephemeral and unauthenticated — fine for a quick
look, not for anything sensitive (use a named Cloudflare tunnel + Access for that).

**Restricted / non-privileged servers** (Rancher/RKE2/containerd, no systemd, no
sudo, no Docker bridge, and image builds blocked by missing `CAP_SYS_ADMIN`). Build
the images on any x86-64 machine, ship them over, and run pre-built with host
networking:

```bash
# ── on a build machine (or CI) ──
git clone https://github.com/ArioMoniri/3Dorth.git && cd 3Dorth
docker compose --profile all build          # tags 3dorth-api/trame/react:latest
docker save 3dorth-api:latest 3dorth-trame:latest 3dorth-react:latest -o 3dorth-images.tar
scp -P 30405 3dorth-images.tar root@10.6.110.10:/root/3Dorth/3Dorth/

# ── on the restricted server (root, no sudo) ──
cd /root/3Dorth/3Dorth               # a clone of the repo lives here (scripts + compose + demo)
./scripts/start_docker_restricted.sh # starts dockerd (vfs, no bridge, no iptables)
docker load -i 3dorth-images.tar
./scripts/deploy_restricted.sh       # STRICT bind (127.0.0.1), auto-tunes to RAM/MIG,
                                     # AUTO-PICKS free ports, host-networked, no build
# deploy_restricted.sh prints the exact next line with the chosen ports, e.g.:
tmux new -s tunnel './scripts/share.sh 8088 8081'
cat outputs/public_urls.json         # the public Cloudflare link (also in the app top bar)
```

`docker-compose.restricted.yml` uses `network_mode: host` and pre-built images (no
bridge, no build). Ports are **dynamic** — `scripts/pick_ports.sh` avoids any port
already in use and `deploy_restricted.sh` prints the exact `share.sh` command with
the chosen ones (also written to `outputs/ports.env`). The default bind is **strict
`127.0.0.1`** so only the local Cloudflare tunnel can reach the app (nothing on the
pod network); pass `--expose` for `0.0.0.0`. `scripts/dynamic_resources.sh` reads
`free -g` + `nvidia-smi` and picks
`THREEDORTH_MAX_SESSIONS/COMPUTE_CONCURRENCY/MAX_WORK_VOXELS/GPU` — high on a big box,
never maxing RAM/VRAM, and safe when `nvidia-smi` returns `[Insufficient Permissions]`
(GPU then stays off; the app runs CPU-only). The Cloudflare tunnel is outbound-only,
so no inbound ports are needed and the link never exposes SSH/the shell.

### Which deploy? (normal vs strict)

| | command | networking | bind | ports |
|---|---|---|---|---|
| **Normal** (own box / VM) | `./serve-public.sh` or `./deploy.sh` | Docker bridge | `0.0.0.0` (behind your firewall) | auto-picked, or `REACT_HOST_PORT=…` |
| **Strict / tunnel-only** | `BIND_ADDR=127.0.0.1 ./serve-public.sh` | Docker bridge | `127.0.0.1` (tunnel is the only door) | auto-picked |
| **Restricted server** (RKE2, no build/bridge/systemd) | `./scripts/deploy_restricted.sh` | host (no bridge) | `127.0.0.1` strict (default) · `--expose` for `0.0.0.0` | auto-picked |
| **Native** (no Docker at all) | `./scripts/run_native.sh` | none (one process) | `127.0.0.1` strict · `--expose` | auto-picked |
| **Kubernetes** (GPU + autoscale) | `./scripts/deploy_k8s.sh` | ClusterIP + tunnel | in-cluster | Service ports |

Don't know which? `./scripts/setup.sh` detects and installs for you.

All print the public Cloudflare link and keep it alive; none need an inbound port opened.

### Kubernetes (GPU on the H200, build on-cluster, autoscale)

The **only** way to actually reach the GPU inside a container on a cluster like this
is a native Deployment that *requests* a MIG slice (device passthrough is done by the
cluster's NVIDIA device plugin, not by a non-privileged pod's Docker). This path also
**removes the Mac transfer** — it builds the images **on the cluster** with Kaniko
(no privileged Docker) and pushes to your registry. Needs `kubectl` access, a
registry, and the NVIDIA device plugin.

```bash
./scripts/deploy_k8s.sh --check                        # what's available (GPU resource, registry, kubectl)
kubectl -n 3dorth create secret docker-registry regcred \
  --docker-server=<registry> --docker-username=<user> --docker-password=<token>
REGISTRY=<registry>/<you> ./scripts/deploy_k8s.sh --build   # build 3dorth-api-gpu + 3dorth-react on-cluster
REGISTRY=<registry>/<you> ./scripts/deploy_k8s.sh           # apply Deployments/Services/HPA
# expose (from this pod, outbound-only):
kubectl -n 3dorth port-forward svc/3dorth-react 8088:80 &
tmux new -s tunnel './scripts/share.sh 8088 8081'
```

`deploy/Dockerfile.backend.gpu` is a CUDA-12 image with CuPy so the distance
transforms run on the H200; `deploy/k8s/3dorth.yaml` requests
`${GPU_RESOURCE}` (auto-detected, e.g. `nvidia.com/gpu` or `nvidia.com/mig-3g.71gb`).
The **API runs as one replica scaled vertically** (a MIG slice + high concurrency)
because sessions are in memory; the **stateless React tier gets an HPA**. True
multi-replica API autoscale would need sticky routing / shared session storage — the
one place k8s complexity pays off, and easy to add on request. If you have no cluster
access, the single-pod `deploy_restricted.sh` path still works (CPU-only).

<details>
<summary><b>Performance, memory, and GPU</b></summary>

The compute (segmentation, local thickness, registration) is bounded so it does
not exhaust RAM on a small machine, and uses the GPU where present:

- Volumes are held as int16 HU; oversized uploads are block-downsampled to a
  voxel budget; the local-thickness grid resolution adapts to volume size.
- Heavy computes are serialised (one at a time by default), and only the most
  recent few scans are kept in memory.
- Rendering uses the GPU (vtk.js in the browser, VTK server-side); if CuPy + a
  CUDA device are present, distance transforms run on the GPU, otherwise on the
  CPU. Everything degrades gracefully.

All limits are environment variables so a device can be sized:
`THREEDORTH_MAX_SESSIONS`, `THREEDORTH_COMPUTE_CONCURRENCY`,
`THREEDORTH_MAX_WORK_VOXELS`, `THREEDORTH_MAX_ISO_VOXELS`, `THREEDORTH_GPU`.

</details>

<details>
<summary><b>Security &amp; scaling — what's handled, and the honest gaps</b></summary>

**Security (handled)**
- **Tunnel isolation** — the Cloudflare tunnel is outbound-only and forwards *only*
  the app's HTTP port; it is never a path to SSH or your shell. Strict mode
  (`BIND_ADDR=127.0.0.1`, or `deploy_restricted.sh` by default) binds the app to
  localhost so nothing on the LAN/pod network can reach it — the tunnel is the only door.
- **Inputs** — nginx caps uploads at 300 MB; ingest sanitises archive paths (no
  directory traversal / arbitrary file read); heavy compute is bounded by a semaphore
  so one caller can't exhaust the box.
- **Data** — no PHI is baked into the images (the demo is de-identified NIfTI);
  uploads are the user's own data and, in restricted mode, ephemeral unless you
  persist `./data`. Containers run as a **non-root** user; no privileged flags.
- **Transport** — TLS is terminated at Cloudflare's edge and the edge→origin hop
  rides the encrypted tunnel.

**Security (honest gaps — add these for real multi-tenant use)**
- **No app-level auth or rate-limiting** beyond the compute semaphore: *anyone with
  the URL* can upload and compute. Put **Cloudflare Access** (a named tunnel + email/
  SSO) in front for a controlled audience, or keep the quick-tunnel URL private and
  rotate it (restart `share.sh`). This is a research tool, not a hardened service.

**Scaling**
- **Vertical (works today)** — the compute knobs auto-tune to the box
  (`dynamic_resources.sh` / `serve-public.sh`); raise `THREEDORTH_COMPUTE_CONCURRENCY`
  for more parallel computes (costs CPU/RAM), and `THREEDORTH_MAX_WORK_VOXELS` trades
  speed for resolution. RAM is bounded by int16 volumes + adaptive downsampling + LRU
  session eviction (`THREEDORTH_MAX_SESSIONS`). One big node (e.g. the H200 box)
  serves many users this way.
- **Horizontal (the honest limit)** — sessions live **in memory in one API process**,
  so you can't naively load-balance across replicas — a user's scan is pinned to the
  node that ingested it. Multi-node scaling needs sticky routing or shared session
  storage (not implemented), which is the only case where Kubernetes actually earns
  its complexity here. Ask and I'll add sticky-session manifests.
- **GPU** — distance transforms use CuPy when a CUDA device is reachable, else CPU;
  in a restricted container without device passthrough it is CPU-only (the app falls
  back automatically).

</details>

## Which frontend?

Both run the same analysis; they differ in where the 3D drawing happens.

- **trame** renders on the server with VTK and calls the Python core directly.
  Nothing to build, quickest to stand up — use it to look at your own data.
- **React** renders in the browser and talks to the API. More setup, but scales
  to many users and is easier to embed — use it when deploying for a group.

Both build their control panels from the same parameter list, so they always
expose the same knobs (a test fails the build if they ever drift apart).

<p align="center">
  <img src="docs/assets/ui_trame.png" alt="The trame frontend: thickness map, stats, and Share URL" width="100%">
</p>
<p align="center"><sub>The trame frontend on the demo — same features as React, rendered server-side. The Share URL (top) is a live Cloudflare link.</sub></p>

<details>
<summary><b>Using it, step by step</b></summary>

1. **Load** a CT `.zip` (the sample archives wrap a Weasis viewer around a
   `dicom/` folder — the ingest recurses past it), or use the bundled demo scan
   locally. The ingest reports geometry, laterality, and hardware, and splits a
   bilateral scan into left/right. To compare across visits, use **＋ Add series**
   to load a baseline and one or more follow-ups into the same session.
2. **Mode A** — pick a side, adjust parameters if you want (they default to the
   paper's values), and Apply. The server re-segments and recomputes the map.
   Region toggles hide non-bone (table, ribs); line/height tools reproduce the
   paper's measurements.
3. **Mode B** — choose a **reference** side and a **target** side, then compute.
   For a single scan, turn on the sagittal mirror to compare left vs right; across
   series, pick the same side of two series (e.g. baseline·Left → follow-up·Left).
   The panel labels which series·side each role is, and reference/target are
   swappable (swapping flips the sign and the red/green colours). It reports the
   registration error, the deviation statistics, and the percent of surface past
   1 mm and 2 mm, split into gain and loss.
4. **Statistics & figures** — after a compute in either mode, open the
   **Statistics & figures** section for the distribution histogram + per-region
   summary, and export them as PNG/TIFF/JPG at a chosen DPI. **Reset to defaults**
   restores the registry defaults for the current mode.

</details>

<details>
<summary><b>Full parameter list (36 knobs) and reproducibility</b></summary>

Everything configurable lives in one registry,
[`core/parameters.py`](core/parameters.py) — all 36 parameters with ranges and
units. Both UIs read that registry, and the active values are written to
[`config.yaml`](config.yaml), so re-running from a saved `config.yaml`
reproduces the numbers. The defaults reproduce Guo et al. 2022:

| Parameter | Default | From the paper |
|---|---|---|
| HU threshold | 226–1600 | bone lower/upper bound |
| Cortical thickness clamp | 0.33–10 mm | min/max wall thickness |
| Thickness method | local thickness (Hildebrand–Rüegsegger) | = 3-Matic wall thickness |
| Colorbar | green→red, 7 steps, 0.1537–6.5202 mm | Fig. 2 legend |
| Sampling line | 3 points below the lesser tuberosity | Fig. 2A |

</details>

<details>
<summary><b>Method and how it was checked</b></summary>

Segmentation and thickness follow **Guo et al. 2022, _Eur J Med Res_ 27:102**
(3D cortical bone mapping of the proximal-humerus surgical neck). The full
mapping of each default to the paper is in [`docs/METHOD.md`](docs/METHOD.md).

Thickness is the largest-inscribed-sphere ("local") thickness of the cortical
mask. A second method — two-surface ray casting — is kept as a cross-check: the
two agree on a hollow-shell phantom, and on the real humerus the local-thickness
whole-surface mean (~2.8 mm) sits inside the paper's Table-1 range (2.1–2.85 mm).
They diverge in dense subcortical trabecular bone, which is expected — that is
why density-deconvolution methods (Treece/Poole) are noted as future work rather
than used as the main measure.

For Mode B, positive means the target surface sits **outside** the reference
(bone gain); the sign is verified on concentric-sphere phantoms before any real
result is reported.

The paper's publication figure — the discrete colorbar and thickness map — is
reproduced below.

![Publication-style thickness figure](docs/assets/figure_thickness.png)

</details>

<details>
<summary><b>Run locally (development)</b></summary>

```bash
uv venv --python 3.12 .venv
uv pip install -r requirements.txt
make test                    # 190+ tests
python scripts/watchdog.py   # independent verification, should be GREEN

# then, in three terminals:
.venv/bin/python -m uvicorn api.main:app --port 8000        # API
cd app_react && npm install && npm run dev                  # React on :5173
.venv/bin/python -m app_trame.app --server --port 8081 --timeout 0   # trame
```

Python 3.12 is required — the imaging stack (SimpleITK, VTK, open3d) has no
wheels for 3.13/3.14 yet.

Behind a reverse proxy in production, keep the WebSocket upgrade headers and long
read timeouts already set in [`deploy/nginx.conf.template`](deploy/nginx.conf.template) and allow
~300 MB uploads. 8 GB RAM is comfortable; volumes and meshes stay in memory
during compute.

</details>

<details>
<summary><b>Limitations (read before trusting a result)</b></summary>

- **One subject describes; it does not prove.** A left/right difference in a
  single person mixes surgical change with normal dominant-arm asymmetry.
- **A fused bone needs manual isolation.** If the bone touches its neighbours in
  the scan (an adducted humerus against the ribcage), auto-isolation can grab the
  wrong structure — select or clip the region by hand before Mode B.
- **CT cannot see radiolucent anchors.** Bioabsorbable/PEEK suture anchors don't
  show up, so the operated side can't always be told from the scan alone.
- **Metal artifact.** Dense hardware is masked and reported, but streak artifact
  can still nudge nearby thresholding.
- Research use only — not a clinical diagnostic.

</details>

## Imaging viewer, cross-sections & AR

Shipped in both frontends:

- ✅ In-panel **image viewer** (MPR) — axial/coronal/sagittal slices beside the 3D
  map with a linked crosshair. Slices render on demand by the API, so the whole
  volume never goes to the browser.
- ✅ **Oblique / arbitrary cross-section** — a tiltable cutting plane at any
  orientation with a live reformat matched to the 3D cut at every point (exact
  pixel↔world inverse, so a click on the 2D image lands on the precise 3D point).
- ✅ **Compare** two series' matched cross-sections side by side, gated on
  registration quality so it never implies a correspondence the fit can't support.
- ✅ **AR** — a GLB of the coloured bone for native AR on Android and a three.js
  WebXR clipping-plane cross-section where the device supports it (graceful,
  feature-detected fallback everywhere else).

Per the review: measurement stays on the source geometry (never on a reformatted
slice), orientation and laterality are shown as array-oriented / unverified (never
guessed), and AR is for education/consent, not measurement.

## Contributing, changelog, license

[`CONTRIBUTING.md`](CONTRIBUTING.md) covers the frontend-parity rule and the
workflow; [`CHANGELOG.md`](CHANGELOG.md) has the release history; bug reports and
feature requests use the templates in `.github/ISSUE_TEMPLATE/`.

Apache License 2.0 — © 2026 Ariorad Moniri. See [`LICENSE`](LICENSE) and
[`NOTICE`](NOTICE).
