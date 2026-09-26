# `side_by_triangle` returns a wrong non-zero sign for nearly collinear points, and `within()`/`intersection()` then fail for two triangles sharing a decimal line (1.83 … 1.92, develop)

This is a separate, long-standing problem found in the same differential-testing run as ISSUE.md. It is not a regression: every version I tested, from 1.83 to develop, behaves the same.

## Summary

Take two valid triangles on opposite sides of the line y = 0.8x + 0.4, each with one edge on that line in decimal arithmetic. Boost.Geometry returns:

- `within(A, B) == true`;
- `intersection(A, B)` equal to all of A;
- `union_(A, B)` equal to B alone.

A reasonable answer, allowing for tolerance, would be "touching" (intersection ≈ 0, union ≈ area(A) + area(B)). The exact answer is an overlap sliver of area 1.85e-17.

The cause I can identify is that the default side strategy, `side_by_triangle`, returns +1 for a point whose exact side is -1. Its zero tolerance grows linearly with the coordinate differences, while the rounding error of the determinant it computes grows with the product of two differences.

## Minimal reproduction (`repro_side_sign.cpp`)

The polygons use the default types (clockwise, closed). Both are valid according to `bg::is_valid`.

```cpp
polygon_t a, b;   // bg::model::polygon<bg::model::d2::point_xy<double>>
bg::read_wkt("POLYGON((-2 -1.2,1 1.2,2 0,-2 -1.2))", a);
bg::read_wkt("POLYGON((-3 -2,-2 3,0 0.4,-3 -2))", b);
// within(a, b), relation(a, b), intersection / union_ / difference areas

point_t q1(-3, -2), q2(0, 0.4), p(1, 1.2);
bg::strategy::side::side_by_triangle<>::apply(q1, q2, p);   // returns 1; exact sign is -1
```

The four points (-2,-1.2), (1,1.2), (-3,-2) and (0,0.4) all satisfy y = 0.8x + 0.4 in decimal. A lies below the line and B above it, and their edges on the line overlap for x in [-2, 0].

## Expected vs actual

| | exact (rational arithmetic) | 1.83, 1.92.0, develop 196d04c |
|---|---|---|
| relation(A,B) | 212101212 (sliver overlap), or FF2F11212 (touch) if tolerance is applied | **2FF10F212** |
| within(A,B) | false | **true** |
| area(intersection) | 1.85e-17 | **3** (= area(A)) |
| area(union) | 9.3 | **6.3** (= area(B)) |
| area(difference A−B) | 3 | 3 |
| side_by_triangle((-3,-2),(0,0.4),(1,1.2)) | -1 | **+1** |

With `-DBOOST_GEOMETRY_DEFAULT_STRATEGY_SIDE_USE_SIDE_ROBUST` (develop), this input gives `FF2F11212`, `touches=true`, intersection 0 and union 9.3. That is correct up to tolerance. `side_robust` returns 0 for the same triple (see `output_side_sign_develop_side_robust.txt`).

## Analysis

`side_by_triangle::apply` (develop, `strategy/cartesian/side_by_triangle.hpp:207-234`) orders the triple, computes `dx, dy, dpx, dpy` as rounded differences of the coordinates, and computes s = dx·dpy − dy·dpx. It reports 0 when

    |s| <= DBL_EPSILON * max(|dx|, |dy|, |dpx|, |dpy|, 1)

using `equals_factor_policy` (`util/math.hpp:131-135`).

For the triple above:

- dx = 3 and dpx = 4 are exact.
- dy = 0.4 − (−2) is rounded to 2.4 with an error of −1.1e-16.
- dpy = 1.2 − (−2) is rounded to 3.2 with an error of +2.2e-16.
- The computed s is +1.78e-15 (2^-49), while the exact determinant is −2.2e-16 (−2^-52).
- The threshold is only 8.9e-16 (4·DBL_EPSILON), so the wrong sign +1 is returned rather than 0.

In general, the rounding error of s is on the order of DBL_EPSILON·(|dx·dpy| + |dy·dpx|), which is quadratic in the coordinate differences, while the threshold is linear in them. For coordinates of magnitude about 1 or less the two stay close, which may be why this is rarely seen with unit-scale data.

`side_robust` avoids the wrong sign: it computes the exact orient2d sign and then applies the same epsilon test for zero. In my corpus (below) it is only a partial remedy, though. It reduces the gross overlay/relate errors on these nearly collinear inputs by roughly 40-70% but does not remove them, so there are further mechanisms that I have not analysed.

## Scale

Test corpus:

- 72,403 random pairs of triangles with one-decimal coordinates in [-3, 3], each pair having a shared edge line that is collinear in decimal arithmetic.
- Only inputs that are valid (by the exact oracle and by `bg::is_valid`) are counted, and each result was checked against the exact oracle.

Gross errors (areas off by more than 1e-6 relative, or a wrong `within`/`covered_by`/`contains`/`covers`):

| version | within/covered_by wrong | intersection area wrong | union area wrong |
|---|---|---|---|
| 1.83 | 185 | 688 | 2076 |
| develop 196d04c | 185 | 687 | 2009 |
| develop + side_robust | 105 | 227 | 1183 |

## Documentation

`doc/robustness.qbk` says that Boost.Geometry "does not promise absolute numerical stability". However, that file is not included from `doc/geometry.qbk`, and the reference docs for `side_by_triangle` and the algorithms do not mention a tolerance. More to the point, the failure here is not "touching versus sliver overlap". `within()` returns true for a triangle whose far vertex (2, 0) is 2.04 units from B, and the intersection area is 3 for inputs that touch.

## Related issues

- #702 (open): consistency of `side_by_triangle` for nearly collinear points, in that case with FMA.
- #918 (open): `side_robust` causes regressions when rescaling is off.
- #704 (open): `overlaps()` vs `intersection()` inconsistency for polygons meeting along a line.
- #1201 (open): intersection returns the second polygon, for a different near-degenerate input. There the side signs are correct, and neither `side_robust` nor anything else I tried changes it.

Found by differential testing against an exact rational-arithmetic oracle, with an independent second exact implementation.
