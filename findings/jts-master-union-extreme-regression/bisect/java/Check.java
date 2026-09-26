import org.locationtech.jts.geom.*;
import org.locationtech.jts.io.WKTReader;
import org.locationtech.jts.operation.overlayng.*;
public class Check {
  public static void main(String[] args) throws Exception {
    WKTReader r = new WKTReader();
    Geometry a = r.read("POLYGON ((-3.6403423436814706e220 3.8270972661136905e220, -3.6403407277677217e220 3.8270908024586947e220, -3.6403391118539727e220 3.8270956501999416e220, -3.6403423436814706e220 3.8270972661136905e220))");
    Geometry b = r.read("MULTILINESTRING ((-3.6403407277677217e220 3.8270908024586947e220, -3.6403391118539727e220 3.8270956501999416e220), (-3.640325645906065e220 3.8271075002341006e220, -3.640324568630232e220 3.8271091161478495e220))");
    Geometry u = OverlayNGRobust.overlay(a, b, OverlayNG.UNION);
    System.out.println(u.getGeometryType() + " empty=" + u.isEmpty() + " n=" + u.getNumPoints());
    System.exit(u.isEmpty() ? 1 : 0);
  }
}
