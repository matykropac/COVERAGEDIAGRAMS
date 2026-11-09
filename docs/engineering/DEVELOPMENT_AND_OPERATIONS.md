# CD-SDD-002 — Development, Verification and Operations

**Version:** 1.0 / 2026-11-09. Companion to [SOFTWARE_DESIGN_DESCRIPTION.md](SOFTWARE_DESIGN_DESCRIPTION.md).  
**Intended audience:** developer, build/release engineer, GIS analyst, test engineer, technical sales/system engineer.

## 1. Supported application modes

- Web UI: Streamlit server with MAPA / PŘEKÁŽKY / RADAR / POZICE sidebar; persistent Leaflet JS component.
- Legacy web: older folium controls retained for backward comparison.
- Desktop: COVERAGEDIAGRAMS.py; packaging via GitHub Actions and build scripts, platform-specific dependencies. **Known parity problem** with web radar_core implementation.
- Offline: locally available DEM and local exports can run without fetching a new DEM; online tiles, OpenAIP, OSM, remote geodata and live ADS-B do not work offline.

## 2. Build and runtime dependencies

Pinned root requirements, verified by source review:
- Python 3.12 recommended in repo deployment documentation.
- streamlit 1.65.0; streamlit-folium 0.27.4; folium 0.20.0.
- numpy 2.3.5; matplotlib 3.10.8; rasterio 1.5.2; pyproj 3.8.0; shapely 2.1.2.
- Pillow 12.3.0; pandas 2.2.3; reportlab 4.4.4.
- Optional desktop dependencies include customtkinter, tkinter and keyring (requirements and OS-dependent).

Local commands:
~~~bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run streamlit_app.py
~~~
Windows activation: .venv\Scripts\activate. For automated tests install pytest too; do not assume requirements.txt contains it.

## 3. Environment configuration / credentials

| Secret | Consumed by | Purpose | Security notes |
|---|---|---|---|
| OPENTOPOGRAPHY_API_KEY | map_workspace / radar_core | OpenTopography DEM | server-side secret only |
| OPENAIP_API_KEY | aviation_basemap, browser tile overlays | OpenAIP raster maps | browser tile URL may expose key; restrict scope/domain |
| OPENAIP_DATA_API_KEY | map_workspace / airspace_geometry | OpenAIP Core Data vector API CTR/TMA | separate server-side key; provider must authorize core API |

Configure in Streamlit Secrets or server environment, not committed .py/.toml. HTTP 403 from OpenAIP is not automatically fixed by retries; verify account access to Core Data API. Avoid printing secret values.

## 4. External provider matrix / failure behavior

| Provider | Query | Failure handling | Attribution / caveat |
|---|---|---|---|
| OpenTopography | DEM download, chosen dataset | error; keep previous calculated result | data licensing and vertical datum |
| OpenAIP Core Data | CTR/TMA vectors | 401/403 action text; preserve prior airspaces; use GeoJSON import | verify official AIP, service access |
| OpenAIP tiles | browser aviation map tiles | can hide tiles without removing vectors | key may be client-visible |
| Overpass OSM | on-demand nearby obstacles | fallback across allowlisted hosts; preserve old dataset; offer GeoJSON import | ODbL; unknown physical height |
| OurAirports | runway table | 24-hour Streamlit cache; preserve existing runway geometry on failure | public dataset not certified thresholds |
| Microsoft buildings | building footprint tiles | on-demand, bounded; may fail in large cities | verify dataset terms |
| ADS-B | traffic snapshot | independent, best-effort | not certified flight surveillance |

## 5. Change control / configuration management

1. Each change references an identified requirement ID from CD-SDD-004.
2. Source must be changed on a dedicated branch with explicit, bounded commits.
3. Any physics-affecting edit also checks web/desktop parity and core regression fixtures.
4. Any external-data change adds negative tests: HTTP errors, invalid geometry, empty but valid result, missing height and offline behavior.
5. Any export change adds KML/KMZ parser round-trip, GeoJSON interchange, report smoke and source attribution tests.
6. Targeted checks **and** the whole regression suite must pass before calling a build releasable.
7. Merge review logs commit SHA, test evidence, known exceptions and deployment status.
8. Deployment and application UI must be verified independently; GitHub main != automatically deployed app.

## 6. Validation strategy

### Unit
- numeric radar geometry / k factor / azimuth wrap;
- PAR 3D gain interpolation, steering loss and illustrative Pd/Pfa reference;
- low-altitude AGL vs AMSL comparison; missing terrain propagation;
- obstacle point/arc/polygon validation and shadowing;
- airport ICAO geodesic thresholds and true bearing;
- airspace Polygon/MultiPolygon and hole validation; vertical reference filtering;
- Overpass provider fallback and HTTP response bounds;
- KML/KMZ/GeoJSON serializations without radar result; corrupt imports rejected.

### Integration
- compute → add/edit/delete obstacle → cached recompute → before/after comparison;
- position-only: enter ICAO → RWY and CTR/TMA → fetch OSM around site → export KML/KMZ → import in QGIS;
- project: save .cdproj, restart session, reload, recompute, compare source hashes;
- report: generate PDF 600 DPI, verify pages, metadata, selected FL and basemap fallback;
- Streamlit sidebar transitions keep selected reference/levels and never blank the map unexpectedly;
- browser Leaflet overlay toggles and modal dialogs.

### Nonfunctional
- bounded network replies, timeouts and retries; identify provider health.
- memory profile at maximum sampled grid plus 50k reference objects.
- no data loss on provider failure or invalid imported project.
- correct coordinate order, units, attribution, HTTP security, license restrictions.
- reproducible artifacts and numerically stable tolerance fixtures.

### Current evidence and gaps
Focused PAR/runway/geospatial and provider fallback tests passed on dedicated CI after the latest fixes. Previous general smoke and radar test jobs were not green (stale test expectations, desktop/web divergence, UI component registration). They require remediation before release qualification. No independent end-to-end production deployment test or aviation safety certification exists.

## 7. Incident troubleshooting

### CTR/TMA: HTTP 403 Forbidden
A refused Core Data API request typically indicates auth/scope/access policy. Confirm that OPENAIP_DATA_API_KEY is configured for server-side airspace data. Separate it from tile-only OPENAIP_API_KEY. An HTTP 403 must be presented as an authorization error; do not silently hide CTR boundaries. GeoJSON import remains a workaround when legally usable source data are available.

### OSM: Connection refused
Public Overpass hosts are not guaranteed; the adapter tries a bounded list of independent allowlisted servers. Confirm outbound HTTPS from hosting provider. If every service fails, preserve loaded OSM data and use local GeoJSON import. Do not invent obstacle heights.

### PDF or PNG missing in the interface
Open MAPA → EXPORTNÍ CENTRUM → PDF 600 DPI / PNG / QUICKREPORT / ZIP. These require a successful radar computation. MAPA → KML/KMZ/GeoJSON export works without one. If export fails with a missing basemap, investigate rendering tile access, not radar physics.

### Blank PAR at low levels
Confirm AGL vs AMSL; 50 ft AMSL may be below terrain. Check known terrain samples, geometric horizon vs elevation cap, gain-limited range and vector polygonization separately. Never fabricate a filled sector just to remove a blank display.

### Stale project
Source DEM and config are tied to the polar grid. Obstacle edits permit recalculation from cached terrain; moving radar or changing grid requires DEM re-sampling. Save .cdproj for persistence across server restarts.

## 8. Deployment and release record template

- Release ID, date, Git commit SHA:
- Target web/desktop platform:
- Python and pinned packages:
- Secrets present (names only, no values):
- DEM/source versions, rights and known limitations:
- Core parity test evidence:
- Unit/integration/browser/regression CI URLs:
- PDF/PNG/KML/KMZ artefact smoke results:
- User-acceptance steps / screenshots:
- Known exceptions (findings IDs), risk owner and expiry:
- Deployment confirmation in actual UI:
- Rollback commit and backup validation:

## 9. Coding conventions and document maintenance

Use clear units in names and stored schemas (ft, km, m, AMSL, AGL), typed interfaces or docstrings for critical public APIs, deterministic serialization, explicit errors without secrets, small pure functions for physics, and stable model-version metadata. The documentation must be updated in the same PR as an architectural or schema change, not after deployment.
