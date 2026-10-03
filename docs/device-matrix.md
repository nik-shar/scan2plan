# Device matrix — which tier runs where, and what it honestly delivers

Capture route: **Route 2, stock tools** (`docs/adr/0001-capture-route.md`). The LiDAR
logger app + version is pinned at install time (recorded in each bundle's `meta.json` and
in the technical report).

## Hardware × tier

| Device | LiDAR sensor | LiDAR tier | Photos tier | Video tier |
|---|---|---|---|---|
| iPhone 15 / 15 Plus | ✗ | ✗ | ✅ (≥ 15) | ✅ |
| iPhone 15 Pro / Pro Max | ✓ | ✅ | ✅ | ✅ |
| iPhone 16 / 16 Plus | ✗ | ✗ | ✅ | ✅ |
| iPhone 16 Pro / Pro Max | ✓ | ✅ | ✅ | ✅ |
| iPhone 17 / Air | ✗ | ✗ | ✅ | ✅ |
| iPhone 17 Pro / Pro Max | ✓ | ✅ | ✅ | ✅ |

**Rule to state plainly:** the **LiDAR tier requires a Pro-class device**; photos and video
run on any iPhone 15 or newer. (There is no non-Pro iPhone with a LiDAR sensor.)

## Tier status in this repo (honest)

| Tier | Ingest | Recon | Geometry → plan | Gate target (brief) |
|---|---|---|---|---|
| **LiDAR** | ✅ implemented | ✅ implemented (`recon/lidar.py`) | ✅ implemented + invariant-checked | opening ≤ 2 cm on ≥ 85 %; ceiling ≤ 1.5 cm |
| **Photos** | ⚠️ layout recognised; **poses required by ingest** | ❌ not implemented (SfM + mono-depth scale) | ✅ (tier-agnostic once recon exists) | wall lengths ±8 %, must stitch per-room folders |
| **Video** | ⚠️ layout recognised | ❌ not implemented (frame extract + SfM) | ✅ (tier-agnostic once recon exists) | wall lengths ±3 % |

## Honest accuracy (LiDAR tier, from the seed captures)

- Metric scale is **confirmed millimetres** (ADR-0002); camera height 1.40–1.46 m and room
  height ~2.35–2.44 m across three independent captures.
- Depth is used as-is (metric), so per-measurement intervals are dominated by pose drift
  and plane RMS, not scale error.
- Known limits on the seeds: the multi-room capture resolves **7 rooms** after the fix loop
  (was 2 + 8 unobserved regions); ceilings are often reported `unmeasured` with the prior
  interval rather than guessed. These are reported, not hidden — see
  `docs/plans/04i-stage3.md` and `CHANGELOG.md`.

**Photos / video tiers are not yet runnable** — the pipeline stops at S2 for them
(`recon for tier 'photos' is not implemented yet`). Until they land, the walk-in test can
only be taken on a Pro-class device (LiDAR tier).
