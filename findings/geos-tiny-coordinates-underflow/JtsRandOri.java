import org.locationtech.jts.algorithm.Orientation;
import org.locationtech.jts.geom.Coordinate;
import java.nio.file.*; import java.util.*;
public class JtsRandOri { public static void main(String[] a) throws Exception {
  List<double[]> base = new ArrayList<>(); List<Integer> sg = new ArrayList<>();
  for (String line : Files.readAllLines(Paths.get("triples.txt"))) {
    String[] p = line.trim().split(" "); double[] t = new double[6];
    for (int i = 0; i < 6; i++) t[i] = Double.parseDouble(p[i]);
    int x = Integer.parseInt(p[6]);
    if (base.size() < 20000 && idx(t, 0) == x) { base.add(t); sg.add(x); }
  }
  System.out.println(base.size() + " triples correct at unit scale");
  for (int k : new int[]{-505,-510,-512,-515,-520,-530,505,507,508,510,512,600}) {
    int zero = 0, flip = 0;
    for (int i = 0; i < base.size(); i++) { int g = idx(base.get(i), k); if (g != sg.get(i)) { if (g == 0) zero++; else flip++; } }
    System.out.println("2^" + k + ": collinear " + zero + ", opposite sign " + flip);
  }
}
static int idx(double[] t, int k) {
  double[] s = new double[6]; for (int i = 0; i < 6; i++) { s[i] = Math.scalb(t[i], k); if (Math.scalb(s[i], -k) != t[i]) throw new RuntimeException("inexact"); }
  return Orientation.index(new Coordinate(s[0], s[1]), new Coordinate(s[2], s[3]), new Coordinate(s[4], s[5]));
}}
