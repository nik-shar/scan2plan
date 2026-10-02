# ADR-0001 — Capture route: stock protocol (Route 2), not a custom iOS app

* Status: Accepted
* Date: 2026-08
* Owner plan: `docs/plans/03-part1-capture.md`
* Supersedes: —

## Context

The brief (Part 1) allows two capture routes: Route 1, our own iOS capture app
(TestFlight/dev build) using ARKit/RoomPlan/raw LiDAR; or Route 2, a stock
off-the-shelf capture protocol (a LiDAR logging app + the native camera) with a
one-page protocol a non-engineer follows.

At the defense the reviewers install **our** capture tool on **their** device and
follow **our** page literally. Install time is scored (`< 10 min`) and ambiguity in
the page is scored against us.

## Decision

Adopt **Route 2 — stock capture protocol (hybrid)**:

* Photos and video: the native **Camera** app (any iPhone 15 or newer).
* LiDAR: a raw LiDAR logger that exports exactly interface **I1** (depth +
  confidence + odometry poses + intrinsics + IMU + rgb).

The three seed captures already present in the repo match this export format, so
the ingest contract is **proven against real data**, not hypothetical.

## Consequences

* No custom build to maintain, sign, or explain; install time is dominated by
  App Store download.
* We inherit the logger's export spec; it is pinned by version and verified
  against `I1` in CI (`03` task P1-2/P1-3).
* LiDAR tier is limited to Pro-class devices; the device matrix states this plainly
  and photos/video always remain runnable on non-Pro hardware.

## Alternatives considered

* **Route 1 — custom iOS app.** Rejected: install-time risk (signing/TestFlight
  friction) and build cost, with no accuracy benefit over the logger export for
  Round 1 scope.