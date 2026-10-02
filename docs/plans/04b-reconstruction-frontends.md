# 04b — Reconstruction Front-ends (per tier) & Scale

```
Owner:           04b
Provides:        I8 (recon artifact)
Consumes:        I1 (bundle), I7 (frames/units), I2 (CIR)
Must-not-change: I1, I2, I3, I6
Depends-on:      01, 02, 04a
```

The only tier-specific code. Output: **CIR `frames[]` + `recon`** (`I8`), consumed by `04c`/`04d`.

## 1. Tier → front-end → scale

| Tier | Front-end | Poses | Scale source | Honest CI driver |
|---|---|---|---|---|
| **lidar** | depth + ARKit odometry (already in `I1`) | from `odometry.csv` | **metric** (depth) | depth + pose noise |
| **video** | SfM (pycolmap/GLOMAP) | from SfM | **mono-depth or reference** (up-to-scale) | recon residuals |
| **photos** | SfM on 2–8 stills/room | from SfM | **mono-depth or reference** | few-view ambiguity |

## 2. B-0 — CRITICAL first task: verify depth units

Seed depth PNGs are uint16 with values ≈506–3732 for a room-sized scene ⇒ hypothesis **millimetres**.
**Verify before `I2` freezes:** back-project a wall, compare a known tape length.
If wrong, set `depth_scale_m` (I4) accordingly and record in ADR. *This gates M1.*

## 3. LiDAR front-end

1. Parse `odometry.csv` → `T_wc` per frame (quaternion **xyzw** → rotation), per-frame `K`.
2. Resize depth `256×192`→ model grid; scale `K` by `(256/1920, 192/1440)` for back-projection.
3. Back-project depth → point cloud in **camera** frame → transform via `T_wc` → **world**.
4. Filter by `confidence ≥ 1`; drop depth==0.
5. Downsample (voxel ~1 cm) → `points_ref` (PLY/npz). Build `pose_graph_ref` from odometry **as init only**
   (never "as-is" — `04d` optimizes).

## 4. Video front-end

1. Extract frames from `rgb.mp4` at fixed stride (e.g. 5) → `frames[]` (no poses).
2. SfM: intrinsics from `camera_matrix.csv`; run **pycolmap** (or GLOMAP) → sparse model + poses.
3. Dense: MVS or mono-depth-based dense; optional Open3D TSDF.
4. **Scale recovery:** (a) mono metric-depth model (disclosed) → align to SfM; or (b) reference
   (known camera height / door height 2.03 m). Record `scale_source`.

## 5. Photos front-end (hardest)

1. Per room, 2–8 stills → frames (EXIF focal length → FOV).
2. SfM per room; if too few views, fall back to **mono-depth + plane fitting** only (wider CI).
3. **Scale:** mono metric-depth or in-room reference; `scale_source` recorded.
4. Emit same `recon` shape so `04c` is unaware of the tier.

## 6. Scale strategy (shared)

- Prefer a **reference object/height** when present (most reliable, cheapest CI).
- Else **mono metric-depth** (e.g. a disclosed monocular metric depth model), aligned to SfM by robust
  scale search minimizing plane residuals.
- `I8.quality.scale_uncertainty` feeds `04f` → **wider CI on photo/video automatically**.

## 7. Determinism

- SfM seeded/deterministic config; cache `recon` by input hash.
- Mono-depth model output cached; **live path also runs** (walk-in requirement).

## 8. Tasks

| ID | Task | Done when |
|---|---|---|
| B-0 | **Verify depth units** on seed | known-wall error < 2 cm |
| B-1 | LiDAR ingest → CIR frames+recon | seed → world cloud + poses |
| B-2 | Video SfM path | seed `rgb.mp4` → poses + cloud |
| B-3 | Photos SfM path | synthesized photo folders → cloud |
| B-4 | Scale recovery (reference + mono-depth) | `scale_source` set; CI reflects it |
| B-5 | `I8` freeze + docs | `04c` consumes without tier checks |

## 9. Risks

| Risk | Mitigation |
|---|---|
| Depth-scale wrong | B-0 gate; ADR before freeze |
| Video/photos up-to-scale | reference first, mono-depth second; honest CI |
| Few-view photos fail SfM | mono-depth + plane fallback |
| Mono-depth model drift | pin version; cache; disclose |