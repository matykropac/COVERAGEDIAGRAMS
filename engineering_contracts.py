"""COVERAGEDIAGRAMS 2.0 immutable engineering identity/provenance contracts.

Phase 0: no changes to radar_core, persisted CDPROJ or existing solver.
Normalized dataclasses are boundary types for future modules.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import math
from typing import Optional


class DataOrigin(str, Enum):
    MEASURED = "MEASURED"
    SIMULATED = "SIMULATED"
    DERIVED = "DERIVED"
    UNKNOWN = "UNKNOWN"


class SensorType(str, Enum):
    PSR = "PSR"
    SSR = "SSR"
    PAR = "PAR"
    ADS_B = "ADS-B"


def _utc(value: datetime, name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware UTC")
    if value.utcoffset().total_seconds() != 0:
        raise ValueError(f"{name} must use UTC offset +00:00")


def _finite(value: float, name: str, minimum: float, maximum: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} is out of range [{minimum}, {maximum}]")


@dataclass(frozen=True)
class Provenance:
    origin: DataOrigin
    producer: str
    created_utc: datetime
    source_sha256: Optional[str] = None
    limitations: tuple[str, ...] = ()

    def __post_init__(self):
        if not isinstance(self.origin, DataOrigin):
            raise ValueError("origin must be a recognized provenance classification")
        if not self.producer or not self.producer.strip():
            raise ValueError("producer must be set")
        _utc(self.created_utc, "created_utc")
        if self.source_sha256 is not None:
            h = self.source_sha256
            if len(h) != 64 or any(ch not in "0123456789abcdef" for ch in h):
                raise ValueError("source_sha256 must be 64 lowercase hex characters")
        if not isinstance(self.limitations, tuple) or not all(
            isinstance(item, str) for item in self.limitations
        ):
            raise ValueError("limitations must be tuple of strings")


@dataclass(frozen=True)
class SensorDefinition:
    sensor_id: str
    kind: SensorType
    latitude_deg: float
    longitude_deg: float
    site_altitude_m_amsl: float
    antenna_height_m_agl: float
    orientation_deg_true: float
    revision: int = 1

    def __post_init__(self):
        if not self.sensor_id or not self.sensor_id.strip():
            raise ValueError("sensor_id is required")
        if not isinstance(self.kind, SensorType):
            raise ValueError("Unsupported sensor kind")
        _finite(self.latitude_deg, "latitude_deg", -90, 90)
        _finite(self.longitude_deg, "longitude_deg", -180, 180)
        _finite(self.site_altitude_m_amsl, "site_altitude_m_amsl", -1000, 9000)
        _finite(self.antenna_height_m_agl, "antenna_height_m_agl", 0, 5000)
        _finite(self.orientation_deg_true, "orientation_deg_true", 0, 360)
        if self.orientation_deg_true == 360:
            raise ValueError("orientation_deg_true must be less than 360")
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 1:
            raise ValueError("revision must be positive integer")


@dataclass(frozen=True)
class ObservationIdentity:
    sensor_id: str
    asterix_category: int
    asterix_edition: str
    message_index: int
    timestamp_utc: datetime
    time_uncertainty_ms: Optional[float]
    provenance: Provenance

    def __post_init__(self):
        if not self.sensor_id.strip():
            raise ValueError("sensor_id is required")
        if not (0 <= self.asterix_category <= 255):
            raise ValueError("ASTERIX category out of range")
        if not self.asterix_edition.strip():
            raise ValueError("ASTERIX edition is mandatory; never guess")
        if self.message_index < 0:
            raise ValueError("message_index must be non-negative")
        _utc(self.timestamp_utc, "timestamp_utc")
        if self.time_uncertainty_ms is not None:
            _finite(self.time_uncertainty_ms, "time_uncertainty_ms", 0, 86400000)


def sha256_bytes(data: bytes) -> str:
    if not isinstance(data, bytes):
        raise TypeError("data must be bytes")
    return hashlib.sha256(data).hexdigest()
