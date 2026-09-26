# geo-i-overlay-thin-polygon-collapse: triage result

## Verdict: by design, and undocumented in geo. File it as a documentation/enhancement request, not a bug.

The behaviour reproduces on geo's latest development code and on its latest release. It is
not a defect in i_overlay's code. It follows from the overlay's precision model: geo's
`BooleanOps` hands `f64` input to i_overlay's float API. That API snaps every coordinate to
an **i32 grid** whose step is about 2^-29 of the half-extent of the joint bounding box, and
then runs an exact integer overlay. A valid polygon narrower than about one grid step
collapses to nothing. A polygon a few steps wide comes back visibly changed.

- **i_overlay documents this.** In 4.5.2, the version geo uses, the docs say only that float
  geometry is "converted to integer space" with a scale taken from the bounds. The README of
  the latest release (9.0.0, "Integer Coordinate Limits") states the 29-bit budget
  (`I::BITS - 3`) of the default i32 engine. It says to "use `i64` when the input bounds need
  a wider integer range".
- **geo does not document it.** The `BooleanOps` docs (geo 0.33.1 and `main`) say nothing
  about precision. They say that only "Degenerate 2-d geoms with 0 area are ... ignored".
- **The geo maintainers know about the grid.** It is mentioned in:
  - the commit that introduced i_overlay (`4915dfc`: "maps floating point geometries to a
    scaled fixed point grid");
  - a test comment (`bool_ops/tests.rs:95-97`);
  - Discussion #1215, where michaelkirk writes "expect no greater than 32 bit fixed point
    precision".

  None of these reach the API documentation.

### Facts established

| item | result |
|---|---|
| Latest development code | georust/geo `main` = `c12769fdf7453df1dd590e6e3bca28913d3c0564` (2026-09-19). It pins `i_overlay = "4.5.1, < 4.6.0"` (geo/Cargo.toml:43) and resolves to 4.5.2. Reproduces, with output identical to the release (`output_geo-main-c12769f.txt`). `bool_ops/` is byte-identical to 0.33.1. |
| Latest release | geo 0.33.1 (crates.io), with i_overlay 4.5.2 and i_float 1.16.0. Reproduces (`output_geo-0.33.1_i_overlay-4.5.2.txt`). rustc 1.94.1, release profile. |
| Latest i_overlay | 9.0.0 (i_float 5.0.0), iOverlay `main` `552e547`. Tested directly with the same inputs and `OverlayOptions::ogc()` + EvenOdd, as geo uses them. The default **i32** engine gives the same wrong results. The **i64** engine gives exact results for all inputs (`output_i_overlay-9.0.0_i32_vs_i64.txt`). |
| Minimal input | `POLYGON((0 0,1 0,0 2000000000,0 0))`, a right triangle 1 wide and 2e9 tall (area exactly 1e9). `a.intersection(&a)`, `a.union(&a)` and `a.union(&empty)` all return `MULTIPOLYGON EMPTY`. The same triangle 4 wide is returned exactly. |
| Other shapes | (a) Two 2e9 squares overlapping in a 1-wide strip: `A ∩ B` is empty, while geo's own `relate` gives `212111212` (interiors meet in 2-D). (b) `POLYGON((0 0,1 0,0 1e9,0 0))` (area 5e8): `A ∩ A` has area **1e9**, the triangle `(-0.5 0,1.5 0,-0.5 1e9)`, which is not inside A. (c) The fuzzer's `int-thin-triangle-1-0010`. |
| Input validity | All inputs are valid by geo's `Validation::is_valid()`, by GEOS 3.13.1 (shapely 2.1.2) and by oracle.py. The rings are closed, the shells are CCW (EvenOdd ignores orientation anyway), and the coordinates are exact doubles with no documented range limit in geo. |
| Exact answer | oracle.py and oracle_review/indep.py agree exactly on every case (`oracle_vs_indep.txt`, 0 disagreements). GEOS gives the exact areas (`output_shapely-2.1.2_geos-3.13.1.txt`). |
| compare.py | 8 `area` disagreements over 6 cases (`compare.txt`). The strip case is below the 1e-6 relative threshold (2e9 against operands of 4e18), but its intersection is still empty. |
| Root cause | `geo-0.33.1/src/algorithm/bool_ops/mod.rs:99` calls `FloatOverlay::with_subj_and_clip_custom`. That calls `FloatPointAdapter::with_iter` (`i_overlay-4.5.2/src/float/overlay.rs:153`), which sets `scale = 2^(29 - round(log2(max half-extent)))` (`i_float-1.16.0/src/adapter.rs:17-41`, rounding half away from zero at `float/number.rs:211-213`). Each point becomes `round((p - bbox_centre) * scale)` (`adapter.rs:116-129`, applied at `overlay.rs:239`). In the minimal case, the grid step is 2, the bbox centre is x = 0.5, and x = 0 and x = 1 both snap to integer 0. All three vertices then lie on one line, so the contour has zero area and nothing is output (`snap_emulate.py` emulates this snapping in IEEE doubles, and the snapped inputs in `snap_emulate_output.txt` account for every observed result, including the exact control). |

### Upstream tracker search

georust/geo issues and PRs, open and closed, searched for: "precision BooleanOps",
"i_overlay precision", "i_overlay", "union empty result", "intersection empty polygon",
"sliver", "integer BooleanOps", "grid", "BooleanOps area", "difference area wrong",
"union self area", and PRs for "i_overlay" and "precision". Semantic searches: "thin polygon
disappears union intersection returns empty", "boolean operation result loses precision
coordinates snapped". iShape-Rust/iOverlay issues searched for: "precision", "empty", "i64",
"scale", "large coordinates", and "thin OR narrow OR sliver OR disappear".

**No duplicate found.** No report shows a valid polygon vanishing, or being enlarged, by
`BooleanOps`. Related reports:

- **georust/geo#1493 "Union with self results in changing shape"** (closed 2026-01-29):
  https://github.com/georust/geo/issues/1493. This is the same mechanism in a mild form: a
  100-vertex unit circle, where `s.union(&s)` changes the area by about 1.7e-10 relative. It
  still reproduces on 0.33.1 (checked here), and no geo commit references it, so it appears
  to have been closed without a code change. The issue matches the tracker searches for
  "grid" and "integer", but its comments could not be loaded from this sandbox.
- **georust/geo Discussion #1215** (iOverlay introduction):
  https://github.com/georust/geo/discussions/1215. michaelkirk writes "expect no greater than
  32 bit fixed point precision", and the i_overlay author describes the bbox-centred scaling.
- **georust/geo Discussion #1540** "Boolean operations over integer coordinates" (June 2026):
  https://github.com/georust/geo/discussions/1540. It notes that i_overlay 7.0.0 added
  i16/i32/i64 engines, and the maintainer suggests upgrading i_overlay as a first step.
- **georust/geo PR #1234** (i_overlay introduced): https://github.com/georust/geo/pull/1234.
- **iShape-Rust/iOverlay#26** "Configurable Precision via `grid_size` Parameter" (closed
  completed 2026-01-02): https://github.com/iShape-Rust/iOverlay/issues/26. It led to the
  fixed-scale API (`overlay_with_fixed_scale`). It concerns precision control, not thin
  features.

### Recommendation for the hunt

Treat `BooleanOps` area disagreements in geo whose inputs have a feature narrower than a few
grid steps (step = `2^(round(log2 H) - 29)`, where H is the max half-extent of the joint
bbox) as this known limitation, not as new bugs. `snap_emulate.py` predicts the snapped
input. The draft below asks for documentation, and mentions the i64 engine as an option.

---

## Draft issue (for georust/geo)

**Title:** BooleanOps: document the fixed-precision grid (a valid thin polygon can vanish), and consider i_overlay's i64 engine

Hi, thanks for geo.

`BooleanOps` goes through i_overlay's float API. That API snaps every coordinate to an
`i32` grid scaled to the joint bounding box of both operands. The step is
`2^(round(log2(max half-extent)) - 29)`, so there are about 2^30 steps across the box. This
is known (#1215 and #1493, and the comment in `bool_ops/tests.rs`), but the `BooleanOps`
docs don't mention it. Its consequences can be surprising: a valid, non-degenerate polygon
narrower than about one grid step disappears, and one a few steps wide can change shape
noticeably.

```rust
// geo 0.33.1 (i_overlay 4.5.2); identical on main c12769f
use geo::{Area, BooleanOps, LineString, Polygon, Relate, Validation};
let p = |v: &[(f64, f64)]| Polygon::new(LineString::from(v.to_vec()), vec![]);

let a = p(&[(0., 0.), (1., 0.), (0., 2e9), (0., 0.)]);        // area 1e9
assert!(a.is_valid());
assert_eq!(a.intersection(&a).0.len(), 0);                    // MULTIPOLYGON EMPTY
assert_eq!(a.union(&a).0.len(), 0);                           // MULTIPOLYGON EMPTY

let s1 = p(&[(0., 0.), (2e9, 0.), (2e9, 2e9), (0., 2e9), (0., 0.)]);
let s2 = p(&[(-2e9 + 1., 0.), (1., 0.), (1., 2e9), (-2e9 + 1., 2e9), (-2e9 + 1., 0.)]);
assert!(s1.relate(&s2).is_overlaps());                        // "212111212"
assert_eq!(s1.intersection(&s2).0.len(), 0);                  // exact: the 1 x 2e9 strip

let b = p(&[(0., 0.), (1., 0.), (0., 1e9), (0., 0.)]);        // area 5e8
println!("{}", b.intersection(&b).unsigned_area());           // 1000000000
// result: POLYGON((-0.5 1e9,-0.5 0,1.5 0,-0.5 1e9)), not a subset of b
```

**Expected (exact):**
- `area(a ∩ a) = area(a ∪ a) = 1e9`.
- `s1 ∩ s2` is the strip `[0,1] x [0,2e9]`, area 2e9.
- `b ∩ b = b`, area 5e8.

These were confirmed with two independent exact rational implementations. GEOS 3.13.1
gives the same values.

**Actual:** empty, empty, and area 1e9. All the inputs are valid (`is_valid()`, GEOS, and
the exact checker). `a.union(&empty_polygon)` is also empty. The docs suggest that call as a
way to clean up geometry.

**Why:** `FloatOverlay::with_subj_and_clip_custom` builds `FloatPointAdapter::with_iter`
(i_float 1.16.0 `adapter.rs:17-41`, `116-129`). For `a`, the grid step is 2 and the box
centre is x = 0.5, so x = 0 and x = 1 both round to integer 0. The triangle becomes a line
and is dropped. For `b`, the step is 1, so 0 and 1 round to -1 and +1, which doubles the
width. Each output vertex is within about half a grid step of an exact position. For many
GIS inputs that step is small: about 1 mm for a 1000 km projected extent, and about 2.4e-7
degrees (about 2.7 cm at the equator) for a whole-world lon/lat extent. But it is far coarser than `f64`,
and it depends on the extent of both operands together.

**Suggestions (your call):**
1. Add a short "Precision" section to the `BooleanOps` (and `unary_union`/`Buffer`) docs.
   It would say that coordinates are snapped to a grid of about 2^-29 of the operands'
   half-extent, and that parts narrower than about one grid step may be removed or reshaped.
2. When geo moves past `i_overlay < 4.6`: i_overlay 7.0+ has selectable integer engines. With
   i_overlay 9.0.0, `FloatOverlay::<[f64; 2], i64>::from_subj_and_clip_custom(..,
   OverlayOptions::ogc(), ..)` returns the exact results for all the inputs above, while the
   default i32 engine still gives the same wrong results. The performance cost of i64 is not
   measured here.

**Versions:** geo 0.33.1 (crates.io) and geo `main` c12769f, both with i_overlay 4.5.2 and
i_float 1.16.0. i_overlay 9.0.0 tested directly. rustc 1.94.1, `--release`, Linux x86-64.

This was found by differential testing against an exact rational-arithmetic oracle, and the
expected values were confirmed by a second, independent exact implementation.

---

## Files

- `repro/` (Cargo.toml, Cargo.lock, src/main.rs): geo public API only. `./run.sh` runs it on
  geo 0.33.1; `GEO_SRC=/path/to/geo ./run.sh` runs it on a checkout.
- `output_geo-0.33.1_i_overlay-4.5.2.txt`, `output_geo-main-c12769f.txt`: captured runs.
- `i_overlay_9_check/`, `output_i_overlay-9.0.0_i32_vs_i64.txt`: i_overlay 9.0.0, i32 against i64.
- `cases.jsonl`, `oracle.jsonl`, `indep.jsonl`, `oracle_vs_indep.txt`: exact answers.
- `geo_adapter_0.33.1.jsonl`, `compare.txt`: the hunt adapter on the same cases.
- `output_shapely-2.1.2_geos-3.13.1.txt`: GEOS for comparison.
- `snap_emulate.py`, `snap_emulate_output.txt`: the grid snapping emulated in doubles.
