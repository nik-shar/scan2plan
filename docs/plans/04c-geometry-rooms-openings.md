# 04c — Geometry: Planes, Rooms, Walls, Openings

```
Owner:           04c
Provides:        rooms[] + surfaces[] + openings[] in I2
Consumes:        I8 (recon), I7 (frames), I6 (Measurement)
Must-not-change: I1, I2, I3, I8, I6
Depends-on:      04a, 04b
```

Turns the point cloud + poses into **rooms, walls, ceiling, floor area, openings** (OUT-1) — shared for all tiers.

## 1. Pipeline inside S3

1. **Floor/ceiling detection:** RANSAC horizontal planes; globally align gravity (from IMU) so floors are z=0.
2. **Manhattan alignment:** snap dominant wall normals to orthogonal axes (configurable).
3. **Wall extraction:** vertical planes via RANSAC/normal clustering; constrain to room extent.
4. **Room segmentation:** floor-plane polygons; ceiling height = distance floor↔ceiling plane.
5. **Wall polygons:** intersect wall planes with floor & ceiling → 2D wall segments.
6. **Openings:** detect on wall faces (see §3).
7. **Dimensions:** wall lengths, room floor area (Shapely), perimeter.

## 2. Room model

- `Room.boundary` = floor polygon (metres, Z-up room frame).
- `ceiling_height` = `Measurement` (plane-fit mean ± RMS-derived CI).
- `floor_area` = `Measurement` (polygon area; CI from boundary uncertainty).

## 3. Opening detection (G-OPEN: ≤2 cm on ≥85%, misses & phantoms both penalised)

Signals combined:
- **Depth discontinuity / hole** in the wall plane (passage/door).
- **Edge/colour continuity** break (window/door frame).
- Classification: `door` (to floor), `window` (onset above floor), `passage` (skinny, floor-to-ceiling).

Scoring note: the harness in `08` must count **false negatives and false positives**; so detection emits
`Opening` + a `detection_confidence` used to tune the operating point (precision/recall tradeoff) *before* the 85% gate.

## 4. Tier-agnostic contract

`04c` reads only `I8`. It **must not** branch on `session.tier`; instead tier differences arrive purely as
`recon.quality` → propagated to `Measurement` CI by `04f`.

## 5. Accuracy targets

| Quantity | Target | Gate |
|---|---|---|
| Opening width | ≤2 cm on ≥85% | G-OPEN |
| Ceiling height | ≤1.5 cm/room | G-CEIL |
| Wall length | LiDAR ~cm; photo ±8%; video ±3% | G-TIERACC |
| Floor area | footprint ±8% (photo) | G-PSTITCH |

## 6. Tasks

| ID | Task | Done when |
|---|---|---|
| G-1 | Floor/ceiling plane detection + gravity align | z axis = vertical on seeds |
| G-2 | Wall plane extraction + Manhattan snap | walls per seed room |
| G-3 | Room boundary + area + ceiling height | single-room plan renders (`04g`) |
| G-4 | Opening detector + classifier | opens found on seeds; P/R measured |
| G-5 | Dimension emitter (all as Measurement) | no bare floats |

## 7. Risks

| Risk | Mitigation |
|---|---|
| Mirror/glass false planes | reject planes with low depth-confidence support |
| Low light → sparse cloud | widen CI; flag in `recon.quality` |
| Phantom openings | precision/recall tuning in `08`; confidence threshold |
| Non-Manhattan rooms | config to relax orthogonality |