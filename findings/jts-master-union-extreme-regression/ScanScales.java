// Scale two inputs by exact powers of two (2^k, which cannot change the correct answer) and
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
    System.out.println("JTS " + JTSVersion.CURRENT_VERSION + ": OverlayNGRobust UNION of A*2^k and B*2^k");
    String t = "POLYGON ((0 0, 2 1, 1 2, 0 0))";
    scan("A = B = " + t + " (the largest ordinate is 2^(k+1))", t, t, OverlayNG.UNION, 400, 1022);
    // the corpus case line-polygon-1-000090-along-edge-full.ba.int.extreme divided by 2^732
    // (k = 732 is the corpus case; its largest ordinate is about 1.69 * 2^k)
    String ca = "POLYGON ((-1.6113333702087402 1.6939971446990967, -1.611332654953003 1.6939942836761475, -1.6113319396972656 1.6939964294433594, -1.6113333702087402 1.6939971446990967))";
    String cb = "MULTILINESTRING ((-1.611332654953003 1.6939942836761475, -1.6113319396972656 1.6939964294433594), (-1.611325979232788 1.6940016746520996, -1.6113255023956299 1.694002389907837))";
    scan("corpus case line-polygon-1-000090 at unit scale, times 2^k (k = 732 is the corpus case)", ca, cb, OverlayNG.UNION, 400, 1023);
  }
}
