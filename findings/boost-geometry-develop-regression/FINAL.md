**Title:** Regression since 1.87: `within()` is true and `intersection()` returns all of A for two overlapping triangles with a near-coincident vertex (bisected to 0edb673)

---

### Summary

Take two valid triangles A and B, where one vertex of B is 1 to 2 ulps away from a vertex of A. Boost.Geometry 1.87.0 through 1.92.0 and current `develop` give wrong results:

- `relation(A, B)` is `2FF10F212` and `within(A, B)` is true, although area(A) = 3.63 is much larger than area(B) = 0.27;
- `intersection(A, B)` returns all of A;
- `union_(A, B)` returns B alone.

The correct answer is a partial overlap with intersection area ≈ 0.0777. Versions 1.83 to 1.86 get it right.

I bisected the change to commit 0edb673, "fix: add condition to handle_as_touch" (fixes #1288, one of the four commits of PR #1346). It adds an early `return false` to `touch_interior::handle_as_touch`. Disabling that condition fixes this input, but it also breaks the #1288/#1293 regression tests, so I don't have a fix to propose.

### Reproducer

Both inputs use the default `bg::model::polygon<bg::model::d2::point_xy<double>>` (clockwise, closed), and both pass `bg::is_valid`.

```
A = POLYGON((-0.6 3,2 -1,-1.7 1.9,-0.6 3))
B = POLYGON((-1.6999999999999997 1.9000000000000004,-1 2,-2.6 1,-1.6999999999999997 1.9000000000000004))
```

```cpp
#include <boost/geometry.hpp>
#include <iomanip>
#include <iostream>

namespace bg = boost::geometry;
using point_t = bg::model::d2::point_xy<double>;
using polygon_t = bg::model::polygon<point_t>;   // default: clockwise, closed
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
              << "is_valid: " << bg::is_valid(a) << " " << bg::is_valid(b) << "\n"
              << "relation: " << bg::relation(a, b).str() << "\n"
              << "within: " << bg::within(a, b) << "  overlaps: " << bg::overlaps(a, b) << "\n"
              << "area A: " << bg::area(a) << "  area B: " << bg::area(b) << "\n"
              << "intersection: " << bg::area(i) << "\n"
              << "union: " << bg::area(u) << "\n"
              << "difference: " << bg::area(d) << "\n";
}
```

To check the geometry by hand:

- B's first vertex is A's vertex (-1.7, 1.9) moved by +1 ulp in x and +2 ulps in y, which is 5.0e-16 away.
- B's vertex (-1, 2) is strictly inside A. It is 0.6 below A's edge on the line y = x + 3.6 and inside A's other two edges.
- A's vertex (-1.7, 1.9) is strictly inside B.
- So the interiors overlap. A cannot be within B, because A's vertex (2, -1) is far outside B.

### Expected

These values are computed in exact rational arithmetic on the double inputs. Two independently written implementations agree.

```
relation: 212101212
within: false  overlaps: true
area A: 3.63  area B: 0.27
intersection: 0.077697841726618824
union: 3.8223021582733816
difference: 3.5523021582733811
```

Boost 1.86.0 prints:

```
is_valid: true true
relation: 212101212
within: false  overlaps: true
area A: 3.6299999999999999  area B: 0.27000000000000024
intersection: 0.077697841726618866
union: 3.8223021582733807
difference: 3.5523021582733816
```

### Actual

On develop 196d04c the output is the following. 1.87.0, 1.88.0, 1.89.0, 1.90.0, 1.91.0 and 1.92.0 print the same.

```
is_valid: true true
relation: 2FF10F212
within: true  overlaps: false
area A: 3.6299999999999999  area B: 0.27000000000000024
intersection: 3.6299999999999994
union: 0.27000000000000024
difference: 3.5523021582733816
```

The results also contradict each other. `difference` is correct, but intersection + difference = 7.18, far more than area(A) = 3.63.

### Versions tested

| Boost.Geometry | this input | original input (below) |
|---|---|---|
| 1.83.0 (600bac843, and Ubuntu's system 1.83), 1.84.0 (da14168e3), 1.85.0/1.86.0 (f82eb32da; both tags are the same geometry commit) | correct | correct up to tolerance: empty intersection instead of the 3.9e-16 sliver, relation `212101212` |
| develop cd4deda8e (parent of 0edb673) | correct | correct (intersection 4.3e-16) |
| develop **0edb673** "fix: add condition to handle_as_touch" | wrong | wrong: within, intersection = A, union area 0 |
| release branch 754695969 (parent of 9c4d7529b) | correct | correct |
| release branch **9c4d7529b** (cherry-pick of 0edb673) | wrong | wrong: union area 0 |
| 1.87.0 (c5ebb039a), 1.88.0 (c12caf960) | wrong | wrong: union area 0 |
| 1.89.0 (617d75e0c), 1.90.0 (93a8ff869), 1.91.0 (002ae2629), 1.92.0 (90c27ef0b) | wrong | wrong: union = B |
| develop **196d04c** (current HEAD, 2026-09-26) | wrong | wrong: union = B |
| open PR #1491, head 0f07f60 | wrong | – |

Test setup:

- g++ 13.3.0 with `-std=c++17 -O2` on x86-64, Ubuntu 24.04.
- The results are the same with `-O0`, `-march=native`, clang++ 18.1.3, and `-DBOOST_GEOMETRY_DEFAULT_STRATEGY_SIDE_USE_SIDE_ROBUST`.
- Each geometry tree's `include/` was placed ahead of the system Boost 1.83. Versions from 1.84 on also needed a one-line shim for `<boost/core/invoke_swap.hpp>`.

### Analysis

**1. Bisection.** Commit 0edb673 added the following early return at `include/boost/geometry/algorithms/detail/overlay/get_turn_info.hpp:366-378` (line numbers are from develop 196d04c):

```cpp
bool const has_k = ! non_touching_range.is_last_segment()
    && ! other_range.is_last_segment();
if (has_k
    && (same(side.pj_wrt_q1(), side.qj_wrt_p2())
     || same(side.pj_wrt_q2(), side.qj_wrt_p1())))
{
    ...
    return false;
}
```

**2. Trace.** I added an `fprintf` to `handle_as_touch` on develop. The function is called from `get_turn_info` at get_turn_info.hpp:1488 and :1502. Both `relation()` and `intersection()` reach the same call.

In `handle_as_touch`'s own naming, the non-touching range P is B's segments (-2.6, 1) → B0 → (-1, 2), and the other range Q is A's segments (2, -1) → (-1.7, 1.9) → (-0.6, 3). So pj = B0 and qj = A's vertex (-1.7, 1.9), which are 5.0e-16 apart. The values are:

| | pj_wrt_q1 | pj_wrt_q2 | qj_wrt_p1 | qj_wrt_p2 |
|---|---|---|---|---|
| computed (side_by_triangle) | -1 | 0 | 0 | -1 |
| exact | -1 | +1 | -1 | -1 |

`has_k` is 1, and `dm` is 8.87e-31.

- The early return fires on the first disjunct, `same(pj_wrt_q1, qj_wrt_p2)` = `same(-1, -1)`. Both of these signs are exactly correct, so exact side predicates alone would not avoid it.
- Before 0edb673, the call went on to the distance test at :410-412. There `dm` = 8.87e-31 ≈ 0, so the intersection was handled as a touch, which gives the correct result.
- The rounded zeros matter one step earlier. In exact arithmetic, A's (2, -1) and (-1.7, 1.9) are both strictly on the same side of P1 = (-2.6, 1) → B0, so P1 and Q1 do not intersect at all. They are found to touch only because `qj_wrt_p1` (determinant -2.0e-16) is within side_by_triangle's tolerance and comes out as 0.
- The comment on the condition gives the reason "segments might cross each other or touch the other in the middle". That does not seem to apply when pj and qj are the same point up to a few ulps.

**3. Experiments.** Neither of these is a proposed fix.

- Disabling the whole condition (`if (false && has_k && ...)`) makes both inputs correct. But the upstream test `test/algorithms/set_operations/set_ops_areal_areal.cpp`, which passes on develop, then fails 3 checks: `issue_1288_0_2` difference (a-b) is not valid, `issue_1288_0_2` symmetric difference is not valid, and `issue_1293` symmetric difference is not valid. So the condition is still needed.
- Keeping the condition, but skipping it when pj and qj are equal within 8·eps·max(|c|, 1) per coordinate, also makes both inputs correct, and `issue_1288_0_2` passes again. `issue_1293` symmetric difference is still reported as not valid.

**4. Relate and overlay.** Both are wrong from the same commit on, which fits the shared turn computation. The regression predates the graph-based traversal (`algorithms/detail/overlay/graph/`, new in 1.89). In 1.89 only the form of the wrong union for the original input changed, from area 0 to area(B).

<details>
<summary>Original input (two unit squares edge to edge; exact overlap is a 3.9e-16 sliver)</summary>

```
A = POLYGON((-0.07442943330621471 -0.7031786824539803,-0.7031786824539803 0.07442943330621471,0.07442943330621471 0.7031786824539803,0.7031786824539803 -0.07442943330621471,-0.07442943330621471 -0.7031786824539803))
B = POLYGON((0.7031786824539801 -0.07442943330621504,0.07442943330621438 0.7031786824539801,0.8520375490664094 1.3319279316017456,1.480786798214175 0.5543198158415505,0.7031786824539801 -0.07442943330621504))
```

- Exact: relation `212101212`, intersection 3.9034e-16, union 1.9999999999999993.
- develop 196d04c: relation `2FF11F212`, `within` = true, intersection 0.99999999999999967 (all of A), union 0.99999999999999956 (B only).
- 1.87 and 1.88 give union area 0.
- 1.83 to 1.86 give relation `212101212` with an empty intersection and union 1.9999999999999993.

</details>

### Related issues

- #1288 (closed): the issue fixed by 0edb673. The same PR #1346 also fixes #1345, in commit aa2162f.
- #1487 (open), "No intersection for polygons with close boundaries":
  - Its test case is correct in 1.86 to 1.88 and gives an empty intersection from 1.89 on.
  - With the condition above disabled, its intersection is correct but its union becomes empty. The same happens with the second experiment.
  - So it goes through the same code, but it is not the same regression.
- Checked and not the same: #1201, #1362, #1414, #1419, #1439, #1490. With double coordinates, #1414 and #1419 already fail on 1.83 and do not change when the condition is disabled.

This was found by differential testing against an exact rational-arithmetic oracle (geotruth: https://github.com/abafaboy/geotruth).
