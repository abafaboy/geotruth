import org.locationtech.jts.geom.*;
import org.locationtech.jts.io.WKTReader;
import org.locationtech.jts.operation.overlayng.*;
public class Check {
  public static void main(String[] args) throws Exception {
    WKTReader r = new WKTReader();
    Geometry a = r.read("POLYGON ((-1.4498499853679761e162 1.5242294244407106e162, -1.4498493417931955e162 1.524226850141588e162, -1.4498486982184148e162 1.52422878086593e162, -1.4498499853679761e162 1.5242294244407106e162))");
    Geometry b = r.read("MULTILINESTRING ((-1.4498493417931955e162 1.524226850141588e162, -1.4498486982184148e162 1.52422878086593e162), (-1.4498433350952429e162 1.5242335004143213e162, -1.4498429060453891e162 1.524234143989102e162))");
    Geometry u = OverlayNGRobust.overlay(a, b, OverlayNG.UNION);
    System.out.println(u.getGeometryType() + " empty=" + u.isEmpty() + " n=" + u.getNumPoints());
    System.exit(u.isEmpty() ? 1 : 0);
  }
}
