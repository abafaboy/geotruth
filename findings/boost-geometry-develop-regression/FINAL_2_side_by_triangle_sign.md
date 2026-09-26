**Title:** `within()` is true and `intersection()` returns all of A for two triangles that meet along a line; `side_by_triangle` returns the wrong non-zero sign (1.83 through develop)

---

### Summary

Take two valid triangles A and B that lie on opposite sides of the line y = 0.8x + 0.4, each with one edge on that line (in decimal). Boost.Geometry gives these results with the default strategies:

- `within(A, B)` is true;
- `intersection(A, B)` returns all of A;
- `union_(A, B)` returns B alone.

Exactly, the triangles overlap only in a sliver of area 1.85e-17, so "touching" would be the tolerance-level answer. The same results appear on 1.83, 1.86, 1.92.0 and develop 196d04c, so this is long-standing, not a regression.

The default side strategy `side_by_triangle` returns +1 for a triple whose exact orientation is -1. With `side_robust` as the default strategy, this input gives a result that is correct up to tolerance.

### Reproducer

Both inputs use the default types (clockwise, closed), and both pass `bg::is_valid`.

```
A = POLYGON((-2 -1.2,1 1.2,2 0,-2 -1.2))
B = POLYGON((-3 -2,-2 3,0 0.4,-3 -2))
```

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
    bg::read_wkt("POLYGON((-2 -1.2,1 1.2,2 0,-2 -1.2))", a);
    bg::read_wkt("POLYGON((-3 -2,-2 3,0 0.4,-3 -2))", b);
    mpolygon_t i, u;
    bg::intersection(a, b, i);
    bg::union_(a, b, u);
    std::cout << std::setprecision(17) << std::boolalpha
              << "relation: " << bg::relation(a, b).str()
              << "  within: " << bg::within(a, b) << "  touches: " << bg::touches(a, b) << "\n"
              << "intersection: " << bg::area(i) << "  union: " << bg::area(u) << "\n"
              << "side_by_triangle((-3,-2),(0,0.4),(1,1.2)) = "
              << bg::strategy::side::side_by_triangle<>::apply(point_t(-3, -2), point_t(0, 0.4), point_t(1, 1.2))
              << "\n";
}
```

To check the geometry by hand:

- (-2, -1.2), (1, 1.2), (-3, -2) and (0, 0.4) all satisfy y = 0.8x + 0.4 in decimal.
- A's third vertex (2, 0) is below that line, and B's third vertex (-2, 3) is above it.
- The two edges on the line overlap for x in [-2, 0].

### Expected vs actual

On develop 196d04c the program prints the following. 1.83, 1.86.0 and 1.92.0 print the same.

```
relation: 2FF10F212  within: true  touches: false
intersection: 3  union: 6.3000000000000007
side_by_triangle((-3,-2),(0,0.4),(1,1.2)) = 1
```

In the table below, the exact values are computed in rational arithmetic on the double inputs.

| | exact | 1.83, 1.86.0, 1.92.0, develop 196d04c |
|---|---|---|
| relation(A,B) | `212101212` (sliver overlap); `FF2F11212` (touch) would be acceptable within tolerance | `2FF10F212` |
| within(A,B) | false | true |
| area(intersection) | 1.85e-17 | 3 (= area(A)) |
| area(union) | 9.3 | 6.3000000000000007 (= area(B)) |
| side_by_triangle((-3,-2),(0,0.4),(1,1.2)) | -1 | +1 |

With `-DBOOST_GEOMETRY_DEFAULT_STRATEGY_SIDE_USE_SIDE_ROBUST` on develop, the output is `FF2F11212`, `touches` = true, intersection 0 and union 9.3. `side_robust` returns 0 for that triple.

The builds used g++ 13.3.0 with `-std=c++17 -O2` on x86-64, Ubuntu 24.04.

### Analysis

`side_by_triangle::apply` is at `strategy/cartesian/side_by_triangle.hpp:207-234` on develop 196d04c. It works as follows:

- It rotates the triple so that the lexicographically smallest point comes first. Here that point is (-3, -2).
- `side_value` (:94-117) computes the rounded differences dx, dy, dpx and dpy, then s = dx·dpy − dy·dpx.
- It returns 0 when |s| ≤ eps·max(|dx|, |dy|, |dpx|, |dpy|, 1), using `equals_factor_policy` (`util/math.hpp:131-135`).

For this triple:

- dx = 3 and dpx = 4 are exact.
- dy = 0.4 − (−2) rounds to 2.4, with an error of −1.1e-16.
- dpy = 1.2 − (−2) rounds to 3.2, with an error of +2.2e-16.
- The computed s is +2^-49 = +1.78e-15. The exact determinant of the double inputs is −2^-52 = −2.2e-16.
- The zero threshold is 4·eps = 8.9e-16, so the function returns +1 instead of 0.

The rounding error of s grows with the products |dx·dpy| and |dy·dpx|, but the threshold grows only with the largest difference. So nearly collinear points a few units apart can get a wrong non-zero sign.

I understand that `side_by_triangle` is a floating-point predicate with a tolerance. Here, though, the sign is wrong rather than zero, and the final error is not tolerance-sized: `within()` is true for a triangle whose vertex (2, 0) is 2.04 units away from B.

### Related issues

- #702 (open): FMA makes `side_by_triangle` inconsistent for nearly collinear points. This case is different: the sign is wrong without FMA, and it is consistently wrong.
- #918 (open): `side_robust` causes regressions when rescaling is off.
- #704 (open): `overlaps()` and `intersection()` disagree for polygons that meet along a line.

This was found by differential testing against an exact rational-arithmetic oracle (geotruth: https://github.com/abafaboy/geotruth).
