// JTS counterpart of repro.c: the same shapes at unit scale (control) and at 1e-200.
// Public JTS API only.
//   javac -cp jts-core.jar Repro.java && java -cp jts-core.jar:. Repro
import org.locationtech.jts.geom.Geometry;
import org.locationtech.jts.geom.prep.PreparedGeometry;
import org.locationtech.jts.geom.prep.PreparedGeometryFactory;
import org.locationtech.jts.io.WKTReader;
import org.locationtech.jts.operation.overlayng.OverlayNG;
import org.locationtech.jts.operation.overlayng.OverlayNGRobust;
import org.locationtech.jts.operation.relateng.RelateNG;
import org.locationtech.jts.operation.valid.IsValidOp;
import org.locationtech.jts.JTSVersion;

public class Repro {
  static int nbad = 0;
  static WKTReader rdr = new WKTReader();

  static Geometry rd(String tmpl, String unit) throws Exception {
    return rdr.read(tmpl.replace("S", unit));
  }

  interface Call { Object get() throws Exception; }

  static void check(String what, Call c, Object expected) {
    String got;
    try {
      Object o = c.get();
      got = String.valueOf(o);
    } catch (Throwable t) {
      got = "EXCEPTION " + t.getClass().getSimpleName() + ": " + t.getMessage();
    }
    boolean ok = got.equals(String.valueOf(expected));
    if (!ok) nbad++;
    System.out.printf("  %-34s %s (expected %s)%s%n", what, got, expected, ok ? "" : "  <-- WRONG");
  }

  // WKT with full double precision (JTS's default WKTWriter prints 1e-200 as 0).
  static String num(double d) {
    String s = Double.toString(d);
    if (s.endsWith(".0")) s = s.substring(0, s.length() - 2);
    return s.replace(".0E", "E").replace("E", "e");
  }

  static String ring(org.locationtech.jts.geom.LineString r) {
    StringBuilder sb = new StringBuilder("(");
    for (int i = 0; i < r.getNumPoints(); i++) {
      if (i > 0) sb.append(", ");
      sb.append(num(r.getCoordinateN(i).x)).append(' ').append(num(r.getCoordinateN(i).y));
    }
    return sb.append(')').toString();
  }

  static String txt(Geometry g) {
    if (g instanceof org.locationtech.jts.geom.Point)
      return "POINT (" + num(g.getCoordinate().x) + " " + num(g.getCoordinate().y) + ")";
    if (g instanceof org.locationtech.jts.geom.Polygon) {
      org.locationtech.jts.geom.Polygon p = (org.locationtech.jts.geom.Polygon) g;
      StringBuilder sb = new StringBuilder("POLYGON (").append(ring(p.getExteriorRing()));
      for (int i = 0; i < p.getNumInteriorRing(); i++) sb.append(", ").append(ring(p.getInteriorRingN(i)));
      return sb.append(')').toString();
    }
    return g.toText();
  }

  static String norm(Geometry g) {
    Geometry c = g.copy();
    c.normalize();
    return txt(c);
  }

  static void run(String unit) throws Exception {
    System.out.println("===== unit S = \"" + unit + "\" =====");
    Geometry t = rd("POLYGON ((0 0, 1S 0, 0 1S, 0 0))", unit);
    System.out.println("T = " + txt(t));
    check("IsValidOp(T).isValid()", () -> new IsValidOp(t).isValid(), true);
    check("IsValidOp(T).getValidationError()", () -> new IsValidOp(t).getValidationError(), null);

    Geometry h = rd("POLYGON ((0 0, 4S 0, 4S 4S, 0 4S, 0 0), (1S 1S, 1S 2S, 2S 2S, 2S 1S, 1S 1S))", unit);
    System.out.println("H = " + txt(h));
    check("IsValidOp(H).isValid()", () -> new IsValidOp(h).isValid(), true);

    Geometry a = rd("POLYGON ((0 0, 2S 0, 2S 2S, 0 2S, 0 0))", unit);
    Geometry p = rd("POINT (1S 1S)", unit);
    System.out.println("A = " + txt(a) + "\nP = " + txt(p) + "  (the centre of A)");
    check("A.contains(P)", () -> a.contains(p), true);
    check("A.relate(P)  [RelateOp]", () -> a.relate(p).toString(), "0F2FF1FF2");
    check("RelateNG.relate(A, P)", () -> RelateNG.relate(a, p).toString(), "0F2FF1FF2");

    Geometry b = rd("POLYGON ((1S 1S, 3S 1S, 3S 3S, 1S 3S, 1S 1S))", unit);
    System.out.println("B = " + txt(b));
    check("A.relate(B)  [RelateOp]", () -> a.relate(b).toString(), "212101212");
    check("RelateNG.relate(A, B)", () -> RelateNG.relate(a, b).toString(), "212101212");
    check("A.overlaps(B)  [RelateOp]", () -> a.overlaps(b), true);
    check("A.touches(B)  [RelateOp]", () -> a.touches(b), false);
    PreparedGeometry pa = PreparedGeometryFactory.prepare(a);
    check("prepared A.overlaps(B)", () -> pa.overlaps(b), true);
    check("OverlayNGRobust intersection", () -> norm(OverlayNGRobust.overlay(a, b, OverlayNG.INTERSECTION)),
        txt(rd("POLYGON ((1S 1S, 1S 2S, 2S 2S, 2S 1S, 1S 1S))", unit)));
    check("OverlayNGRobust union", () -> norm(OverlayNGRobust.overlay(a, b, OverlayNG.UNION)),
        txt(rd("POLYGON ((0 0, 0 2S, 1S 2S, 1S 3S, 3S 3S, 3S 1S, 2S 1S, 2S 0, 0 0))", unit)));
    System.out.println();
  }

  public static void main(String[] args) throws Exception {
    System.out.println("JTS " + JTSVersion.CURRENT_VERSION);
    System.out.println();
    run("");
    run("e-200");
    System.out.println(nbad + " wrong result(s)");
  }
}
