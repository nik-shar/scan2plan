# 04f — Uncertainty & Calibration

```
Owner:           04f
Provides:        I6 (Measurement type), calibration model
Consumes:        every measurement producer (04b/04c/04d/04e), I8 quality
Must-not-change: I1, I2, I3, I8
Depends-on:      04a, 04b, 04c
```

Requirement: **a confidence interval on every measurement**, honest as sensor data thins (OUT-6).
"Confident garbage on thin input caps your total score."

## 1. Measurement type (I6) — defined here, used repo-wide

```python
class Measurement(BaseModel):
    id: str; kind: str; value: float; unit: str
    ci_low: float; ci_high: float
    method: str                    # plane_fit | sfm | lidar | rule
    tier: Literal["photos","video","lidar"]
    sources: list[str] = []
```
Invariant: `ci_low ≤ value ≤ ci_high`; nominal coverage **90%** unless a measurement states otherwise.

## 2. Error sources per tier

| Tier | Dominant error | Feeds CI via |
|---|---|---|
| lidar | depth noise, pose drift, plane RMS | low |
| video | SfM residual, scale (mono) | medium |
| photos | few-view ambiguity, scale | high |

## 3. Calibration model — conformal prediction (distribution-free)

1. On the benchmark set, collect **nonconformity scores** `|pred − gt|` per `(kind × tier)`.
2. Compute quantile `q̂` at nominal 90%.
3. At inference: `CI = value ± q̂(kind, tier, feature_bucket)`; bucket by features (room size, wall length,
   `recon.quality`).
4. **Guarantee:** empirical coverage ≈ nominal; report it.

Fallback (if data thin): per-tier multiplicative `σ` model from `recon.quality` (analytic propagation).

## 4. Tier multipliers (validated, not asserted)

`width(CI): photos > video > lidar`. Enforced by construction and **measured** in `08` (coverage table).

## 5. Walk-in behaviour

- No ground truth on the day → CI computed from the **fitted calibration** (features only).
- If inputs are thin (few photos, blurry video) → features push `q̂` up → **wider CI** automatically.

## 6. Deliverables from this part

- `uncertainty/calibrate.py` (fit) + `uncertainty/conformal.py` (apply).
- Coverage table: per `(kind, tier)` predicted vs empirical.

## 7. Tasks

| ID | Task | Done when |
|---|---|---|
| U-1 | `I6` Measurement type frozen | used by all producers |
| U-2 | Nonconformity collection harness | scores per kind×tier |
| U-3 | Conformal fit + apply | coverage within ±5% of 90% |
| U-4 | Feature bucketing | thin input ⇒ wider CI |
| U-5 | Coverage report | in benchmark report |

## 8. Risks

| Risk | Mitigation |
|---|---|
| Too few calibration samples | pool kinds; fallback analytic σ |
| CI too tight (overconfident) | conformal guarantee + coverage check in CI |
| Tier leakage in features | features exclude tier label except as multiplier |