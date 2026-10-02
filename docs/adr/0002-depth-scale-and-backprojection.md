# ADR-0002 — Depth units (millimetres) and the back-projection convention

* Status: Accepted
* Date: 2026-10
* Owner plan: `docs/plans/04b-reconstruction-frontends.md` (task **B-0**), `docs/plans/01` §4
* Supersedes: —

## Context

Interface **I1** stores `depth/*.png` as uint16; config **I4** hypothesises
`depth_scale_m = 0.001` (i.e. **millimetres**). Plan `04b` §2 makes verifying this
a **gate (B-0)**: `I2` must not freeze on an unverified scale.

Separately, plan `01` §4 describes the camera frame as "+X right, +Y up, −Z
forward", while the existing `util/frames.py:depth_to_points` uses the pinhole form
`X=(u−cx)Z/fx, Y=(v−cy)Z/fy, Z=depth`. Both define a right-handed frame (the former
is the OpenGL/ARKit view frame; the latter matches ARKit's
`cameraIntrinsics.inverse` / `unproject`). The two disagree on which camera axis is
world-up, and no tape measure is available for the seed captures.

## Evidence

`scripts/verify_depth_units.py` back-projects sampled depth frames with the
`odometry.csv` poses into the gravity-aligned world frame and looks for sharp
horizontal planes (a floor and, when present, a ceiling). Reproduce:

```
python scripts/verify_depth_units.py --json out/b0_depth_units.json
```

| Capture | floor y | ceiling y | camera height | room height | verdict |
|---|---|---|---|---|---|
| `single_room/c00a170fe1` | −1.474 m | — | **1.401 m** | n/a | plausible |
| `single_scan_floor_only/1a8384c3f6` | −1.410 m | — | **1.412 m** | n/a | plausible |
| `single_scan_with_ceiling/c7d28f72c6` | −1.491 m | +0.859 m | **1.464 m** | **2.35 m** | plausible |

Two decisive facts:

1. **Sharpness.** The pinhole convention yields sharp planes (floor support ~10–18%,
   RMS ≤ 1.3 cm; ceiling RMS 1.5 cm). The three other handedness-preserving axis
   maps are ambiguous/smeared (top Y-peaks only ~56k of 2.4M points, no clean
   geometry), so the empirical data selects the pinhole convention.
2. **Scale.** A handheld room scan must put the camera at ~1.2–1.6 m and the room at
   ~2.3–2.8 m. Scale discrimination (`single_room`):

   | assumed scale | camera height | plausible? |
   |---|---|---|
   | 0.0005 (½ mm) | +0.711 m | no |
   | **0.001 (1 mm)** | **+1.403 m** | **yes** |
   | 0.002 (2 mm) | +2.714 m | no |
   | 0.01 (10 mm) | +14.390 m | no |

   Only millimetres is plausible, and the inferred camera height is consistent
   (1.40–1.46 m) across three independent captures.

## Decision

1. **Confirmed: depth is in millimetres**, so `depth_scale_m = 0.001` stands as
   configured. `I2` may freeze on this basis (`04b` B-0 passes).
2. **Back-projection convention = pinhole** `X=(u−cx)Z/fx, Y=(v−cy)Z/fy, Z=depth`
   (camera −Z is forward-equivalent to OpenGL −Z; image centre is `(cx, cy)`). This
   is the convention `recon` implementations use; plan `01` §4's "+Y up" wording is
   read as describing the ARKit *view* frame and is superseded for the pixel→ray
   mapping by this ADR.

## Consequences

* `util/frames.py:depth_to_points` already matches the chosen convention.
* No `depth_scale_m` change is needed; no downstream re-derivation.
* Room/ceiling heights from the seed `with_ceiling` capture (~2.35 m) are usable as a
  sanity bound in `04c`.

## Alternatives considered

* Re-deriving scale per capture from a reference object — deferred; not needed while
  the metric depth is confirmed.
* Adopting the "+Y up" view frame for the pixel→ray map — rejected: it produced
  ambiguous plane geometry on the actual seed data.