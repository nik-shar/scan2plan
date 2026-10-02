# 01 — Shared Conventions & Frozen Interfaces (the spine)

```
Owner:           01
Provides:        I1 (layout), I7 (frames/units)
Consumes:        —
Must-not-change: I2–I6, I8, I9
Depends-on:      —
```

Every other plan conforms to this doc. If any plan needs a different convention, it files an ADR (`README` §5).

## 1. Units

- **SI metres** everywhere internally. `mm`/`cm` only at capture/ground-truth boundaries.
- Angles in **radians**; timestamps in **seconds** (float, monotonic per capture).
- Areas in **m²**, volumes **m³**.

## 2. Language / packaging conventions

- Python **3.11+**, package `scan2plan` under `src/`.
- Typed with `pydantic` v2 for all serialisable data (CIR, config, schema).
- Formatter `ruff format`; lint `ruff`; types `mypy --strict` on `cir/`.
- Tests `pytest`; fixtures read from `bench/` and the **seed captures**.

## 3. Identifier conventions

| Entity | Pattern | Example |
|---|---|---|
| capture | `cap_<8hex>` | `cap_c00a170fe1` |
| room | `room_<slug>` | `room_living` |
| surface | `<room_id>_<type>_<n>` | `room_living_wall_3` |
| opening | `open_<room_id>_<n>` | `open_room_living_1` |
| damage | `dmg_<8hex>` | `dmg_9f31ab07` |
| measurement | `<entity>.<quantity>` | `room_living_wall_3.length` |

## 4. Coordinate frames (I7)

| Frame | Convention | Source |
|---|---|---|
| `world` (ARKit) | right-handed, **Y-up**, gravity-aligned, origin = session start | `odometry.csv` positions |
| `camera` | ARKit camera: **+X right, +Y up, −Z forward** | intrinsics in `camera_matrix.csv` |
| `room` | per-room local, Z-up, floor plane at z=0 | produced by `04c` |
| `plan` | 2D stitched, metres, axes = stitched world XY | produced by `04d` |

Pose in `odometry.csv` = `(x,y,z, qx,qy,qz,qw)` = **camera→world** `T_wc`. Quaternion order is **xyzw**.
Intrinsics `K` apply to the **1920×1440** RGB frame; depth is **256×192** ⇒ always resize depth and scale
`K` by `(256/1920, 192/1440)` before back-projection.

## 5. Measurement + uncertainty (owned by `04f`, referenced here)

```
Measurement{ id, kind, value, unit, ci_low, ci_high, method, tier, sources[] }
```
- `ci_low ≤ value ≤ ci_high`, 90% nominal coverage unless stated.
- **No bare float may cross a module boundary** — always a `Measurement`.

## 6. Interface I1 — Raw capture bundle (mirrors the seed data exactly)

```
<capture_group>/<capture_id>/            # capture_id = 8 hex (e.g. c00a170fe1)
  rgb.mp4                                # HEVC, 1920x1440, 60fps  (tier: video & lidar)
  depth/000000.png ...                   # uint16 256x192, units = MILLIMETRES  (tier: lidar)
  confidence/000000.png ...              # uint8  256x192, values {0,1,2}       (tier: lidar)
  odometry.csv                           # timestamp,frame,x,y,z,qx,qy,qz,qw,fx,fy,cx,cy,dcx,dcy
  camera_matrix.csv                       # 3x3 K (row-major, 3 lines)
  imu.csv                                # timestamp,a_x,a_y,a_z,alpha_x,alpha_y,alpha_z
  photos/room_<slug>/IMG_*.HEIC|JPG       # OPTIONAL tier: photos (2–8 per room)
  meta.json                              # OPTIONAL: device, iOS, tool+version, tier, rooms
```
- **Depth scale is an assumption (`0.001 m/unit`) and MUST be verified** (`04b` task B-0) against a
  known wall before `I2` freezes.
- `frame` index is zero-padded 6-digit and aligns `odometry` ↔ `depth` ↔ `confidence` ↔ `rgb` frames.
- Tier is **inferred** when `meta.json` absent: `depth/` present ⇒ LiDAR; else photos `photos/` ⇒ photos; else video.

## 7. Determinism & caching contract

- Cache dir `out/<capture_id>/cache/`, key = `sha256(input bytes + config digest + code version)`.
- Every stochastic step takes `seed` from config; default `1337`.
- Cached model outputs **must replay deterministically**, and the **live path must also run** (walk-in).
- No network calls at run time except `scripts/fetch_weights.sh`.

## 8. Config (`I4`) — minimal keys

```yaml
tier: auto            # auto|photos|video|lidar
seed: 1337
depth_scale_m: 0.001
units: m
output_dir: out
cache: true
loop_closure: true    # enables G-DRIFT ablation when false
calibration: { model: conformal, nominal: 0.90 }
```

## 9. Disclosure policy

Every pretrained model / dataset / API is listed in `09` with: name, version, licence, where used,
whether on-device or fetched. No undisclosed dependency may influence a reported number.

## 10. Interface change log

| Interface | Version | Change | Date |
|---|---|---|---|
| I1 | 1.0 | initial, matches seed captures | 2026-08 |