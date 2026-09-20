"""Sweep and detection records -- the robot's half of the Bayesian update.

Two rules here are safety requirements, not style choices.

PROVENANCE IS A HARD GATE.  A robot "detection" is a sensor anomaly, not a
confirmed mine.  Only an operator-confirmed or EOD-disposed record meets the
IMAS bar of DIRECT evidence, and only those may ever be drawn as a registered
mine or exported.  Synthetic records must be REJECTED with an exception, never
filtered out silently -- a filter that quietly drops bad records also quietly
drops good ones when a provenance string is misspelled.

NULL SWEEPS MUST BE LOGGED.  Keeping only the runs that found something is the
easiest way to corrupt this dataset, and it happens by accident when only
"interesting" runs get saved.  Null sweeps are the overwhelming majority of the
robot's output and the only unbiased signal it produces.

The tasking PROPENSITY is recorded with every sweep: the probability that cell
was selected at the time it was selected.  Without it no unbiased retrospective
evaluation is possible, because the robot is sent where the model says risk is
high and then finds mines there, which confirms nothing.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path


class Provenance(str, Enum):
    SYNTHETIC = "synthetic"                # demo/simulation. Never exported.
    SENSOR_ANOMALY = "sensor_anomaly"      # raw detector alarm, unadjudicated
    OPERATOR_CONFIRMED = "operator_confirmed"
    EOD_DISPOSED = "eod_disposed"


CONFIRMED = (Provenance.OPERATOR_CONFIRMED, Provenance.EOD_DISPOSED)


class ProvenanceError(ValueError):
    """Raised when a record's provenance disqualifies it from the operation."""


@dataclass
class Detection:
    lat: float
    lon: float
    provenance: Provenance
    ts: float = field(default_factory=time.time)
    mine_type: str = "unknown"
    depth_m: float | None = None
    run_id: str = ""
    note: str = ""

    def __post_init__(self):
        self.provenance = Provenance(self.provenance)

    @property
    def is_confirmed(self) -> bool:
        return self.provenance in CONFIRMED

    def require_confirmed(self):
        if self.provenance is Provenance.SYNTHETIC:
            raise ProvenanceError(
                "synthetic detections must never reach an operational export")
        if not self.is_confirmed:
            raise ProvenanceError(
                f"provenance {self.provenance.value!r} is a sensor anomaly, not a "
                "confirmed mine; only operator_confirmed or eod_disposed records "
                "may be published as registered hazards")
        return self


@dataclass
class Sweep:
    """One pass over one cell. Logged whether or not anything was found."""
    cell_x: int
    cell_y: int
    swept_m2: float
    sensitivity: float
    alarms: int = 0
    confirmed: int = 0
    false_alarm_rate_per_km2: float = 0.0
    propensity: float = 1.0
    """P(this cell was selected) at tasking time. 1.0 means 'not recorded',
    which makes any later inverse-propensity analysis invalid -- set it."""
    exploration: bool = False
    """True if drawn by the randomised exploration arm rather than by the
    acquisition score. These are the only sweeps that can falsify the model,
    because the acquisition arm never visits low-risk cells."""
    sensor_depth_m: float = 0.13
    """IMAS 09.10's default minimum clearance depth for metal-detector
    operations. A sweep that does not reach it is not evidence of absence for
    anything deeper, and p_d is near zero for minimum-metal ordnance regardless."""
    ts: float = field(default_factory=time.time)
    run_id: str = ""

    def __post_init__(self):
        if not 0.0 < self.sensitivity <= 1.0:
            raise ValueError("sensitivity must be in (0, 1]")
        if self.sensitivity >= 1.0:
            # p_d = 1 asserts a perfect detector, which does not exist for
            # PFM-1 scatterables, low-metal AT mines, or anything under rubble.
            raise ValueError("sensitivity of 1.0 is a safety defect: no sensor "
                             "detects every mine type at every depth")
        if self.swept_m2 < 0:
            raise ValueError("swept_m2 must be non-negative")


class SweepLog:
    """Append-only JSONL log. Replaying it reproduces the posterior exactly."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, rec: Sweep | Detection):
        d = asdict(rec)
        d["_kind"] = "sweep" if isinstance(rec, Sweep) else "detection"
        if isinstance(rec, Detection):
            d["provenance"] = rec.provenance.value
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(d) + "\n")

    def read(self):
        if not self.path.exists():
            return [], []
        sweeps, dets = [], []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            kind = d.pop("_kind", "sweep")
            (sweeps if kind == "sweep" else dets).append(
                Sweep(**d) if kind == "sweep" else Detection(**d))
        return sweeps, dets

    def replay(self, field_obj):
        """Fold every logged sweep into a PosteriorField, in order."""
        sweeps, _ = self.read()
        for s in sweeps:
            field_obj.observe(
                s.cell_x, s.cell_y, swept_m2=s.swept_m2, sensitivity=s.sensitivity,
                alarms=s.alarms, confirmed=s.confirmed,
                false_alarm_rate_per_km2=s.false_alarm_rate_per_km2)
        return len(sweeps)


def export_registered(detections, *, strict: bool = True):
    """Registered-hazard records fit to publish.

    With strict=True (the default) a synthetic or unadjudicated record raises,
    rather than being dropped. That is deliberate: the caller must decide, and a
    silent filter hides provenance bugs.
    """
    out = []
    for d in detections:
        if strict:
            d.require_confirmed()
        elif not d.is_confirmed:
            continue
        out.append({"lat": d.lat, "lon": d.lon, "provenance": d.provenance.value,
                    "mine_type": d.mine_type, "ts": d.ts, "run_id": d.run_id})
    return out
