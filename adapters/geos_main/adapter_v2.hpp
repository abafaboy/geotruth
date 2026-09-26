// geotruth adapter contract v2 runtime, shared by the native adapters
// (geos_main, boost_geometry, clipper2, cgal). Header-only, C++17, no dependencies.
//
// Contract: docs/DESIGN.md §4.1 and schemas/result.v2.schema.json.
//
//   * Input: one case per line, {"id", "ops"?, "a", "b", ...}. An operand is a typed JSON
//     geometry ({"type": "Point" | ... | "GeometryCollection", "coordinates" | "geometries"})
//     or a FORMAT-v1 multipolygon array (a Polygon when it has exactly one part). A line is a
//     v2 case when an operand is an object or "ops" is present; otherwise it is a legacy v1
//     case, which each adapter answers with its unchanged v1 code (--contract v2 forces v2).
//   * Numbers are read with strtod (glibc rounds correctly, so every JSON number becomes the
//     double float() gives: 9007199254740993 -> 2^53) and written back with std::to_chars,
//     the shortest decimal that round-trips. NaN / Infinity / -Infinity are read and written
//     as the Python json module does. Nothing goes through a library's WKT writer.
//   * Output: {"id", "lib", "relate"?, "predicates"?, "valid_a"?, "valid_b"?, "overlay"?,
//     "echo"?, "errors", "elapsed_ms"?}: only the groups the case asks for ("ops"; absent
//     means everything except echo). A field is null when the library does not provide it,
//     "unsupported" when the input is outside the library's contract, and null plus an
//     entry in errors (keyed by field path) when it failed.
//   * Isolation: every operation runs in a forked child that streams each result to the
//     parent as soon as it has it. A crash or a hang (per-operation timeout, SIGKILL) fails
//     that one operation, {"kind": "crash" | "timeout", ...}, and a fresh child continues
//     with the next one. The child's address space is capped (std::bad_alloc is reported
//     as {"kind": "memory", ...}).
#pragma once

#include <array>
#include <cerrno>
#include <charconv>
#include <cmath>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <memory>
#include <new>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <poll.h>
#include <sys/resource.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

namespace gt {

// =========================================================================== JSON

struct JsonError : std::runtime_error {
    using std::runtime_error::runtime_error;
};

struct JVal {
    enum Kind { NUL, BOOL, NUM, STR, ARR, OBJ } kind = NUL;
    bool b = false;
    double num = 0;
    std::string raw; // STR: the JSON text with quotes and escapes; NUM: the number token
    std::vector<JVal> arr;
    std::vector<std::pair<std::string, JVal>> obj; // key: raw JSON text, quotes included

    const JVal *get(const char *key) const
    {
        std::string want = std::string("\"") + key + "\"";
        for (auto &kv : obj)
            if (kv.first == want)
                return &kv.second;
        return nullptr;
    }
    // the decoded value of a string without escapes (keys and type names never have any)
    std::string str() const { return raw.size() >= 2 ? raw.substr(1, raw.size() - 2) : raw; }
};

class JsonParser {
  public:
    JsonParser(const char *s, size_t n) : start_(s), p_(s), end_(s + n) {}

    JVal document()
    {
        JVal v = value(0);
        ws();
        if (p_ != end_)
            fail("trailing characters");
        return v;
    }

  private:
    const char *start_, *p_, *end_;

    [[noreturn]] void fail(const std::string &what) const
    {
        throw JsonError(what + " at byte " + std::to_string(p_ - start_));
    }
    void ws()
    {
        while (p_ < end_ && (*p_ == ' ' || *p_ == '\t' || *p_ == '\n' || *p_ == '\r'))
            ++p_;
    }
    bool lit(const char *w)
    {
        size_t n = std::strlen(w);
        if (size_t(end_ - p_) >= n && !std::memcmp(p_, w, n)) {
            p_ += n;
            return true;
        }
        return false;
    }
    std::string string_token()
    {
        const char *s = p_;
        if (p_ >= end_ || *p_ != '"')
            fail("expected string");
        ++p_;
        while (p_ < end_ && *p_ != '"') {
            if (*p_ == '\\')
                ++p_;
            ++p_;
        }
        if (p_ >= end_)
            fail("unterminated string");
        ++p_;
        return std::string(s, p_);
    }
    JVal value(int depth)
    {
        if (depth > 200)
            fail("nesting too deep");
        ws();
        if (p_ >= end_)
            fail("unexpected end of input");
        JVal v;
        const char c = *p_;
        if (c == '{') {
            v.kind = JVal::OBJ;
            ++p_;
            ws();
            if (p_ < end_ && *p_ == '}') {
                ++p_;
                return v;
            }
            for (;;) {
                ws();
                std::string k = string_token();
                ws();
                if (p_ >= end_ || *p_ != ':')
                    fail("expected ':'");
                ++p_;
                v.obj.emplace_back(std::move(k), value(depth + 1));
                ws();
                if (p_ < end_ && *p_ == ',') {
                    ++p_;
                    continue;
                }
                if (p_ < end_ && *p_ == '}') {
                    ++p_;
                    break;
                }
                fail("expected ',' or '}'");
            }
        } else if (c == '[') {
            v.kind = JVal::ARR;
            ++p_;
            ws();
            if (p_ < end_ && *p_ == ']') {
                ++p_;
                return v;
            }
            for (;;) {
                v.arr.push_back(value(depth + 1));
                ws();
                if (p_ < end_ && *p_ == ',') {
                    ++p_;
                    continue;
                }
                if (p_ < end_ && *p_ == ']') {
                    ++p_;
                    break;
                }
                fail("expected ',' or ']'");
            }
        } else if (c == '"') {
            v.kind = JVal::STR;
            v.raw = string_token();
        } else if (lit("true")) {
            v.kind = JVal::BOOL;
            v.b = true;
        } else if (lit("false")) {
            v.kind = JVal::BOOL;
        } else if (lit("null")) {
            v.kind = JVal::NUL;
        } else if (lit("NaN")) {
            v.kind = JVal::NUM;
            v.num = NAN;
            v.raw = "NaN";
        } else if (lit("Infinity")) {
            v.kind = JVal::NUM;
            v.num = INFINITY;
            v.raw = "Infinity";
        } else if (lit("-Infinity")) {
            v.kind = JVal::NUM;
            v.num = -INFINITY;
            v.raw = "-Infinity";
        } else {
            const char *s = p_;
            while (p_ < end_ && ((*p_ >= '0' && *p_ <= '9') || *p_ == '-' || *p_ == '+' ||
                                 *p_ == '.' || *p_ == 'e' || *p_ == 'E'))
                ++p_;
            if (p_ == s)
                fail("unexpected character");
            if (p_ - s > 1000)
                fail("number too long");
            v.kind = JVal::NUM;
            v.raw.assign(s, p_);
            char *e = nullptr;
            // glibc strtod rounds correctly (round-half-even), like Python's float();
            // ERANGE (overflow to inf, subnormal results) is not an error for us
            v.num = std::strtod(v.raw.c_str(), &e);
            if (*e != '\0')
                fail("bad number '" + v.raw.substr(0, 40) + "'");
        }
        return v;
    }
};

inline JVal parse_json(const std::string &s) { return JsonParser(s.data(), s.size()).document(); }

// A JSON string literal, quotes included; long messages are cut with "...".
inline std::string json_quote(const std::string &s, size_t maxlen = 1500)
{
    std::string out = "\"";
    for (unsigned char c : s) {
        if (out.size() > maxlen) {
            out += "...";
            break;
        }
        switch (c) {
        case '"': out += "\\\""; break;
        case '\\': out += "\\\\"; break;
        case '\n': out += "\\n"; break;
        case '\r': out += "\\r"; break;
        case '\t': out += "\\t"; break;
        default:
            if (c < 0x20 || c == 0x7f) {
                char b[8];
                std::snprintf(b, sizeof b, "\\u%04x", c);
                out += b;
            } else {
                out += static_cast<char>(c); // UTF-8 passes through
            }
        }
    }
    out += '"';
    return out;
}

// The shortest decimal that reads back as the same double (std::to_chars), always
// float-looking ("2.0", "-0.0", "5e-324", "1.7976931348623157e+308"). Non-finite values are
// written as Python's json module does: NaN, Infinity, -Infinity.
inline std::string fmt_double(double v)
{
    if (std::isnan(v))
        return "NaN";
    if (std::isinf(v))
        return v > 0 ? "Infinity" : "-Infinity";
    char buf[64];
    auto r = std::to_chars(buf, buf + sizeof buf - 3, v);
    std::string s(buf, r.ptr);
    if (s.find_first_of(".e") == std::string::npos)
        s += ".0";
    return s;
}

// =========================================================================== geometry

using XY = std::array<double, 2>;

enum class GType { Point, LineString, Polygon, MultiPoint, MultiLineString, MultiPolygon, Collection };

inline const char *type_name(GType t)
{
    switch (t) {
    case GType::Point: return "Point";
    case GType::LineString: return "LineString";
    case GType::Polygon: return "Polygon";
    case GType::MultiPoint: return "MultiPoint";
    case GType::MultiLineString: return "MultiLineString";
    case GType::MultiPolygon: return "MultiPolygon";
    case GType::Collection: return "GeometryCollection";
    }
    return "?";
}

// A typed geometry with double ordinates (Z and M are dropped when reading).
//   Point: coords has 0 (empty) or 1 position; LineString: coords;
//   Polygon: rings (shell first, then holes; [] when empty);
//   Multi* and GeometryCollection: parts (a MultiPoint part may be an empty Point).
struct Geom {
    GType type = GType::Collection;
    std::vector<XY> coords;
    std::vector<std::vector<XY>> rings;
    std::vector<Geom> parts;
};

struct GeomError : std::runtime_error {
    using std::runtime_error::runtime_error;
};

namespace detail {

inline XY read_position(const JVal &v)
{
    if (v.kind != JVal::ARR || v.arr.size() < 2)
        throw GeomError("a position needs at least 2 ordinates");
    for (size_t i = 0; i < v.arr.size() && i < 4; i++)
        if (v.arr[i].kind != JVal::NUM)
            throw GeomError("an ordinate is not a number");
    if (v.arr.size() > 4)
        throw GeomError("a position has more than 4 ordinates");
    return XY{v.arr[0].num, v.arr[1].num}; // Z and M are ignored
}

inline std::vector<XY> read_positions(const JVal &v)
{
    if (v.kind != JVal::ARR)
        throw GeomError("expected an array of positions");
    std::vector<XY> out;
    out.reserve(v.arr.size());
    for (auto &p : v.arr)
        out.push_back(read_position(p));
    return out;
}

inline std::vector<std::vector<XY>> read_rings(const JVal &v)
{
    if (v.kind != JVal::ARR)
        throw GeomError("expected an array of rings");
    std::vector<std::vector<XY>> out;
    for (auto &r : v.arr)
        out.push_back(read_positions(r));
    return out;
}

inline Geom read_typed(const JVal &v, int depth)
{
    if (depth > 64)
        throw GeomError("geometry collections nested too deeply");
    if (v.kind != JVal::OBJ)
        throw GeomError("a geometry must be a JSON object");
    const JVal *t = v.get("type");
    if (!t || t->kind != JVal::STR)
        throw GeomError("geometry without a \"type\"");
    const std::string type = t->str();
    Geom g;
    if (type == "GeometryCollection") {
        g.type = GType::Collection;
        const JVal *gs = v.get("geometries");
        if (!gs || gs->kind != JVal::ARR)
            throw GeomError("GeometryCollection without \"geometries\"");
        for (auto &e : gs->arr)
            g.parts.push_back(read_typed(e, depth + 1));
        return g;
    }
    const JVal *c = v.get("coordinates");
    if (!c || c->kind != JVal::ARR)
        throw GeomError(type + " without \"coordinates\"");
    if (type == "Point") {
        g.type = GType::Point;
        if (!c->arr.empty())
            g.coords.push_back(read_position(*c));
    } else if (type == "LineString") {
        g.type = GType::LineString;
        g.coords = read_positions(*c);
    } else if (type == "Polygon") {
        g.type = GType::Polygon;
        g.rings = read_rings(*c);
    } else if (type == "MultiPoint") {
        g.type = GType::MultiPoint;
        for (auto &p : c->arr) {
            Geom pt;
            pt.type = GType::Point;
            if (p.kind != JVal::ARR)
                throw GeomError("expected a position");
            if (!p.arr.empty())
                pt.coords.push_back(read_position(p));
            g.parts.push_back(std::move(pt));
        }
    } else if (type == "MultiLineString") {
        g.type = GType::MultiLineString;
        for (auto &l : c->arr) {
            Geom ls;
            ls.type = GType::LineString;
            ls.coords = read_positions(l);
            g.parts.push_back(std::move(ls));
        }
    } else if (type == "MultiPolygon") {
        g.type = GType::MultiPolygon;
        for (auto &p : c->arr) {
            Geom pg;
            pg.type = GType::Polygon;
            pg.rings = read_rings(p);
            g.parts.push_back(std::move(pg));
        }
    } else {
        throw GeomError("unknown geometry type \"" + type + "\"");
    }
    return g;
}

inline void write_pos(std::string &o, const XY &p)
{
    o += '[';
    o += fmt_double(p[0]);
    o += ", ";
    o += fmt_double(p[1]);
    o += ']';
}

inline void write_seq(std::string &o, const std::vector<XY> &s)
{
    o += '[';
    for (size_t i = 0; i < s.size(); i++) {
        if (i)
            o += ", ";
        write_pos(o, s[i]);
    }
    o += ']';
}

inline void write_rings(std::string &o, const std::vector<std::vector<XY>> &rs)
{
    o += '[';
    for (size_t i = 0; i < rs.size(); i++) {
        if (i)
            o += ", ";
        write_seq(o, rs[i]);
    }
    o += ']';
}

inline void write_geom(std::string &o, const Geom &g)
{
    o += "{\"type\": \"";
    o += type_name(g.type);
    o += "\", ";
    switch (g.type) {
    case GType::Point:
        o += "\"coordinates\": ";
        if (g.coords.empty())
            o += "[]";
        else
            write_pos(o, g.coords[0]);
        break;
    case GType::LineString:
        o += "\"coordinates\": ";
        write_seq(o, g.coords);
        break;
    case GType::Polygon:
        o += "\"coordinates\": ";
        write_rings(o, g.rings);
        break;
    case GType::MultiPoint:
    case GType::MultiLineString:
    case GType::MultiPolygon:
        o += "\"coordinates\": [";
        for (size_t i = 0; i < g.parts.size(); i++) {
            if (i)
                o += ", ";
            const Geom &p = g.parts[i];
            if (g.type == GType::MultiPoint) {
                if (p.coords.empty())
                    o += "[]";
                else
                    write_pos(o, p.coords[0]);
            } else if (g.type == GType::MultiLineString) {
                write_seq(o, p.coords);
            } else {
                write_rings(o, p.rings);
            }
        }
        o += ']';
        break;
    case GType::Collection:
        o += "\"geometries\": [";
        for (size_t i = 0; i < g.parts.size(); i++) {
            if (i)
                o += ", ";
            write_geom(o, g.parts[i]);
        }
        o += ']';
        break;
    }
    o += '}';
}

} // namespace detail

// A typed geometry, or a FORMAT-v1 multipolygon array (one part -> Polygon).
inline Geom read_geometry(const JVal &v)
{
    if (v.kind == JVal::OBJ)
        return detail::read_typed(v, 0);
    if (v.kind != JVal::ARR)
        throw GeomError("an operand must be a typed geometry object or a multipolygon array");
    Geom mp;
    mp.type = GType::MultiPolygon;
    for (auto &p : v.arr) {
        Geom pg;
        pg.type = GType::Polygon;
        pg.rings = detail::read_rings(p);
        mp.parts.push_back(std::move(pg));
    }
    if (mp.parts.size() == 1)
        return std::move(mp.parts[0]);
    return mp;
}

inline std::string write_geometry(const Geom &g)
{
    std::string o;
    detail::write_geom(o, g);
    return o;
}

inline bool is_empty(const Geom &g)
{
    switch (g.type) {
    case GType::Point:
    case GType::LineString: return g.coords.empty();
    case GType::Polygon: return g.rings.empty() || g.rings[0].empty();
    default:
        for (auto &p : g.parts)
            if (!is_empty(p))
                return false;
        return true;
    }
}

inline bool is_polygonal(const Geom &g) { return g.type == GType::Polygon || g.type == GType::MultiPolygon; }

template <class F> inline void for_each_xy(const Geom &g, F &&f)
{
    for (auto &p : g.coords)
        f(p);
    for (auto &r : g.rings)
        for (auto &p : r)
            f(p);
    for (auto &q : g.parts)
        for_each_xy(q, f);
}

// =========================================================================== fields

// The v2 result fields, in output order. OPS[i] is the field path used in "errors".
enum Op {
    OP_ECHO,
    OP_RELATE,
    OP_INTERSECTS, OP_DISJOINT, OP_TOUCHES, OP_CROSSES, OP_OVERLAPS, OP_CONTAINS, OP_COVERS,
    OP_WITHIN, OP_COVERED_BY, OP_EQUALS,
    OP_VALID_A, OP_VALID_B,
    OP_INTERSECTION, OP_UNION, OP_DIFFERENCE, OP_SYMDIFFERENCE,
    NOPS
};

inline const char *op_path(int op)
{
    static const char *const P[NOPS] = {
        "echo", "relate",
        "predicates.intersects", "predicates.disjoint", "predicates.touches", "predicates.crosses",
        "predicates.overlaps", "predicates.contains", "predicates.covers", "predicates.within",
        "predicates.covered_by", "predicates.equals",
        "valid_a", "valid_b",
        "overlay.intersection", "overlay.union", "overlay.difference", "overlay.symdifference",
    };
    return P[op];
}

// the key inside its group object (predicates.x -> x), or the top-level key
inline const char *op_key(int op)
{
    const char *p = op_path(op);
    const char *dot = std::strchr(p, '.');
    return dot ? dot + 1 : p;
}

enum Group { G_ECHO = 1, G_RELATE = 2, G_PREDICATES = 4, G_VALIDITY = 8, G_OVERLAY = 16 };
constexpr unsigned G_DEFAULT = G_RELATE | G_PREDICATES | G_VALIDITY | G_OVERLAY;

inline unsigned op_group(int op)
{
    if (op == OP_ECHO)
        return G_ECHO;
    if (op == OP_RELATE)
        return G_RELATE;
    if (op >= OP_INTERSECTS && op <= OP_EQUALS)
        return G_PREDICATES;
    if (op == OP_VALID_A || op == OP_VALID_B)
        return G_VALIDITY;
    return G_OVERLAY;
}

inline bool is_overlay(int op) { return op >= OP_INTERSECTION && op <= OP_SYMDIFFERENCE; }

// JSON literals
inline const char *jbool(bool v) { return v ? "true" : "false"; }
const char *const UNSUPPORTED = "\"unsupported\"";

// An error value: a message (kind exception) or {"kind": ..., "message": ...}.
inline std::string error_kind(const char *kind, const std::string &message)
{
    return std::string("{\"kind\": \"") + kind + "\", \"message\": " + json_quote(message) + "}";
}

// =========================================================================== cases

struct Case {
    std::string id_json = "null"; // the raw JSON token of "id"
    unsigned groups = G_DEFAULT;  // requested groups ("ops")
    Geom a, b;
};

// Only the "id" of a line (for lines that fail to parse), or "null".
inline std::string id_of_line(const std::string &line)
{
    try {
        JVal v = parse_json(line);
        if (const JVal *id = v.get("id"))
            if (id->kind == JVal::STR)
                return id->raw;
    } catch (const std::exception &) {
    }
    return "null";
}

// Is this line a v2 case: an operand is an object, or "ops" is present? Cheap and
// forgiving (a line that is not JSON is left to the v1 code, which reports it).
inline bool looks_v2(const std::string &line)
{
    try {
        JVal v = parse_json(line);
        if (v.kind != JVal::OBJ)
            return false;
        const JVal *a = v.get("a"), *b = v.get("b");
        return v.get("ops") || (a && a->kind == JVal::OBJ) || (b && b->kind == JVal::OBJ);
    } catch (const std::exception &) {
        return false;
    }
}

// Parse a v2 case (typed or legacy operands). Throws JsonError / GeomError.
inline Case read_case(const std::string &line)
{
    JVal v = parse_json(line);
    if (v.kind != JVal::OBJ)
        throw JsonError("a case must be a JSON object");
    Case c;
    if (const JVal *id = v.get("id"))
        if (id->kind == JVal::STR)
            c.id_json = id->raw;
    if (const JVal *ops = v.get("ops")) {
        if (ops->kind != JVal::ARR)
            throw JsonError("\"ops\" must be an array");
        c.groups = 0;
        for (auto &o : ops->arr) {
            std::string s = o.kind == JVal::STR ? o.str() : "";
            if (s == "echo") c.groups |= G_ECHO;
            else if (s == "relate") c.groups |= G_RELATE;
            else if (s == "predicates") c.groups |= G_PREDICATES;
            else if (s == "validity") c.groups |= G_VALIDITY;
            else if (s == "overlay") c.groups |= G_OVERLAY;
            else throw JsonError("unknown op " + (o.kind == JVal::STR ? o.raw : std::string("?")));
        }
    }
    const JVal *a = v.get("a"), *b = v.get("b");
    if (!a || !b)
        throw JsonError("missing \"a\" or \"b\"");
    try {
        c.a = read_geometry(*a);
    } catch (const GeomError &e) {
        throw GeomError(std::string("a: ") + e.what());
    }
    try {
        c.b = read_geometry(*b);
    } catch (const GeomError &e) {
        throw GeomError(std::string("b: ") + e.what());
    }
    return c;
}

// =========================================================================== running

// What one operation produced: a JSON value and, on failure, an error value.
struct OpOut {
    std::string value = "null";
    std::string error; // empty, a JSON string, or an error_kind() object
};

// The library side of one case, living in the (forked) child: it builds the library's
// geometries once in its constructor (which must not throw; build failures are reported by
// run() for every operation that needs the geometry) and computes one operation per run().
struct Session {
    virtual ~Session() = default;
    virtual OpOut run(int op) = 0;
};
using SessionFactory = std::function<std::unique_ptr<Session>(const Case &)>;

struct RunConfig {
    double timeout_s = 10.0; // per operation
    long mem_mb = 4096;      // child address-space limit, 0 = none
    bool fork = true;
    bool timing = false;     // add elapsed_ms
    std::string test_fault;  // "crash:<path>" / "hang_:<path>" / "throw:<path>" (self-test only)
};

struct FieldResult {
    bool done = false;
    std::string value = "null";
    std::string error;
    double ms = -1;
};

inline double now_s()
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return double(ts.tv_sec) + 1e-9 * double(ts.tv_nsec);
}

namespace detail {

inline void write_all(int fd, const std::string &s)
{
    const char *p = s.data();
    size_t n = s.size();
    while (n > 0) {
        ssize_t w = write(fd, p, n);
        if (w < 0) {
            if (errno == EINTR)
                continue;
            _exit(3);
        }
        p += w;
        n -= size_t(w);
    }
}

// One operation with the fault hook and the exception net around Session::run.
inline OpOut run_one(Session &s, int op, const RunConfig &cfg)
{
    if (!cfg.test_fault.empty() && cfg.test_fault.size() > 6 &&
        cfg.test_fault.compare(6, std::string::npos, op_path(op)) == 0) {
        std::string kind = cfg.test_fault.substr(0, 6);
        if (kind == "crash:")
            std::raise(SIGSEGV);
        if (kind == "hang_:")
            for (;;)
                pause();
        if (kind == "throw:") {
            OpOut o;
            o.error = json_quote("injected test fault");
            return o;
        }
    }
    try {
        return s.run(op);
    } catch (const std::bad_alloc &e) {
        OpOut o;
        o.error = error_kind("memory", e.what());
        return o;
    } catch (const std::exception &e) {
        OpOut o;
        o.error = json_quote(e.what());
        return o;
    } catch (...) {
        OpOut o;
        o.error = json_quote("unknown exception");
        return o;
    }
}

} // namespace detail

// Run the requested operations of one case, in order, filling res[op] for each of them.
inline void run_case(const Case &c, const SessionFactory &make, const RunConfig &cfg,
                     std::vector<FieldResult> &res)
{
    res.assign(NOPS, FieldResult());
    std::vector<int> ops;
    for (int op = 0; op < NOPS; op++)
        if (c.groups & op_group(op))
            ops.push_back(op);
    if (!cfg.fork) {
        std::unique_ptr<Session> s = make(c);
        for (int op : ops) {
            double t0 = now_s();
            OpOut o = detail::run_one(*s, op, cfg);
            res[op].done = true;
            res[op].value = std::move(o.value);
            res[op].error = std::move(o.error);
            res[op].ms = 1000.0 * (now_s() - t0);
        }
        return;
    }
    size_t next = 0; // index into ops of the first operation without a result
    while (next < ops.size()) {
        int fds[2];
        if (pipe(fds) != 0) {
            std::perror("pipe");
            std::exit(2);
        }
        std::fflush(stdout);
        std::fflush(stderr);
        pid_t pid = fork();
        if (pid < 0) {
            std::perror("fork");
            std::exit(2);
        }
        if (pid == 0) { // child: stream "<index>\t<ms>\t<value>\t<error>\n" per operation
            close(fds[0]);
            if (cfg.mem_mb > 0) {
                struct rlimit rl;
                rl.rlim_cur = rl.rlim_max = rlim_t(cfg.mem_mb) << 20;
                setrlimit(RLIMIT_AS, &rl);
            }
            std::unique_ptr<Session> s;
            try {
                s = make(c);
            } catch (const std::exception &e) {
                OpOut o;
                o.error = json_quote(std::string("building the geometries: ") + e.what());
                detail::write_all(fds[1], std::to_string(next) + "\t0\tnull\t" + o.error + "\n");
                _exit(0);
            }
            for (size_t i = next; i < ops.size(); i++) {
                double t0 = now_s();
                OpOut o = detail::run_one(*s, ops[i], cfg);
                char ms[32];
                std::snprintf(ms, sizeof ms, "%.3f", 1000.0 * (now_s() - t0));
                detail::write_all(fds[1], std::to_string(i) + "\t" + ms + "\t" + o.value + "\t" + o.error + "\n");
            }
            _exit(0);
        }
        close(fds[1]);
        std::string buf;
        std::vector<char> chunk(1 << 16);
        double deadline = now_s() + cfg.timeout_s;
        bool timed_out = false;
        while (next < ops.size()) {
            double left = deadline - now_s();
            if (left <= 0) {
                timed_out = true;
                break;
            }
            struct pollfd pfd = {fds[0], POLLIN, 0};
            int pr = poll(&pfd, 1, left > 1e6 ? 1000000000 : int(left * 1000) + 1);
            if (pr < 0) {
                if (errno == EINTR)
                    continue;
                std::perror("poll");
                std::exit(2);
            }
            if (pr == 0)
                continue; // the loop re-checks the deadline
            ssize_t n = read(fds[0], chunk.data(), chunk.size());
            if (n < 0) {
                if (errno == EINTR)
                    continue;
                std::perror("read");
                std::exit(2);
            }
            if (n == 0)
                break; // EOF: the child finished or died
            buf.append(chunk.data(), size_t(n));
            size_t nl;
            while ((nl = buf.find('\n')) != std::string::npos) {
                size_t t1 = buf.find('\t'), t2 = buf.find('\t', t1 + 1), t3 = buf.find('\t', t2 + 1);
                if (t1 < nl && t2 < nl && t3 < nl) {
                    size_t i = std::strtoul(buf.c_str(), nullptr, 10);
                    if (i < ops.size()) {
                        FieldResult &r = res[ops[i]];
                        r.done = true;
                        r.ms = std::atof(buf.c_str() + t1 + 1);
                        r.value = buf.substr(t2 + 1, t3 - t2 - 1);
                        r.error = buf.substr(t3 + 1, nl - t3 - 1);
                        next = i + 1;
                        deadline = now_s() + cfg.timeout_s; // per-operation budget
                    }
                }
                buf.erase(0, nl + 1);
            }
        }
        if (timed_out)
            kill(pid, SIGKILL);
        close(fds[0]);
        int status = 0;
        while (waitpid(pid, &status, 0) < 0 && errno == EINTR)
            ;
        if (next >= ops.size())
            break;
        // the child stopped before finishing ops[next]: blame that operation, go on
        FieldResult &r = res[ops[next]];
        r.done = true;
        r.value = "null";
        char msg[160];
        if (timed_out) {
            std::snprintf(msg, sizeof msg, "no result after %g s (killed)", cfg.timeout_s);
            r.error = error_kind("timeout", msg);
            r.ms = 1000.0 * cfg.timeout_s;
        } else if (WIFSIGNALED(status)) {
            std::snprintf(msg, sizeof msg, "process killed by signal %d (%s)", WTERMSIG(status),
                          strsignal(WTERMSIG(status)));
            r.error = error_kind("crash", msg);
        } else {
            std::snprintf(msg, sizeof msg, "process exited with status %d",
                          WIFEXITED(status) ? WEXITSTATUS(status) : -1);
            r.error = error_kind("crash", msg);
        }
        next++;
    }
}

// The result line (without the newline).
inline std::string render(const std::string &lib, const Case &c, const std::vector<FieldResult> &res,
                          const RunConfig &cfg)
{
    std::string o = "{\"id\": " + c.id_json + ", \"lib\": " + json_quote(lib);
    auto val = [&](int op) -> const std::string & {
        static const std::string null = "null";
        return res[op].done ? res[op].value : null;
    };
    if (c.groups & G_RELATE)
        o += ", \"relate\": " + val(OP_RELATE);
    if (c.groups & G_PREDICATES) {
        o += ", \"predicates\": {";
        for (int op = OP_INTERSECTS; op <= OP_EQUALS; op++)
            o += std::string(op == OP_INTERSECTS ? "\"" : ", \"") + op_key(op) + "\": " + val(op);
        o += "}";
    }
    if (c.groups & G_VALIDITY)
        o += ", \"valid_a\": " + val(OP_VALID_A) + ", \"valid_b\": " + val(OP_VALID_B);
    if (c.groups & G_OVERLAY) {
        o += ", \"overlay\": {";
        for (int op = OP_INTERSECTION; op <= OP_SYMDIFFERENCE; op++)
            o += std::string(op == OP_INTERSECTION ? "\"" : ", \"") + op_key(op) + "\": " + val(op);
        o += "}";
    }
    // echo is an object or absent (a failed echo has only its errors entry)
    if ((c.groups & G_ECHO) && val(OP_ECHO) != "null")
        o += ", \"echo\": " + val(OP_ECHO);
    o += ", \"errors\": {";
    bool first = true;
    for (int op = 0; op < NOPS; op++)
        if (res[op].done && !res[op].error.empty()) {
            o += std::string(first ? "\"" : ", \"") + op_path(op) + "\": " + res[op].error;
            first = false;
        }
    o += "}";
    if (cfg.timing) {
        o += ", \"elapsed_ms\": {";
        first = true;
        for (int op = 0; op < NOPS; op++)
            if (res[op].done && res[op].ms >= 0) {
                char b[32];
                std::snprintf(b, sizeof b, "%.3f", res[op].ms);
                o += std::string(first ? "\"" : ", \"") + op_path(op) + "\": " + b;
                first = false;
            }
        o += "}";
    }
    return o + "}";
}

// A line whose case could not be read at all: {"id", "lib", "errors": {"*": message}}.
inline std::string render_failed(const std::string &lib, const std::string &id_json, const std::string &msg)
{
    return "{\"id\": " + id_json + ", \"lib\": " + json_quote(lib) + ", \"errors\": {\"*\": " +
           json_quote(msg) + "}}";
}

// Answer one v2 line: parse, run, render (no newline).
inline std::string answer_v2(const std::string &lib, const std::string &line, const SessionFactory &make,
                             const RunConfig &cfg)
{
    Case c;
    try {
        c = read_case(line);
    } catch (const std::exception &e) {
        return render_failed(lib, id_of_line(line), std::string("input parse error: ") + e.what());
    }
    std::vector<FieldResult> res;
    run_case(c, make, cfg, res);
    return render(lib, c, res, cfg);
}

// Write one output line and flush; stop when the reader went away.
inline void emit_line(const std::string &s, const char *prog)
{
    std::string out = s + "\n";
    if (std::fwrite(out.data(), 1, out.size(), stdout) != out.size() || std::fflush(stdout) != 0) {
        std::fprintf(stderr, "%s: cannot write output: %s\n", prog, std::strerror(errno));
        std::exit(1);
    }
}

// =========================================================================== helpers

// The parsed operands written back unchanged: the parse-echo canary of adapters that echo
// their own reading (libraries without a representation for the type).
inline std::string echo_of(const Geom &a, const Geom &b)
{
    return "{\"a\": " + write_geometry(a) + ", \"b\": " + write_geometry(b) + "}";
}

// A closed ring: first position == last position (bitwise equal doubles, -0.0 == 0.0).
inline bool ring_closed(const std::vector<XY> &r)
{
    return !r.empty() && r.front()[0] == r.back()[0] && r.front()[1] == r.back()[1];
}

} // namespace gt
