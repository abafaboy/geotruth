// JTS (locationtech/jts, jts-core) adapter for the geometry bug hunt.
// Contract: ../../FORMAT.md.  Usage (via run.sh):  JtsAdapter [options] CASES.jsonl > RESULTS.jsonl
//
// Options:
//   --lib STRING       value of the "lib" field (run.sh passes jts@<version>-<short commit>)
//   --relate ng|old    predicate engine: "old" = RelateOp (JTS default), "ng" = RelateNG.
//                      With "ng" the lib string gets a "+relateng" suffix.
//   --timeout SECONDS  per-case wall-clock budget (default 10, 0 = none); on timeout every
//                      field is null and errors.timeout is set.
//
// Geometry: a one-part multipolygon becomes a Polygon, otherwise a MultiPolygon, built with the
// default GeometryFactory (floating PrecisionModel, coordinates exactly as parsed by
// Double.parseDouble, which is correctly rounded).
// valid_a/valid_b: IsValidOp.  Predicates: Geometry.intersects/disjoint/touches/overlaps/contains/
// covers/within/coveredBy/equalsTopo.  Areas: OverlayNGRobust.overlay(a, b, op).getArea().

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.FileInputStream;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Callable;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.FutureTask;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

import org.locationtech.jts.geom.Coordinate;
import org.locationtech.jts.geom.Geometry;
import org.locationtech.jts.geom.GeometryFactory;
import org.locationtech.jts.geom.LinearRing;
import org.locationtech.jts.geom.Polygon;
import org.locationtech.jts.operation.overlayng.OverlayNG;
import org.locationtech.jts.operation.overlayng.OverlayNGRobust;
import org.locationtech.jts.operation.valid.IsValidOp;

public class JtsAdapter {

  static final String[] FIELDS = {
      "valid_a", "valid_b",
      "intersects", "disjoint", "touches", "overlaps", "contains", "covers", "within",
      "covered_by", "equals",
      "area_inter", "area_union", "area_diff", "area_symdiff"};

  static final GeometryFactory GF = new GeometryFactory();

  interface BoolOp { boolean apply(Geometry a, Geometry b); }

  static String lib = "jts@unknown";

  public static void main(String[] args) throws Exception {
    String path = null;
    String relate = "old";
    double timeoutSec = 10.0;
    for (int i = 0; i < args.length; i++) {
      switch (args[i]) {
        case "--lib": lib = args[++i]; break;
        case "--relate": relate = args[++i]; break;
        case "--timeout": timeoutSec = Double.parseDouble(args[++i]); break;
        default:
          if (path != null) usage("unexpected argument " + args[i]);
          path = args[i];
      }
    }
    if (path == null) usage("missing CASES.jsonl");
    if (!relate.equals("old") && !relate.equals("ng")) usage("--relate must be old or ng");
    // Must be set before org.locationtech.jts.geom.GeometryRelate is initialised.
    System.setProperty("jts.relate", relate);
    if (relate.equals("ng")) lib = lib + "+relateng";

    PrintWriter out = new PrintWriter(new BufferedWriter(
        new OutputStreamWriter(System.out, StandardCharsets.UTF_8)), false);
    try (BufferedReader in = new BufferedReader(
        new InputStreamReader(new FileInputStream(path), StandardCharsets.UTF_8))) {
      String line;
      int lineNo = 0;
      while ((line = in.readLine()) != null) {
        lineNo++;
        if (line.trim().isEmpty()) continue;
        String result;
        try {
          result = runWithTimeout(line, timeoutSec);
        } catch (Throwable t) {
          // Should not happen (runCase catches per operation); keep the one-line-per-case promise.
          result = allNull(idOf(line), "adapter", describe(t));
        }
        out.println(result);
        out.flush();
      }
    }
  }

  static void usage(String msg) {
    System.err.println("JtsAdapter: " + msg);
    System.err.println("usage: JtsAdapter [--lib S] [--relate old|ng] [--timeout SEC] CASES.jsonl");
    System.exit(2);
  }

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
