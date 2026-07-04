# Imaging viewer, cross-sections, compare & AR — CLINICAL requirements

Author: Dr. Elif Kaya (shoulder & upper-limb ortho; reads MSK CT; proximal-humerus
morphology). Scope: the clinical half of `GOAL_IMAGING.md`. The technical half
(endpoints, RAM budget, vtk.js plumbing) lives in `IMAGING_DESIGN.md` — this
document says **what a clinician needs to see, and what must never be implied.**

Grounding in the existing code (so the caveats are real, not decorative):
- Registration returns `rms` (inlier RMS, mm), `fitness`, `inlier_fraction`
  (`core/registration/register.py`); `converged = fitness > 0.3`. These are the
  only honest numbers we have to gate the "matched cross-section" on.
- Ingest reports `laterality` (from `ImageLaterality`/`Laterality`, else a text
  guess), `pixel_spacing`, `slice_thickness`, `spacing_between_slices`,
  `is_isotropic`, `PatientPosition` (`core/ingest/dicom_ingest.py`). Every one of
  those is a label the viewer is **obligated** to surface, because a viewer that
  hides them invites the exact misread I care about.

---

## 0. The one-sentence clinical test I apply to every item below

> Does it change what I can *see* or *decide*, and can it be *trusted not to lie*?

If a feature is pretty but I'd never act on it, it's a nice-to-have or overkill.
I've sorted everything on that basis.

---

## 1. Which views actually help

### 1.1 MPR planes — YES, all three, but with an anatomy-honest default (MUST)

Axial / coronal / sagittal MPR beside the 3D map is the core of the feature and it
earns its place. Reasons specific to the proximal humerus:

- **The 3D thickness/deviation map answers "where", the slice answers "what".**
  When the surface map shows a thin-cortex patch or a signed-deviation blob, the
  first question every reader asks is *is that real bone, or is it a segmentation
  edge, a nutrient foramen, a partial-volume artefact at the physis scar, or the
  bicipital groove?* Only the grey-scale slice can adjudicate. Without it the map
  is un-auditable.
- **Coronal and sagittal are the working planes for the proximal humerus**
  (head-shaft angle, greater/lesser tuberosity, calcar, medial hinge). Axial is
  where you confirm tuberosity vs groove and rotation. All three are load-bearing
  — do not ship "axial only".

Requirements:
- **Oblique / plane-locked-to-the-picked-point is a nice-to-have, not v1.** True
  double-oblique MPR is where OHIF-likes get expensive and where orientation bugs
  hide. v1 ships the three **orthogonal** planes in the volume's own frame. (See
  §1.3 for the one exception that IS worth it.)
- **Window/level is mandatory and must default to a bone window** (roughly
  WL ~300 / WW ~1500, exposed and adjustable) with a soft-tissue preset available.
  A single hardcoded window is a clinical failure: a "thin cortex" on a lung window
  is meaningless.
- Slice scrubbing must show the **slice index and the physical position (mm)**, not
  just a 0–N counter.

### 1.2 The crosshair correlating a 3D spot to the slice — YES, this is the feature (MUST)

This is the single most clinically valuable element and the reason to build the
viewer at all. Bidirectional linkage:

- **3D → slice:** click a thin-cortex / high-deviation spot on the 3D surface →
  the three MPR planes recentre on that voxel and a crosshair marks it. This is
  what converts "the algorithm flagged something" into "let me look at it myself."
- **slice → 3D:** drag the crosshair in any MPR view → the marker moves on the 3D
  surface. This lets me start from a slice finding (a cyst, a cortical break I saw
  on greyscale) and ask what the thickness map says there.

Honesty constraints on the crosshair (non-negotiable):
- The picked 3D point is a **surface** point; the crosshair in the slice sits at
  that surface voxel. It must be visually clear the marker is *on the cortex*, not
  floating in marrow. If we snap to nearest surface voxel, say so on hover.
- The thickness value shown at the crosshair must be the **same number** the 3D map
  used for that vertex — never recomputed on the slice by eye. If they can't be
  guaranteed identical, show the map's value and label the slice as "for visual
  confirmation only" (see §4).

### 1.3 The compare of matched cross-sections — YES, but this is the honesty minefield (MUST, with heavy caveats — see §3)

Side-by-side MPR of two bones on the *same anatomical plane* (via the Mode-B
registration) is genuinely useful — operated vs contralateral is the whole clinical
question. It is also the single most likely thing to mislead, because "the same
plane" is only as true as the registration. Everything about how it's presented is
in §3. The *view* itself (two linked MPR triplets, synchronised scrub) is a
must-have.

The **one oblique plane worth building**: the plane **perpendicular to the
registered axis / defined by three anatomical landmarks**, so both bones are cut on
the *anatomically* matched plane rather than each scanner's arbitrary acquisition
frame. Without this, "matched cross-section" degrades to "same slice number", which
is meaningless across two scans with different positioning. This is the one place
oblique reformatting pays for itself.

### 1.4 Views that are OVERKILL — do not build

- **Curved MPR / centreline reformat.** That's a long-bone / vessel tool. The
  proximal humerus is short and lumpy; a curved reformat adds a fabrication surface
  (the centreline) for no decision I'd make. Skip.
- **Volume-rendered/MIP "CT-like" cinematic renders inside the viewer.** We already
  have the quantitative 3D map; a second beauty render competes with it and tempts
  people to read it diagnostically. Skip.
- **Measurement calipers *on the reformatted slice*.** Tempting, dangerous: a
  caliper on an oblique/interpolated reformat produces a number that looks
  clinical and isn't traceable to the source geometry. Measurement stays in the
  existing Mode-A/B tools on the reconstructed geometry. On-slice measurement is
  explicitly a **red line** (§4), not a nice-to-have.
- **Free double-oblique scrubbing in v1** (§1.1).

---

## 2. Mandatory orientation / laterality / scale labeling

A research viewer that a surgeon glances at *will* be misread if these are absent.
Every one of these is derivable from data already in `dicom_ingest.py`, so "we
don't have it" is not an excuse.

### 2.1 Radiological orientation letters on every MPR pane (MUST)
- Axial: **A/P** top/bottom, **L/R** left/right, in **radiological convention**
  (patient left on image right) — and the convention itself stated in the corner.
- Coronal: **S/I**, **L/R**. Sagittal: **S/I**, **A/P**.
- These letters must be derived from the DICOM `ImageOrientationPatient` /
  `PatientPosition`, **not assumed**. If orientation cannot be derived, the pane is
  labeled **"orientation unverified"** and the letters are hidden — never guessed.
  (Guessing L/R is how a left humerus gets read as a right. Unacceptable.)

### 2.2 Laterality banner (MUST)
- Each series shows its laterality (**LEFT / RIGHT / unknown**) prominently, sourced
  from `laterality`. If it came from the text-heuristic fallback rather than the
  `ImageLaterality` tag, mark it **"(inferred)"**. In compare, if the two sides'
  laterality is `unknown` or equal (both "right"), warn — because mirror-based
  Mode-B assumes contralateral sides.
- If a side has been **mirrored** for registration (Mode-B `mirror()`), the pane
  must say **"MIRRORED"**. A mirrored image with radiological L/R letters is a
  laterality landmine; the mirror flag has to be louder than the letters.

### 2.3 Scale (MUST)
- A **physical scale bar in mm** on each MPR pane, computed from `pixel_spacing` /
  reformat spacing — not a pixel ruler. It must remain correct under zoom.
- Show **voxel spacing and `is_isotropic`**. If `is_isotropic` is false, display
  **"anisotropic — through-plane N mm"**; reformatted (coronal/sagittal) planes off
  an anisotropic axial stack are interpolated and blockier, and the reader must know
  the sagittal "detail" is partly synthesised.

### 2.4 Window/level readout (MUST)
- Current WL/WW shown numerically and the preset name ("bone"). A cortex judgement
  is window-dependent; the window has to be on screen.

### 2.5 De-identification / provenance strip (MUST)
- Persistent footer: **"De-identified • Research use only • Not for diagnosis"** and
  the session/scan short-hash. This is not legal theatre — it's the thing that stops
  a screenshot of this viewer being pasted into a clinical note.

---

## 3. Presenting the "matched cross-section" honestly under registration uncertainty

This is where I push hardest. The compare view's entire value rests on a claim —
"these two slices show the same anatomy" — that is **only approximately true**, and
the degree of approximation is quantified by numbers we already compute. Present it
honestly or don't ship it.

### 3.1 Always show the registration quality, inline, next to the compare (MUST)
- Display **inlier RMS (mm)** and **fitness / inlier fraction** from
  `RegistrationResult`, right at the compare view — not buried in a report.
- Give it a **plain-language band**, thresholded off the existing gate
  (`converged = fitness > 0.3`) plus an RMS band tied to voxel size:
  - **Good** — RMS ≲ 1 voxel and fitness high: "planes are well matched."
  - **Fair** — RMS ~1–2 voxels: "approximately matched; interpret sub-mm
    differences with caution."
  - **Poor / not converged** — fitness ≤ 0.3 or RMS large: **the compare view is
    disabled or hard-gated behind a warning**; we do not draw two slices side by
    side and imply they're the same plane when we know they aren't.

### 3.2 Show the residual as a band, not a false line (MUST)
- The matched-plane crosshair on the *second* bone must carry a visible
  **uncertainty halo ≈ the RMS radius**, not a hairline crosshair. A 1-pixel
  crosshair claims sub-voxel correspondence we cannot honour. The halo says "the
  true corresponding point is somewhere in here."
- Corollary: **no automatic side-to-side difference measurement on the matched
  slices.** Any apparent "the operated cortex is 0.4 mm thinner here" read off the
  paired slices is within registration noise and must not be offered as a number.
  Quantitative side differences remain the job of the Mode-B signed-deviation map,
  which is computed on registered *geometry* with the sign verified — that's the
  honest channel for "how different".

### 3.3 Make it obvious which side is reference and which is moving (MUST)
- Label **REFERENCE** vs **REGISTERED-TO-REF (moved)**. The moved side has been
  transformed; its greyscale has been **resampled/interpolated** onto the common
  plane and is therefore slightly smoothed. Label the moved pane
  **"reformatted — interpolated"** so nobody reads its texture as native resolution.

### 3.4 Never fabricate the paired slice (MUST / red line)
- If the second volume has no data at the matched plane (out of field of view,
  cropped series), show **"no corresponding data"** — a blank labeled pane — never a
  nearest-substitute slice silently. Reusing the wrong slice to fill the box is the
  worst possible failure for a compare tool.

### 3.5 Let me sanity-check the registration myself (nice-to-have, high value)
- A quick **overlay/checkerboard/swipe** toggle of the two registered greyscale
  slices at the matched plane, so I can eyeball whether the cortices line up. This
  is the fastest way for a reader to catch a bad registration the metric didn't.
  Nice-to-have, but the cheapest trust-builder in the whole feature.

---

## 4. What must be caveated / labeled (the red-line list)

Persistent or context-shown, not a one-time modal people dismiss:

1. **Research use only, not a diagnostic device.** Footer, always (§2.5).
2. **De-identified data only.** The viewer must refuse / not display PHI overlays;
   burned-in annotations from source must be flagged if detected.
3. **Not for measurement off the slice.** No calipers on reformatted/interpolated
   slices. Measurement lives only in the Mode-A/B tools on source geometry. (§1.4)
4. **Orientation/laterality shown only when derived**, else "unverified/inferred"
   — never guessed. (§2.1–2.2)
5. **Mirrored views are labeled MIRRORED**, louder than the L/R letters. (§2.2)
6. **Matched cross-section is approximate**, carries RMS/fitness and an uncertainty
   halo; poor registration disables it. (§3)
7. **Interpolated/reformatted panes are labeled as such** (anisotropic reformats,
   the moved side). (§2.3, §3.3)
8. **Thickness numbers come from the map, not re-measured on the slice.** (§1.2)

---

## 5. AR — useful, or a toy?

Honest answer for the proximal humerus: **AR is not a clinical measurement tool and
must never pretend to be. Its real value is communication, and that value is real.**
I'd reject it as a diagnostic gimmick and accept it in three specific, honest roles.

### Where AR genuinely helps (accept):
- **Consent & patient education (highest value).** Handing a patient their own
  de-identified humerus, rotating on their phone, "here is where the cortex is thin
  / here is the remodeling", is a materially better conversation than a 2D printout.
  This is a real clinical use — of *communication*, not of *diagnosis*.
- **Teaching / trainees.** Registrars grasping 3D tuberosity/calcar morphology from
  a rotatable object beats flat slices. Genuine.
- **Sizing intuition at the table / MDT (soft).** A life-scale GLB gives a gestalt of
  size and defect location for planning conversation. **Not** for implant sizing or
  any measurement — see below.

### Where AR is a toy / dangerous (reject):
- **AR measurement / templating.** model-viewer scale, phone tracking drift, and the
  GLB being a *derived surface* (not the source volume) make any AR-measured distance
  untrustworthy. Explicitly disallowed. If someone rulers the AR model, they're
  measuring our mesh error plus ARKit drift, not the patient.
- **AR as a substitute for the slice viewer.** AR shows the surface; the clinical
  adjudication (§1.1) needs greyscale. AR does not replace MPR.

### AR requirements (MUST, if built):
- The exported **GLB carries a scale bar / known-size reference and the
  "research, de-identified, not to scale for measurement" note baked in**, because
  the GLB leaves our UI and loses our on-screen banners.
- **Laterality baked into the model label** (a floating "LEFT / RIGHT" or a text
  plate), because an AR object with no letters is trivially mirrored by the viewer's
  own perspective.
- MVP tier (GLB → `<model-viewer>` / Quick Look / Scene Viewer) is the right scope.
  The **WebXR clipping-plane cross-section is a genuinely nice prototype** — cutting
  the bone in the air to see the cortex is a good teaching moment — but it is
  Phase VI, Android-Chrome-limited, and must degrade to "not supported on this
  device" cleanly. Do not gate any must-have on it.

### AR overkill — avoid:
- Multi-user shared AR, AR annotation/markup, AR side-by-side compare of two bones.
  Cross-section compare is an on-desk task; doing it in AR is engineering for a demo,
  not for a decision.

---

## 6. Priorities — must-have vs nice-to-have

### MUST-HAVE (the feature is dishonest or useless without these)
- Three orthogonal MPR planes beside the 3D map, bone window default, adjustable
  WL/WW, slice index + mm position. (§1.1)
- Bidirectional 3D↔slice crosshair; thickness value from the map. (§1.2)
- Full orientation/laterality/scale/window labeling, derived-or-hidden. (§2)
- Compare = two linked MPR triplets on the registration-matched plane. (§1.3)
- Registration quality (RMS/fitness) shown inline + plain-language band; poor
  registration disables compare; uncertainty halo, not a hairline; no on-slice side
  difference number; "no corresponding data" instead of a substitute slice. (§3)
- Persistent research-only / de-identified / not-for-measurement caveats. (§4)
- AR MVP: GLB with baked-in scale reference + laterality + research note. (§5)

### NICE-TO-HAVE (add if cheap; don't block on)
- Overlay/checkerboard/swipe registration sanity-check on paired slices. (§3.5)
- The single anatomically-matched oblique plane for compare. (§1.3)
- Soft-tissue and custom window presets.
- WebXR clipping-plane cross-section prototype. (§5)

### OVERKILL — do not build
- Curved MPR, in-viewer VR/MIP cinematic render, on-slice calipers, free
  double-oblique in v1 (§1.4); AR measurement/templating, multi-user/annotation AR,
  AR compare (§5).

---

## 7. Things in the plan I'm flagging as illogical / risky

1. **"Compare reuses Mode-B registration to show the same plane"** is stated in the
   goal as if it's free truth. It isn't — it's only as true as `fitness`/`rms`.
   The plan must not present the compare view until those numbers are surfaced and
   gated (§3). As written, the goal risks a beautiful side-by-side that quietly
   lies. This is my strongest objection: **wire the gate before the view.**
2. **Slice-on-demand + oblique matched plane is a subtle correctness trap.** The
   matched plane is oblique in each volume's frame, so the backend must reformat
   (interpolate) — the "raw slice" honesty of slice-on-demand does not extend to the
   compare plane. That reformat must be labeled interpolated (§3.3). Don't let
   "slice-on-demand = always native pixels" leak into the compare path as a false
   reassurance.
3. **Laterality from the text heuristic** (`_laterality_from_ds` fallback) is a
   guess, and Mode-B mirror logic depends on it. The viewer must distinguish
   tag-derived from inferred laterality (§2.2), or a mislabeled side silently
   corrupts the whole compare.
4. **AR "views the 3D bone on a phone" with no baked-in scale/laterality/caveat**
   is the plan's biggest over-claim risk. Once the GLB leaves the app, every
   on-screen guardrail is gone. Bake them into the asset or the AR claim is
   unsupportable (§5).
5. **`is_isotropic` false + reformatted coronal/sagittal** will look deceptively
   detailed. If the plan doesn't label interpolation, a reader over-trusts a
   synthesised plane (§2.3).

Build the honesty rails first; then the views are safe to draw.
