"""Y8600 PAR-NG system-reference parameters.

From Y8600 System Description, chapters 1.1 and 1.2, pages 16-19.
These are documented system constraints, not antenna calibration tables
or channel-specific RF link budgets.

This module deliberately DOES NOT construct fictitious AZ/EL antenna gain
patterns or assign frequency channels unsupported by the source.
"""
from dataclasses import dataclass

FREQUENCY_SET_1_MHZ=(9110,9130,9210,9230)
FREQUENCY_SET_2_MHZ=(9150,9180,9250,9280)
INSTRUMENTED_RANGE_KM=40.0
AZIMUTH_SCAN_FULL_DEG=(-15.0,15.0)
ELEVATION_SCAN_FULL_DEG=(-1.0,14.0)
AZIMUTH_SCAN_ICAO_DEG=(-10.0,10.0)
ELEVATION_SCAN_ICAO_DEG=(-1.0,7.0)
AVERAGE_PRI_US=452.0
CPI_PULSES=12
RANGE_QUANTUM_M=17
SIGNAL_PROCESSING="Adaptive MTD"
DOPPLER_CHANNELS=12
RECEIVER_DYNAMIC_RANGE_DB=63.0
STC_DYNAMIC_RANGE_DB=61.5
PEAK_POWER_LINEAR_W=300.0
PEAK_POWER_ELLIPTICAL_W=600.0
SHORT_PULSE_US=.5
LONG_PULSE_US=50.2
LONG_PULSE_NLFM_BANDWIDTH_MHZ=2.0


@dataclass(frozen=True)
class AntennaChannel:
    name: str
    axis: str
    beamwidth_limit_deg: float
    broad_plane: str
    narrow_plane: str


AZIMUTH_ANTENNA=AntennaChannel(
    "AZIMUTH ANTENNA","AZ",.9,"elevation (cosecant)","azimuth")
ELEVATION_ANTENNA=AntennaChannel(
    "ELEVATION ANTENNA","EL",.65,"azimuth","elevation")


def audit(current):
    """Return comparison data only, never silently modify an RF model."""
    checks=[
        ("Instrumented slant range",float(current.range_km),
         INSTRUMENTED_RANGE_KM,"km"),
        ("Minimum elevation",float(current.min_elev),
         ELEVATION_SCAN_FULL_DEG[0],"deg"),
        ("Maximum elevation",float(current.max_elev),
         ELEVATION_SCAN_FULL_DEG[1],"deg"),
    ]
    return [{"parameter":key,"configured":configured,"Y8600":expected,
             "unit":unit,"aligned":abs(configured-expected)<1e-8}
            for key,configured,expected,unit in checks]
