import org.locationtech.jts.algorithm.*;
import org.locationtech.jts.geom.*;
import org.locationtech.jts.io.WKTReader;
import org.locationtech.jts.operation.overlayng.*;
import org.locationtech.jts.operation.relateng.RelateNG;

public class ExtremeScale {
  public static void main(String[] args) throws Exception {
    WKTReader r = new WKTReader();
    for (String e : new String[] {"e102", "e103", "e105", "e-104"}) {
      String S = "1" + e, S2 = "2" + e, S3 = "3" + e;
      Geometry a = r.read("POLYGON ((0 0, " + S2 + " 0, " + S2 + " " + S2 + ", 0 " + S2 + ", 0 0))");
      Geometry b = r.read("POLYGON ((" + S + " " + S + ", " + S3 + " " + S + ", " + S3 + " " + S3 + ", " + S + " " + S3 + ", " + S + " " + S + "))");
      double s = Double.parseDouble(S);
      Geometry inter = OverlayNGRobust.overlay(a, b, OverlayNG.INTERSECTION).copy();
      inter.apply((CoordinateFilter) c -> { c.x /= s; c.y /= s; });   // print in units of S
      String relOp;
      try { relOp = a.relate(b).toString(); } catch (Exception ex) { relOp = ex.getClass().getSimpleName() + " " + ex.getMessage(); }
      RobustLineIntersector li = new RobustLineIntersector();
      li.computeIntersection(new Coordinate(0, 0), new Coordinate(4 * s, 2 * s), new Coordinate(0, 2 * s), new Coordinate(4 * s, 0));
      Coordinate p = li.getIntersection(0);
      System.out.println("S = " + S + ": RelateNG " + RelateNG.relate(a, b) + ", Geometry.relate " + relOp
          + ", intersection/S " + inter + ", crossing/S (" + p.x / s + " " + p.y / s + ")");
    }
    System.out.println("Orientation.index((0 0),(S 0),(0 S)), S = 1e-200: "
        + Orientation.index(new Coordinate(0, 0), new Coordinate(1e-200, 0), new Coordinate(0, 1e-200)));
  }
}
