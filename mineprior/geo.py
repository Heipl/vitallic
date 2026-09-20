"""Projections and grid geometry.

Two projections, for two different jobs:

  LAEA  Lambert azimuthal equal-area, for the national grid.  Equal-area matters
        because the product reports mines per km^2: a grid defined in raw
        lat/lon degrees has cells that shrink markedly from southern to northern
        Ukraine, so densities would be systematically wrong.

  ENU   Local east-north tangent plane, for the robot's area of operations.
        Over a ~20 km AO the tangent-plane error is a few cm, and it keeps the
        robot in a plain metric frame with no dependency on pyproj.

dimOS ships only a LatLon dataclass, a haversine distance and Web-Mercator tile
helpers -- there is no projection anywhere in it, so this bridge is ours.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

R_EARTH_KM = 6371.0
R_EARTH_M = 6371000.0


# ---------------------------------------------------------------------------
# Lambert azimuthal equal-area (spherical)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LAEA:
    lat0: float
    lon0: float

    def forward(self, lat, lon):
        """(lat, lon) degrees -> (x, y) km east/north of the projection centre."""
        p0 = math.radians(self.lat0)
        p = np.radians(np.asarray(lat, dtype=np.float64))
        dl = np.radians(np.asarray(lon, dtype=np.float64) - self.lon0)
        cosc = math.sin(p0) * np.sin(p) + math.cos(p0) * np.cos(p) * np.cos(dl)
        k = np.sqrt(np.maximum(2.0 / (1.0 + cosc), 0.0))
        x = R_EARTH_KM * k * np.cos(p) * np.sin(dl)
        y = R_EARTH_KM * k * (math.cos(p0) * np.sin(p) - math.sin(p0) * np.cos(p) * np.cos(dl))
        return x, y

    def inverse(self, x, y):
        """(x, y) km -> (lat, lon) degrees."""
        p0 = math.radians(self.lat0)
        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        rho = np.sqrt(x * x + y * y)
        rho_safe = np.where(rho == 0, 1e-12, rho)
        c = 2.0 * np.arcsin(np.clip(rho_safe / (2.0 * R_EARTH_KM), -1.0, 1.0))
        sinc, cosc = np.sin(c), np.cos(c)
        lat = np.degrees(np.arcsin(cosc * math.sin(p0) + y * sinc * math.cos(p0) / rho_safe))
        lon = self.lon0 + np.degrees(np.arctan2(
            x * sinc, rho_safe * math.cos(p0) * cosc - y * math.sin(p0) * sinc))
        lat = np.where(rho == 0, self.lat0, lat)
        lon = np.where(rho == 0, self.lon0, lon)
        return lat, lon


UKRAINE_LAEA = LAEA(lat0=49.0, lon0=31.0)


# ---------------------------------------------------------------------------
# Local ENU tangent plane, for the robot AO
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ENU:
    """East-north tangent plane anchored at (lat0, lon0). Units: metres."""
    lat0: float
    lon0: float

    @property
    def m_per_deg_lat(self) -> float:
        return math.pi * R_EARTH_M / 180.0

    @property
    def m_per_deg_lon(self) -> float:
        return math.pi * R_EARTH_M * math.cos(math.radians(self.lat0)) / 180.0

    def forward(self, lat, lon):
        e = (np.asarray(lon, dtype=np.float64) - self.lon0) * self.m_per_deg_lon
        n = (np.asarray(lat, dtype=np.float64) - self.lat0) * self.m_per_deg_lat
        return e, n

    def inverse(self, e, n):
        lon = self.lon0 + np.asarray(e, dtype=np.float64) / self.m_per_deg_lon
        lat = self.lat0 + np.asarray(n, dtype=np.float64) / self.m_per_deg_lat
        return lat, lon


# ---------------------------------------------------------------------------
# Regular grid in a projected frame
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Grid:
    """Axis-aligned regular grid. (x0, y0) is the BOTTOM-LEFT corner.

    Row index is y and column index is x, matching the dimOS/ROS OccupancyGrid
    convention -- shape is (height, width), and the origin is the bottom-left
    corner, not the top-left.
    """
    x0: float
    y0: float
    res: float
    width: int
    height: int

    @property
    def shape(self):
        return (self.height, self.width)

    @property
    def n_cells(self) -> int:
        return self.width * self.height

    @property
    def cell_area(self) -> float:
        """In the square of whatever unit `res` uses (km^2 for LAEA, m^2 for ENU)."""
        return self.res * self.res

    def centres(self):
        """(xs, ys) 1-D arrays of cell-centre coordinates."""
        xs = self.x0 + (np.arange(self.width) + 0.5) * self.res
        ys = self.y0 + (np.arange(self.height) + 0.5) * self.res
        return xs, ys

    def centre_mesh(self):
        xs, ys = self.centres()
        return np.meshgrid(xs, ys)

    def index_of(self, x, y):
        """Continuous coords -> (col, row) integer indices. No bounds checking."""
        cx = np.floor((np.asarray(x) - self.x0) / self.res).astype(np.int64)
        cy = np.floor((np.asarray(y) - self.y0) / self.res).astype(np.int64)
        return cx, cy

    def in_bounds(self, cx, cy):
        return (cx >= 0) & (cx < self.width) & (cy >= 0) & (cy < self.height)

    @classmethod
    def covering(cls, x, y, res: float, pad: float = 0.0):
        """Smallest grid at `res` covering all of (x, y), plus `pad` on each side."""
        x0 = math.floor((float(np.min(x)) - pad) / res) * res
        y0 = math.floor((float(np.min(y)) - pad) / res) * res
        x1 = math.ceil((float(np.max(x)) + pad) / res) * res
        y1 = math.ceil((float(np.max(y)) + pad) / res) * res
        return cls(x0=x0, y0=y0, res=res,
                   width=int(round((x1 - x0) / res)), height=int(round((y1 - y0) / res)))
