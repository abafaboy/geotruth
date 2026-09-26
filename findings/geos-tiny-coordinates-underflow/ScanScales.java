// JTS counterpart of scan_scales.c: the checks of Repro.java for S = 1e<k>,
// k = -320 .. 307; prints, per check, the ranges of k with a wrong answer.
//   javac -cp jts-core.jar ScanScales.java && java -cp jts-core.jar:. ScanScales
import org.locationtech.jts.JTSVersion;
import org.locationtech.jts.algorithm.Orientation;
import org.locationtech.jts.geom.Coordinate;
import org.locationtech.jts.geom.Geometry;
import org.locationtech.jts.io.WKTReader;
import org.locationtech.jts.operation.overlayng.OverlayNG;
import org.locationtech.jts.operation.overlayng.OverlayNGRobust;
import org.locationtech.jts.operation.relateng.RelateNG;
import org.locationtech.jts.operation.valid.IsValidOp;
import java.util.function.IntPredicate;

public class ScanScales {
  static WKTReader rdr = new WKTReader();
  static Geometry rd(String t, String unit) {
    try { return rdr.read(t.replace("S", unit)); } catch (Exception e) { throw new RuntimeException(e); }
  }
  static boolean same(Geometry got, Geometry exp) {
    Geometry g = got.copy(); g.normalize(); Geometry e = exp.copy(); e.normalize();
    return g.equalsExact(e, 0.0);
  }
  static boolean ok(java.util.function.BooleanSupplier f) {
    try { return f.getAsBoolean(); } catch (Throwable t) { return false; }
  }
  public static void main(String[] args) {
    System.out.println("JTS " + JTSVersion.CURRENT_VERSION);
    String[] names = {"Orientation.index((0 0),(1S 0),(0 1S)) != 0", "isValid(T)", "isValid(H)",
        "A.relate(P) = 0F2FF1FF2 [RelateOp]", "A.relate(B) = 212101212 [RelateOp]",
        "RelateNG.relate(A, B) = 212101212", "OverlayNGRobust intersection exact",
        "OverlayNGRobust union exact"};
    int lo = -320, hi = 307;
    boolean[][] bad = new boolean[names.length][hi - lo + 1];
    for (int k = lo; k <= hi; k++) {
      String u = "E" + k;
      double s = Double.parseDouble("1" + u);
      Geometry t = rd("POLYGON ((0 0, 1S 0, 0 1S, 0 0))", u);
      Geometry h = rd("POLYGON ((0 0, 4S 0, 4S 4S, 0 4S, 0 0), (1S 1S, 1S 2S, 2S 2S, 2S 1S, 1S 1S))", u);
      Geometry a = rd("POLYGON ((0 0, 2S 0, 2S 2S, 0 2S, 0 0))", u);
      Geometry p = rd("POINT (1S 1S)", u);
      Geometry b = rd("POLYGON ((1S 1S, 3S 1S, 3S 3S, 1S 3S, 1S 1S))", u);
      Geometry ei = rd("POLYGON ((1S 1S, 2S 1S, 2S 2S, 1S 2S, 1S 1S))", u);
      Geometry eu = rd("POLYGON ((0 0, 2S 0, 2S 1S, 3S 1S, 3S 3S, 1S 3S, 1S 2S, 0 2S, 0 0))", u);
      int i = k - lo;
      bad[0][i] = !ok(() -> Orientation.index(new Coordinate(0, 0), new Coordinate(s, 0), new Coordinate(0, s)) != 0);
      bad[1][i] = !ok(() -> new IsValidOp(t).isValid());
      bad[2][i] = !ok(() -> new IsValidOp(h).isValid());
      bad[3][i] = !ok(() -> a.relate(p).toString().equals("0F2FF1FF2"));
      bad[4][i] = !ok(() -> a.relate(b).toString().equals("212101212"));
      bad[5][i] = !ok(() -> RelateNG.relate(a, b).toString().equals("212101212"));
      bad[6][i] = !ok(() -> same(OverlayNGRobust.overlay(a, b, OverlayNG.INTERSECTION), ei));
      bad[7][i] = !ok(() -> same(OverlayNGRobust.overlay(a, b, OverlayNG.UNION), eu));
    }
    for (int c = 0; c < names.length; c++) {
      StringBuilder sb = new StringBuilder();
      for (int k = lo; k <= hi; k++) {
        if (!bad[c][k - lo]) continue;
        int e = k;
        while (e + 1 <= hi && bad[c][e + 1 - lo]) e++;
        sb.append(" [").append(k).append(", ").append(e).append("]");
        k = e;
      }
      System.out.printf("  %-44s wrong for S = 1e<k>, k in:%s%n", names[c], sb.length() == 0 ? " none" : sb);
    }
  }
}
