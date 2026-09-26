// CGAL adapter for geotruth: the exact control (docs/DESIGN.md §0.2).
//
//   cgal_adapter [--v2] [--exact SIDECAR.jsonl] [--timing] [--no-fork] CASES.jsonl > RESULTS.jsonl
//
// Kernel: CGAL::Exact_predicates_exact_constructions_kernel (Epeck): every double input is
// an exact rational and every constructed point (edge intersections) is exact. Overlay:
// Boolean_set_operations_2 (CGAL::Polygon_set_2) on polygons with holes, i.e. the
// REGULARIZED AREAL overlay only (DESIGN.md §1): no lines, no points, faces merged, so a
// result is a (multi)polygon or POLYGON EMPTY.
//
// Contract v2 (typed operands or "ops"; --v2 also for legacy lines), per-operation fork
// isolation from ../geos_main/adapter_v2.hpp:
//   overlay.<op>   Polygon_set_2 intersection / join / difference (A - B) /
//                  symmetric_difference; vertices written as correctly rounded doubles
//                  (round-half-even from the exact rational, subnormals included; never
//                  CGAL::to_double, which does not promise round-to-nearest). With --exact,
//                  a side-car line per case carries the EXACT result: every ordinate as a
//                  canonical "n/d" string from the kernel's exact FT, the exact area and the
//                  vertex count (the "areal" OverlayResult of schemas/expected.v2, minus wkt).
//   valid_a/_b     Polygon: after the adapter's own OGC pre-checks (finite ordinates,
//                  closed rings of >= 4 positions), on the rings with repeated points removed
//                  and shells turned CCW / holes CW (orientation is not an OGC criterion):
//                  CGAL::is_valid_polygon of the shell (strictly simple), and with holes also
//                  CGAL::is_valid_polygon_with_holes. MultiPolygon: null (CGAL has no
//                  multipolygon validity that matches OGC's). Known differences from OGC:
//                  a hole touching the shell or another hole at a point inside an edge is
//                  invalid for CGAL, valid for OGC; an interior disconnected by holes is not
//                  checked by CGAL.
//   predicates     derived for Polygon/MultiPolygon pairs from exact regularized overlays and
//                  exact segment contacts, which is exact for valid (regular closed) inputs:
//                    II = A∩*B ≠ ∅, AB = A−*B ≠ ∅, BA = B−*A ≠ ∅,
//                    contact = some boundary segment of A meets one of B (K::Do_intersect_2);
//                  intersects = II or contact, disjoint = not intersects, touches =
//                  intersects and not II, overlaps = II and AB and BA, contains = covers =
//                  not BA, within = covered_by = not AB, equals = not AB and not BA,
//                  crosses = false (A/A). null when an operand is empty (empty conventions).
//   relate         null (CGAL has no DE-9IM).
//   echo           the operands as CGAL points and back, through the exact conversion above.
//   Non-polygonal operands: every field but echo "unsupported"; non-finite ordinates: valid
//   false, the rest "unsupported". A polygon whose holes touch its shell or each other
//   (OGC-valid, but not a CGAL Polygon_with_holes_2) enters the overlay as its shell minus
//   its holes, the same point set; a shell or hole that is not a simple polygon makes the
//   overlays and predicates "unsupported" (outside CGAL's documented preconditions).
//
// Contract v1 (legacy lines, ../../harness/FORMAT-v1.md): the same computations mapped onto
// the v1 fields (areas = the correctly rounded exact areas), plus an extra field
// "exact": {"inter", "union", "diff", "symdiff"} with the exact areas as "n/d".
//
// Environment: CGAL_ADAPTER_TIMEOUT (per operation, default 10 s), CGAL_ADAPTER_MEM_MB
// (child address space, default 4096, 0 = none), CGAL_ADAPTER_TEST_FAULT (self-test).
#include <CGAL/Boolean_set_operations_2/Gps_polygon_validation.h>
#include <CGAL/Exact_predicates_exact_constructions_kernel.h>
#include <CGAL/Gps_segment_traits_2.h>
#include <CGAL/Polygon_2.h>
#include <CGAL/Polygon_set_2.h>
#include <CGAL/Polygon_with_holes_2.h>
#include <CGAL/assertions_behaviour.h>
#include <CGAL/version.h>

#include <gmp.h>

#include "adapter_v2.hpp"

#include <fstream>
#include <iostream>
#include <iterator>
#include <list>
#include <optional>
#include <sstream>

namespace {

using K = CGAL::Epeck;
using FT = K::FT;
using Point = K::Point_2;
using Segment = K::Segment_2;
using Polygon = CGAL::Polygon_2<K>;
using PWH = CGAL::Polygon_with_holes_2<K>;
using PSet = CGAL::Polygon_set_2<K>;
using Traits = CGAL::Gps_segment_traits_2<K>;

const char *const SEP = "\x1f"; // separates a value from its exact side-car part

struct Unsupported : std::runtime_error {
    using std::runtime_error::runtime_error;
};

std::string lib_string() { return std::string("cgal@") + CGAL_STR(CGAL_VERSION); }

// ------------------------------------------------------------------ exact numbers

// An mpq_t holder.
struct Q {
    mpq_t q;
    Q() { mpq_init(q); }
    ~Q() { mpq_clear(q); }
    Q(const Q &) = delete;
    Q &operator=(const Q &) = delete;
};

// The exact value of an Epeck number, canonical.
void to_mpq(const FT &x, Q &out)
{
    std::ostringstream os;
    os << CGAL::exact(x); // "n/d" or "n", whatever the exact backend (Gmpq, mpq_rational)
    if (mpq_set_str(out.q, os.str().c_str(), 10) != 0)
        throw std::runtime_error("cannot read the exact value '" + os.str().substr(0, 60) + "'");
    mpq_canonicalize(out.q);
}

std::string rational_string(const Q &x)
{
    char *s = mpq_get_str(nullptr, 10, x.q); // canonical: "n" or "n/d", d > 1, "0"
    std::string out(s);
    void (*freefunc)(void *, size_t);
    mp_get_memory_functions(nullptr, nullptr, &freefunc);
    freefunc(s, std::strlen(s) + 1);
    return out;
}

// The double nearest to the rational (ties to even), with subnormals and overflow to
// infinity: q is scaled by 2^sh so that the integer part has 53 bits (or sits on the
// subnormal grid 2^-1074), rounded once, and scaled back exactly.
double round_to_double(const Q &x)
{
    const int s = mpq_sgn(x.q);
    if (s == 0)
        return 0.0;
    mpz_t n, d, t, qt, r;
    mpz_inits(n, d, t, qt, r, nullptr);
    mpz_abs(n, mpq_numref(x.q));
    mpz_set(d, mpq_denref(x.q));
    long e = long(mpz_sizeinbase(n, 2)) - long(mpz_sizeinbase(d, 2)); // floor(log2 q) is e or e-1
    int cmp;
    if (e >= 0) {
        mpz_mul_2exp(t, d, (unsigned long)e);
        cmp = mpz_cmp(n, t);
    } else {
        mpz_mul_2exp(t, n, (unsigned long)(-e));
        cmp = mpz_cmp(t, d);
    }
    if (cmp < 0)
        e -= 1; // now 2^e <= q < 2^(e+1)
    double v;
    if (e > 1023) {
        v = INFINITY;
    } else {
        const long sh = e < -1022 ? 1074 : 52 - e;
        if (sh >= 0)
            mpz_mul_2exp(n, n, (unsigned long)sh);
        else
            mpz_mul_2exp(d, d, (unsigned long)(-sh));
        mpz_fdiv_qr(qt, r, n, d);
        mpz_mul_2exp(r, r, 1);
        int c = mpz_cmp(r, d);
        if (c > 0 || (c == 0 && mpz_odd_p(qt)))
            mpz_add_ui(qt, qt, 1);
        v = std::ldexp(mpz_get_d(qt), int(-sh)); // qt <= 2^53: exact; overflow -> inf
    }
    mpz_clears(n, d, t, qt, r, nullptr);
    return s < 0 ? -v : v;
}

struct ExactXY {
    std::string x, y; // "n/d"
    gt::XY rounded;
};

ExactXY exact_point(const Point &p)
{
    Q qx, qy;
    to_mpq(p.x(), qx);
    to_mpq(p.y(), qy);
    return ExactXY{rational_string(qx), rational_string(qy), {round_to_double(qx), round_to_double(qy)}};
}

// ------------------------------------------------------------------ building

bool finite(const gt::Geom &g)
{
    bool ok = true;
    gt::for_each_xy(g, [&](const gt::XY &p) { ok = ok && std::isfinite(p[0]) && std::isfinite(p[1]); });
    return ok;
}

// A ring as a CGAL polygon: closing point and repeated consecutive points dropped (they do
// not change the point set), turned CCW (shell) or CW (hole) by the exact signed area.
Polygon ring_polygon(const std::vector<gt::XY> &ring, bool shell)
{
    std::vector<Point> pts;
    for (const gt::XY &p : ring) {
        Point q(p[0], p[1]);
        if (pts.empty() || pts.back() != q)
            pts.push_back(q);
    }
    while (pts.size() > 1 && pts.front() == pts.back())
        pts.pop_back();
    Polygon pg(pts.begin(), pts.end());
    if (pts.size() >= 3) {
        CGAL::Sign sa = CGAL::sign(pg.area());
        if ((shell && sa == CGAL::NEGATIVE) || (!shell && sa == CGAL::POSITIVE))
            pg.reverse_orientation();
    }
    return pg;
}

PWH polygon_pwh(const gt::Geom &p)
{
    std::vector<Polygon> holes;
    for (size_t i = 1; i < p.rings.size(); i++)
        holes.push_back(ring_polygon(p.rings[i], false));
    return PWH(ring_polygon(p.rings[0], true), holes.begin(), holes.end());
}

std::vector<const gt::Geom *> polygons_of(const gt::Geom &g)
{
    std::vector<const gt::Geom *> out;
    if (g.type == gt::GType::Polygon) {
        if (!gt::is_empty(g))
            out.push_back(&g);
    } else {
        for (auto &p : g.parts)
            if (!gt::is_empty(p))
                out.push_back(&p);
    }
    return out;
}

// ------------------------------------------------------------------ output

struct Written {
    std::string rounded; // typed geometry, doubles
    std::string exact;   // {"exact": ExactGeometry, "area": Rational, "num_vertices": n}
    std::string area;    // exact area "n/d"
    double area_rounded = 0;
};

void ring_json(const Polygon &pg, std::string &rj, std::string &ej, size_t &nv)
{
    rj += '[';
    ej += '[';
    bool first = true;
    std::string ex0, rd0;
    for (auto it = pg.vertices_begin(); it != pg.vertices_end(); ++it) {
        ExactXY p = exact_point(*it);
        std::string rd = "[" + gt::fmt_double(p.rounded[0]) + ", " + gt::fmt_double(p.rounded[1]) + "]";
        std::string ex = "[\"" + p.x + "\", \"" + p.y + "\"]";
        if (first) {
            rd0 = rd;
            ex0 = ex;
        }
        rj += (first ? "" : ", ") + rd;
        ej += (first ? "" : ", ") + ex;
        first = false;
        nv++;
    }
    if (!first) { // close the ring
        rj += ", " + rd0;
        ej += ", " + ex0;
    }
    rj += ']';
    ej += ']';
}

Written write_set(const PSet &s)
{
    std::list<PWH> pwhs;
    s.polygons_with_holes(std::back_inserter(pwhs));
    std::vector<std::string> rparts, eparts;
    FT area(0);
    size_t nv = 0;
    for (const PWH &p : pwhs) {
        if (p.is_unbounded())
            throw std::runtime_error("unbounded overlay result");
        std::string rj = "[", ej = "[";
        ring_json(p.outer_boundary(), rj, ej, nv);
        area += p.outer_boundary().area();
        for (auto h = p.holes_begin(); h != p.holes_end(); ++h) {
            rj += ", ";
            ej += ", ";
            ring_json(*h, rj, ej, nv);
            area += h->area(); // holes are clockwise: negative
        }
        rparts.push_back(rj + "]");
        eparts.push_back(ej + "]");
    }
    auto geom = [](const std::vector<std::string> &parts) {
        if (parts.empty())
            return std::string("{\"type\": \"Polygon\", \"coordinates\": []}");
        if (parts.size() == 1)
            return "{\"type\": \"Polygon\", \"coordinates\": " + parts[0] + "}";
        std::string o = "{\"type\": \"MultiPolygon\", \"coordinates\": [";
        for (size_t i = 0; i < parts.size(); i++)
            o += (i ? ", " : "") + parts[i];
        return o + "]}";
    };
    Written w;
    Q qa;
    to_mpq(area, qa);
    w.area = rational_string(qa);
    w.area_rounded = round_to_double(qa);
    w.rounded = geom(rparts);
    w.exact = "{\"exact\": " + geom(eparts) + ", \"area\": \"" + w.area + "\", \"num_vertices\": " +
              std::to_string(nv) + "}";
    return w;
}

// ------------------------------------------------------------------ the session

class CgalSession : public gt::Session {
  public:
    explicit CgalSession(const gt::Case &c) : c_(c)
    {
        poly_ = gt::is_polygonal(c.a) && gt::is_polygonal(c.b);
        finite_ = finite(c.a) && finite(c.b);
    }

    gt::OpOut run(int op) override
    {
        gt::OpOut o;
        if (op == gt::OP_ECHO) {
            o.value = echo();
            return o;
        }
        if (!poly_) {
            o.value = gt::UNSUPPORTED;
            return o;
        }
        if (op == gt::OP_VALID_A || op == gt::OP_VALID_B) {
            o.value = validity(op == gt::OP_VALID_A ? c_.a : c_.b);
            return o;
        }
        if (op == gt::OP_RELATE)
            return o; // null: CGAL has no DE-9IM
        if (!finite_) {
            o.value = gt::UNSUPPORTED;
            return o;
        }
        try {
            return compute(op);
        } catch (const Unsupported &) {
            o.value = gt::UNSUPPORTED;
            return o;
        }
    }

  private:
    gt::OpOut compute(int op)
    {
        gt::OpOut o;
        if (gt::is_overlay(op)) {
            PSet r = set_a();
            switch (op) {
            case gt::OP_INTERSECTION: r.intersection(set_b()); break;
            case gt::OP_UNION: r.join(set_b()); break;
            case gt::OP_DIFFERENCE: r.difference(set_b()); break;
            default: r.symmetric_difference(set_b()); break;
            }
            Written w = write_set(r);
            o.value = w.rounded + SEP + w.exact;
            return o;
        }
        o.value = predicate(op);
        return o;
    }

    const gt::Case &c_;
    bool poly_ = false, finite_ = false;
    std::optional<PSet> a_, b_;
    std::optional<bool> ii_, ab_, ba_, contact_;

    // An operand as a CGAL polygon set. A polygon CGAL accepts as a Polygon_with_holes_2 goes
    // in as one; otherwise (OGC allows holes that touch the shell or each other at a point,
    // CGAL's polygon with holes does not) it is built as its shell minus its holes, the same
    // point set, from simple polygons only. A shell or hole that is not a simple polygon is
    // outside CGAL's contract: Unsupported.
    static PSet build_set(const gt::Geom &g)
    {
        const Traits traits;
        PSet s;
        for (const gt::Geom *p : polygons_of(g)) {
            PWH pwh = polygon_pwh(*p);
            if (CGAL::is_valid_polygon_with_holes(pwh, traits)) {
                s.join(pwh);
                continue;
            }
            if (!CGAL::is_valid_polygon(pwh.outer_boundary(), traits))
                throw Unsupported("the shell is not a simple polygon (CGAL precondition)");
            PSet part(pwh.outer_boundary());
            for (auto h = pwh.holes_begin(); h != pwh.holes_end(); ++h) {
                Polygon hole = *h;
                hole.reverse_orientation(); // clockwise hole -> counter-clockwise polygon
                if (!CGAL::is_valid_polygon(hole, traits))
                    throw Unsupported("a hole is not a simple polygon (CGAL precondition)");
                part.difference(hole);
            }
            s.join(part);
        }
        return s;
    }
    const PSet &set_a()
    {
        if (!a_)
            a_ = build_set(c_.a);
        return *a_;
    }
    const PSet &set_b()
    {
        if (!b_)
            b_ = build_set(c_.b);
        return *b_;
    }

    std::string validity(const gt::Geom &g)
    {
        if (!finite(g))
            return "false"; // OGC: Invalid Coordinate
        if (g.type == gt::GType::MultiPolygon)
            return "null"; // not comparable with OGC's multipolygon rules
        if (gt::is_empty(g))
            return "true"; // OGC: empty geometries are valid
        for (auto &r : g.rings)
            if (!gt::ring_closed(r) || r.size() < 4)
                return "false"; // OGC: ring not closed / too few points
        const Traits traits;
        PWH pwh = polygon_pwh(g);
        // the shell must be strictly simple (OGC); CGAL's polygon-with-holes rule alone would
        // accept a "relatively simple" shell that touches itself at a vertex
        if (!CGAL::is_valid_polygon(pwh.outer_boundary(), traits))
            return "false";
        if (pwh.number_of_holes() == 0)
            return "true";
        return gt::jbool(CGAL::is_valid_polygon_with_holes(pwh, traits));
    }

    bool interiors_meet()
    {
        if (!ii_) {
            PSet r = set_a();
            r.intersection(set_b());
            ii_ = !r.is_empty();
        }
        return *ii_;
    }
    bool a_minus_b()
    {
        if (!ab_) {
            PSet r = set_a();
            r.difference(set_b());
            ab_ = !r.is_empty();
        }
        return *ab_;
    }
    bool b_minus_a()
    {
        if (!ba_) {
            PSet r = set_b();
            r.difference(set_a());
            ba_ = !r.is_empty();
        }
        return *ba_;
    }

    static void segments(const gt::Geom &g, std::vector<std::pair<Segment, std::array<double, 4>>> &out)
    {
        for (const gt::Geom *p : polygons_of(g))
            for (auto &r : p->rings)
                for (size_t i = 0; i + 1 < r.size(); i++) {
                    const gt::XY &a = r[i], &b = r[i + 1];
                    if (a[0] == b[0] && a[1] == b[1])
                        continue;
                    out.push_back({Segment(Point(a[0], a[1]), Point(b[0], b[1])),
                                   {std::min(a[0], b[0]), std::min(a[1], b[1]), std::max(a[0], b[0]),
                                    std::max(a[1], b[1])}});
                }
    }
    // some boundary segment of A meets some boundary segment of B (exact)
    bool contact()
    {
        if (!contact_) {
            std::vector<std::pair<Segment, std::array<double, 4>>> sa, sb;
            segments(c_.a, sa);
            segments(c_.b, sb);
            bool hit = false;
            K::Do_intersect_2 meet;
            for (auto &x : sa) {
                for (auto &y : sb) {
                    const auto &p = x.second, &q = y.second; // exact double boxes
                    if (p[2] < q[0] || q[2] < p[0] || p[3] < q[1] || q[3] < p[1])
                        continue;
                    if (meet(x.first, y.first)) {
                        hit = true;
                        break;
                    }
                }
                if (hit)
                    break;
            }
            contact_ = hit;
        }
        return *contact_;
    }

    std::string predicate(int op)
    {
        if (gt::is_empty(c_.a) || gt::is_empty(c_.b))
            return "null"; // empty-geometry conventions: CGAL has no opinion
        switch (op) {
        case gt::OP_INTERSECTS: return gt::jbool(interiors_meet() || contact());
        case gt::OP_DISJOINT: return gt::jbool(!(interiors_meet() || contact()));
        case gt::OP_TOUCHES: return gt::jbool(!interiors_meet() && contact());
        case gt::OP_CROSSES: return "false"; // A/A
        case gt::OP_OVERLAPS: return gt::jbool(interiors_meet() && a_minus_b() && b_minus_a());
        case gt::OP_CONTAINS:
        case gt::OP_COVERS: return gt::jbool(!b_minus_a());
        case gt::OP_WITHIN:
        case gt::OP_COVERED_BY: return gt::jbool(!a_minus_b());
        case gt::OP_EQUALS: return gt::jbool(!a_minus_b() && !b_minus_a());
        }
        return "null";
    }

    // echo: each position as an exact CGAL point, then back through the exact conversion
    static void echo_geom(const gt::Geom &g, gt::Geom &rounded, std::string &exact)
    {
        rounded = g;
        bool ok = true;
        std::function<void(gt::Geom &)> conv = [&](gt::Geom &h) {
            auto one = [&](gt::XY &p) {
                if (!std::isfinite(p[0]) || !std::isfinite(p[1])) {
                    ok = false; // no exact value: echoed as parsed
                    return;
                }
                p = exact_point(Point(p[0], p[1])).rounded;
            };
            for (auto &p : h.coords)
                one(p);
            for (auto &r : h.rings)
                for (auto &p : r)
                    one(p);
            for (auto &q : h.parts)
                conv(q);
        };
        conv(rounded);
        if (!ok) {
            exact = "null";
            return;
        }
        exact = exact_geometry(g); // the same structure with "n/d" ordinates
    }

    static std::string exact_pos(const gt::XY &p)
    {
        ExactXY e = exact_point(Point(p[0], p[1]));
        return "[\"" + e.x + "\", \"" + e.y + "\"]";
    }
    static std::string exact_seq(const std::vector<gt::XY> &s)
    {
        std::string o = "[";
        for (size_t i = 0; i < s.size(); i++)
            o += (i ? ", " : "") + exact_pos(s[i]);
        return o + "]";
    }
    static std::string exact_rings(const std::vector<std::vector<gt::XY>> &rs)
    {
        std::string o = "[";
        for (size_t i = 0; i < rs.size(); i++)
            o += (i ? ", " : "") + exact_seq(rs[i]);
        return o + "]";
    }
    static std::string exact_geometry(const gt::Geom &g)
    {
        std::string o = std::string("{\"type\": \"") + gt::type_name(g.type) + "\", ";
        switch (g.type) {
        case gt::GType::Point: return o + "\"coordinates\": " + (g.coords.empty() ? "[]" : exact_pos(g.coords[0])) + "}";
        case gt::GType::LineString: return o + "\"coordinates\": " + exact_seq(g.coords) + "}";
        case gt::GType::Polygon: return o + "\"coordinates\": " + exact_rings(g.rings) + "}";
        case gt::GType::Collection: {
            o += "\"geometries\": [";
            for (size_t i = 0; i < g.parts.size(); i++)
                o += (i ? ", " : "") + exact_geometry(g.parts[i]);
            return o + "]}";
        }
        default: {
            o += "\"coordinates\": [";
            for (size_t i = 0; i < g.parts.size(); i++) {
                const gt::Geom &p = g.parts[i];
                o += i ? ", " : "";
                if (g.type == gt::GType::MultiPoint)
                    o += p.coords.empty() ? "[]" : exact_pos(p.coords[0]);
                else if (g.type == gt::GType::MultiLineString)
                    o += exact_seq(p.coords);
                else
                    o += exact_rings(p.rings);
            }
            return o + "]}";
        }
        }
    }

    std::string echo()
    {
        gt::Geom ra, rb;
        std::string ea, eb;
        echo_geom(c_.a, ra, ea);
        echo_geom(c_.b, rb, eb);
        std::string exact = ea == "null" || eb == "null" ? "null" : "{\"a\": " + ea + ", \"b\": " + eb + "}";
        return gt::echo_of(ra, rb) + SEP + exact;
    }
};

// ------------------------------------------------------------------ driver

struct Options {
    bool v2 = false, timing = false;
    std::string exact_path;
    gt::RunConfig cfg;
};

// value and exact side-car part of a field
std::pair<std::string, std::string> split(const std::string &v)
{
    size_t i = v.find(SEP);
    if (i == std::string::npos)
        return {v, ""};
    return {v.substr(0, i), v.substr(i + 1)};
}

gt::SessionFactory factory()
{
    return [](const gt::Case &c) { return std::make_unique<CgalSession>(c); };
}

void answer_v2(const std::string &lib, const std::string &line, const Options &o, std::ofstream *side)
{
    gt::Case c;
    try {
        c = gt::read_case(line);
    } catch (const std::exception &e) {
        gt::emit_line(gt::render_failed(lib, gt::id_of_line(line), std::string("input parse error: ") + e.what()),
                      "cgal_adapter");
        return;
    }
    std::vector<gt::FieldResult> res;
    gt::run_case(c, factory(), o.cfg, res);
    std::string exact = "{\"id\": " + c.id_json + ", \"lib\": " + gt::json_quote(lib);
    std::string ov;
    for (int op = 0; op < gt::NOPS; op++) {
        if (!res[op].done)
            continue;
        auto [value, ex] = split(res[op].value);
        res[op].value = value;
        if (ex.empty())
            continue;
        if (op == gt::OP_ECHO)
            exact += ", \"echo\": " + ex;
        else
            ov += std::string(ov.empty() ? "" : ", ") + "\"" + gt::op_key(op) + "\": " + ex;
    }
    if (!ov.empty())
        exact += ", \"overlay\": {" + ov + "}";
    if (side) {
        *side << exact << "}\n";
        side->flush();
    }
    gt::emit_line(gt::render(lib, c, res, o.cfg), "cgal_adapter");
}

// Legacy v1 line: the same computations under the v1 field names.
void answer_v1(const std::string &lib, const std::string &line, const Options &o)
{
    gt::Case c;
    try {
        c = gt::read_case(line);
    } catch (const std::exception &e) {
        std::string msg = std::string("input parse error: ") + e.what();
        std::string out = "{\"id\": " + gt::id_of_line(line) + ", \"lib\": " + gt::json_quote(lib);
        for (const char *k : {"valid_a", "valid_b", "intersects", "disjoint", "touches", "overlaps", "contains",
                              "covers", "within", "covered_by", "equals", "area_inter", "area_union",
                              "area_diff", "area_symdiff"})
            out += std::string(", \"") + k + "\": null";
        gt::emit_line(out + ", \"errors\": {\"parse\": " + gt::json_quote(msg) + "}}", "cgal_adapter");
        return;
    }
    c.groups = gt::G_VALIDITY | gt::G_PREDICATES | gt::G_OVERLAY;
    std::vector<gt::FieldResult> res;
    gt::run_case(c, factory(), o.cfg, res);
    struct F {
        const char *key;
        int op;
    };
    const F fields[] = {{"valid_a", gt::OP_VALID_A},       {"valid_b", gt::OP_VALID_B},
                        {"intersects", gt::OP_INTERSECTS}, {"disjoint", gt::OP_DISJOINT},
                        {"touches", gt::OP_TOUCHES},       {"overlaps", gt::OP_OVERLAPS},
                        {"contains", gt::OP_CONTAINS},     {"covers", gt::OP_COVERS},
                        {"within", gt::OP_WITHIN},         {"covered_by", gt::OP_COVERED_BY},
                        {"equals", gt::OP_EQUALS},         {"area_inter", gt::OP_INTERSECTION},
                        {"area_union", gt::OP_UNION},      {"area_diff", gt::OP_DIFFERENCE},
                        {"area_symdiff", gt::OP_SYMDIFFERENCE}};
    const char *exact_keys[] = {"inter", "union", "diff", "symdiff"};
    std::string out = "{\"id\": " + c.id_json + ", \"lib\": " + gt::json_quote(lib), errors, exact;
    for (const F &f : fields) {
        std::string v = res[f.op].done ? res[f.op].value : "null";
        if (gt::is_overlay(f.op)) {
            auto [value, ex] = split(v);
            v = "null";
            if (!ex.empty()) { // {"exact": ..., "area": "n/d", "num_vertices": n}
                gt::JVal j = gt::parse_json(ex);
                std::string area = j.get("area")->str();
                Q qa;
                mpq_set_str(qa.q, area.c_str(), 10);
                v = gt::fmt_double(round_to_double(qa));
                exact += std::string(exact.empty() ? "" : ", ") + "\"" + exact_keys[f.op - gt::OP_INTERSECTION] +
                         "\": \"" + area + "\"";
            }
        }
        if (v == gt::UNSUPPORTED)
            v = "null";
        out += std::string(", \"") + f.key + "\": " + v;
        if (res[f.op].done && !res[f.op].error.empty())
            errors += std::string(errors.empty() ? "" : ", ") + "\"" + f.key + "\": " + res[f.op].error;
    }
    if (!(gt::is_polygonal(c.a) && gt::is_polygonal(c.b)))
        errors += std::string(errors.empty() ? "" : ", ") + "\"unsupported\": \"non-polygonal operand\"";
    out += ", \"errors\": {" + errors + "}";
    if (!exact.empty())
        out += ", \"exact\": {" + exact + "}";
    gt::emit_line(out + "}", "cgal_adapter");
}

void quiet_warning(const char *, const char *, const char *, int, const char *) {}

[[noreturn]] void usage()
{
    std::fprintf(stderr, "usage: cgal_adapter [--v2] [--exact SIDECAR.jsonl] [--timing] [--no-fork] "
                         "CASES.jsonl > RESULTS.jsonl\n       cgal_adapter --version\n");
    std::exit(2);
}

} // namespace

int main(int argc, char **argv)
{
    const std::string lib = lib_string();
    Options o;
    std::string path;
    for (int i = 1; i < argc; i++) {
        std::string a = argv[i];
        if (a == "--version") {
            std::printf("%s\n", lib.c_str());
            return 0;
        } else if (a == "--v2") {
            o.v2 = true;
        } else if (a == "--timing") {
            o.cfg.timing = true;
        } else if (a == "--no-fork") {
            o.cfg.fork = false;
        } else if (a == "--exact" && i + 1 < argc) {
            o.exact_path = argv[++i];
        } else if (!a.empty() && a[0] == '-' && a != "-") {
            usage();
        } else {
            path = a;
        }
    }
    if (path.empty())
        usage();
    const char *e;
    if ((e = std::getenv("CGAL_ADAPTER_TIMEOUT")) && *e && std::atof(e) > 0)
        o.cfg.timeout_s = std::atof(e);
    if ((e = std::getenv("CGAL_ADAPTER_MEM_MB")) && *e)
        o.cfg.mem_mb = std::atol(e);
    if ((e = std::getenv("CGAL_ADAPTER_TEST_FAULT")))
        o.cfg.test_fault = e;
    // validity checks report through CGAL_warning_msg; the answer is the boolean
    CGAL::set_warning_handler(quiet_warning);
    std::signal(SIGPIPE, SIG_IGN);

    std::ifstream fin;
    std::istream *in = &std::cin;
    if (path != "-") {
        fin.open(path);
        if (!fin) {
            std::perror(path.c_str());
            return 2;
        }
        in = &fin;
    }
    std::unique_ptr<std::ofstream> side;
    if (!o.exact_path.empty()) {
        side = std::make_unique<std::ofstream>(o.exact_path);
        if (!*side) {
            std::perror(o.exact_path.c_str());
            return 2;
        }
    }
    std::string line;
    while (std::getline(*in, line)) {
        size_t s = line.find_first_not_of(" \t\r\n");
        if (s == std::string::npos)
            continue; // blank line: no output
        line = line.substr(s, line.find_last_not_of(" \t\r\n") - s + 1);
        if (o.v2 || gt::looks_v2(line))
            answer_v2(lib, line, o, side.get());
        else
            answer_v1(lib, line, o);
    }
    return 0;
}
