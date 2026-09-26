# Regression in 1.87: `within()` returns true and `intersection()` returns all of A for two triangles with nearly coincident vertices (bisected to 0edb673, "fix: add condition to handle_as_touch")

## Summary

Take two valid triangles whose vertices nearly coincide at one point (1 to 2 ulps apart). Boost.Geometry 1.87.0 through 1.92.0 and current `develop` return:

- `within(A, B) == true` and `relation(A, B) == "2FF10F212"`;
- `intersection(A, B)` equal to all of A: area 3.63, while area(B) is only 0.27;
- `union_(A, B)` equal to B alone.

The two triangles overlap in a small triangle of area about 0.078. That is not a sliver. So the correct answers are `within == false`, `overlaps == true`, intersection area ≈ 0.078 and union area ≈ 3.82. Boost 1.83 through 1.86 return these correct answers.

I bisected the change to commit 0edb673, "fix: add condition to handle_as_touch" (PR #1346, fixes #1288). Its cherry-pick onto the release branch is 9c4d7529b. In a local experiment, disabling only that added condition on `develop` gives the correct answer for this input. That experiment is not a fix, because it breaks the upstream regression test for #1288 (point 4 of the analysis).

## Minimal reproduction

The polygons use the default types (clockwise, closed), and the rings are written clockwise. `bg::is_valid` accepts both inputs.

```cpp
#include <boost/geometry.hpp>
#include <iomanip>
#include <iostream>
namespace bg = boost::geometry;
using point_t = bg::model::d2::point_xy<double>;
using polygon_t = bg::model::polygon<point_t>;
using mpolygon_t = bg::model::multi_polygon<polygon_t>;

int main()
{
    polygon_t a, b;
    bg::read_wkt("POLYGON((-0.6 3,2 -1,-1.7 1.9,-0.6 3))", a);
    bg::read_wkt("POLYGON((-1.6999999999999997 1.9000000000000004,-1 2,-2.6 1,"
                 "-1.6999999999999997 1.9000000000000004))", b);
    mpolygon_t i, u, d;
    bg::intersection(a, b, i);
    bg::union_(a, b, u);
    bg::difference(a, b, d);
    std::cout << std::setprecision(17) << std::boolalpha
              << bg::is_valid(a) << " " << bg::is_valid(b) << "\n"
              << bg::relation(a, b).str() << " within=" << bg::within(a, b) << "\n"
              << "area A=" << bg::area(a) << " B=" << bg::area(b) << "\n"
              << "intersection=" << bg::area(i) << " union=" << bg::area(u)
              << " difference=" << bg::area(d) << "\n";
}
```

`repro.cpp` is the full program. It also runs the original case in which this was found: two unit squares placed edge to edge, where B is A shifted by one edge vector.

The geometry, for checking by hand:

- A = (-0.6, 3), (2, -1), (-1.7, 1.9).
- B's first vertex is (-1.7, 1.9) moved by +1 ulp in x and +2 ulps in y, which is 5e-16 away.
- In decimal, A's edge from (-0.6, 3) to (-1.7, 1.9) and B's edge to (-2.6, 1) both lie on the line y = x + 3.6.
- B's vertex (-1, 2) is strictly inside A: it is 0.6 below the line y = x + 3.6, and on the inner side of A's other two edges. So the interiors overlap near (-1, 2), and A's vertex (2, -1) is far outside B.

## Expected

These values are computed in exact rational arithmetic on the exact double inputs. Two independently written exact implementations agree.

| | value |
|---|---|
| is_valid(A), is_valid(B) | true, true |
| relation(A,B) | 212101212 (the interiors intersect) |
| within(A,B), covered_by(A,B) | false, false |
| overlaps(A,B) | true |
| area(A), area(B) | 3.63, 0.27 |
| area(intersection) | 0.077697841726618824 |
| area(union) | 3.8223021582733816 |
| area(difference A−B) | 3.5523021582733811 |

## Actual

`repro.cpp` prints the same output on develop 196d04c, 1.92.0 and 1.87.0:

```
relation(A,B) = 2FF10F212
within(A,B) = true   covered_by(A,B) = true   overlaps(A,B) = false
area(intersection) = 3.6299999999999994
area(union)        = 0.27000000000000024
area(difference)   = 3.5523021582733816
intersection = MULTIPOLYGON(((-1.7 1.8999999999999999,-0.59999999999999998 3,2 -1,-1.7 1.8999999999999999)))
```

The results are also inconsistent with each other. `difference` is correct (3.55), but `intersection` returns all of A (3.63), so the two add up to about twice area(A).

On 1.83 and 1.86 (`output_1.83-system.txt`, `output_1.86.0.txt`) the output is `212101212`, `within=false`, `overlaps=true`, intersection 0.0776978…, union 3.8223….

## Versions

| Boost.Geometry | minimal case | original case (unit squares) |
|---|---|---|
| 1.83.0, 1.84.0, 1.86.0 | correct | correct |
| develop cd4deda8e (parent of 0edb673) | correct | correct |
| develop 0edb673 "fix: add condition to handle_as_touch" | **wrong** | **wrong** (union area 0) |
| release branch: 754695969 (parent of 9c4d7529b) | correct | correct |
| release branch: 9c4d7529b (cherry-pick of 0edb673) | **wrong** | **wrong** (union area 0) |
| 1.87.0, 1.88.0 | **wrong** | **wrong** (union area 0) |
| 1.89.0, 1.90.0, 1.91.0, 1.92.0 | **wrong** | **wrong** (union = B, area 1) |
| develop 196d04c (2026-08-17, current HEAD) | **wrong** | **wrong** (union = B, area 1) |

Test setup:

- g++ 13.3, `-std=c++17 -O2`, on x86-64 Ubuntu 24.04. The results are the same with `-O0`, with `-march=native`, and with clang++ 18.1.
- Each Boost.Geometry version's headers were placed in front of the system Boost 1.83. Versions from 1.84 on also needed a one-line shim for `<boost/core/invoke_swap.hpp>`.
- `BOOST_GEOMETRY_DEFAULT_STRATEGY_SIDE_USE_SIDE_ROBUST` does not change the result.

## Analysis

These points are based on bisection, a trace of the values involved, and two local experiments. Neither experiment is a proposed fix.

1. **Bisection.** `git bisect` between boost-1.86.0 and boost-1.87.0 points to 9c4d7529b. On `develop`, the same change is 0edb673 in PR #1346; its parent cd4deda8e is correct and 0edb673 is wrong (`output_develop_first_bad_pair.txt`). The commit added this early return to `touch_interior::handle_as_touch` (develop: `include/boost/geometry/algorithms/detail/overlay/get_turn_info.hpp:366-378`):

   ```cpp
   if (has_k
       && (same(side.pj_wrt_q1(), side.qj_wrt_p2())
        || same(side.pj_wrt_q2(), side.qj_wrt_p1())))
   {
       return false;
   }
   ```

2. **Trace for this input.** `handle_as_touch` is called from `get_turn_info` (get_turn_info.hpp:1481-1510). For one of the calls, `non_touching_range` is B's segment (-2.6, 1) → B0 → (-1, 2), and `other_range` is A's segment (2, -1) → A1 = (-1.7, 1.9) → (-0.6, 3). So pj = B0 and qj = A1, which are 5e-16 apart.
   - `pj_wrt_q1` and `qj_wrt_p2` are both -1. Checked with exact arithmetic, both signs are correct: B0 lies just outside A, and A1 lies just inside B.
   - `pj_wrt_q2` and `qj_wrt_p1` are 0. `side_by_triangle` classifies them as collinear, although the exact values are +1 and -1 (the determinants are about 2e-16).
   - `same(-1, -1)` is true, so the new condition returns `false`, and the intersection is processed as a `touch_interior` turn.

3. **Experiment.** On develop, I disabled only that `if` (`experiment_disable_condition.diff`; output in `output_develop_condition_disabled.txt`). The same calls then reach the existing distance test at get_turn_info.hpp:410-412. That test gives `dm = 8.9e-31`, so the intersection is handled as a touch, and the final results are correct for both inputs:
   - minimal case: relation 212101212, intersection area 0.0776978…, union 3.8223…;
   - original case: relation 212101212, intersection 4.3e-16, union 2.0.

4. **Not a fix.** Disabling the condition is not a fix; the condition is still needed:
   - The upstream test `set_ops_areal_areal`, which holds the #1288 and #1345 cases on develop, passes on develop. With the condition disabled it fails 3 checks: `issue_1288_0_2` difference and sym_difference are not valid, and `issue_1293` sym_difference is not valid (`output_upstream_set_ops_areal_areal.txt`).
   - The test case of #1487 changes from an empty *intersection* (develop) to an empty *union* (`output_issue1487_condition_disabled.txt`). 1.88.0 gets both right.
   - `intersection`, `intersection_multi`, `union`, `union_multi`, `difference`, `difference_multi` and `relate_areal_areal` pass both with and without the condition. I built them outside b2, double only. This is a partial check, not a full test-suite run.

   The condition seems to catch configurations with nearly coincident pj/qj, where the reasoning in its comment ("segments might cross each other or touch the other in the middle") does not hold, because both points are on the same side of the other segment only by a few ulps.

   I tried a second experiment (`experiment_nearly_same.diff`): keep the condition, but skip the early return when pj and qj are equal within 8·eps·max(|coordinate|, 1) per coordinate. With that change:
   - this input and the original case are correct;
   - `issue_1288` passes again;
   - `issue_1293` sym_difference is still reported invalid, and #1487 still gets an empty union (`output_experiment_nearly_same.txt`).

   So that is not a fix either. I have not found a change that keeps all of the existing tests passing and also handles this input.

5. Relate (`within`/`relation`) and overlay change together. This fits a change in the shared turn computation (`get_turn_info`) rather than in traversal. The regression is also older than the graph-based traversal (`algorithms/detail/overlay/graph/`, first in 1.89.0). In 1.89 only the *form* of the wrong union changed: the original case gives area 0 in 1.87 and 1.88, and area(B) from 1.89 on.

## Related issues

- #1288: the issue fixed by the commit. PR #1346 contains it, together with the fix for #1345.
- #1487 (open), "No intersection for polygons with close boundaries". In my builds its test case is correct in 1.87.0 and 1.88.0 and fails from 1.89.0 on. Disabling the condition moves the failure from intersection to union (point 4), so the two may share code paths, but it is not the same regression.
- #1360 (open), "Buffer (or other overlays) fail because arrival is not handled correctly". It is in the same area of `get_turn_info` (arrival handling for nearly collinear touching segments), but in a different block.
- Checked and not the same: #1414 (union fails on 1.87/1.88; with double coordinates its input already fails on 1.83 in my builds, and the condition does not change it), #1201 (fails in 1.83 as well and is not affected by the experiment), and #1439 and #1395 (both correct in my double-precision builds of all tested versions).

## How it was found

This was found by differential testing against an exact rational-arithmetic oracle. The oracle computes predicates and overlay areas exactly for the exact double inputs, and a second, independently written exact implementation cross-checks it. The minimal case was reduced automatically from the original case, keeping the requirements that develop is wrong while 1.83, 1.86 and develop with the condition disabled are all correct.
