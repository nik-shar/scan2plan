# Capture protocol — one page (Route 2, stock tools)

**What this is.** How to capture a property so `scan2plan` turns it into a plan. Follow it
literally; nothing here needs engineering knowledge. Route 2 is the locked decision
(`docs/adr/0001-capture-route.md`).

## Which device (LiDAR tier)

The working tier is **LiDAR**, which needs a **Pro-class iPhone**:

| Device | LiDAR | Tiers you can capture |
|---|---|---|
| iPhone 15 / 15 Plus / 16 / 16 Plus / 17 / Air | ✗ | photos, video |
| **iPhone 15 Pro / Pro Max, 16 Pro / Pro Max, 17 Pro / Pro Max** | ✓ | **LiDAR**, photos, video |

See `docs/device-matrix.md`. Everything below is the **LiDAR** route (the one the pipeline
currently runs end to end).

## 1. Install (once, < 10 min)

1. Install the **raw LiDAR logger** named in the submission (App Store), version pinned in
   `docs/device-matrix.md`. It must export: `depth/*.png` (256×192, uint16, **millimetres**),
   `confidence/*.png` (256×192, values 0/1/2), `odometry.csv` (poses + intrinsics),
   `camera_matrix.csv` (3×3 K), optional `imu.csv`, optional `rgb.mp4`.
2. No account, no network is needed at capture time.

## 2. Capture one room (~1–2 min per room)

1. Stand **inside** the room, phone at chest height (~1.3–1.5 m), **1× lens** (never 0.5×).
2. Press record and **walk slowly** around the room: keep every wall in view for a few
   seconds, **including the ceiling and the floor edges**, and pass **through each doorway**
   so rooms connect.
3. Move at ~0.3 m/s; do not stand still for long, do not spin fast.
4. For a whole property, record **one continuous scan** that visits every room (the
   pipeline stitches it); for a single room, ~30–60 s is enough.
5. Stop recording **inside** the last room (do not stop in a doorway).

**Avoid:** ultrawide lens, fast motion, mirrors/glass head-on, direct sunlight or very low
light, and re-compressing the video.

## 3. Hand off the files

1. Export the scan from the logger app to **Files → `raw/<capture_id>/`** (any 8-character id).
2. Copy that folder to a machine with the repo and run the two commands:

   ```bash
   scripts/build_bundle.sh raw/<capture_id> --out bundles \
       --device "iPhone 15 Pro" --ios "iOS 18.1" \
       --app "<logger name>" --app-version "<version>" --rooms-expected <N>
   python scripts/check_bundle.py bundles/<capture_id>     # capture QA (do this before leaving)
   scripts/run_capture.sh bundles/<capture_id>             # one command per capture
   ```

3. Read `out/<capture_id>/plan.svg` (the plan) and `out/<capture_id>/plan.json` (the data).
   If the run prints `STAGE-3 INVARIANTS FAILED`, the plan is written but flagged — the
   capture was too thin; re-shoot per §2.

## 4. What "good" looks like (capture QA)

`python scripts/check_bundle.py` prints frames, depth coverage and camera travel. Aim for
**coverage ≥ 30 %**, **travel ≥ 1 m per room**, and a depth range ~0.3–8 m. If it warns,
re-shoot before leaving the property.
