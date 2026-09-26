package org.locationtech.jts.operation.overlayng;
import org.locationtech.jts.geom.*;
import org.locationtech.jts.io.WKTReader;
import org.locationtech.jts.noding.snap.SnappingNoder;
/**
 * Diagnostic, not a repro: replays OverlayNGRobust.overlay(A, B, UNION)'s fallback chain step
 * by step (snapping tries with tolerance magnitude/1e12 * 10^i, snapSelf of each operand, then
 * snap-rounding). It is in package org.locationtech.jts.operation.overlayng only to call the
 * package-private OverlayNG(Geometry, PrecisionModel) constructor, as OverlayNGRobust.snapSelf does.
 *
 *   javac -cp jts-core.jar -d out DiagFallback.java
 *   java -cp jts-core.jar:out org.locationtech.jts.operation.overlayng.DiagFallback "WKT A" "WKT B"
 */
public class DiagFallback {
  // WKT with Double.toString ordinates
  static String seq(Coordinate[] cs) {
    StringBuilder sb = new StringBuilder("(");
    for (int i = 0; i < cs.length; i++) { if (i > 0) sb.append(", "); sb.append(cs[i].x).append(' ').append(cs[i].y); }
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
    for (int i = 0; i < g.getNumGeometries(); i++) { if (i > 0) sb.append(", "); sb.append(typed ? w(g.getGeometryN(i)) : body(g.getGeometryN(i))); }
    return sb.append(')').toString();
  }
  static String w(Geometry g) { return g.getGeometryType().toUpperCase() + " " + body(g); }
  static String s(Geometry g) { return w(g) + " area=" + g.getArea(); }
  static Geometry snapSelf(Geometry geom, double snapTol) {
    OverlayNG ov = new OverlayNG(geom, null); ov.setNoder(new SnappingNoder(snapTol)); ov.setStrictMode(true); return ov.getResult();
  }
  public static void main(String[] args) throws Exception {
    WKTReader r = new WKTReader();
    Geometry a = r.read(args[0]), b = r.read(args[1]);
    int op = OverlayNG.UNION;
    Envelope env = a.getEnvelopeInternal(); env.expandToInclude(b.getEnvelopeInternal());
    double mag = Math.max(Math.max(Math.abs(env.getMinX()), Math.abs(env.getMaxX())), Math.max(Math.abs(env.getMinY()), Math.abs(env.getMaxY())));
    double tol = mag / 1e12;
    System.out.println("area(A)=" + a.getArea());
    for (int i = 0; i < 5; i++, tol *= 10) {
      try { System.out.println("try " + i + " snapping: " + s(OverlayNG.overlay(a, b, op, new SnappingNoder(tol)))); break; }
      catch (TopologyException e) { System.out.println("try " + i + " snapping: " + e.getMessage()); }
      try {
        Geometry sa = snapSelf(a, tol), sb = snapSelf(b, tol);
        System.out.println("try " + i + " snapSelf(A) = " + s(sa) + "\n       snapSelf(B) = " + w(sb));
        System.out.println("try " + i + " snapBoth: " + s(OverlayNG.overlay(sa, sb, op, new SnappingNoder(tol)))); break;
      } catch (TopologyException e) { System.out.println("try " + i + " snapBoth: " + e.getMessage()); }
    }
    double scale = PrecisionUtil.safeScale(a, b);
    System.out.println("SR scale " + scale + ": " + s(OverlayNG.overlay(a, b, op, new PrecisionModel(scale))));
  }
}
