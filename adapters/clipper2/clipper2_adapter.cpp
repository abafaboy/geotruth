// Clipper2 adapter for the geometry bug hunt (contract: ../../FORMAT.md).
//
//   clipper2_adapter [options] CASES.jsonl > RESULTS.jsonl
//
// Clipper2 works on int64 coordinates, so each case is scaled by the smallest 2^k
// (0 <= k <= 60) that makes every coordinate an integer; that is exact for doubles.
// A case with no such k, or with a scaled coordinate of magnitude >= 2^62, is reported
// with every field null and errors.unsupported. Areas of the result paths are
// accumulated exactly in 192-bit integers and divided by 4^k at the end.
//
// Options:
//   --fill evenodd|nonzero   fill rule (default evenodd; nonzero re-orients shells CCW and
//                            holes CW with an exact orientation test first)
//   --pathsd8                run ClipperD with precision 8 instead of Clipper64 (only for
//                            cases where ClipperD's scaling is exact, else unsupported)
//   --strict-range           treat scaled |coord| > Clipper2's MAX_COORD (2^61-1) as unsupported
//   --scale-bits B           scale by the largest 2^k (>= the smallest one) with every scaled
//                            |coord| < 2^B, for a finer snapping grid (default: smallest k)
//   --dump-paths             add the result paths (scaled integer coordinates) as paths_<op>
//   --no-fork                run cases in-process (no crash/timeout isolation)
//   --timeout S              per-case budget in seconds (default 10, 0 = none)
//   --version                print the lib string and exit
#include "clipper2/clipper.h"

#include <cerrno>
#include <cmath>
#include <csignal>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <fstream>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

#include <poll.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#ifndef CLIPPER2_COMMIT
#define CLIPPER2_COMMIT "unknown"
#endif

using namespace Clipper2Lib;

// ---------------------------------------------------------------------------------------
// minimal JSON reader (just enough for the case format)

struct JVal {
  enum Kind { NUL, BOOL, NUM, STR, ARR, OBJ } kind = NUL;
  bool b = false;
  double num = 0;
  std::string raw;  // STR: the raw JSON text, quotes and escapes included
  std::vector<JVal> arr;
  std::vector<std::pair<std::string, JVal>> obj;  // key is the raw JSON text too
  const JVal* get(const char* key) const {
    std::string want = std::string("\"") + key + "\"";
    for (auto& kv : obj)
      if (kv.first == want) return &kv.second;
    return nullptr;
  }
};

struct JParser {
  const char* p;
  const char* end;
  [[noreturn]] void fail(const char* what) { throw std::runtime_error(std::string("JSON: ") + what); }
  void ws() {
    while (p < end && (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r')) ++p;
  }
  std::string str() {
    const char* s = p;
    if (p >= end || *p != '"') fail("expected string");
    ++p;
    while (p < end && *p != '"') {
      if (*p == '\\') ++p;
      ++p;
    }
    if (p >= end) fail("unterminated string");
    ++p;
    return std::string(s, p);
  }
  JVal value() {
    ws();
    if (p >= end) fail("unexpected end");
    JVal v;
    char c = *p;
    if (c == '{') {
      v.kind = JVal::OBJ;
      ++p;
      ws();
      if (p < end && *p == '}') { ++p; return v; }
      while (true) {
        ws();
        std::string k = str();
        ws();
        if (p >= end || *p != ':') fail("expected ':'");
        ++p;
        v.obj.emplace_back(k, value());
        ws();
        if (p < end && *p == ',') { ++p; continue; }
        if (p < end && *p == '}') { ++p; break; }
        fail("expected ',' or '}'");
      }
    } else if (c == '[') {
      v.kind = JVal::ARR;
      ++p;
      ws();
      if (p < end && *p == ']') { ++p; return v; }
      while (true) {
        v.arr.push_back(value());
        ws();
        if (p < end && *p == ',') { ++p; continue; }
        if (p < end && *p == ']') { ++p; break; }
        fail("expected ',' or ']'");
      }
    } else if (c == '"') {
      v.kind = JVal::STR;
      v.raw = str();
    } else if (!strncmp(p, "true", 4)) { v.kind = JVal::BOOL; v.b = true; p += 4; }
    else if (!strncmp(p, "false", 5)) { v.kind = JVal::BOOL; p += 5; }
    else if (!strncmp(p, "null", 4)) { v.kind = JVal::NUL; p += 4; }
    else if (!strncmp(p, "NaN", 3)) { v.kind = JVal::NUM; v.num = NAN; p += 3; }
    else if (!strncmp(p, "Infinity", 8)) { v.kind = JVal::NUM; v.num = INFINITY; p += 8; }
    else if (!strncmp(p, "-Infinity", 9)) { v.kind = JVal::NUM; v.num = -INFINITY; p += 9; }
    else {
      // strtod is correctly rounded in glibc, so a round-trip decimal gives the exact double
      std::string tok;
      while (p < end && (isdigit((unsigned char)*p) || *p == '-' || *p == '+' || *p == '.' ||
                         *p == 'e' || *p == 'E'))
        tok.push_back(*p++);
      if (tok.empty()) fail("unexpected character");
      char* e = nullptr;
      errno = 0;
      v.kind = JVal::NUM;
      v.num = strtod(tok.c_str(), &e);
      if (*e) fail("bad number");
    }
    return v;
  }
};

static JVal parse_json(const std::string& s) {
  JParser jp{s.data(), s.data() + s.size()};
  JVal v = jp.value();
  jp.ws();
  if (jp.p != jp.end) jp.fail("trailing characters");
  return v;
}

static std::string json_escape(const std::string& s) {
  std::string o = "\"";
  for (unsigned char c : s) {
    if (c == '"' || c == '\\') { o += '\\'; o += (char)c; }
    else if (c < 0x20) { char buf[8]; snprintf(buf, sizeof buf, "\\u%04x", c); o += buf; }
    else o += (char)c;
  }
  return o + "\"";
}

// shortest %.Ng that round-trips, always with a '.' or exponent (so it reads as a float)
static std::string fmt_double(double x) {
  if (!std::isfinite(x)) return "null";
  char buf[40];
  for (int prec = 1; prec <= 17; ++prec) {
    snprintf(buf, sizeof buf, "%.*g", prec, x);
    if (strtod(buf, nullptr) == x) break;
  }
  std::string s = buf;
  if (s.find_first_of(".eEn") == std::string::npos) s += ".0";
  return s;
}

// ---------------------------------------------------------------------------------------
// geometry: GeoJSON MultiPolygon coordinates -> list of polygons -> list of rings

using DRing = std::vector<std::pair<double, double>>;
using DPoly = std::vector<DRing>;
using DMulti = std::vector<DPoly>;

static DMulti read_multi(const JVal* v, const char* name) {
  if (!v || v->kind != JVal::ARR) throw std::runtime_error(std::string(name) + ": not an array");
  DMulti m;
  for (auto& poly : v->arr) {
    if (poly.kind != JVal::ARR) throw std::runtime_error(std::string(name) + ": polygon not an array");
    DPoly dp;
    for (auto& ring : poly.arr) {
      if (ring.kind != JVal::ARR) throw std::runtime_error(std::string(name) + ": ring not an array");
      DRing r;
      for (auto& pt : ring.arr) {
        if (pt.kind != JVal::ARR || pt.arr.size() < 2 || pt.arr[0].kind != JVal::NUM ||
            pt.arr[1].kind != JVal::NUM)
          throw std::runtime_error(std::string(name) + ": bad point");
        r.emplace_back(pt.arr[0].num, pt.arr[1].num);
      }
      dp.push_back(std::move(r));
    }
    m.push_back(std::move(dp));
  }
  return m;
}

// smallest j >= 0 with x * 2^j an integer; false for inf/nan
static bool dyadic_exponent(double x, int& need) {
  if (!std::isfinite(x)) return false;
  need = 0;
  if (x == 0) return true;
  int e;
  double f = std::frexp(std::fabs(x), &e);  // |x| = f * 2^e, f in [0.5, 1)
  uint64_t m = (uint64_t)std::ldexp(f, 53);  // exact 53-bit integer, |x| = m * 2^(e-53)
  int ex = e - 53;
  while ((m & 1) == 0) { m >>= 1; ++ex; }
  need = ex < 0 ? -ex : 0;
  return true;
}

// ---------------------------------------------------------------------------------------
// exact area: sum of int128 products in a 192-bit accumulator

struct Acc {
  __int128 hi = 0;          // value = hi * 2^64 + lo
  unsigned __int128 lo = 0;
  void add(__int128 p) {
    hi += (p >> 64);  // arithmetic shift (floor) on gcc/clang
    lo += (uint64_t)(unsigned __int128)p;
  }
  void sub(__int128 p) { add(-p); }
  void merge(const Acc& o) { hi += o.hi; lo += o.lo; }
  void norm() {
    hi += (__int128)(lo >> 64);
    lo &= (unsigned __int128)UINT64_MAX;
  }
  int sign() {
    norm();
    if (hi < 0) return -1;
    return (hi > 0 || lo > 0) ? 1 : 0;
  }
  long double value() {
    norm();
    const __int128 lim = (__int128)1 << 62;
    if (hi < lim && hi > -lim) {
      __int128 v = hi * ((__int128)1 << 64) + (__int128)lo;  // exact
      return (long double)v;                                   // one rounding (64-bit mantissa)
    }
    return std::ldexp((long double)hi, 64) + (long double)(uint64_t)lo;
  }
};

// twice the signed area of a closed path (implicitly closed), exact
static void twice_area(const Path64& p, Acc& acc) {
  size_t n = p.size();
  if (n < 3) return;
  for (size_t i = 0; i < n; ++i) {
    const Point64& a = p[i];
    const Point64& b = p[(i + 1) % n];
    acc.add((__int128)a.x * b.y);
    acc.sub((__int128)b.x * a.y);
  }
}

static long double paths_area(const Paths64& ps, int k) {
  Acc acc;
  for (auto& p : ps) twice_area(p, acc);
  return std::ldexp(acc.value(), -(2 * k + 1));
}

// ---------------------------------------------------------------------------------------
// exact boundary contact test with Clipper2's own exact primitives
// (PointInPolygon and CrossProductSign both use int128 products, exact for |coord| < 2^62)

static bool on_boundary(const Point64& pt, const Paths64& rings) {
  for (auto& r : rings)
    if (PointInPolygon(pt, r) == PointInPolygonResult::IsOn) return true;
  return false;
}

static bool proper_crossing(const Point64& a, const Point64& b, const Point64& c, const Point64& d) {
  int o1 = CrossProductSign(a, b, c), o2 = CrossProductSign(a, b, d);
  if (o1 == 0 || o2 == 0 || o1 == o2) return false;
  int o3 = CrossProductSign(c, d, a), o4 = CrossProductSign(c, d, b);
  return o3 != 0 && o4 != 0 && o3 != o4;
}

// the boundaries of A and B share a point: a vertex of one lies on the other's boundary,
// or two edges cross at a point interior to both
static bool boundaries_meet(const Paths64& A, const Paths64& B) {
  for (auto& r : A)
    for (auto& pt : r)
      if (on_boundary(pt, B)) return true;
  for (auto& r : B)
    for (auto& pt : r)
      if (on_boundary(pt, A)) return true;
  for (auto& ra : A) {
    size_t na = ra.size();
    if (na < 2) continue;
    for (size_t i = 0; i < na; ++i) {
      const Point64 &a = ra[i], &b = ra[(i + 1) % na];
      if (a == b) continue;
      int64_t axl = std::min(a.x, b.x), axh = std::max(a.x, b.x);
      int64_t ayl = std::min(a.y, b.y), ayh = std::max(a.y, b.y);
      for (auto& rb : B) {
        size_t nb = rb.size();
        if (nb < 2) continue;
        for (size_t j = 0; j < nb; ++j) {
          const Point64 &c = rb[j], &d = rb[(j + 1) % nb];
          if (std::max(c.x, d.x) < axl || std::min(c.x, d.x) > axh ||
              std::max(c.y, d.y) < ayl || std::min(c.y, d.y) > ayh || c == d)
            continue;
          if (proper_crossing(a, b, c, d)) return true;
        }
      }
    }
  }
  return false;
}

// ---------------------------------------------------------------------------------------

struct Options {
  bool nonzero = false;
  bool pathsd8 = false;
  bool strict_range = false;
  int scale_bits = 0;  // 0: smallest k (default)
  bool dump_paths = false;
  bool fork = true;
  double timeout = 10.0;
  std::string lib;
};

static const char* AREA_KEYS[4] = {"area_inter", "area_union", "area_diff", "area_symdiff"};
static const ClipType CLIP_TYPES[4] = {ClipType::Intersection, ClipType::Union,
                                       ClipType::Difference, ClipType::Xor};
static const char* PRED_KEYS[9] = {"intersects", "disjoint", "touches", "overlaps", "contains",
                                   "covers", "within", "covered_by", "equals"};

struct Result {
  std::string id = "null";
  // tri-state: -1 null, 0 false, 1 true
  int intersects = -1, disjoint = -1;
  bool have_area[4] = {false, false, false, false};
  double area[4] = {0, 0, 0, 0};
  std::vector<std::pair<std::string, std::string>> errors;  // key, message
  std::vector<std::pair<std::string, std::string>> extra;   // key, raw JSON value
};

static std::string render(const Result& r, const Options& o) {
  std::string s = "{\"id\": " + r.id + ", \"lib\": " + json_escape(o.lib);
  s += ", \"valid_a\": null, \"valid_b\": null";
  for (auto key : PRED_KEYS) {
    std::string k = key;
    int v = k == "intersects" ? r.intersects : k == "disjoint" ? r.disjoint : -1;
    s += ", \"" + k + "\": " + (v < 0 ? "null" : v ? "true" : "false");
  }
  for (int i = 0; i < 4; ++i)
    s += std::string(", \"") + AREA_KEYS[i] + "\": " + (r.have_area[i] ? fmt_double(r.area[i]) : "null");
  s += ", \"errors\": {";
  for (size_t i = 0; i < r.errors.size(); ++i)
    s += (i ? ", " : "") + json_escape(r.errors[i].first) + ": " + json_escape(r.errors[i].second);
  s += "}";
  for (auto& kv : r.extra) s += ", " + json_escape(kv.first) + ": " + kv.second;
  return s + "}";
}

static std::string id_of(const std::string& line) {
  try {
    JVal v = parse_json(line);
    const JVal* id = v.get("id");
    if (!id) return "null";
    if (id->kind == JVal::STR) return id->raw;
    if (id->kind == JVal::NUM) return fmt_double(id->num);
  } catch (...) {
  }
  return "null";
}

static std::string failed_case(const std::string& line, const Options& o, const char* key,
                               const std::string& msg) {
  Result r;
  r.id = id_of(line);
  r.errors.emplace_back(key, msg);
  return render(r, o);
}

// scale every coordinate by 2^k (exact) into Paths64, one path per ring, closing point dropped
static Paths64 to_paths64(const DMulti& m, int k) {
  Paths64 out;
  for (auto& poly : m)
    for (auto& ring : poly) {
      Path64 p;
      for (auto& xy : ring)
        p.emplace_back((int64_t)std::ldexp(xy.first, k), (int64_t)std::ldexp(xy.second, k));
      if (p.size() > 1 && p.front() == p.back()) p.pop_back();
      out.push_back(std::move(p));
    }
  return out;
}

// back to doubles (exact: every value is a double times 2^k)
static PathsD to_pathsd(const Paths64& ps, int k) {
  PathsD out;
  for (auto& p : ps) {
    PathD d;
    for (auto& pt : p) d.emplace_back(std::ldexp((double)pt.x, -k), std::ldexp((double)pt.y, -k));
    out.push_back(std::move(d));
  }
  return out;
}

// NonZero needs consistent orientation: shells counter-clockwise, holes clockwise
static void orient_for_nonzero(const DMulti& m, Paths64& paths) {
  size_t idx = 0;
  for (auto& poly : m)
    for (size_t r = 0; r < poly.size(); ++r, ++idx) {
      Acc acc;
      twice_area(paths[idx], acc);
      int s = acc.sign();
      if ((r == 0 && s < 0) || (r > 0 && s > 0)) std::reverse(paths[idx].begin(), paths[idx].end());
    }
}

static std::string run_case(const std::string& line, const Options& o) {
  Result r;
  JVal v;
  try {
    v = parse_json(line);
  } catch (std::exception& e) {
    r.errors.emplace_back("parse", e.what());
    return render(r, o);
  }
  if (const JVal* id = v.get("id")) {
    if (id->kind == JVal::STR) r.id = id->raw;
    else if (id->kind == JVal::NUM) r.id = fmt_double(id->num);
  }
  // self-test hooks for the crash/timeout isolation (see README)
  if (const char* t = getenv("CLIPPER2_ADAPTER_TEST_CRASH_ID"))
    if (r.id == json_escape(t)) raise(SIGSEGV);
  if (const char* t = getenv("CLIPPER2_ADAPTER_TEST_HANG_ID"))
    if (r.id == json_escape(t))
      for (;;) pause();
  DMulti ma, mb;
  try {
    ma = read_multi(v.get("a"), "a");
    mb = read_multi(v.get("b"), "b");
  } catch (std::exception& e) {
    r.errors.emplace_back("parse", e.what());
    return render(r, o);
  }

  // smallest k making every coordinate an integer
  int k = 0;
  bool ok = true;
  for (auto* m : {&ma, &mb})
    for (auto& poly : *m)
      for (auto& ring : poly)
        for (auto& xy : ring) {
          int n1, n2;
          if (!dyadic_exponent(xy.first, n1) || !dyadic_exponent(xy.second, n2)) ok = false;
          else k = std::max(k, std::max(n1, n2));
        }
  const double lim = o.strict_range ? std::ldexp(1.0, 61) : std::ldexp(1.0, 62);
  double maxabs = 0;
  if (ok && k <= 60) {
    for (auto* m : {&ma, &mb})
      for (auto& poly : *m)
        for (auto& ring : poly)
          for (auto& xy : ring)
            maxabs = std::max(maxabs, std::max(std::fabs(std::ldexp(xy.first, k)),
                                               std::fabs(std::ldexp(xy.second, k))));
  }
  if (!ok || k > 60 || !(maxabs < lim)) {
    r.errors.emplace_back("unsupported", "non-dyadic or out of range");
    return render(r, o);
  }
  const int k_min = k;
  // --scale-bits B: use the largest 2^k (at least the minimal one) that keeps every scaled
  // coordinate below 2^B, so intersection points are snapped to a finer integer grid
  if (o.scale_bits > 0 && maxabs > 0) {
    int e;
    std::frexp(std::ldexp(maxabs, -k), &e);  // unscaled max |coord| < 2^e
    int k_up = (o.strict_range ? std::min(o.scale_bits, 61) : o.scale_bits) - e;
    if (k_up > k) {
      maxabs = std::ldexp(maxabs, k_up - k);
      k = k_up;
    }
  }

  // ClipperD scales by 2^(ilogb(10^precision)+1); it is exact here only when every
  // coordinate times that power of two is an integer below 2^53 (so the way back to
  // double is exact too)
  int kd = k;
  if (o.pathsd8) {
    double sc = std::pow(std::numeric_limits<double>::radix, std::ilogb(std::pow(10, 8)) + 1);
    int e;
    double f = std::frexp(sc, &e);
    kd = e - 1;
    if (f != 0.5 || k > kd || std::ldexp(maxabs, kd - k) >= std::ldexp(1.0, 53)) {
      r.errors.emplace_back("unsupported", "not exact in ClipperD precision 8");
      return render(r, o);
    }
  }

  r.extra.emplace_back("scale_log2", std::to_string(o.pathsd8 ? kd : k));
  if (k != k_min) r.extra.emplace_back("min_scale_log2", std::to_string(k_min));
  if (maxabs >= std::ldexp(1.0, 61) && !o.pathsd8)
    r.extra.emplace_back("over_max_coord", "true");  // beyond Clipper2's documented MAX_COORD

  Paths64 A = to_paths64(ma, k), B = to_paths64(mb, k);
  if (o.nonzero) {
    orient_for_nonzero(ma, A);
    orient_for_nonzero(mb, B);
  }
  const FillRule fr = o.nonzero ? FillRule::NonZero : FillRule::EvenOdd;
  // ClipperD input: the (possibly re-oriented) rings as doubles again, exactly
  PathsD AD, BD;
  if (o.pathsd8) {
    AD = to_pathsd(A, k);
    BD = to_pathsd(B, k);
  }

  for (int i = 0; i < 4; ++i) {
    try {
      bool succeeded;
      Paths64 sol;
      if (o.pathsd8) {
        ClipperD c(8);
        c.AddSubject(AD);
        c.AddClip(BD);
        PathsD sold;
        succeeded = c.Execute(CLIP_TYPES[i], fr, sold);
        for (auto& p : sold) {
          Path64 q;
          for (auto& pt : p) q.emplace_back((int64_t)std::ldexp(pt.x, kd), (int64_t)std::ldexp(pt.y, kd));
          sol.push_back(std::move(q));
        }
      } else {
        Clipper64 c;
        c.AddSubject(A);
        c.AddClip(B);
        succeeded = c.Execute(CLIP_TYPES[i], fr, sol);
      }
      if (!succeeded) {
        r.errors.emplace_back(AREA_KEYS[i], "Clipper Execute returned false");
        continue;
      }
      if (o.dump_paths) {  // result paths in scaled integer coordinates
        std::string js = "[";
        for (size_t pi = 0; pi < sol.size(); ++pi) {
          js += pi ? ", [" : "[";
          for (size_t qi = 0; qi < sol[pi].size(); ++qi)
            js += (qi ? ", [" : "[") + std::to_string(sol[pi][qi].x) + ", " + std::to_string(sol[pi][qi].y) + "]";
          js += "]";
        }
        r.extra.emplace_back(std::string("paths_") + (AREA_KEYS[i] + 5), js + "]");
      }
      long double a = paths_area(sol, o.pathsd8 ? kd : k);
      r.have_area[i] = true;
      r.area[i] = (double)a;
    } catch (std::exception& e) {
      r.errors.emplace_back(AREA_KEYS[i], std::string("exception: ") + e.what());
    } catch (...) {
      r.errors.emplace_back(AREA_KEYS[i], "unknown exception");
    }
  }

  // intersects = intersection area > 0 or the boundaries meet (exact); disjoint = !intersects
  try {
    bool meet = boundaries_meet(A, B);
    r.extra.emplace_back("boundaries_meet", meet ? "true" : "false");
    if (meet) r.intersects = 1;
    else if (r.have_area[0]) r.intersects = r.area[0] > 0;
    if (r.intersects >= 0) r.disjoint = !r.intersects;
  } catch (std::exception& e) {
    r.errors.emplace_back("intersects", std::string("exception: ") + e.what());
  }
  return render(r, o);
}

// ---------------------------------------------------------------------------------------
// driver: a forked worker runs the cases in order; a crash or a case over the time budget
// is reported for that case and a fresh worker resumes with the next one

static double now() {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return ts.tv_sec + ts.tv_nsec * 1e-9;
}

static void write_all(int fd, const std::string& s) {
  const char* p = s.data();
  size_t left = s.size();
  while (left) {
    ssize_t w = write(fd, p, left);
    if (w < 0) {
      if (errno == EINTR) continue;
      _exit(3);
    }
    p += w;
    left -= (size_t)w;
  }
}

static void run_forked(const std::vector<std::string>& lines, const Options& o) {
  size_t idx = 0;
  while (idx < lines.size()) {
    int fds[2];
    if (pipe(fds) != 0) { perror("pipe"); exit(1); }
    fflush(stdout);
    pid_t pid = fork();
    if (pid < 0) { perror("fork"); exit(1); }
    if (pid == 0) {
      close(fds[0]);
      for (size_t i = idx; i < lines.size(); ++i) write_all(fds[1], run_case(lines[i], o) + "\n");
      _exit(0);
    }
    close(fds[1]);
    std::string buf;
    double started = now();
    bool dead = false, timed_out = false;
    while (!dead && idx < lines.size()) {
      struct pollfd pfd = {fds[0], POLLIN, 0};
      int wait_ms = -1;
      if (o.timeout > 0) {
        double left = o.timeout - (now() - started);
        if (left <= 0) { timed_out = true; break; }
        wait_ms = (int)(left * 1000) + 1;
      }
      int pr = poll(&pfd, 1, wait_ms);
      if (pr < 0) {
        if (errno == EINTR) continue;
        perror("poll");
        exit(1);
      }
      if (pr == 0) continue;  // re-check the budget
      char chunk[65536];
      ssize_t n = read(fds[0], chunk, sizeof chunk);
      if (n < 0) {
        if (errno == EINTR) continue;
        perror("read");
        exit(1);
      }
      if (n == 0) { dead = true; break; }
      buf.append(chunk, (size_t)n);
      size_t nl;
      while ((nl = buf.find('\n')) != std::string::npos) {
        fwrite(buf.data(), 1, nl + 1, stdout);
        fflush(stdout);
        buf.erase(0, nl + 1);
        ++idx;
        started = now();
      }
    }
    close(fds[0]);
    if (timed_out) {
      kill(pid, SIGKILL);
      waitpid(pid, nullptr, 0);
      char msg[64];
      snprintf(msg, sizeof msg, "over %g s", o.timeout);
      std::string out = failed_case(lines[idx], o, "timeout", msg);
      printf("%s\n", out.c_str());
      fflush(stdout);
      ++idx;
      continue;
    }
    int status = 0;
    waitpid(pid, &status, 0);
    if (idx < lines.size()) {
      char msg[96];
      if (WIFSIGNALED(status))
        snprintf(msg, sizeof msg, "worker killed by signal %d (%s)", WTERMSIG(status), strsignal(WTERMSIG(status)));
      else
        snprintf(msg, sizeof msg, "worker exited with status %d", WEXITSTATUS(status));
      std::string out = failed_case(lines[idx], o, "crash", msg);
      printf("%s\n", out.c_str());
      fflush(stdout);
      ++idx;
    }
  }
}

int main(int argc, char** argv) {
  Options o;
  std::string path;
  bool version = false;
  for (int i = 1; i < argc; ++i) {
    std::string a = argv[i];
    if (a == "--fill" && i + 1 < argc) {
      std::string f = argv[++i];
      if (f == "nonzero") o.nonzero = true;
      else if (f == "evenodd") o.nonzero = false;
      else { fprintf(stderr, "unknown fill rule %s\n", f.c_str()); return 2; }
    } else if (a == "--pathsd8") o.pathsd8 = true;
    else if (a == "--strict-range") o.strict_range = true;
    else if (a == "--dump-paths") o.dump_paths = true;
    else if (a == "--scale-bits" && i + 1 < argc) {
      o.scale_bits = atoi(argv[++i]);
      if (o.scale_bits < 1 || o.scale_bits > 62) { fprintf(stderr, "--scale-bits must be 1..62\n"); return 2; }
    }
    else if (a == "--no-fork") o.fork = false;
    else if (a == "--timeout" && i + 1 < argc) o.timeout = atof(argv[++i]);
    else if (a == "--version") version = true;
    else if (!a.empty() && a[0] == '-' && a != "-") { fprintf(stderr, "unknown option %s\n", a.c_str()); return 2; }
    else path = a;
  }
  o.lib = std::string("clipper2@") + CLIPPER2_VERSION + "-" + CLIPPER2_COMMIT;
  if (o.pathsd8) o.lib += "+pathsd8";
  if (o.nonzero) o.lib += "+nonzero";
  if (o.strict_range) o.lib += "+strict";
  if (o.scale_bits) o.lib += "+scale" + std::to_string(o.scale_bits);
  if (o.scale_bits && o.pathsd8) { fprintf(stderr, "--scale-bits does not apply to --pathsd8\n"); return 2; }
  if (version) {
    printf("%s\n", o.lib.c_str());
    return 0;
  }
  if (path.empty()) {
    fprintf(stderr, "usage: %s [--fill evenodd|nonzero] [--pathsd8] [--strict-range] [--scale-bits B] [--no-fork] [--timeout S] CASES.jsonl\n", argv[0]);
    return 2;
  }
  std::vector<std::string> lines;
  {
    std::ifstream in(path == "-" ? "/dev/stdin" : path);
    if (!in) { fprintf(stderr, "cannot open %s\n", path.c_str()); return 2; }
    std::string line;
    while (std::getline(in, line)) {
      bool blank = true;
      for (char c : line)
        if (!isspace((unsigned char)c)) { blank = false; break; }
      if (!blank) lines.push_back(line);
    }
  }
  if (o.fork) run_forked(lines, o);
  else
    for (auto& l : lines) printf("%s\n", run_case(l, o).c_str());
  return 0;
}
