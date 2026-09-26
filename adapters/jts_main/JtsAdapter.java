// JTS (locationtech/jts, jts-core) adapter: adapter contract v2 (docs/DESIGN.md §4.1,
// schemas/result.v2.schema.json) and the legacy FORMAT-v1 contract (harness/FORMAT-v1.md).
//
// Usage (via run.sh / run_release.sh):
//   JtsAdapter [--lib S] [--relate ng|old] [--timeout SEC] [--v2] [--timing] [--no-fork] CASES.jsonl|-
//   JtsAdapter [--lib S] --version
//
// A line is answered with contract v2 when an operand is a typed geometry (a JSON object) or
// "ops" is present (--v2: every line); other lines are legacy v1 cases, answered by the
// unchanged v1 code below.
//
// v2 (one field path per operation, in this order; "ops" selects the groups):
//   echo                 the operands as built, written back by this adapter
//   relate               RelateNG.relate(a, b) (--relate old: Geometry.relate, i.e. RelateOp)
//   predicates.<name>    RelateNG.relate(a, b, RelatePredicate.<name>()) (--relate old: the
//                        Geometry methods, i.e. RelateOp); covered_by = coveredBy,
//                        equals = equalsTopo
//   valid_a, valid_b     IsValidOp.isValid()
//   overlay.<op>         OverlayNGRobust.overlay(a, b, OverlayNG.<OP>) (non-strict OverlayNG
//                        with its snapping / snap-rounding fallbacks)
// Every type is built with the default GeometryFactory (floating PrecisionModel), empty
// geometries and empty elements included; a geometry JTS refuses to build (an unclosed ring, a
// one-point line) fails every field that needs it with "building A: ...". Out of JTS's
// contract, reported "unsupported": GeometryCollection operands of the old RelateOp, and
// GeometryCollection operands that OverlayNG rejects (it takes only collections that flatten
// into a valid multi-geometry). Output coordinates are written by this adapter with
// Double.toString (the shortest round-trip decimal on JDK >= 19), never by a WKT writer.
//
// Isolation (v2): the operations run in a worker JVM (this class with --worker) that sends
// each result as soon as it has it. An operation with no result within the timeout
// (--timeout, else JTS_ADAPTER_TIMEOUT or GEOTRUTH_OP_TIMEOUT, default 10 s) kills the worker:
// {"kind": "timeout"}; a worker that dies fails that one operation: {"kind": "crash"}; a new
// worker continues with the next operation. The worker heap is capped at JTS_ADAPTER_MEM_MB
// MiB (default 2048); an OutOfMemoryError is {"kind": "memory"}. --no-fork runs in-process.
// JTS_ADAPTER_TEST_FAULT=crash:<path>|hang_:<path>|throw:<path> injects a fault (self-test).
//
// v1: a one-part multipolygon becomes a Polygon, otherwise a MultiPolygon; valid_a/valid_b:
// IsValidOp; predicates: Geometry.intersects/disjoint/touches/overlaps/contains/covers/within/
// coveredBy/equalsTopo (--relate ng: RelateNG through jts.relate=ng); areas:
// OverlayNGRobust.overlay(a, b, op).getArea(); a per-case --timeout (default 10 s).

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.Callable;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.FutureTask;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

import org.locationtech.jts.geom.Coordinate;
import org.locationtech.jts.geom.CoordinateSequence;
import org.locationtech.jts.geom.Geometry;
import org.locationtech.jts.geom.GeometryCollection;
import org.locationtech.jts.geom.GeometryFactory;
import org.locationtech.jts.geom.LineString;
import org.locationtech.jts.geom.LinearRing;
import org.locationtech.jts.geom.MultiPoint;
import org.locationtech.jts.geom.Point;
import org.locationtech.jts.geom.Polygon;
import org.locationtech.jts.operation.overlayng.OverlayNG;
import org.locationtech.jts.operation.overlayng.OverlayNGRobust;
import org.locationtech.jts.operation.relateng.RelateNG;
import org.locationtech.jts.operation.relateng.RelatePredicate;
import org.locationtech.jts.operation.relateng.TopologyPredicate;
import org.locationtech.jts.operation.valid.IsValidOp;

public class JtsAdapter {

  // ================================================================ command line

  static String relateV1 = "old";
  static String relateV2 = "ng";
  static double opTimeout = 10.0;
  static boolean timing = false;
  static long memMb = 2048;
  static String fault = "";

  public static void main(String[] args) throws Exception {
    String path = null;
    String relate = null;
    Double timeoutArg = null;
    boolean forceV2 = false, noFork = false, worker = false, version = false;
    for (int i = 0; i < args.length; i++) {
      switch (args[i]) {
        case "--lib": lib = args[++i]; break;
        case "--relate": relate = args[++i]; break;
        case "--timeout": timeoutArg = Double.parseDouble(args[++i]); break;
        case "--v2": forceV2 = true; break;
        case "--timing": timing = true; break;
        case "--no-fork": noFork = true; break;
        case "--worker": worker = true; break;
        case "--version": version = true; break;
        default:
          if (path != null) usage("unexpected argument " + args[i]);
          path = args[i];
      }
    }
    if (relate != null && !relate.equals("old") && !relate.equals("ng")) usage("--relate must be old or ng");
    if (relate != null) { relateV1 = relate; relateV2 = relate; }
    String base = lib;
    if (relateV2.equals("old")) lib = base + "+relateop";
    if (version) {
      System.out.println(lib);
      return;
    }
    opTimeout = timeoutArg != null ? timeoutArg : envDouble(10.0, "JTS_ADAPTER_TIMEOUT", "GEOTRUTH_OP_TIMEOUT");
    memMb = (long) envDouble(2048, "JTS_ADAPTER_MEM_MB");
    String f = System.getenv("JTS_ADAPTER_TEST_FAULT");
    fault = f == null ? "" : f;
    if (worker) {
      workerLoop();
      return;
    }
    if (path == null) usage("missing CASES.jsonl");
    // Must be set before org.locationtech.jts.geom.GeometryRelate is initialised (v1 only).
    System.setProperty("jts.relate", relateV1);
    String libV1 = relateV1.equals("ng") ? base + "+relateng" : base;
    double v1Timeout = timeoutArg != null ? timeoutArg : 10.0;

    PrintWriter out = new PrintWriter(new BufferedWriter(
        new OutputStreamWriter(System.out, StandardCharsets.UTF_8)), false);
    Supervisor sup = noFork ? null : new Supervisor();
    InputStream ins = path.equals("-") ? System.in : new FileInputStream(path);
    try (BufferedReader in = new BufferedReader(new InputStreamReader(ins, StandardCharsets.UTF_8))) {
      String line;
      while ((line = in.readLine()) != null) {
        if (line.trim().isEmpty()) continue;
        String result;
        Object parsed = null;
        try {
          parsed = new Json(line).parse();
        } catch (Throwable t) {
          parsed = null;
        }
        if (forceV2 || isV2(parsed)) {
          result = answerV2(line, parsed, sup);
        } else {
          String saved = lib;
          lib = libV1;
          try {
            result = runWithTimeout(line, v1Timeout);
          } catch (Throwable t) {
            // Should not happen (runCase catches per operation); keep one line per case.
            result = allNull(idOf(line), "adapter", describe(t));
          }
          lib = saved;
        }
        out.println(result);
        out.flush();
      }
    } finally {
      if (sup != null) sup.close();
    }
  }

  static double envDouble(double dflt, String... names) {
    for (String n : names) {
      String v = System.getenv(n);
      if (v != null && !v.isEmpty()) {
        try {
          double d = Double.parseDouble(v);
          if (d > 0) return d;
        } catch (NumberFormatException e) { /* ignore */ }
      }
    }
    return dflt;
  }

  static void usage(String msg) {
    System.err.println("JtsAdapter: " + msg);
    System.err.println("usage: JtsAdapter [--lib S] [--relate old|ng] [--timeout SEC] [--v2] [--timing] "
        + "[--no-fork] CASES.jsonl|-");
    System.exit(2);
  }

  // ================================================================ contract v2

  static final String[] PREDICATES = {"intersects", "disjoint", "touches", "crosses", "overlaps",
      "contains", "covers", "within", "covered_by", "equals"};
  static final String[] OVERLAYS = {"intersection", "union", "difference", "symdifference"};

  static boolean isV2(Object parsed) {
    if (!(parsed instanceof Map)) return false;
    Map<?, ?> m = (Map<?, ?>) parsed;
    return m.containsKey("ops") || m.get("a") instanceof Map || m.get("b") instanceof Map;
  }

  static String groupOf(String path) {
    if (path.equals("valid_a") || path.equals("valid_b")) return "validity";
    int dot = path.indexOf('.');
    return dot < 0 ? path : path.substring(0, dot);
  }

  static List<String> allPaths() {
    List<String> p = new ArrayList<>();
    p.add("echo");
    p.add("relate");
    for (String s : PREDICATES) p.add("predicates." + s);
    p.add("valid_a");
    p.add("valid_b");
    for (String s : OVERLAYS) p.add("overlay." + s);
    return p;
  }

  /** The field paths a case asks for ("ops"; absent = everything but echo). */
  static List<String> requested(Map<?, ?> c) {
    List<String> groups = new ArrayList<>();
    Object ops = c.get("ops");
    if (ops == null) {
      groups.add("relate"); groups.add("predicates"); groups.add("validity"); groups.add("overlay");
    } else {
      if (!(ops instanceof List)) throw new IllegalArgumentException("\"ops\" must be an array");
      for (Object o : (List<?>) ops) {
        if (!(o instanceof String)) throw new IllegalArgumentException("unknown op");
        String s = (String) o;
        if (!(s.equals("echo") || s.equals("relate") || s.equals("predicates") || s.equals("validity")
            || s.equals("overlay"))) throw new IllegalArgumentException("unknown op \"" + s + "\"");
        groups.add(s);
      }
    }
    List<String> out = new ArrayList<>();
    for (String p : allPaths()) if (groups.contains(groupOf(p))) out.add(p);
    return out;
  }

  static final class Unsupported extends RuntimeException {
    Unsupported() { super("unsupported"); }
  }

  /** One operation's outcome as JSON texts: value ("null" when failed) and error (or null). */
  static final class OpResult {
    String value = "null";
    String error = null;
    double ms = -1;
  }

  /** A case on the library side: both operands built once (errors deferred). */
  static final class Session {
    Geometry a, b;
    String errA, errB;

    Session(Map<?, ?> c) {
      try { a = buildAny(c.get("a")); } catch (Throwable t) { errA = "building A: " + describe(t); }
      try { b = buildAny(c.get("b")); } catch (Throwable t) { errB = "building B: " + describe(t); }
    }

    OpResult run(String path) {
      OpResult r = new OpResult();
      long t0 = System.nanoTime();
      try {
        injectFault(path);
        r.value = compute(path);
      } catch (Unsupported u) {
        r.value = "\"unsupported\"";
      } catch (OutOfMemoryError e) {
        r.value = "null";
        r.error = "{\"kind\": \"memory\", \"message\": " + quote(describe(e)) + "}";
      } catch (Throwable t) {
        r.value = "null";
        r.error = quote(describe(t));
      }
      r.ms = (System.nanoTime() - t0) / 1e6;
      return r;
    }

    String compute(String path) {
      boolean needA = !path.equals("valid_b"), needB = !path.equals("valid_a");
      if (needA && a == null) throw new IllegalStateException(errA);
      if (needB && b == null) throw new IllegalStateException(errB);
      boolean gc = isCollection(a) || isCollection(b);
      if (path.equals("echo")) return "{\"a\": " + geomJson(a) + ", \"b\": " + geomJson(b) + "}";
      if (path.equals("valid_a")) return Boolean.toString(new IsValidOp(a).isValid());
      if (path.equals("valid_b")) return Boolean.toString(new IsValidOp(b).isValid());
      if (path.equals("relate")) {
        if (relateV2.equals("old")) {
          if (gc) throw new Unsupported();
          return quote(a.relate(b).toString());
        }
        return quote(RelateNG.relate(a, b).toString());
      }
      if (path.startsWith("predicates.")) {
        String name = path.substring("predicates.".length());
        if (relateV2.equals("old")) {
          if (gc) throw new Unsupported();
          return Boolean.toString(oldPredicate(name, a, b));
        }
        return Boolean.toString(RelateNG.relate(a, b, ngPredicate(name)));
      }
      if (path.startsWith("overlay.")) {
        int code = overlayCode(path.substring("overlay.".length()));
        try {
          return geomJson(OverlayNGRobust.overlay(a, b, code));
        } catch (IllegalArgumentException e) {
          if (gc) throw new Unsupported();
          throw e;
        }
      }
      throw new IllegalArgumentException("unknown field path " + path);
    }
  }

  static boolean isCollection(Geometry g) {
    return g != null && g.getGeometryType().equals("GeometryCollection");
  }

  static TopologyPredicate ngPredicate(String name) {
    switch (name) {
      case "intersects": return RelatePredicate.intersects();
      case "disjoint": return RelatePredicate.disjoint();
      case "touches": return RelatePredicate.touches();
      case "crosses": return RelatePredicate.crosses();
      case "overlaps": return RelatePredicate.overlaps();
      case "contains": return RelatePredicate.contains();
      case "covers": return RelatePredicate.covers();
      case "within": return RelatePredicate.within();
      case "covered_by": return RelatePredicate.coveredBy();
      case "equals": return RelatePredicate.equalsTopo();
      default: throw new IllegalArgumentException("unknown predicate " + name);
    }
  }

  static boolean oldPredicate(String name, Geometry a, Geometry b) {
    switch (name) {
      case "intersects": return a.intersects(b);
      case "disjoint": return a.disjoint(b);
      case "touches": return a.touches(b);
      case "crosses": return a.crosses(b);
      case "overlaps": return a.overlaps(b);
      case "contains": return a.contains(b);
      case "covers": return a.covers(b);
      case "within": return a.within(b);
      case "covered_by": return a.coveredBy(b);
      case "equals": return a.equalsTopo(b);
      default: throw new IllegalArgumentException("unknown predicate " + name);
    }
  }

  static int overlayCode(String op) {
    switch (op) {
      case "intersection": return OverlayNG.INTERSECTION;
      case "union": return OverlayNG.UNION;
      case "difference": return OverlayNG.DIFFERENCE;
      case "symdifference": return OverlayNG.SYMDIFFERENCE;
      default: throw new IllegalArgumentException("unknown overlay " + op);
    }
  }

  static void injectFault(String path) {
    if (fault.length() <= 6 || !fault.substring(6).equals(path)) return;
    String kind = fault.substring(0, 6);
    if (kind.equals("crash:")) Runtime.getRuntime().halt(134);
    if (kind.equals("hang_:")) { while (true) { try { Thread.sleep(3600_000); } catch (InterruptedException e) { /* keep hanging */ } } }
    if (kind.equals("throw:")) throw new IllegalStateException("injected test fault");
  }

  // ---------------------------------------------------------------- building (v2)

  static Geometry buildAny(Object o) {
    if (o instanceof List) return build(o);  // legacy multipolygon array
    if (!(o instanceof Map)) throw new IllegalArgumentException("not a typed geometry");
    return buildTyped((Map<?, ?>) o);
  }

  static Geometry buildTyped(Map<?, ?> g) {
    Object t = g.get("type");
    if (!(t instanceof String)) throw new IllegalArgumentException("geometry without a type");
    String type = (String) t;
    if (type.equals("GeometryCollection")) {
      List<?> gs = (List<?>) g.get("geometries");
      if (gs == null) throw new IllegalArgumentException("GeometryCollection needs 'geometries'");
      Geometry[] parts = new Geometry[gs.size()];
      for (int i = 0; i < parts.length; i++) {
        Object p = gs.get(i);
        if (!(p instanceof Map)) throw new IllegalArgumentException("not a typed geometry");
        parts[i] = buildTyped((Map<?, ?>) p);
      }
      return GF.createGeometryCollection(parts);
    }
    Object c = g.get("coordinates");
    if (!(c instanceof List)) throw new IllegalArgumentException(type + " needs a 'coordinates' list");
    List<?> cs = (List<?>) c;
    switch (type) {
      case "Point": return point(cs);
      case "LineString": return GF.createLineString(coords(cs));
      case "Polygon": return typedPolygon(cs);
      case "MultiPoint": {
        Point[] ps = new Point[cs.size()];
        for (int i = 0; i < ps.length; i++) ps[i] = point((List<?>) cs.get(i));
        return GF.createMultiPoint(ps);
      }
      case "MultiLineString": {
        LineString[] ls = new LineString[cs.size()];
        for (int i = 0; i < ls.length; i++) ls[i] = GF.createLineString(coords((List<?>) cs.get(i)));
        return GF.createMultiLineString(ls);
      }
      case "MultiPolygon": {
        Polygon[] ps = new Polygon[cs.size()];
        for (int i = 0; i < ps.length; i++) ps[i] = typedPolygon((List<?>) cs.get(i));
        return GF.createMultiPolygon(ps);
      }
      default: throw new IllegalArgumentException("unknown geometry type " + type);
    }
  }

  static Point point(List<?> c) {
    if (c.isEmpty()) return GF.createPoint();
    return GF.createPoint(coord(c));
  }

  static Coordinate coord(Object o) {
    List<?> p = (List<?>) o;
    if (p.size() < 2) throw new IllegalArgumentException("a position needs at least 2 numbers");
    return new Coordinate(num(p.get(0)), num(p.get(1)));
  }

  static Coordinate[] coords(List<?> cs) {
    Coordinate[] out = new Coordinate[cs.size()];
    for (int i = 0; i < out.length; i++) out[i] = coord(cs.get(i));
    return out;
  }

  static Polygon typedPolygon(List<?> rings) {
    if (rings.isEmpty()) return GF.createPolygon();
    LinearRing shell = GF.createLinearRing(coords((List<?>) rings.get(0)));
    LinearRing[] holes = new LinearRing[rings.size() - 1];
    for (int i = 1; i < rings.size(); i++) holes[i - 1] = GF.createLinearRing(coords((List<?>) rings.get(i)));
    return GF.createPolygon(shell, holes);
  }

  // ---------------------------------------------------------------- writing (v2)

  static String fmt(double d) {
    // Double.toString: the shortest decimal that round-trips (JDK >= 19); "1.0E-10" is JSON.
    return Double.toString(d);
  }

  static void position(StringBuilder sb, CoordinateSequence s, int i) {
    sb.append('[').append(fmt(s.getX(i))).append(", ").append(fmt(s.getY(i))).append(']');
  }

  static void sequence(StringBuilder sb, CoordinateSequence s) {
    sb.append('[');
    for (int i = 0; i < s.size(); i++) {
      if (i > 0) sb.append(", ");
      position(sb, s, i);
    }
    sb.append(']');
  }

  static void polygonCoords(StringBuilder sb, Polygon p) {
    if (p.isEmpty()) { sb.append("[]"); return; }
    sb.append('[');
    sequence(sb, p.getExteriorRing().getCoordinateSequence());
    for (int i = 0; i < p.getNumInteriorRing(); i++) {
      sb.append(", ");
      sequence(sb, p.getInteriorRingN(i).getCoordinateSequence());
    }
    sb.append(']');
  }

  static void pointCoords(StringBuilder sb, Point p) {
    if (p.isEmpty()) sb.append("[]");
    else position(sb, p.getCoordinateSequence(), 0);
  }

  /** Typed JSON of a JTS geometry, coordinates written here (no WKT writer). */
  static String geomJson(Geometry g) {
    StringBuilder sb = new StringBuilder(256);
    writeGeom(sb, g);
    return sb.toString();
  }

  static void writeGeom(StringBuilder sb, Geometry g) {
    String t = g.getGeometryType();
    switch (t) {
      case "Point":
        sb.append("{\"type\": \"Point\", \"coordinates\": ");
        pointCoords(sb, (Point) g);
        break;
      case "LineString":
      case "LinearRing":
        sb.append("{\"type\": \"LineString\", \"coordinates\": ");
        sequence(sb, ((LineString) g).getCoordinateSequence());
        break;
      case "Polygon":
        sb.append("{\"type\": \"Polygon\", \"coordinates\": ");
        polygonCoords(sb, (Polygon) g);
        break;
      case "MultiPoint":
      case "MultiLineString":
      case "MultiPolygon": {
        sb.append("{\"type\": \"").append(t).append("\", \"coordinates\": [");
        for (int i = 0; i < g.getNumGeometries(); i++) {
          if (i > 0) sb.append(", ");
          Geometry e = g.getGeometryN(i);
          if (e instanceof Point) pointCoords(sb, (Point) e);
          else if (e instanceof Polygon) polygonCoords(sb, (Polygon) e);
          else sequence(sb, ((LineString) e).getCoordinateSequence());
        }
        sb.append(']');
        break;
      }
      default: {  // GeometryCollection
        sb.append("{\"type\": \"GeometryCollection\", \"geometries\": [");
        for (int i = 0; i < g.getNumGeometries(); i++) {
          if (i > 0) sb.append(", ");
          writeGeom(sb, g.getGeometryN(i));
        }
        sb.append(']');
      }
    }
    sb.append('}');
  }

  static String quote(String s) {
    StringBuilder sb = new StringBuilder(s.length() + 2);
    writeString(sb, s);
    return sb.toString();
  }

  // ---------------------------------------------------------------- one v2 line

  static String answerV2(String line, Object parsed, Supervisor sup) {
    String idJson = "null";
    if (parsed instanceof Map && ((Map<?, ?>) parsed).get("id") instanceof String) {
      idJson = quote((String) ((Map<?, ?>) parsed).get("id"));
    }
    List<String> paths;
    try {
      if (!(parsed instanceof Map)) throw new IllegalArgumentException("a case must be a JSON object");
      Map<?, ?> c = (Map<?, ?>) parsed;
      if (!c.containsKey("a") || !c.containsKey("b")) throw new IllegalArgumentException("missing \"a\" or \"b\"");
      paths = requested(c);
    } catch (Throwable t) {
      return "{\"id\": " + idJson + ", \"lib\": " + quote(lib) + ", \"errors\": {\"*\": "
          + quote("input parse error: " + describe(t)) + "}}";
    }
    OpResult[] res = new OpResult[paths.size()];
    if (sup == null) {
      Session s = new Session((Map<?, ?>) parsed);
      for (int k = 0; k < res.length; k++) res[k] = s.run(paths.get(k));
    } else {
      sup.runCase(line, paths, res);
    }
    return render(idJson, paths, res);
  }

  static String render(String idJson, List<String> paths, OpResult[] res) {
    Map<String, OpResult> by = new LinkedHashMap<>();
    for (int k = 0; k < res.length; k++) by.put(paths.get(k), res[k]);
    StringBuilder o = new StringBuilder(512);
    o.append("{\"id\": ").append(idJson).append(", \"lib\": ").append(quote(lib));
    if (by.containsKey("relate")) o.append(", \"relate\": ").append(by.get("relate").value);
    if (by.containsKey("predicates.intersects")) {
      o.append(", \"predicates\": {");
      for (int i = 0; i < PREDICATES.length; i++) {
        if (i > 0) o.append(", ");
        o.append('"').append(PREDICATES[i]).append("\": ").append(by.get("predicates." + PREDICATES[i]).value);
      }
      o.append('}');
    }
    if (by.containsKey("valid_a")) {
      o.append(", \"valid_a\": ").append(by.get("valid_a").value);
      o.append(", \"valid_b\": ").append(by.get("valid_b").value);
    }
    if (by.containsKey("overlay.intersection")) {
      o.append(", \"overlay\": {");
      for (int i = 0; i < OVERLAYS.length; i++) {
        if (i > 0) o.append(", ");
        o.append('"').append(OVERLAYS[i]).append("\": ").append(by.get("overlay." + OVERLAYS[i]).value);
      }
      o.append('}');
    }
    if (by.containsKey("echo") && !by.get("echo").value.equals("null")) {
      o.append(", \"echo\": ").append(by.get("echo").value);
    }
    o.append(", \"errors\": {");
    boolean first = true;
    for (Map.Entry<String, OpResult> e : by.entrySet()) {
      if (e.getValue().error == null) continue;
      if (!first) o.append(", ");
      first = false;
      o.append('"').append(e.getKey()).append("\": ").append(e.getValue().error);
    }
    o.append('}');
    if (timing) {
      o.append(", \"elapsed_ms\": {");
      first = true;
      for (Map.Entry<String, OpResult> e : by.entrySet()) {
        if (e.getValue().ms < 0) continue;
        if (!first) o.append(", ");
        first = false;
        o.append('"').append(e.getKey()).append("\": ").append(String.format("%.3f", e.getValue().ms));
      }
      o.append('}');
    }
    return o.append('}').toString();
  }

  // ---------------------------------------------------------------- worker process

  /** Requests on stdin: "<first index>\t<case line>"; for every path from there on one line
   *  "<index>\t<value JSON>\t<error JSON or empty>\t<ms>" on stdout. */
  static void workerLoop() throws IOException {
    BufferedReader in = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
    PrintWriter out = new PrintWriter(new BufferedWriter(
        new OutputStreamWriter(System.out, StandardCharsets.UTF_8)), false);
    String req;
    while ((req = in.readLine()) != null) {
      int tab = req.indexOf('\t');
      if (tab < 0) continue;
      int start = Integer.parseInt(req.substring(0, tab));
      Map<?, ?> c = (Map<?, ?>) new Json(req.substring(tab + 1)).parse();
      List<String> paths = requested(c);
      Session s = new Session(c);
      for (int k = start; k < paths.size(); k++) {
        OpResult r = s.run(paths.get(k));
        out.print(k + "\t" + r.value + "\t" + (r.error == null ? "" : r.error) + "\t" + r.ms + "\n");
        out.flush();
      }
    }
  }

  static final String EOF = "\u0000EOF";

  /** Runs cases in a worker JVM, re-started after a timeout or a crash. */
  static final class Supervisor {
    Process proc;
    BufferedWriter toWorker;
    BlockingQueue<String> lines;
    int restarts = 0;

    void start() throws IOException {
      String java = System.getProperty("java.home") + "/bin/java";
      List<String> cmd = new ArrayList<>();
      cmd.add(java);
      cmd.add("-Xss64m");
      cmd.add("-Xmx" + memMb + "m");
      cmd.add("-XX:+UseSerialGC");
      cmd.add("-cp");
      cmd.add(System.getProperty("java.class.path"));
      cmd.add("JtsAdapter");
      cmd.add("--worker");
      cmd.add("--relate");
      cmd.add(relateV2);
      ProcessBuilder pb = new ProcessBuilder(cmd);
      pb.redirectError(ProcessBuilder.Redirect.INHERIT);
      proc = pb.start();
      toWorker = new BufferedWriter(new OutputStreamWriter(proc.getOutputStream(), StandardCharsets.UTF_8));
      final BlockingQueue<String> q = new LinkedBlockingQueue<>();
      lines = q;
      final BufferedReader r = new BufferedReader(new InputStreamReader(proc.getInputStream(), StandardCharsets.UTF_8));
      Thread t = new Thread(() -> {
        try {
          String l;
          while ((l = r.readLine()) != null) q.add(l);
        } catch (IOException e) { /* the worker died */ }
        q.add(EOF);
      }, "jts-worker-reader");
      t.setDaemon(true);
      t.start();
    }

    String stop(boolean kill) {
      if (proc == null) return "no worker";
      if (kill) proc.destroyForcibly();
      try { toWorker.close(); } catch (IOException e) { /* ignore */ }
      int rc;
      try { rc = proc.waitFor(); } catch (InterruptedException e) { rc = -1; }
      proc = null;
      return rc > 128 ? "worker killed by signal " + (rc - 128) : "worker exited with status " + rc;
    }

    void close() { if (proc != null) stop(false); }

    void runCase(String line, List<String> paths, OpResult[] res) {
      int next = 0;
      int failedStarts = 0;
      while (next < paths.size()) {
        try {
          if (proc == null) start();
          toWorker.write(next + "\t" + line + "\n");
          toWorker.flush();
        } catch (IOException e) {
          stop(true);
          if (++failedStarts > 2) {
            for (int k = next; k < res.length; k++) {
              res[k] = new OpResult();
              res[k].error = "{\"kind\": \"crash\", \"message\": " + quote("worker unusable: " + e) + "}";
            }
            return;
          }
          continue;
        }
        while (next < paths.size()) {
          String msg;
          try {
            msg = lines.poll((long) (opTimeout * 1000), TimeUnit.MILLISECONDS);
          } catch (InterruptedException e) {
            msg = null;
          }
          if (msg == null) {
            stop(true);
            OpResult r = new OpResult();
            r.error = "{\"kind\": \"timeout\", \"message\": " + quote("no result after " + fmtSec(opTimeout) + " s (worker killed)") + "}";
            res[next++] = r;
            break;
          }
          if (msg.equals(EOF)) {
            String how = stop(false);
            OpResult r = new OpResult();
            r.error = "{\"kind\": \"crash\", \"message\": " + quote(how) + "}";
            res[next++] = r;
            break;
          }
          String[] f = msg.split("\t", -1);
          int k = Integer.parseInt(f[0]);
          OpResult r = new OpResult();
          r.value = f[1];
          r.error = f[2].isEmpty() ? null : f[2];
          r.ms = Double.parseDouble(f[3]);
          res[k] = r;
          next = k + 1;
        }
      }
    }
  }

  static String fmtSec(double s) {
    return s == Math.rint(s) ? Long.toString((long) s) : Double.toString(s);
  }

  // ================================================================ legacy contract v1

  static final String[] FIELDS = {
      "valid_a", "valid_b",
      "intersects", "disjoint", "touches", "overlaps", "contains", "covers", "within",
      "covered_by", "equals",
      "area_inter", "area_union", "area_diff", "area_symdiff"};

  static final GeometryFactory GF = new GeometryFactory();

  interface BoolOp { boolean apply(Geometry a, Geometry b); }

  static String lib = "jts@unknown";

  // ---------------------------------------------------------------- timeout handling

  static int abandoned = 0;

  static String runWithTimeout(String line, double timeoutSec) throws Exception {
    if (timeoutSec <= 0) return runCase(line);
    FutureTask<String> task = new FutureTask<>((Callable<String>) () -> runCase(line));
    // Fresh thread per case with a large stack; JTS ignores interrupts, so a timed-out worker
    // is abandoned (daemon, lowest priority) rather than killed.
    Thread th = new Thread(null, task, "jts-case", 256L << 20);
    th.setDaemon(true);
    th.start();
    try {
      return task.get((long) (timeoutSec * 1000), TimeUnit.MILLISECONDS);
    } catch (TimeoutException e) {
      th.setPriority(Thread.MIN_PRIORITY);
      th.interrupt();
      abandoned++;
      String id = idOf(line);
      System.err.println("JtsAdapter: case " + id + " timed out after " + timeoutSec
          + " s (abandoned worker threads: " + abandoned + ")");
      return allNull(id, "timeout", "timed out after " + timeoutSec + " s");
    } catch (ExecutionException e) {
      throw new RuntimeException(e.getCause());
    }
  }

  static String idOf(String line) {
    try {
      Object o = new Json(line).parse();
      if (o instanceof Map) {
        Object id = ((Map<?, ?>) o).get("id");
        if (id instanceof String) return (String) id;
      }
    } catch (Throwable t) { /* fall through */ }
    return null;
  }

  static String allNull(String id, String errKey, String msg) {
    Map<String, Object> res = new LinkedHashMap<>();
    res.put("id", id);
    res.put("lib", lib);
    for (String f : FIELDS) res.put(f, null);
    Map<String, Object> errors = new LinkedHashMap<>();
    errors.put(errKey, msg);
    res.put("errors", errors);
    return toJson(res);
  }

  // ---------------------------------------------------------------- per-case work

  static String runCase(String line) {
    @SuppressWarnings("unchecked")
    Map<String, Object> c = (Map<String, Object>) new Json(line).parse();
    String id = (String) c.get("id");
    Map<String, Object> res = new LinkedHashMap<>();
    Map<String, String> errors = new LinkedHashMap<>();
    res.put("id", id);
    res.put("lib", lib);
    for (String f : FIELDS) res.put(f, null);

    Geometry a = null, b = null;
    String buildErr = null;
    try {
      a = build(c.get("a"));
    } catch (Throwable t) {
      buildErr = "building A: " + describe(t);
    }
    try {
      b = build(c.get("b"));
    } catch (Throwable t) {
      buildErr = (buildErr == null ? "" : buildErr + "; ") + "building B: " + describe(t);
    }
    if (a == null || b == null) {
      // JTS refuses to construct the geometry (e.g. an unclosed ring or a ring with 1-2 points).
      for (String f : FIELDS) {
        boolean mine = (f.equals("valid_a") && a == null) || (f.equals("valid_b") && b == null)
            || (!f.startsWith("valid_"));
        if (mine) errors.put(f, buildErr);
      }
      if (a != null) validity(res, errors, "valid_a", a);
      if (b != null) validity(res, errors, "valid_b", b);
      res.put("errors", errors);
      return toJson(res);
    }

    validity(res, errors, "valid_a", a);
    validity(res, errors, "valid_b", b);

    pred(res, errors, a, b, "intersects", Geometry::intersects);
    pred(res, errors, a, b, "disjoint", Geometry::disjoint);
    pred(res, errors, a, b, "touches", Geometry::touches);
    pred(res, errors, a, b, "overlaps", Geometry::overlaps);
    pred(res, errors, a, b, "contains", Geometry::contains);
    pred(res, errors, a, b, "covers", Geometry::covers);
    pred(res, errors, a, b, "within", Geometry::within);
    pred(res, errors, a, b, "covered_by", Geometry::coveredBy);
    pred(res, errors, a, b, "equals", Geometry::equalsTopo);

    area(res, errors, a, b, "area_inter", OverlayNG.INTERSECTION);
    area(res, errors, a, b, "area_union", OverlayNG.UNION);
    area(res, errors, a, b, "area_diff", OverlayNG.DIFFERENCE);
    area(res, errors, a, b, "area_symdiff", OverlayNG.SYMDIFFERENCE);

    res.put("errors", errors);
    return toJson(res);
  }

  static void validity(Map<String, Object> res, Map<String, String> errors, String key, Geometry g) {
    try {
      res.put(key, new IsValidOp(g).isValid());
    } catch (Throwable t) {
      res.put(key, null);
      errors.put(key, describe(t));
    }
  }

  static void pred(Map<String, Object> res, Map<String, String> errors, Geometry a, Geometry b,
      String key, BoolOp op) {
    try {
      res.put(key, op.apply(a, b));
    } catch (Throwable t) {
      res.put(key, null);
      errors.put(key, describe(t));
    }
  }

  static void area(Map<String, Object> res, Map<String, String> errors, Geometry a, Geometry b,
      String key, int opCode) {
    try {
      double v = OverlayNGRobust.overlay(a, b, opCode).getArea();
      if (Double.isFinite(v)) {
        res.put(key, v);
      } else {
        res.put(key, null);
        errors.put(key, "non-finite area: " + v);
      }
    } catch (Throwable t) {
      res.put(key, null);
      errors.put(key, describe(t));
    }
  }

  static String describe(Throwable t) {
    String m = t.getMessage();
    return t.getClass().getSimpleName() + (m == null ? "" : ": " + m);
  }

  // ---------------------------------------------------------------- geometry construction

  static Geometry build(Object mp) {
    List<?> parts = (List<?>) mp;
    Polygon[] polys = new Polygon[parts.size()];
    for (int i = 0; i < polys.length; i++) polys[i] = polygon((List<?>) parts.get(i));
    if (polys.length == 1) return polys[0];
    return GF.createMultiPolygon(polys);
  }

  static Polygon polygon(List<?> rings) {
    if (rings.isEmpty()) return GF.createPolygon();
    LinearRing shell = ring((List<?>) rings.get(0));
    LinearRing[] holes = new LinearRing[rings.size() - 1];
    for (int i = 1; i < rings.size(); i++) holes[i - 1] = ring((List<?>) rings.get(i));
    return GF.createPolygon(shell, holes);
  }

  static LinearRing ring(List<?> pts) {
    Coordinate[] cs = new Coordinate[pts.size()];
    for (int i = 0; i < cs.length; i++) {
      List<?> p = (List<?>) pts.get(i);
      cs[i] = new Coordinate(num(p.get(0)), num(p.get(1)));
    }
    return GF.createLinearRing(cs);
  }

  static double num(Object o) {
    return Double.parseDouble(((Json.Num) o).text);
  }

  // ---------------------------------------------------------------- JSON output

  static String toJson(Map<String, ?> m) {
    StringBuilder sb = new StringBuilder(512);
    writeJson(sb, m);
    return sb.toString();
  }

  static void writeJson(StringBuilder sb, Object v) {
    if (v == null) {
      sb.append("null");
    } else if (v instanceof Boolean) {
      sb.append(((Boolean) v) ? "true" : "false");
    } else if (v instanceof Double) {
      // Double.toString is the shortest round-tripping decimal (JDK >= 19), and its
      // "1.0E-10" form is valid JSON.
      sb.append(Double.toString((Double) v));
    } else if (v instanceof String) {
      writeString(sb, (String) v);
    } else if (v instanceof Map) {
      sb.append('{');
      boolean first = true;
      for (Map.Entry<?, ?> e : ((Map<?, ?>) v).entrySet()) {
        if (!first) sb.append(", ");
        first = false;
        writeString(sb, (String) e.getKey());
        sb.append(": ");
        writeJson(sb, e.getValue());
      }
      sb.append('}');
    } else {
      throw new IllegalArgumentException("cannot serialise " + v.getClass());
    }
  }

  static void writeString(StringBuilder sb, String s) {
    sb.append('"');
    for (int i = 0; i < s.length(); i++) {
      char ch = s.charAt(i);
      switch (ch) {
        case '"': sb.append("\\\""); break;
        case '\\': sb.append("\\\\"); break;
        case '\n': sb.append("\\n"); break;
        case '\r': sb.append("\\r"); break;
        case '\t': sb.append("\\t"); break;
        default:
          if (ch < 0x20 || ch > 0x7e) sb.append(String.format("\\u%04x", (int) ch));
          else sb.append(ch);
      }
    }
    sb.append('"');
  }

  // ---------------------------------------------------------------- tiny JSON reader
  // Objects -> LinkedHashMap, arrays -> ArrayList, strings -> String, true/false -> Boolean,
  // null -> null, numbers -> Json.Num (raw text, so coordinates are parsed once, exactly).

  static final class Json {
    static final class Num {
      final String text;
      Num(String text) { this.text = text; }
    }

    private final String s;
    private int i = 0;

    Json(String s) { this.s = s; }

    Object parse() {
      Object v = value();
      ws();
      if (i != s.length()) throw err("trailing characters");
      return v;
    }

    private RuntimeException err(String msg) {
      return new IllegalArgumentException("JSON parse error at offset " + i + ": " + msg);
    }

    private void ws() {
      while (i < s.length()) {
        char c = s.charAt(i);
        if (c == ' ' || c == '\t' || c == '\n' || c == '\r') i++;
        else break;
      }
    }

    private Object value() {
      ws();
      if (i >= s.length()) throw err("unexpected end");
      char c = s.charAt(i);
      switch (c) {
        case '{': return object();
        case '[': return array();
        case '"': return string();
        case 't': lit("true"); return Boolean.TRUE;
        case 'f': lit("false"); return Boolean.FALSE;
        case 'n': lit("null"); return null;
        case 'N': lit("NaN"); return new Num("NaN");
        case 'I': lit("Infinity"); return new Num("Infinity");
        default:
          if (c == '-' || (c >= '0' && c <= '9')) return number();
          throw err("unexpected character '" + c + "'");
      }
    }

    private void lit(String w) {
      if (!s.startsWith(w, i)) throw err("expected " + w);
      i += w.length();
    }

    private Map<String, Object> object() {
      Map<String, Object> m = new LinkedHashMap<>();
      i++; // {
      ws();
      if (i < s.length() && s.charAt(i) == '}') { i++; return m; }
      while (true) {
        ws();
        if (i >= s.length() || s.charAt(i) != '"') throw err("expected key");
        String k = string();
        ws();
        if (i >= s.length() || s.charAt(i) != ':') throw err("expected ':'");
        i++;
        m.put(k, value());
        ws();
        if (i >= s.length()) throw err("unterminated object");
        char c = s.charAt(i++);
        if (c == '}') return m;
        if (c != ',') throw err("expected ',' or '}'");
      }
    }

    private List<Object> array() {
      List<Object> a = new ArrayList<>();
      i++; // [
      ws();
      if (i < s.length() && s.charAt(i) == ']') { i++; return a; }
      while (true) {
        a.add(value());
        ws();
        if (i >= s.length()) throw err("unterminated array");
        char c = s.charAt(i++);
        if (c == ']') return a;
        if (c != ',') throw err("expected ',' or ']'");
      }
    }

    private String string() {
      StringBuilder sb = new StringBuilder();
      i++; // opening quote
      while (true) {
        if (i >= s.length()) throw err("unterminated string");
        char c = s.charAt(i++);
        if (c == '"') return sb.toString();
        if (c != '\\') { sb.append(c); continue; }
        if (i >= s.length()) throw err("bad escape");
        char e = s.charAt(i++);
        switch (e) {
          case '"': sb.append('"'); break;
          case '\\': sb.append('\\'); break;
          case '/': sb.append('/'); break;
          case 'b': sb.append('\b'); break;
          case 'f': sb.append('\f'); break;
          case 'n': sb.append('\n'); break;
          case 'r': sb.append('\r'); break;
          case 't': sb.append('\t'); break;
          case 'u':
            if (i + 4 > s.length()) throw err("bad \\u escape");
            sb.append((char) Integer.parseInt(s.substring(i, i + 4), 16));
            i += 4;
            break;
          default: throw err("bad escape \\" + e);
        }
      }
    }

    private Num number() {
      int start = i;
      if (s.charAt(i) == '-') {
        i++;
        if (s.startsWith("Infinity", i)) { i += 8; return new Num("-Infinity"); }
      }
      while (i < s.length()) {
        char c = s.charAt(i);
        if ((c >= '0' && c <= '9') || c == '.' || c == 'e' || c == 'E' || c == '+' || c == '-') i++;
        else break;
      }
      String t = s.substring(start, i);
      if (t.equals("-")) throw err("bad number");
      return new Num(t);
    }
  }
}
