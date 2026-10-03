# 03 — Part 1: Capture Route, Protocol, Device Matrix

```
Owner:           03
Provides:        I1 (capture bundle writer)
Consumes:        I7 (frames/units)
Must-not-change: I2, I3, I6, I8, I9
Depends-on:      01, 02
```

## 1. Locked decision

**Route 2 — stock capture protocol (hybrid).**

- **Photos:** native **Camera** (any iPhone 15+) — tier forbids depth/poses.
- **Video:** native **Camera** (any iPhone 15+).
- **LiDAR:** a raw LiDAR logger exporting `I1` (depth + confidence + odometry poses + intrinsics + IMU + rgb).
  The **seed captures already match this export**, so the ingest contract is proven, not hypothetical.

(The custom-app option (Route 1) is *rejected* for install-time risk; recorded as ADR-0001.)

## 2. Deliverables from this part

1. `docs/protocol.md` — the **one-page** non-engineer protocol (graded: they follow it literally).
2. **Device matrix** (below) — which tier runs on which hardware + honest accuracy per tier.
3. `scripts/build_bundle.sh` — assemble a conformant `I1` bundle from raw tool exports.
4. Capture QA (optional): overlap/coverage checker that warns *before* leaving the room.

## 3. Device matrix (draft — accuracy filled from `04f`/`08`)

| Device | LiDAR | Photos | Video | LiDAR tier | Honest target |
|---|---|---|---|---|---|
| iPhone 15 / Plus | ✗ | ✅ | ✅ | ✗ | photo ±8%, video ±3% |
| iPhone 15 Pro / Max | ✓ | ✅ | ✅ | ✅ | LiDAR ~±1–1.5 cm |
| iPhone 16 / Plus | ✗ | ✅ | ✅ | ✗ | photo ±8%, video ±3% |
| iPhone 16 Pro / Max | ✓ | ✅ | ✅ | ✅ | LiDAR ~±1–1.5 cm |
| iPhone 17 / Air | ✗ | ✅ | ✅ | ✗ | photo ±8%, video ±3% |
| iPhone 17 Pro / Max | ✓ | ✅ | ✅ | ✅ | LiDAR ~±1–1.5 cm |

Rule to state plainly: **LiDAR tier = Pro-class only; photos/video = any iPhone 15 or newer.**
The accuracy column is a *measured* claim cross-checked by the walk-in test.

## 4. `docs/protocol.md` content spec (keep to one page)

Per tier: **what to install → how to walk/stand → how long → what to avoid → how to hand off files.**

- **Install:** Camera (built-in); LiDAR logger (App Store). Note version.
- **Photos (per room):** 1× lens, phone ~1.2–1.5 m, level; **2–8 stills**; ~60–70% overlap; every wall +
  corners + openings in frame. ~1–2 min/room. → one folder per room.
- **Video (per room):** one continuous clip; walk slowly, 1× lens; cover walls/ceiling/floor/openings;
  ~10–30 s. → original `.mov`, **no transcoding**.
- **LiDAR (per room, Pro):** record full coverage incl. **ceiling** (use `single_scan_with_ceiling` as the
  reference behaviour); ~1–2 min; export raw bundle.
- **Avoid:** ultrawide lens; fast motion; direct mirror/glass reflection; low light; re-compression.
- **Handoff:** drop exports into `<capture_group>/<capture_id>/` matching `I1`; run `scripts/build_bundle.sh`.

## 5. Hard cases to write into the protocol (CAP-5)

Mirrors/glass/wet surfaces (shoot oblique, second pass), low light (add light, avoid blur),
tight rooms (step back, use video tier), reflective floors (tilt to avoid floor mirror).

## 6. Tasks

| ID | Task | Done when |
|---|---|---|
| P1-1 | Write `docs/protocol.md` (≤1 page) | a non-engineer can follow it unaided |
| P1-2 | Name logger + version; record its export spec | export maps 1:1 to `I1` |
| P1-3 | `scripts/build_bundle.sh` | raw export → conformant `I1` bundle |
| P1-4 | Device matrix doc | hardware×tier coverage complete |
| P1-5 | (opt) capture QA checker | warns on low overlap/coverage |
| P1-6 | Synthesize photos/video tiers from seed `rgb.mp4` for dev | folders/`.mov` produced per room |
| P1-7 | Measure install time on a fresh device | recorded, < 10 min |

## 7. Acceptance

- **Install < 10 min** on an unseen device, measured and recorded.
- Protocol page unambiguous: a reviewer following it literally yields a bundle that `04b` ingests.
- `build_bundle.sh` output passes `scan2plan validate` bundle check.
- All three tiers represented in `bench/` (with `08`).

## 9. Implementation progress (04i)

| Task | Status | Artifact |
|---|---|---|
| P1-1 one-page protocol | ✅ | `docs/protocol.md` |
| P1-2 name logger + version, record export spec | 🟡 | app/version pinned at install time and recorded in each bundle's `meta.json`; the export spec is the I1 checklist in `docs/protocol.md` §1 |
| P1-3 `scripts/build_bundle.sh` | ✅ | `src/scan2plan/ingest/build.py` + `scripts/build_bundle.sh` (validated by re-loading as I1) |
| P1-4 device matrix doc | ✅ | `docs/device-matrix.md` (LiDAR = Pro-class only) |
| P1-5 (opt) capture QA checker | ✅ | `scripts/check_bundle.py` |
| P1-6 synthesise photos/video tiers for dev | ⬜ | blocked on the photo/video recon front-ends (04b B-2/B-3) |
| P1-7 measure install time | ⬜ | requires a real device + the pinned app |

The capture route is **LiDAR-only** end to end today (`scripts/run_capture.sh`); photos and
video are recognised by ingest but rejected at S2 (`recon/__init__.py`), which is the
remaining Part-1/Part-2 gap for the walk-in test.

## 8. Risks

| Risk | Mitigation |
|---|---|
| Protocol ambiguity → bad walk-in capture | dry-run the page on a non-engineer; iterate |
| Logger exports differ by version | pin version; verify export against `I1` in CI |
| Non-Pro device at defense | device matrix + photo/video always ready |
| Photos/video tiers not truly "raw" | dev synthesis is for pipeline only; walk-in uses real capture |