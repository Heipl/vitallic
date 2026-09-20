"""geo.py - put the arena on the Earth.

field_scan.py works in a local frame: metres, origin at the dog's starting body
centre, +x the direction it faces, +y left. A map needs latitude and longitude.

The conversion is a local tangent plane ("flat Earth") approximation. Over an
arena tens of metres across the curvature error is millimetres, far below the
dog's own positioning error, so there is no reason for anything fancier.

    geo = ArenaGeo(42.3601, -71.0942, heading_deg=0)   # MIT, +x points north
    lat, lon = geo.to_latlon(1.30, 0.75)

heading_deg is the compass bearing of the arena's +x axis: 0 = north, 90 = east.
Get it from the phone's compass, or just declare one and keep the arena aligned.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# WGS-84. One degree of latitude is ~111.32 km; longitude shrinks with cos(lat).
_M_PER_DEG_LAT = 111_320.0


@dataclass
class ArenaGeo:
    """Maps arena metres (x forward, y left) to WGS-84 lat/lon."""

    origin_lat: float
    origin_lon: float
    heading_deg: float = 0.0

    def to_latlon(self, x: float, y: float) -> tuple[float, float]:
        """Arena (x, y) in metres -> (lat, lon) in degrees."""
        # Arena +y is LEFT of +x. With +x on bearing h, left is bearing h-90.
        h = math.radians(self.heading_deg)
        north = x * math.cos(h) + y * math.sin(h)
        east = x * math.sin(h) - y * math.cos(h)
        dlat = north / _M_PER_DEG_LAT
        # Guard the poles so cos() cannot be zero.
        coslat = max(math.cos(math.radians(self.origin_lat)), 1e-6)
        dlon = east / (_M_PER_DEG_LAT * coslat)
        return self.origin_lat + dlat, self.origin_lon + dlon

    def to_xy(self, lat: float, lon: float) -> tuple[float, float]:
        """Inverse of to_latlon, for turning a clicked map point into arena metres."""
        coslat = max(math.cos(math.radians(self.origin_lat)), 1e-6)
        north = (lat - self.origin_lat) * _M_PER_DEG_LAT
        east = (lon - self.origin_lon) * _M_PER_DEG_LAT * coslat
        h = math.radians(self.heading_deg)
        x = north * math.cos(h) + east * math.sin(h)
        y = north * math.sin(h) - east * math.cos(h)
        return x, y

    def as_dict(self) -> dict:
        return {"origin_lat": self.origin_lat, "origin_lon": self.origin_lon,
                "heading_deg": self.heading_deg}


def _selftest() -> None:
    # 100 m due north of the origin with the arena facing north.
    g = ArenaGeo(42.3601, -71.0942, heading_deg=0.0)
    lat, lon = g.to_latlon(100.0, 0.0)
    assert abs((lat - g.origin_lat) * _M_PER_DEG_LAT - 100.0) < 0.01, "north leg wrong"
    assert abs(lon - g.origin_lon) < 1e-9, "north leg should not move longitude"

    # +y is LEFT of +x. Facing north, left is west, so longitude must DECREASE.
    lat2, lon2 = g.to_latlon(0.0, 100.0)
    assert lon2 < g.origin_lon, "+y (left) of north should be west"
    assert abs(lat2 - g.origin_lat) < 1e-9, "pure-left leg should not move latitude"

    # Facing east, +x should move east and not change latitude.
    ge = ArenaGeo(42.3601, -71.0942, heading_deg=90.0)
    lat3, lon3 = ge.to_latlon(100.0, 0.0)
    assert lon3 > ge.origin_lon and abs(lat3 - ge.origin_lat) < 1e-9, "east heading wrong"

    # Round trip.
    for hd in (0.0, 37.0, 90.0, 213.0):
        g2 = ArenaGeo(42.3601, -71.0942, heading_deg=hd)
        for (x, y) in ((1.3, 0.75), (-2.0, 3.1), (0.0, 0.0)):
            xx, yy = g2.to_xy(*g2.to_latlon(x, y))
            assert abs(xx - x) < 1e-6 and abs(yy - y) < 1e-6, f"round trip failed at {hd}"
    print("geo.py self-test passed (north/left/east legs + round trip)")


if __name__ == "__main__":
    _selftest()
