// JTS master regression: OverlayNGRobust returns POLYGON EMPTY (no exception) for valid
// inputs with coordinates above about 1.3e162 (for these inputs), because KdTree compares squared distances
// and the square of the snapping tolerance overflows to Infinity (since #1114, 4668803).
//
// Public API only (OverlayNGRobust, KdTree, Geometry.union with -Djts.overlay=ng).
//
//   javac -cp jts-core.jar -d out Repro.java
//   java -cp jts-core.jar:out Repro
//   java -Djts.overlay=ng -cp jts-core.jar:out Repro     (also runs Geometry.union through OverlayNG)
import org.locationtech.jts.JTSVersion;
import org.locationtech.jts.geom.Coordinate;
import org.locationtech.jts.geom.Geometry;
import org.locationtech.jts.geom.GeometryCollection;
import org.locationtech.jts.geom.LineString;
import org.locationtech.jts.geom.MultiLineString;
import org.locationtech.jts.geom.MultiPoint;
import org.locationtech.jts.geom.MultiPolygon;
import org.locationtech.jts.geom.Point;
import org.locationtech.jts.geom.Polygon;
import org.locationtech.jts.index.kdtree.KdTree;
import org.locationtech.jts.io.WKTReader;
import org.locationtech.jts.operation.overlayng.OverlayNG;
import org.locationtech.jts.operation.overlayng.OverlayNGRobust;

public class Repro {
  static final WKTReader READER = new WKTReader();
  static int failures = 0;

  // WKT with Double.toString ordinates (WKTWriter prints 1e170 with 171 digits)
  static String seq(Coordinate[] cs) {
    StringBuilder sb = new StringBuilder("(");
    for (int i = 0; i < cs.length; i++) {
      if (i > 0) sb.append(", ");
      sb.append(cs[i].x).append(' ').append(cs[i].y);
    }
    return sb.append(')').toString();
  }
  static String body(Geometry g) {
    if (g.isEmpty()) return "EMPTY";
    if (g instanceof Point || g instanceof LineString) return seq(g.getCoordinates());
    if (g instanceof Polygon) {
      Polygon p = (Polygon) g;
      StringBuilder sb = new StringBuilder("(" + seq(p.getExteriorRing().getCoordinates()));
      for (int i = 0; i < p.getNumInteriorRing(); i++) sb.append(", ").append(seq(p.getInteriorRingN(i).getCoordinates()));
      return sb.append(')').toString();
    }
    boolean typed = !(g instanceof MultiPoint || g instanceof MultiLineString || g instanceof MultiPolygon);
    StringBuilder sb = new StringBuilder("(");
    for (int i = 0; i < g.getNumGeometries(); i++) {
      if (i > 0) sb.append(", ");
      sb.append(typed ? wkt(g.getGeometryN(i)) : body(g.getGeometryN(i)));
    }
    return sb.append(')').toString();
  }
  static String wkt(Geometry g) { return g.getGeometryType().toUpperCase() + " " + body(g); }

  static Geometry read(String wkt) throws Exception { return READER.read(wkt); }

  // per-ordinate comparison (on master, equalsExact(g, tol) itself overflows: it uses
  // Coordinate.distance, which no longer uses Math.hypot since #1112)
  static boolean closeTo(Geometry x, Geometry y, double tol) {
    if (x.getNumGeometries() != y.getNumGeometries()) return false;
    for (int i = 0; i < x.getNumGeometries(); i++)
      if (!x.getGeometryN(i).getGeometryType().equals(y.getGeometryN(i).getGeometryType())) return false;
    Coordinate[] cx = x.getCoordinates(), cy = y.getCoordinates();
    if (cx.length != cy.length) return false;
    for (int i = 0; i < cx.length; i++)
      if (!(Math.abs(cx[i].x - cy[i].x) <= tol && Math.abs(cx[i].y - cy[i].y) <= tol)) return false;
    return true;
  }

  static void check(String label, Geometry actual, Geometry expected) {
    // exact comparison after normalization (equalsTopo does not accept GeometryCollections)
    Geometry na = actual.copy(), ne = expected.copy();
    na.normalize();
    ne.normalize();
    boolean exact = na.equalsExact(ne);
    // OverlayNGRobust's last fallback (snap-rounding) may move vertices by a relative ~1e-13
    org.locationtech.jts.geom.Envelope env = expected.getEnvelopeInternal();
    double mag = Math.max(Math.max(Math.abs(env.getMinX()), Math.abs(env.getMaxX())),
                          Math.max(Math.abs(env.getMinY()), Math.abs(env.getMaxY())));
    boolean rounded = !exact && closeTo(na, ne, 1e-9 * mag);
    if (!exact && !rounded) failures++;
    System.out.println("  " + label);
    System.out.println("    actual:   " + wkt(actual));
    System.out.println("    expected: " + wkt(expected)
        + (exact ? "   OK" : rounded ? "   OK up to rounding (snap-rounding fallback)" : "   WRONG"));
  }

  static void overlayCase(String title, String wa, String wb, int op, String opName, String wExpected) throws Exception {
    Geometry a = read(wa), b = read(wb), expected = read(wExpected);
    System.out.println(title);
    System.out.println("  A = " + wa);
    System.out.println("  B = " + wb);
    Geometry actual;
    try {
      actual = OverlayNGRobust.overlay(a, b, op);
    } catch (RuntimeException e) {
      failures++;
      System.out.println("  OverlayNGRobust.overlay(A, B, " + opName + ") threw " + e);
      return;
    }
    check("OverlayNGRobust.overlay(A, B, " + opName + ")", actual, expected);
  }

  public static void main(String[] args) throws Exception {
    System.out.println("JTS " + JTSVersion.CURRENT_VERSION + ", jts.overlay=" + System.getProperty("jts.overlay"));
    String t170 = "POLYGON ((0 0, 2e170 1e170, 1e170 2e170, 0 0))";
    String t1 = "POLYGON ((0 0, 2 1, 1 2, 0 0))";

    System.out.println("\n1. A triangle overlaid with itself (A union A = A intersection A = A)");
    overlayCase("  1a. unit scale (control)", t1, t1, OverlayNG.UNION, "UNION", t1);
    overlayCase("  1b. coordinates ~1e170", t170, t170, OverlayNG.UNION, "UNION", t170);
    overlayCase("  1c. coordinates ~1e170", t170, t170, OverlayNG.INTERSECTION, "INTERSECTION", t170);

    System.out.println("\n2. The triangle and a disjoint line (no segment intersections to compute)");
    String l170 = "LINESTRING (3e170 0, 4e170 0)";
    overlayCase("  2a. union", t170, l170, OverlayNG.UNION, "UNION", "GEOMETRYCOLLECTION (" + t170 + ", " + l170 + ")");
    overlayCase("  2b. difference", t170, l170, OverlayNG.DIFFERENCE, "DIFFERENCE", t170);
    overlayCase("  2c. symdifference", t170, l170, OverlayNG.SYMDIFFERENCE, "SYMDIFFERENCE", "GEOMETRYCOLLECTION (" + t170 + ", " + l170 + ")");

    System.out.println("\n3. The corpus case line-polygon-1-000090-along-edge-full.ba.int.extreme (coordinates ~3.8e220)");
    String ca = "POLYGON ((-3.6403423436814706e220 3.8270972661136905e220, -3.6403407277677217e220 3.8270908024586947e220, -3.6403391118539727e220 3.8270956501999416e220, -3.6403423436814706e220 3.8270972661136905e220))";
    String cb = "MULTILINESTRING ((-3.6403407277677217e220 3.8270908024586947e220, -3.6403391118539727e220 3.8270956501999416e220), (-3.640325645906065e220 3.8271075002341006e220, -3.640324568630232e220 3.8271091161478495e220))";
    overlayCase("  3a. union", ca, cb, OverlayNG.UNION, "UNION",
        "GEOMETRYCOLLECTION (" + ca + ", LINESTRING (-3.640325645906065e220 3.8271075002341006e220, -3.640324568630232e220 3.8271091161478495e220))");

    if ("ng".equals(System.getProperty("jts.overlay"))) {
      System.out.println("\n4. Geometry.union with -Djts.overlay=ng (goes through OverlayNGRobust)");
      Geometry t = read(t170);
      check("A.union(A), A = " + t170, t.union(t), t);
    }

    System.out.println("\n5. KdTree directly (the first case is the cause; the second predates #1114, see the report)");
    KdTree big = new KdTree(1e155);
    big.insert(new Coordinate(0, 0));
    big.insert(new Coordinate(1e300, 0));
    System.out.println("  new KdTree(1e155); insert (0 0), (1e300 0): size = " + big.size() + " (expected 2: the points are 1e300 apart)"
        + (big.size() == 2 ? "   OK" : "   WRONG"));
    if (big.size() != 2) failures++;
    // Tolerance 0 at the tiny end: not from #1114. The comparison has underflowed like this on
    // master since #1112 (MathUtil.hypot), and in 1.19.0 and earlier; only 1.20.0 keeps the points apart.
    KdTree zero = new KdTree(0.0);
    zero.insert(new Coordinate(0, 0));
    zero.insert(new Coordinate(1e-170, 0));
    System.out.println("  new KdTree(0.0); insert (0 0), (1e-170 0): size = " + zero.size() + " (expected 2: distinct points, tolerance 0)"
        + (zero.size() == 2 ? "   OK" : "   WRONG"));
    if (zero.size() != 2) failures++;

    System.out.println("\n" + (failures == 0 ? "all results correct" : failures + " wrong results"));
  }
}
