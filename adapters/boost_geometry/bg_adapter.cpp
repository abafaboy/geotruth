// Boost.Geometry adapter for the geometry bug hunt.  Implements ../../FORMAT.md:
//
//     bg_adapter CASES.jsonl > RESULTS.jsonl
//
// One output line per non-blank input line, in order.  The same source is compiled twice
// by build.sh: against the system Boost 1.83 headers, and with the Boost.Geometry
// `develop` headers first on the include path (all other Boost libraries from the system).
//
// Geometry types: bg::model::polygon<point_xy<double>, ClockWise=false, Closed=true> and
// bg::model::multi_polygon of it.  The case rings are closed; GeoJSON (RFC 7946) shells are
// counter-clockwise, which is why the counter-clockwise type was chosen.  Rings in the case
// files may still have either orientation, so each ring's orientation is decided *exactly*
// (lowest-leftmost vertex turn, with rational arithmetic) and a ring whose orientation
// disagrees with the type (shell must be CCW, hole CW) is reversed while building the Boost
// geometry.  That is what bg::correct() does to a closed ring, except that bg::correct()
// decides with the floating-point area.  BG_ADAPTER_ORIENT=correct uses bg::correct()
// instead; BG_ADAPTER_ORIENT=none feeds the rings as they are (for triage only).
//
// Robustness: by default every case runs in a forked child which reports each operation's
// result to the parent over a pipe as soon as it is computed.  A crash (signal) or hang
// (per-operation timeout, SIGKILL) is recorded for that one operation in "errors" and the
// case continues with the next operation in a fresh child.  Exceptions are caught per
// operation.  `--no-fork` runs everything in-process (debugging).
//
// Environment:
//   BG_ADAPTER_TIMEOUT     per-operation wall-clock limit in seconds (default 10)
//   BG_ADAPTER_MEM_MB      address-space limit of each child in MiB (default 4096, 0 = none)
//   BG_ADAPTER_ORIENT      exact (default) | correct | none, see above
//   BG_ADAPTER_TEST_FAULT  "crash:<key>" / "hang_:<key>" / "throw:<key>": inject a fault
//                          in front of one operation (self-test of the isolation only)
//
// Flags: --no-fork, --reasons (adds "valid_reasons" with bg::is_valid's message and
// "reversed_rings" with how many rings were reoriented), --version.

#include <boost/geometry.hpp>
#include <boost/geometry/geometries/multi_polygon.hpp>
#include <boost/geometry/geometries/point_xy.hpp>
#include <boost/geometry/geometries/polygon.hpp>
#include <boost/multiprecision/cpp_int.hpp>
#include <boost/version.hpp>

#include <algorithm>
#include <array>
#include <cerrno>
#include <charconv>
#include <cmath>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cxxabi.h>
#include <fstream>
#include <iostream>
#include <memory>
#include <poll.h>
#include <stdexcept>
#include <string>
#include <sys/resource.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <typeinfo>
#include <unistd.h>
#include <variant>
#include <vector>

namespace bg = boost::geometry;

// ------------------------------------------------------------------ library id

#define BG_STR2(x) #x
#define BG_STR(x) BG_STR2(x)
#ifndef BG_ADAPTER_LIB
// system build: boost-geometry@<major>.<minor>, e.g. boost-geometry@1.83
#define BG_ADAPTER_LIB_DEFAULT 1
#endif

static std::string lib_string()
{
#ifdef BG_ADAPTER_LIB_DEFAULT
    return "boost-geometry@" + std::to_string(BOOST_VERSION / 100000) + "." +
           std::to_string(BOOST_VERSION / 100 % 1000);
#else
    return BG_ADAPTER_LIB; // e.g. "boost-geometry@develop-196d04c", from build.sh
#endif
}

// ------------------------------------------------------------------ geometry types

using Pt = bg::model::d2::point_xy<double>;
using Poly = bg::model::polygon<Pt, /*ClockWise=*/false, /*Closed=*/true>;
using MPoly = bg::model::multi_polygon<Poly>;
using Geom = std::variant<Poly, MPoly>; // Poly when the case has exactly one part

using XY = std::array<double, 2>;
using RingIn = std::vector<XY>;
using PolyIn = std::vector<RingIn>;
using MPolyIn = std::vector<PolyIn>;

// ------------------------------------------------------------------ operations

enum {
    OP_VALID_A, OP_VALID_B,
    OP_INTERSECTS, OP_DISJOINT, OP_TOUCHES, OP_OVERLAPS, OP_CONTAINS, OP_COVERS,
    OP_WITHIN, OP_COVERED_BY, OP_EQUALS,
    OP_AREA_INTER, OP_AREA_UNION, OP_AREA_DIFF, OP_AREA_SYMDIFF,
    NOPS
};

static const char *const OP_KEYS[NOPS] = {
    "valid_a", "valid_b",
    "intersects", "disjoint", "touches", "overlaps", "contains", "covers",
    "within", "covered_by", "equals",
    "area_inter", "area_union", "area_diff", "area_symdiff",
};

struct OpResult {
    bool done = false;
    std::string val = "null"; // JSON literal: true / false / null / a number
    std::string err;          // JSON string literal incl. quotes, or empty
    std::string note;         // JSON string literal (is_valid reason), or empty
};

// ------------------------------------------------------------------ small utils

static std::string json_quote(const std::string &s, size_t maxlen = 1500)
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

// Shortest decimal that round-trips (std::to_chars), always float-looking.
static std::string fmt_double(double v)
{
    char buf[64];
    auto r = std::to_chars(buf, buf + sizeof buf - 3, v);
    *r.ptr = '\0';
    std::string s(buf);
    if (s.find_first_of(".eEn") == std::string::npos)
        s += ".0";
    return s;
}

static std::string demangle(const char *name)
{
    int status = 0;
    std::unique_ptr<char, void (*)(void *)> d(abi::__cxa_demangle(name, nullptr, nullptr, &status),
                                              std::free);
    return status == 0 && d ? std::string(d.get()) : std::string(name);
}

static double now_s()
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return double(ts.tv_sec) + 1e-9 * double(ts.tv_nsec);
}

// ------------------------------------------------------------------ JSON input

struct ParseError : std::runtime_error {
    using std::runtime_error::runtime_error;
};

struct Parser {
    const char *start, *p, *end;

    [[noreturn]] void fail(const std::string &what) const
    {
        throw ParseError(what + " at byte " + std::to_string(p - start));
    }
    void ws()
    {
        while (p < end && (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r'))
            p++;
    }
    int peek()
    {
        ws();
        return p < end ? static_cast<unsigned char>(*p) : -1;
    }
    void expect(char c)
    {
        if (peek() != static_cast<unsigned char>(c))
            fail(std::string("expected '") + c + "'");
        p++;
    }
    // string token, returned verbatim including quotes (escapes kept)
    std::string string_token()
    {
        if (peek() != '"')
            fail("expected string");
        const char *s = p++;
        while (p < end && *p != '"') {
            if (*p == '\\')
                p++;
            p++;
        }
        if (p >= end)
            fail("unterminated string");
        p++;
        return std::string(s, p);
    }
    static bool num_char(char c)
    {
        return (c >= '0' && c <= '9') || c == '-' || c == '+' || c == '.' ||
               (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z'); // e, E, NaN, Infinity
    }
    // glibc strtod rounds correctly: JSON numbers map to the exact intended doubles
    double number()
    {
        ws();
        const char *s = p;
        while (p < end && num_char(*p))
            p++;
        if (p == s || p - s > 400)
            fail("expected number");
        std::string tok(s, p);
        char *e = nullptr;
        double v = std::strtod(tok.c_str(), &e);
        if (*e != '\0')
            fail("bad number '" + tok.substr(0, 40) + "'");
        return v;
    }
    // skip any JSON value, returning its raw text
    std::string raw_value(int depth = 0)
    {
        if (depth > 64)
            fail("nesting too deep");
        int c = peek();
        const char *s = p;
        if (c == '"') {
            return string_token();
        } else if (c == '[' || c == '{') {
            char close = c == '[' ? ']' : '}';
            p++;
            if (peek() == close) {
                p++;
            } else {
                for (;;) {
                    if (c == '{') {
                        string_token();
                        expect(':');
                    }
                    raw_value(depth + 1);
                    int d = peek();
                    if (d == ',') {
                        p++;
                        continue;
                    }
                    if (d == close) {
                        p++;
                        break;
                    }
                    fail(std::string("expected ',' or '") + close + "'");
                }
            }
        } else {
            for (const char *lit : {"true", "false", "null"}) {
                size_t n = std::strlen(lit);
                if (size_t(end - p) >= n && !std::memcmp(p, lit, n) &&
                    (size_t(end - p) == n || !num_char(p[n]))) {
                    p += n;
                    return std::string(s, p);
                }
            }
            number();
        }
        return std::string(s, p);
    }
    template <class F> void array(F &&item)
    {
        expect('[');
        if (peek() == ']') {
            p++;
            return;
        }
        for (;;) {
            item();
            int d = peek();
            if (d == ',') {
                p++;
                continue;
            }
            if (d == ']') {
                p++;
                return;
            }
            fail("expected ',' or ']'");
        }
    }
    MPolyIn mpoly()
    {
        MPolyIn mp;
        array([&] {
            PolyIn pg;
            array([&] {
                RingIn r;
                array([&] {
                    XY xy{0, 0};
                    int k = 0;
                    array([&] {
                        double v = number();
                        if (k < 2)
                            xy[k] = v; // a third ordinate is ignored
                        k++;
                    });
                    if (k < 2)
                        fail("point with " + std::to_string(k) + " ordinates");
                    r.push_back(xy);
                });
                pg.push_back(std::move(r));
            });
            mp.push_back(std::move(pg));
        });
        return mp;
    }
};

struct Case {
    std::string id_json = "null";
    MPolyIn a, b;
};

static Case parse_case(const std::string &line)
{
    Parser P{line.data(), line.data(), line.data() + line.size()};
    Case c;
    bool have_a = false, have_b = false;
    P.expect('{');
    if (P.peek() == '}') {
        P.p++;
    } else {
        for (;;) {
            std::string k = P.string_token();
            P.expect(':');
            if (k == "\"id\"") {
                c.id_json = P.raw_value();
            } else if (k == "\"a\"") {
                c.a = P.mpoly();
                have_a = true;
            } else if (k == "\"b\"") {
                c.b = P.mpoly();
                have_b = true;
            } else {
                P.raw_value();
            }
            int d = P.peek();
            if (d == ',') {
                P.p++;
                continue;
            }
            if (d == '}') {
                P.p++;
                break;
            }
            P.fail("expected ',' or '}'");
        }
    }
    if (P.peek() != -1)
        P.fail("trailing characters");
    if (!have_a || !have_b)
        P.fail("missing \"a\" or \"b\"");
    return c;
}

// ------------------------------------------------------------------ orientation

using boost::multiprecision::cpp_rational; // exact: every finite double is a rational

static int sgn_exact_orient(const XY &a, const XY &b, const XY &c)
{
    cpp_rational ax(a[0]), ay(a[1]), bx(b[0]), by(b[1]), cx(c[0]), cy(c[1]);
    cpp_rational d = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax);
    return d.sign();
}

// +1 counter-clockwise, -1 clockwise, 0 undecidable (degenerate or non-finite ring).
// For a simple ring the turn at the lowest-then-leftmost vertex (a strict convex-hull
// vertex) has the ring's orientation; it is 0 only for non-simple rings, where the exact
// signed area is used instead.
static int ring_orientation(const RingIn &in)
{
    std::vector<XY> pts;
    for (const XY &q : in) {
        if (!std::isfinite(q[0]) || !std::isfinite(q[1]))
            return 0;
        if (pts.empty() || q != pts.back())
            pts.push_back(q);
    }
    while (pts.size() > 1 && pts.front() == pts.back())
        pts.pop_back();
    const size_t n = pts.size();
    if (n < 3)
        return 0;
    size_t i = 0;
    for (size_t k = 1; k < n; k++)
        if (pts[k][1] < pts[i][1] || (pts[k][1] == pts[i][1] && pts[k][0] < pts[i][0]))
            i = k;
    int s = sgn_exact_orient(pts[(i + n - 1) % n], pts[i], pts[(i + 1) % n]);
    if (s != 0)
        return s;
    cpp_rational twice_area = 0;
    for (size_t k = 0; k < n; k++) {
        const XY &p = pts[k], &q = pts[(k + 1) % n];
        twice_area += cpp_rational(p[0]) * cpp_rational(q[1]) - cpp_rational(q[0]) * cpp_rational(p[1]);
    }
    return twice_area.sign();
}

enum class OrientMode { exact, correct, none };
static OrientMode ORIENT = OrientMode::exact;

template <class Ring> static void fill_ring(Ring &out, const RingIn &in, bool reverse)
{
    out.clear();
    if (reverse)
        for (auto it = in.rbegin(); it != in.rend(); ++it)
            out.push_back(Pt((*it)[0], (*it)[1]));
    else
        for (const XY &q : in)
            out.push_back(Pt(q[0], q[1]));
}

static Poly build_poly(const PolyIn &in, int &reversed)
{
    Poly pg;
    for (size_t k = 0; k < in.size(); k++) {
        bool rev = false;
        if (ORIENT == OrientMode::exact) {
            int want = k == 0 ? +1 : -1; // CCW shell, CW holes
            int have = ring_orientation(in[k]);
            rev = have != 0 && have != want;
            reversed += rev;
        }
        if (k == 0) {
            fill_ring(pg.outer(), in[k], rev);
        } else {
            pg.inners().emplace_back();
            fill_ring(pg.inners().back(), in[k], rev);
        }
    }
    return pg;
}

// A Polygon when the case has exactly one part, else a MultiPolygon (FORMAT.md).
static Geom build_geom(const MPolyIn &in, int &reversed)
{
    reversed = 0;
    if (in.size() == 1) {
        Poly pg = build_poly(in[0], reversed);
        if (ORIENT == OrientMode::correct)
            bg::correct(pg);
        return pg;
    }
    MPoly mp;
    for (const PolyIn &p : in)
        mp.push_back(build_poly(p, reversed));
    if (ORIENT == OrientMode::correct)
        bg::correct(mp);
    return mp;
}

// ------------------------------------------------------------------ Boost.Geometry work

template <class F> static auto visit2(const Geom &a, const Geom &b, F &&f)
{
    return std::visit([&](const auto &ga) { return std::visit([&](const auto &gb) { return f(ga, gb); }, b); },
                      a);
}

template <class F> static double overlay_area(const Geom &a, const Geom &b, F &&op)
{
    return visit2(a, b, [&](const auto &ga, const auto &gb) {
        MPoly out;
        op(ga, gb, out);
        return static_cast<double>(bg::area(out));
    });
}

static char TEST_FAULT[64];

static OpResult compute(int op, const Geom &A, const Geom &B, bool reasons)
{
    OpResult r;
    r.done = true;
    if (TEST_FAULT[0] && !std::strcmp(TEST_FAULT + 6, OP_KEYS[op])) { // self-test hook
        if (!std::strncmp(TEST_FAULT, "crash:", 6))
            std::raise(SIGSEGV);
        if (!std::strncmp(TEST_FAULT, "hang_:", 6))
            for (;;)
                pause();
    }
    try {
        if (TEST_FAULT[0] && !std::strncmp(TEST_FAULT, "throw:", 6) && !std::strcmp(TEST_FAULT + 6, OP_KEYS[op]))
            throw bg::invalid_input_exception();
        auto B2 = [&](bool v) { r.val = v ? "true" : "false"; };
        auto pred = [&](auto &&fn) { B2(visit2(A, B, fn)); };
        switch (op) {
        case OP_VALID_A:
        case OP_VALID_B: {
            std::string msg;
            bool v = std::visit([&](const auto &g) { return bg::is_valid(g, msg); }, op == OP_VALID_A ? A : B);
            B2(v);
            if (reasons)
                r.note = json_quote(msg, 400);
            break;
        }
        case OP_INTERSECTS: pred([](const auto &a, const auto &b) { return bg::intersects(a, b); }); break;
        case OP_DISJOINT: pred([](const auto &a, const auto &b) { return bg::disjoint(a, b); }); break;
        case OP_TOUCHES: pred([](const auto &a, const auto &b) { return bg::touches(a, b); }); break;
        case OP_OVERLAPS: pred([](const auto &a, const auto &b) { return bg::overlaps(a, b); }); break;
        // Boost.Geometry has no contains/covers: A contains B == B within A, etc.
        case OP_CONTAINS: pred([](const auto &a, const auto &b) { return bg::within(b, a); }); break;
        case OP_COVERS: pred([](const auto &a, const auto &b) { return bg::covered_by(b, a); }); break;
        case OP_WITHIN: pred([](const auto &a, const auto &b) { return bg::within(a, b); }); break;
        case OP_COVERED_BY: pred([](const auto &a, const auto &b) { return bg::covered_by(a, b); }); break;
        case OP_EQUALS: pred([](const auto &a, const auto &b) { return bg::equals(a, b); }); break;
        default: {
            double area = 0;
            switch (op) {
            case OP_AREA_INTER:
                area = overlay_area(A, B, [](const auto &a, const auto &b, MPoly &o) { bg::intersection(a, b, o); });
                break;
            case OP_AREA_UNION:
                area = overlay_area(A, B, [](const auto &a, const auto &b, MPoly &o) { bg::union_(a, b, o); });
                break;
            case OP_AREA_DIFF:
                area = overlay_area(A, B, [](const auto &a, const auto &b, MPoly &o) { bg::difference(a, b, o); });
                break;
            case OP_AREA_SYMDIFF:
                area = overlay_area(A, B, [](const auto &a, const auto &b, MPoly &o) { bg::sym_difference(a, b, o); });
                break;
            }
            if (!std::isfinite(area))
                throw std::range_error("non-finite area " + std::to_string(area));
            r.val = fmt_double(area);
        }
        }
    } catch (const std::exception &e) {
        r.val = "null";
        r.err = json_quote(demangle(typeid(e).name()) + ": " + e.what());
    } catch (...) {
        r.val = "null";
        r.err = json_quote("unknown exception");
    }
    return r;
}

struct CaseState {
    int reversed_a = 0, reversed_b = 0;
};

// Run operations start..NOPS-1, handing each result to emit as soon as it is known.
template <class Emit> static void run_ops(const Case &c, int start, bool reasons, Emit &&emit, CaseState *st)
{
    int ra = 0, rb = 0;
    Geom A = build_geom(c.a, ra);
    Geom B = build_geom(c.b, rb);
    if (st) {
        st->reversed_a = ra;
        st->reversed_b = rb;
    }
    for (int op = start; op < NOPS; op++)
        emit(op, compute(op, A, B, reasons));
}

// ------------------------------------------------------------------ fork isolation

static double TIMEOUT_S = 10.0;
static long MEM_MB = 4096;

static void write_all(int fd, const std::string &s)
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

// Protocol line from child: "<op>\t<value>\t<json error or empty>\t<json note or empty>\n"
// The first line is "-1\t<reversed_a>\t<reversed_b>\t\n".
static int take_record(const std::string &line, OpResult *res, CaseState &st)
{
    size_t t1 = line.find('\t'), t2 = t1 == std::string::npos ? t1 : line.find('\t', t1 + 1),
           t3 = t2 == std::string::npos ? t2 : line.find('\t', t2 + 1);
    if (t3 == std::string::npos)
        return -2;
    int op = std::atoi(line.substr(0, t1).c_str());
    std::string f1 = line.substr(t1 + 1, t2 - t1 - 1), f2 = line.substr(t2 + 1, t3 - t2 - 1),
                f3 = line.substr(t3 + 1);
    if (op == -1) {
        st.reversed_a = std::atoi(f1.c_str());
        st.reversed_b = std::atoi(f2.c_str());
        return -1;
    }
    if (op < 0 || op >= NOPS)
        return -2;
    res[op].done = true;
    res[op].val = f1;
    res[op].err = f2;
    res[op].note = f3;
    return op;
}

static void run_case_forked(const Case &c, OpResult *res, std::string &timeouts, bool reasons, CaseState &st)
{
    int next = 0;
    while (next < NOPS) {
        int fds[2];
        if (pipe(fds) != 0) {
            std::perror("pipe");
            std::exit(2);
        }
        std::fflush(stdout);
        std::cout.flush();
        pid_t pid = fork();
        if (pid < 0) {
            std::perror("fork");
            std::exit(2);
        }
        if (pid == 0) {
            close(fds[0]);
            if (MEM_MB > 0) {
                struct rlimit rl;
                rl.rlim_cur = rl.rlim_max = rlim_t(MEM_MB) << 20;
                setrlimit(RLIMIT_AS, &rl);
            }
            int fd = fds[1];
            try {
                CaseState cs;
                bool first = true;
                run_ops(c, next, reasons,
                        [&](int op, const OpResult &r) {
                            if (first) {
                                write_all(fd, "-1\t" + std::to_string(cs.reversed_a) + "\t" +
                                                  std::to_string(cs.reversed_b) + "\t\n");
                                first = false;
                            }
                            write_all(fd, std::to_string(op) + "\t" + r.val + "\t" + r.err + "\t" + r.note + "\n");
                        },
                        &cs);
            } catch (const std::exception &e) {
                // building the geometries threw (e.g. bad_alloc): report it on the next op
                OpResult r;
                r.done = true;
                r.err = json_quote(std::string("building geometries: ") + demangle(typeid(e).name()) + ": " +
                                   e.what());
                write_all(fd, std::to_string(next) + "\t" + r.val + "\t" + r.err + "\t\n");
            }
            _exit(0);
        }
        close(fds[1]);

        std::string buf;
        char chunk[8192];
        double deadline = now_s() + TIMEOUT_S;
        bool timed_out = false;
        while (next < NOPS) {
            double left = deadline - now_s();
            if (left <= 0) {
                timed_out = true;
                break;
            }
            struct pollfd pfd = {fds[0], POLLIN, 0};
            int pr = poll(&pfd, 1, int(left * 1000) + 1);
            if (pr < 0) {
                if (errno == EINTR)
                    continue;
                std::perror("poll");
                std::exit(2);
            }
            if (pr == 0)
                continue;
            ssize_t n = read(fds[0], chunk, sizeof chunk);
            if (n < 0) {
                if (errno == EINTR)
                    continue;
                std::perror("read");
                std::exit(2);
            }
            if (n == 0)
                break; // EOF
            buf.append(chunk, size_t(n));
            size_t nl;
            while ((nl = buf.find('\n')) != std::string::npos) {
                int op = take_record(buf.substr(0, nl), res, st);
                if (op >= 0) {
                    next = op + 1;
                    deadline = now_s() + TIMEOUT_S; // per-operation budget
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
        if (next >= NOPS)
            break;
        // the child stopped before finishing operation `next`
        std::string msg;
        if (timed_out) {
            char b[128];
            std::snprintf(b, sizeof b, "timeout: no result after %g s (killed)", TIMEOUT_S);
            msg = b;
            timeouts += (timeouts.empty() ? "" : ",") + std::string(OP_KEYS[next]);
        } else if (WIFSIGNALED(status)) {
            msg = "crash: process killed by signal " + std::to_string(WTERMSIG(status)) + " (" +
                  strsignal(WTERMSIG(status)) + ")";
        } else {
            msg = "crash: process exited with status " +
                  std::to_string(WIFEXITED(status) ? WEXITSTATUS(status) : -1);
        }
        res[next].done = true;
        res[next].val = "null";
        res[next].err = json_quote(msg);
        next++;
    }
}

// ------------------------------------------------------------------ driver

static void print_result(const std::string &lib, const std::string &id_json, const OpResult *res,
                         const std::string &timeouts, const std::string &parse_err, bool reasons,
                         const CaseState &st)
{
    std::string out = "{\"id\": " + id_json + ", \"lib\": " + json_quote(lib);
    for (int op = 0; op < NOPS; op++)
        out += std::string(", \"") + OP_KEYS[op] + "\": " + (res[op].done ? res[op].val : "null");
    out += ", \"errors\": {";
    bool first = true;
    auto add = [&](const std::string &k, const std::string &v) {
        out += (first ? "\"" : ", \"") + k + "\": " + v;
        first = false;
    };
    for (int op = 0; op < NOPS; op++)
        if (!res[op].err.empty())
            add(OP_KEYS[op], res[op].err);
    if (!timeouts.empty()) {
        char b[64];
        std::snprintf(b, sizeof b, "%g", TIMEOUT_S);
        add("timeout", json_quote(std::string("operations exceeded ") + b + " s: " + timeouts));
    }
    if (!parse_err.empty())
        add("parse", json_quote(parse_err));
    out += "}";
    if (reasons && parse_err.empty()) {
        out += ", \"valid_reasons\": {\"valid_a\": " + (res[OP_VALID_A].note.empty() ? "null" : res[OP_VALID_A].note) +
               ", \"valid_b\": " + (res[OP_VALID_B].note.empty() ? "null" : res[OP_VALID_B].note) + "}";
        out += ", \"reversed_rings\": {\"a\": " + std::to_string(st.reversed_a) +
               ", \"b\": " + std::to_string(st.reversed_b) + "}";
    }
    out += "}\n";
    if (std::fwrite(out.data(), 1, out.size(), stdout) != out.size() || std::fflush(stdout) != 0) {
        std::fprintf(stderr, "bg_adapter: cannot write output: %s\n", std::strerror(errno));
        std::exit(1); // reader went away
    }
}

[[noreturn]] static void usage()
{
    std::fprintf(stderr, "usage: bg_adapter [--no-fork] [--reasons] CASES.jsonl > RESULTS.jsonl\n"
                         "       bg_adapter --version\n");
    std::exit(2);
}

int main(int argc, char **argv)
{
    const std::string lib = lib_string();
    bool use_fork = true, reasons = false;
    const char *path = nullptr;
    for (int i = 1; i < argc; i++) {
        if (!std::strcmp(argv[i], "--no-fork"))
            use_fork = false;
        else if (!std::strcmp(argv[i], "--reasons"))
            reasons = true;
        else if (!std::strcmp(argv[i], "--version")) {
            std::printf("%s\n", lib.c_str());
            return 0;
        } else if (argv[i][0] == '-' && argv[i][1])
            usage();
        else
            path = argv[i];
    }
    if (!path)
        usage();
    const char *e;
    if ((e = std::getenv("BG_ADAPTER_TIMEOUT")) && *e && std::atof(e) > 0)
        TIMEOUT_S = std::atof(e);
    if ((e = std::getenv("BG_ADAPTER_MEM_MB")) && *e)
        MEM_MB = std::atol(e);
    if ((e = std::getenv("BG_ADAPTER_TEST_FAULT")) && std::strlen(e) > 6)
        std::snprintf(TEST_FAULT, sizeof TEST_FAULT, "%s", e);
    if ((e = std::getenv("BG_ADAPTER_ORIENT")) && *e) {
        if (!std::strcmp(e, "exact"))
            ORIENT = OrientMode::exact;
        else if (!std::strcmp(e, "correct"))
            ORIENT = OrientMode::correct;
        else if (!std::strcmp(e, "none"))
            ORIENT = OrientMode::none;
        else {
            std::fprintf(stderr, "bg_adapter: BG_ADAPTER_ORIENT must be exact, correct or none\n");
            return 2;
        }
    }
    std::signal(SIGPIPE, SIG_IGN);

    std::ifstream fin;
    std::istream *in = &std::cin;
    if (std::strcmp(path, "-")) {
        fin.open(path);
        if (!fin) {
            std::perror(path);
            return 2;
        }
        in = &fin;
    }
    std::string line;
    while (std::getline(*in, line)) {
        size_t s = line.find_first_not_of(" \t\r\n");
        if (s == std::string::npos)
            continue; // blank line: no output, like the reference adapter
        size_t t = line.find_last_not_of(" \t\r\n");
        line = line.substr(s, t - s + 1);

        OpResult res[NOPS];
        std::string timeouts, parse_err, id_json = "null";
        CaseState st;
        Case c;
        try {
            c = parse_case(line);
        } catch (const ParseError &pe) {
            parse_err = std::string("input parse error: ") + pe.what();
            // best effort: still echo the id if the line starts with it
            try {
                Parser P{line.data(), line.data(), line.data() + line.size()};
                P.expect('{');
                while (P.peek() != -1) {
                    std::string k = P.string_token();
                    P.expect(':');
                    std::string v = P.raw_value();
                    if (k == "\"id\"") {
                        id_json = v;
                        break;
                    }
                    P.expect(',');
                }
            } catch (const ParseError &) {
            }
        }
        if (parse_err.empty()) {
            id_json = c.id_json;
            if (use_fork)
                run_case_forked(c, res, timeouts, reasons, st);
            else
                run_ops(c, 0, reasons, [&](int op, const OpResult &r) { res[op] = r; }, &st);
        }
        print_result(lib, id_json, res, timeouts, parse_err, reasons, st);
    }
    return 0;
}
