# VIEWER BOD / PROFIL — two evidence modes

## EDITOR snapshot mode
The native result includes radial azimuth and range, sampled DEM, lower and upper
heights, native status masks and antenna model. VIEWER displays the nearest
sample of the original calculation; coverage verdicts are supplied by
radar_core.status_at_height, not approximated in JavaScript. Missing DEM stays
UNKNOWN.

CDPROJ now stores the original antenna arrays to avoid replacing customer
measurements with default curves on reloading. Old archives without antenna
data must not recalculate other levels.

## Standalone DEM mode
Click BOD / PROFIL and then a target. If no EDITOR grid is available, the
browser automatically requests terrain along the radar-target WGS84 geodesic.

- Data: Copernicus GLO-90 (2021), ~90 m source resolution, via
  Open-Meteo Elevation API.
- Requests contain at most 100 coordinates; profiles contain up to 400 samples.
  Sampling spacing varies with target distance and is reported in the UI.
- When no radar coordinates are available, the first click sets the radar site.
- Antenna height AGL, target altitude AMSL, and k factor are explicit inputs.
- The ray uses the effective-Earth trigonometric model.
- Incomplete DEM yields UNKNOWN, not an invented visible path.
- Session-local caching avoids repeat downloads.

Standalone mode reports LOS VOLNA / LOS BLOKOVANA, never a full radar coverage
verdict. It does not validate RCS, RF SNR, pulse integration, or true Pd, and
does not account for unsampled terrain features, buildings, multipath,
diffraction, Fresnel zones, clutter, or atmospheric vertical profiles.

## Production accuracy
The public Open-Meteo service is a development fallback, not a production SLA.
Verify attribution, licensing and commercial service requirements before
shipping customer deployments. Prefer authenticated OpenTopography/Copernicus
GeoTIFF cache or an organization-operated DEM service for validated studies.
If download fails, the user receives a clear error, not false coverage.
