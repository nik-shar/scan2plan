# archive/old_stage23 — pre-redesign stage 2/3 (plan 04i cleanup)

Moved here (not deleted) when stage 1 was frozen (`stage1-frozen`) and stages 2/3
were sent back for redesign. Nothing in `src/` imports from this directory.

| File | Was | Notes |
|---|---|---|
| `room_outline.py` | `scan2plan.geometry.room_outline` | 3-stage driver, classification (stage 2), snapping/provenance (stage 3) |
| `extract.py` | `scan2plan.geometry.extract` | `extract_room` / `RoomGeometry` entry point |
| `footprint.py` | `scan2plan.geometry.footprint` | occupancy-grid concave footprint + collinear merge |
| `wall_model.py` | `scan2plan.geometry.wall_model` | numpy port of the `room_fit` wall logic |
| `render_plan_svg.py` | `scan2plan.render.svg` | `render_room_svg` / `render_stage_svg` / `render_outline_svg` |
| `test_geometry.py`, `test_room_outline.py`, `test_render.py` | the matching tests | not collected (pytest `testpaths = tests`) |

They are excluded from ruff (`pyproject.toml` `extend-exclude`). The reference
module `scan2plan.geometry.room_fit` (the tested wall finder) was **kept** in
`src/`, unused by default, so the redesign can reuse it.