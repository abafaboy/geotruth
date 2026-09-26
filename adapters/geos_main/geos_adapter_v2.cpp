// GEOS adapter, contract v2 (docs/DESIGN.md §4.1, schemas/result.v2.schema.json).
//
// geos_adapter.c keeps answering legacy FORMAT-v1 lines with its unchanged v1 code; every v2
// line (typed operands or "ops") comes here. Everything goes through the reentrant GEOS C
// API (geos_c.h, *_r functions), with the library defaults: floating PrecisionModel,
// OverlayNG with its snapping / snap-rounding fallbacks, RelateNG predicates (GEOS >= 3.13),
// Mod-2 boundary node rule (GEOSRelate_r, not GEOSRelateBoundaryNodeRule_r), and
// GEOSisValid_r (isInvertedRingValid = false).
//
//   relate                GEOSRelate_r
//   predicates.<name>     GEOSIntersects_r ... GEOSCoveredBy_r, GEOSCrosses_r, GEOSEquals_r
//                         (plain, unprepared calls; A, B order)
//   valid_a, valid_b      GEOSisValid_r
//   overlay.<op>          GEOSIntersection_r / GEOSUnion_r / GEOSDifference_r (A - B) /
//                         GEOSSymDifference_r, written back coordinate by coordinate from
//                         GEOSCoordSeq_copyToBuffer_r (never GEOSWKTWriter)
//   echo                  the operands built as GEOS geometries and read back the same way
//
// Every type is built as GEOS would read it from WKB, including empty elements; a geometry
// GEOS refuses to construct (e.g. an unclosed ring) fails every field that needs it with
// "building A: <GEOS message>".
#define GEOS_USE_ONLY_R_API
#include <geos_c.h>

#include "adapter_v2.hpp"

namespace {

using gt::Geom;
using gt::GType;
using gt::OpOut;
using gt::XY;

struct GeosError : std::runtime_error {
    using std::runtime_error::runtime_error;
};

extern "C" void on_error(const char *message, void *userdata)
{
    auto *m = static_cast<std::string *>(userdata);
    *m = message ? message : "(no message)";
}

extern "C" void on_notice(const char *, void *) {}

class GeosSession : public gt::Session {
  public:
    explicit GeosSession(const gt::Case &c) : h_(GEOS_init_r())
    {
        GEOSContext_setErrorMessageHandler_r(h_, on_error, &msg_);
        GEOSContext_setNoticeMessageHandler_r(h_, on_notice, nullptr);
        A_ = build_top(c.a, "building A", err_a_);
        B_ = build_top(c.b, "building B", err_b_);
    }
    ~GeosSession() override
    {
        if (A_)
            GEOSGeom_destroy_r(h_, A_);
        if (B_)
            GEOSGeom_destroy_r(h_, B_);
        GEOS_finish_r(h_);
    }

    OpOut run(int op) override
    {
        OpOut o;
        const bool need_a = op != gt::OP_VALID_B, need_b = op != gt::OP_VALID_A;
        if (need_a && !A_) {
            o.error = gt::json_quote(err_a_);
            return o;
        }
        if (need_b && !B_) {
            o.error = gt::json_quote(err_b_);
            return o;
        }
        msg_.clear();
        switch (op) {
        case gt::OP_ECHO:
            o.value = "{\"a\": " + gt::write_geometry(read(A_)) + ", \"b\": " + gt::write_geometry(read(B_)) + "}";
            break;
        case gt::OP_RELATE: {
            char *m = GEOSRelate_r(h_, A_, B_);
            if (!m)
                return fail("GEOSRelate_r failed");
            o.value = gt::json_quote(m);
            GEOSFree_r(h_, m);
            break;
        }
        case gt::OP_VALID_A:
        case gt::OP_VALID_B: {
            char v = GEOSisValid_r(h_, op == gt::OP_VALID_A ? A_ : B_);
            if (v != 0 && v != 1)
                return fail("GEOSisValid_r failed");
            o.value = gt::jbool(v);
            break;
        }
        case gt::OP_INTERSECTION:
        case gt::OP_UNION:
        case gt::OP_DIFFERENCE:
        case gt::OP_SYMDIFFERENCE: {
            GEOSGeometry *g = op == gt::OP_INTERSECTION ? GEOSIntersection_r(h_, A_, B_)
                              : op == gt::OP_UNION      ? GEOSUnion_r(h_, A_, B_)
                              : op == gt::OP_DIFFERENCE ? GEOSDifference_r(h_, A_, B_)
                                                        : GEOSSymDifference_r(h_, A_, B_);
            if (!g)
                return fail("overlay failed");
            try {
                o.value = gt::write_geometry(read(g));
            } catch (...) {
                GEOSGeom_destroy_r(h_, g);
                throw;
            }
            GEOSGeom_destroy_r(h_, g);
            break;
        }
        default: {
            char v = pred(op);
            if (v != 0 && v != 1)
                return fail("predicate failed");
            o.value = gt::jbool(v);
        }
        }
        return o;
    }

  private:
    GEOSContextHandle_t h_;
    std::string msg_; // the last GEOS error message
    GEOSGeometry *A_ = nullptr, *B_ = nullptr;
    std::string err_a_, err_b_;

    OpOut fail(const char *fallback)
    {
        OpOut o;
        std::string m = msg_.empty() ? fallback : msg_;
        o.error = m.find("bad_alloc") != std::string::npos ? gt::error_kind("memory", m) : gt::json_quote(m);
        return o;
    }

    char pred(int op)
    {
        switch (op) {
        case gt::OP_INTERSECTS: return GEOSIntersects_r(h_, A_, B_);
        case gt::OP_DISJOINT: return GEOSDisjoint_r(h_, A_, B_);
        case gt::OP_TOUCHES: return GEOSTouches_r(h_, A_, B_);
        case gt::OP_CROSSES: return GEOSCrosses_r(h_, A_, B_);
        case gt::OP_OVERLAPS: return GEOSOverlaps_r(h_, A_, B_);
        case gt::OP_CONTAINS: return GEOSContains_r(h_, A_, B_);
        case gt::OP_COVERS: return GEOSCovers_r(h_, A_, B_);
        case gt::OP_WITHIN: return GEOSWithin_r(h_, A_, B_);
        case gt::OP_COVERED_BY: return GEOSCoveredBy_r(h_, A_, B_);
        case gt::OP_EQUALS: return GEOSEquals_r(h_, A_, B_);
        }
        return 2;
    }

    // ------------------------------------------------------------ building

    GEOSGeometry *build_top(const Geom &g, const char *what, std::string &err)
    {
        msg_.clear();
        GEOSGeometry *out = nullptr;
        try {
            out = build(g);
        } catch (const GeosError &) {
            out = nullptr;
        }
        if (!out)
            err = std::string(what) + ": " + (msg_.empty() ? "failed" : msg_);
        return out;
    }

    GEOSCoordSequence *seq(const std::vector<XY> &pts)
    {
        // XY is std::array<double, 2>: the vector is a contiguous x, y, x, y, ... buffer
        GEOSCoordSequence *cs =
            GEOSCoordSeq_copyFromBuffer_r(h_, pts.empty() ? nullptr : pts.data()->data(), unsigned(pts.size()), 0, 0);
        if (!cs)
            throw GeosError("coordinate sequence");
        return cs;
    }

    GEOSGeometry *ring(const std::vector<XY> &pts)
    {
        GEOSGeometry *r = GEOSGeom_createLinearRing_r(h_, seq(pts)); // takes the sequence
        if (!r)
            throw GeosError("ring");
        return r;
    }

    GEOSGeometry *build(const Geom &g)
    {
        switch (g.type) {
        case GType::Point:
            if (g.coords.empty())
                return GEOSGeom_createEmptyPoint_r(h_);
            return GEOSGeom_createPointFromXY_r(h_, g.coords[0][0], g.coords[0][1]);
        case GType::LineString:
            if (g.coords.empty())
                return GEOSGeom_createEmptyLineString_r(h_);
            return GEOSGeom_createLineString_r(h_, seq(g.coords));
        case GType::Polygon: {
            if (g.rings.empty() || g.rings[0].empty())
                return GEOSGeom_createEmptyPolygon_r(h_);
            std::vector<GEOSGeometry *> rs;
            try {
                for (auto &r : g.rings)
                    rs.push_back(ring(r));
            } catch (...) {
                for (auto *r : rs)
                    GEOSGeom_destroy_r(h_, r);
                throw;
            }
            GEOSGeometry *p = GEOSGeom_createPolygon_r(h_, rs[0], rs.data() + 1, unsigned(rs.size() - 1));
            if (!p)
                for (auto *r : rs)
                    GEOSGeom_destroy_r(h_, r);
            return p;
        }
        default: {
            int t = g.type == GType::MultiPoint        ? GEOS_MULTIPOINT
                    : g.type == GType::MultiLineString ? GEOS_MULTILINESTRING
                    : g.type == GType::MultiPolygon    ? GEOS_MULTIPOLYGON
                                                       : GEOS_GEOMETRYCOLLECTION;
            if (g.parts.empty())
                return GEOSGeom_createEmptyCollection_r(h_, t);
            std::vector<GEOSGeometry *> ps;
            try {
                for (auto &p : g.parts) {
                    GEOSGeometry *e = build(p);
                    if (!e)
                        throw GeosError("part");
                    ps.push_back(e);
                }
            } catch (...) {
                for (auto *e : ps)
                    GEOSGeom_destroy_r(h_, e);
                throw;
            }
            GEOSGeometry *c = GEOSGeom_createCollection_r(h_, t, ps.data(), unsigned(ps.size()));
            if (!c)
                for (auto *e : ps)
                    GEOSGeom_destroy_r(h_, e);
            return c;
        }
        }
    }

    // ------------------------------------------------------------ reading back

    std::vector<XY> coords(const GEOSGeometry *g)
    {
        const GEOSCoordSequence *cs = GEOSGeom_getCoordSeq_r(h_, g);
        if (!cs)
            throw GeosError("GEOSGeom_getCoordSeq_r: " + msg_);
        unsigned n = 0;
        if (!GEOSCoordSeq_getSize_r(h_, cs, &n))
            throw GeosError("GEOSCoordSeq_getSize_r: " + msg_);
        std::vector<XY> out(n);
        if (n && !GEOSCoordSeq_copyToBuffer_r(h_, cs, out.data()->data(), 0, 0))
            throw GeosError("GEOSCoordSeq_copyToBuffer_r: " + msg_);
        return out;
    }

    Geom read(const GEOSGeometry *g)
    {
        Geom out;
        const int t = GEOSGeomTypeId_r(h_, g);
        const bool empty = GEOSisEmpty_r(h_, g) == 1;
        switch (t) {
        case GEOS_POINT:
            out.type = GType::Point;
            if (!empty)
                out.coords = coords(g);
            return out;
        case GEOS_LINESTRING:
        case GEOS_LINEARRING:
            out.type = GType::LineString;
            if (!empty)
                out.coords = coords(g);
            return out;
        case GEOS_POLYGON: {
            out.type = GType::Polygon;
            if (empty)
                return out;
            out.rings.push_back(coords(GEOSGetExteriorRing_r(h_, g)));
            int nh = GEOSGetNumInteriorRings_r(h_, g);
            for (int i = 0; i < nh; i++)
                out.rings.push_back(coords(GEOSGetInteriorRingN_r(h_, g, i)));
            return out;
        }
        case GEOS_MULTIPOINT:
        case GEOS_MULTILINESTRING:
        case GEOS_MULTIPOLYGON:
        case GEOS_GEOMETRYCOLLECTION: {
            out.type = t == GEOS_MULTIPOINT        ? GType::MultiPoint
                       : t == GEOS_MULTILINESTRING ? GType::MultiLineString
                       : t == GEOS_MULTIPOLYGON    ? GType::MultiPolygon
                                                   : GType::Collection;
            int n = GEOSGetNumGeometries_r(h_, g);
            for (int i = 0; i < n; i++)
                out.parts.push_back(read(GEOSGetGeometryN_r(h_, g, i)));
            return out;
        }
        default:
            throw GeosError("GEOS returned a geometry of type id " + std::to_string(t) +
                            ", which the v2 contract cannot express");
        }
    }
};

} // namespace

// ------------------------------------------------------------------ C interface

extern "C" {

// Is this input line a v2 case (typed operands or "ops")?
int geos_v2_is_case(const char *line, size_t len)
{
    return gt::looks_v2(std::string(line, len)) ? 1 : 0;
}

// Answer one v2 line on stdout. use_fork = 0 runs in-process (--no-fork).
void geos_v2_answer(const char *lib, const char *line, size_t len, int use_fork, double timeout_s,
                    long mem_mb, int timing, const char *test_fault)
{
    gt::RunConfig cfg;
    cfg.fork = use_fork != 0;
    cfg.timeout_s = timeout_s;
    cfg.mem_mb = mem_mb;
    cfg.timing = timing != 0;
    cfg.test_fault = test_fault ? test_fault : "";
    gt::SessionFactory make = [](const gt::Case &c) { return std::make_unique<GeosSession>(c); };
    gt::emit_line(gt::answer_v2(lib, std::string(line, len), make, cfg), "geos_adapter");
}

} // extern "C"
