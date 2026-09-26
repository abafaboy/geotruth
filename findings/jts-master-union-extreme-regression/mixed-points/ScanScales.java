// mixed-points: scale two inputs by exact powers of two (2^k, which cannot change the correct answer) and
// compare OverlayNGRobust's union with the unit-scale result scaled by the same factor.
// Public API only.
//
//   javac -cp jts-core.jar -d out ScanScales.java && java -cp jts-core.jar:out ScanScales
import org.locationtech.jts.JTSVersion;
import org.locationtech.jts.geom.CoordinateSequence;
import org.locationtech.jts.geom.CoordinateSequenceFilter;
import org.locationtech.jts.geom.Geometry;
import org.locationtech.jts.io.WKTReader;
import org.locationtech.jts.operation.overlayng.OverlayNG;
import org.locationtech.jts.operation.overlayng.OverlayNGRobust;

public class ScanScales {
  static Geometry scale(Geometry g, final int k) {
    Geometry c = g.copy();
    c.apply(new CoordinateSequenceFilter() {
      public void filter(CoordinateSequence seq, int i) {
        seq.setOrdinate(i, 0, Math.scalb(seq.getOrdinate(i, 0), k));
        seq.setOrdinate(i, 1, Math.scalb(seq.getOrdinate(i, 1), k));
      }
      public boolean isDone() { return false; }
      public boolean isGeometryChanged() { return true; }
    });
    return c;
  }

  static void scan(String title, String wa, String wb, int op, int lo, int hi) throws Exception {
    WKTReader r = new WKTReader();
    Geometry a0 = r.read(wa), b0 = r.read(wb);
    Geometry ref = OverlayNGRobust.overlay(a0, b0, op);
    ref.normalize();
    System.out.println(title);
    String prev = null;
    int start = lo;
    for (int k = lo; k <= hi; k++) {
      Geometry a = scale(a0, k), b = scale(b0, k);
      String res;
      try {
        Geometry u = OverlayNGRobust.overlay(a, b, op);
        Geometry back = scale(u, -k);
        back.normalize();
        if (back.equalsExact(ref)) res = "correct";
        else if (u.isEmpty()) res = "EMPTY " + u.getGeometryType();
        else if (back.equalsExact(ref, 1e-9)) res = "correct up to 1e-9 (rounded by a fallback)";
        else res = "WRONG " + u.getGeometryType();
      } catch (RuntimeException e) {
        res = "exception " + e.getClass().getSimpleName();
      }
      if (!res.equals(prev)) {
        if (prev != null) System.out.println("  k in [" + start + ", " + (k - 1) + "]: " + prev);
        prev = res;
        start = k;
      }
    }
    System.out.println("  k in [" + start + ", " + hi + "]: " + prev);
  }

  public static void main(String[] args) throws Exception {
    System.out.println("JTS " + JTSVersion.CURRENT_VERSION + ": OverlayNGRobust UNION of A*2^k and P*2^k");
    // the corpus case point-geometry-1-000016-in-hole.ba.int.extreme multiplied by 2^534
    // (k = -534 is the corpus case)
    String a = "MULTIPOLYGON (((-0.6474609375 -0.34423828125, -0.43505859375 -0.40283203125, -0.34716796875 -0.379638671875, -0.526611328125 -0.1025390625, -0.6474609375 -0.34423828125), (-0.502197265625 -0.2392578125, -0.4423828125 -0.33203125, -0.4716796875 -0.33935546875, -0.54248046875 -0.31982421875, -0.502197265625 -0.2392578125)), ((0.322265625 0.51318359375, 0.323486328125 0.51318359375, 0.322265625 0.514404296875, 0.322265625 0.51318359375)))";
    String p = "POINT (-0.48974609375 -0.3076171875)";
    scan("corpus case point-geometry-1-000016 at unit scale, times 2^k (k = -534 is the corpus case)", a, p, OverlayNG.UNION, -1074, 1023);
  }
}
