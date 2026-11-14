"""Parsed element sets: one immutable record from TLE or GP (OMM) input.

TLE and OMM text is untrusted input. Every parser here validates what it reads
(checksums, field formats, physical ranges) and raises ``ValueError`` naming the
problem rather than passing a malformed record on.
"""

from __future__ import annotations

import csv
import io
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from sgp4.api import WGS72, Satrec
from sgp4.earth_gravity import wgs72

_MIN_PER_DAY = 1440.0
_REV_PER_DAY_TO_RAD_PER_MIN = 2.0 * math.pi / _MIN_PER_DAY
_SGP4_EPOCH_ZERO = datetime(1949, 12, 31, tzinfo=timezone.utc)


@dataclass(frozen=True, slots=True)
class ElementSet:
    """One SGP4 mean element set for one object at one epoch.

    Angles are degrees, mean motion is revolutions per day, as printed in a TLE
    or a CelesTrak/Space-Track GP record. ``mean_motion_dot`` and
    ``mean_motion_ddot`` are the TLE fields as printed (n-dot / 2 in rev/day^2
    and n-ddot / 6 in rev/day^3); SGP4 does not use them for propagation.

    ``semi_major_axis_km`` is derived, not read. TLE and GP mean motion is the
    Kozai mean motion. SGP4 initialisation converts it to the Brouwer mean motion
    (removing the J2 secular term, which depends on inclination and
    eccentricity) and computes the Brouwer mean semi-major axis
    ``a = (ke / n_brouwer) ** (2/3)`` in Earth radii. This field is that value
    (``Satrec.a``) times the WGS72 equatorial radius, 6378.135 km, so it is the
    same semi-major axis SGP4 itself propagates from. It is a mean element: it
    differs from the osculating semi-major axis by short-period terms of several
    kilometres, and from ``(mu / n_kozai**2) ** (1/3)`` by a few kilometres.
    """

    norad_id: int
    name: str | None
    epoch: datetime  # timezone-aware UTC
    mean_motion: float  # rev/day, Kozai
    eccentricity: float
    inclination: float  # deg
    raan: float  # deg, right ascension of the ascending node
    arg_perigee: float  # deg
    mean_anomaly: float  # deg
    bstar: float  # 1 / Earth radii
    mean_motion_dot: float
    mean_motion_ddot: float
    semi_major_axis_km: float

    def satrec(self) -> Satrec:
        """An initialised ``sgp4`` satellite record for these elements (WGS72)."""
        return _satrec(
            self.norad_id,
            self.epoch,
            self.mean_motion,
            self.eccentricity,
            self.inclination,
            self.raan,
            self.arg_perigee,
            self.mean_anomaly,
            self.bstar,
            self.mean_motion_dot,
            self.mean_motion_ddot,
        )


def _satrec(
    norad_id, epoch, mean_motion, ecc, inc, raan, argp, ma, bstar, ndot, nddot
) -> Satrec:
    sat = Satrec()
    # Unit conversions mirror sgp4's own twoline2rv.
    sat.sgp4init(
        WGS72,
        "i",
        norad_id,
        (epoch - _SGP4_EPOCH_ZERO) / timedelta(days=1),
        bstar,
        ndot * _REV_PER_DAY_TO_RAD_PER_MIN / _MIN_PER_DAY,
        nddot * _REV_PER_DAY_TO_RAD_PER_MIN / _MIN_PER_DAY**2,
        ecc,
        math.radians(argp),
        math.radians(inc),
        math.radians(ma),
        mean_motion * _REV_PER_DAY_TO_RAD_PER_MIN,
        math.radians(raan),
    )
    if sat.error:
        raise ValueError(f"NORAD {norad_id}: SGP4 initialisation failed (error {sat.error})")
    return sat


def _build(
    norad_id: int,
    name: str | None,
    epoch: datetime,
    mean_motion: float,
    ecc: float,
    inc: float,
    raan: float,
    argp: float,
    ma: float,
    bstar: float,
    ndot: float,
    nddot: float,
) -> ElementSet:
    if norad_id <= 0:
        raise ValueError(f"NORAD id must be positive, got {norad_id}")
    if not mean_motion > 0:
        raise ValueError(f"NORAD {norad_id}: mean motion must be positive, got {mean_motion}")
    if not 0.0 <= ecc < 1.0:
        raise ValueError(f"NORAD {norad_id}: eccentricity out of [0, 1): {ecc}")
    if not 0.0 <= inc <= 180.0:
        raise ValueError(f"NORAD {norad_id}: inclination out of [0, 180]: {inc}")
    for label, value in (("RAAN", raan), ("argument of perigee", argp), ("mean anomaly", ma)):
        if not 0.0 <= value <= 360.0:
            raise ValueError(f"NORAD {norad_id}: {label} out of [0, 360]: {value}")
    if not all(math.isfinite(x) for x in (bstar, ndot, nddot)):
        raise ValueError(f"NORAD {norad_id}: non-finite drag term")
    sat = _satrec(norad_id, epoch, mean_motion, ecc, inc, raan, argp, ma, bstar, ndot, nddot)
    return ElementSet(
        norad_id=norad_id,
        name=name,
        epoch=epoch,
        mean_motion=mean_motion,
        eccentricity=ecc,
        inclination=inc,
        raan=raan,
        arg_perigee=argp,
        mean_anomaly=ma,
        bstar=bstar,
        mean_motion_dot=ndot,
        mean_motion_ddot=nddot,
        semi_major_axis_km=sat.a * wgs72.radiusearthkm,
    )


# --- TLE -------------------------------------------------------------------


def _tle_checksum(line: str) -> int:
    return sum(int(c) if c.isdigit() else c == "-" for c in line[:68]) % 10


def _implied_decimal(field: str) -> float:
    """Decode a TLE ' 38792-4' style field: sign, five mantissa digits, exponent."""
    sign, mantissa, exponent = field[0], field[1:6], field[6:8]
    if sign not in " +-" or not mantissa.isdigit() or exponent[0] not in "+-" or not exponent[1].isdigit():
        raise ValueError(f"bad implied-decimal field {field!r}")
    return float(f"{'-' if sign == '-' else ''}0.{mantissa}e{exponent}")


def _tle_epoch(field: str) -> datetime:
    """'19343.69339541' -> UTC datetime, exact to the microsecond (1e-8 day = 864 us)."""
    yy, day = int(field[:2]), Decimal(field[2:].strip())
    if not 1 <= day < 367:
        raise ValueError(f"bad epoch day {field!r}")
    year = 2000 + yy if yy < 57 else 1900 + yy
    micros = int((day - 1) * 86_400_000_000)
    return datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=micros)


def _parse_tle_pair(line1: str, line2: str, name: str | None) -> ElementSet:
    for n, line in ((1, line1), (2, line2)):
        if len(line) != 69 or line[0] != str(n) or line[1] != " ":
            raise ValueError(f"TLE line {n} malformed: {line!r}")
        if not line[68].isdigit() or _tle_checksum(line) != int(line[68]):
            raise ValueError(f"TLE line {n} checksum mismatch: {line!r}")
    # shortcut: numeric catalog numbers only; decode Alpha-5 (e.g. 'A0001') once objects pass 99999.
    if not line1[2:7].strip().isdigit() or line1[2:7] != line2[2:7]:
        raise ValueError(f"TLE catalog numbers missing or differ: {line1[2:7]!r} vs {line2[2:7]!r}")
    try:
        return _build(
            norad_id=int(line1[2:7]),
            name=name,
            epoch=_tle_epoch(line1[18:32]),
            mean_motion=float(line2[52:63]),
            ecc=float("0." + line2[26:33].strip()),
            inc=float(line2[8:16]),
            raan=float(line2[17:25]),
            argp=float(line2[34:42]),
            ma=float(line2[43:51]),
            bstar=_implied_decimal(line1[53:61]),
            ndot=float(line1[33:43]),
            nddot=_implied_decimal(line1[44:52]),
        )
    except (ValueError, InvalidOperation) as exc:
        raise ValueError(f"TLE for {line1[2:7]!r}: {exc}") from exc


def parse_tle(text: str) -> list[ElementSet]:
    """Parse 2-line or 3-line (name line first) TLE text, possibly mixed.

    A Space-Track style ``0 NAME`` name line has its ``0 `` prefix removed.
    """
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    records: list[ElementSet] = []
    name: str | None = None
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("1 ") and len(line) == 69:
            if i + 1 >= len(lines):
                raise ValueError(f"TLE line 1 without line 2: {line!r}")
            records.append(_parse_tle_pair(line, lines[i + 1], name))
            name = None
            i += 2
            continue
        if name is not None:
            raise ValueError(f"expected TLE line 1 after name line {name!r}, got {line!r}")
        name = line[2:].strip() if line.startswith("0 ") else line.strip()
        i += 1
    if name is not None:
        raise ValueError(f"name line {name!r} without element lines")
    return records


# --- GP / OMM --------------------------------------------------------------

_OMM_REQUIRED = (
    "NORAD_CAT_ID",
    "EPOCH",
    "MEAN_MOTION",
    "ECCENTRICITY",
    "INCLINATION",
    "RA_OF_ASC_NODE",
    "ARG_OF_PERICENTER",
    "MEAN_ANOMALY",
    "BSTAR",
    "MEAN_MOTION_DOT",
    "MEAN_MOTION_DDOT",
)


def _omm_epoch(value: str) -> datetime:
    epoch = datetime.fromisoformat(value)
    # CelesTrak and Space-Track print EPOCH without an offset; it is UTC.
    if epoch.tzinfo is None:
        return epoch.replace(tzinfo=timezone.utc)
    return epoch.astimezone(timezone.utc)


def _from_omm_fields(fields: dict[str, str]) -> ElementSet:
    missing = [k for k in _OMM_REQUIRED if fields.get(k) in (None, "")]
    if missing:
        raise ValueError(f"GP record missing fields {missing}: {fields.get('NORAD_CAT_ID')!r}")
    try:
        norad_id = int(fields["NORAD_CAT_ID"])

        def num(key: str) -> float:
            value = float(fields[key])
            if not math.isfinite(value):
                raise ValueError(f"{key} is not finite")
            return value

        name = (fields.get("OBJECT_NAME") or "").strip() or None
        return _build(
            norad_id=norad_id,
            name=name,
            epoch=_omm_epoch(fields["EPOCH"]),
            mean_motion=num("MEAN_MOTION"),
            ecc=num("ECCENTRICITY"),
            inc=num("INCLINATION"),
            raan=num("RA_OF_ASC_NODE"),
            argp=num("ARG_OF_PERICENTER"),
            ma=num("MEAN_ANOMALY"),
            bstar=num("BSTAR"),
            ndot=num("MEAN_MOTION_DOT"),
            nddot=num("MEAN_MOTION_DDOT"),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"GP record {fields.get('NORAD_CAT_ID')!r}: {exc}") from exc


def parse_omm_json(text: str) -> list[ElementSet]:
    """Parse CelesTrak / Space-Track GP JSON: a list of OMM objects (or one object)."""
    # Numbers stay as their text so a JSON value and the same CSV value give the same float.
    data = json.loads(text, parse_float=str, parse_int=str)
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not all(isinstance(d, dict) for d in data):
        raise ValueError("GP JSON must be an object or a list of objects")
    return [_from_omm_fields({k: str(v) for k, v in d.items() if v is not None}) for d in data]


def parse_omm_csv(text: str) -> list[ElementSet]:
    """Parse CelesTrak / Space-Track GP CSV with a header row of OMM field names."""
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or "NORAD_CAT_ID" not in reader.fieldnames:
        raise ValueError("GP CSV has no NORAD_CAT_ID header")
    return [_from_omm_fields(row) for row in reader]
