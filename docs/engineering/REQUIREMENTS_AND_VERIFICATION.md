# CD-SDD-004 — Software Requirements and Verification Matrix

**Revision:** 1.0, 2026-11-09.  
**Reference approach:** ISO/IEC/IEEE 29148-inspired traceable, testable requirements. These are reconstructed *as-implemented* requirements, not an approved customer SRS; formal requirements validation remains outstanding.

| ID | Requirement statement (shall) | Source / implementation | Verification or gap |
|---|---|---|---|
| FR-001 | Application shall accept validated WGS84 radar site location and model settings. | radar_core.Config.validate; map_workspace._cfg | Automated config tests + UI workflow |
| FR-002 | Application shall compute polar radar terrain coverage with unknown DEM values represented as unknown. | radar_core.axes, solve | Core regression, missing DEM fixture |
| FR-003 | Application shall support PSR (RL-2000), SSR and PAR-NG with explicitly identified assumptions. | radar_core, model presets | PAR/SSR fixtures; independent validation not completed |
| FR-004 | PAR calculation shall use a ±15° sector with selectable TRUE bearing and a defined antenna model. | radar_core.axes, ParScanPattern | Sector and gain interpolation tests |
| FR-005 | PAR display shall support low elevations in ft with explicit AMSL/AGL reference. | flight_levels_for, status_at_height, map_workspace | Low-level reference unit tests; **note** code includes 50–450 ft plus standard 500 ft |
| FR-006 | Application shall support user-defined obstacles as point, polygon or arc and affect geometry only when enabled and valid. | obstacles, geodata_obstacle_catalog | Obstacle validation/shadow tests |
| FR-007 | User shall be able to recompute an edited obstacle set over already sampled DEM without a new network request. | map_workspace._recalculate_cached_terrain | Existing cached PAR tests; broader UI test needed |
| FR-008 | Last valid radar result shall remain available if a subsequent recalculation or provider request fails. | map_workspace transaction code | Failure-injection UI integration test required |
| FR-009 | Application shall look up runways from a user-entered four-letter ICAO code. | airport_geometry, map_workspace | Tests/test_airport_geometry.py; provider data availability unverified |
| FR-010 | Runway geometry shall show endpoints, displaced thresholds, centerline and midpoint in WGS84. | airport_geometry.runway_geometry, persistent Leaflet | Geometry unit tests + browser integration gap |
| FR-011 | Application shall optionally align PAR reference bearing to selected runway approach direction from radar site. | airport_geometry.par_bearing_for_runway | Synthetic geodesic tests |
| FR-012 | Application shall load nearby CTR/TMA as vector polygons with source, class and lower/upper limits. | airspace_geometry, map_workspace | Airspace parser tests; provider authorization required |
| FR-013 | Airspace filters shall not silently exclude zones with unknown vertical reference. | airspace_geometry.visible_airspaces | Altitude filtering test |
| FR-014 | Application shall load OSM buildings/forests/towers around site upon explicit request at a bounded radius (default quick action 2 km). | environment_layers.fetch_osm, map_workspace._position_nearby_controls | Provider fallback tests; live service behavior unverified |
| FR-015 | OSM/third-party object heights shall remain unknown when data do not establish reliable numeric height. | environment_layers._height, geodata_obstacle_catalog | Parser and data quality tests |
| FR-016 | Application shall provide map-only selected layer export to KMZ, KML and GeoJSON without a radar result. | position_export, map_workspace.position_layers_export_dialog | tests/test_position_export.py |
| FR-017 | Exported KML/KMZ shall group objects in independently selectable layers and preserve WGS84 geometry and source/height attributes. | position_export.kml_bytes/kmz_bytes | Parser/round-trip tests incl. holes and KMZ doc.kml |
| FR-018 | Existing PDF 600 DPI, PNG, QuickReport, ZIP and scientific export capabilities shall remain accessible after a radar computation. | map_workspace.exports_dialog; coverage_report; selected_export | UI label restored PR #25; PDF E2E smoke outstanding |
| FR-019 | Application shall preserve a portable radar project with DEM matrices, active obstacles and position data. | project_file, map_workspace._airport_project_metadata | Cached project tests; map-only project not yet supported |
| FR-020 | Application shall preserve previous loaded position/geodata layers if a network request fails. | map_workspace, environment_layers fallback | Failure mocks plus UI integration gap |
| NFR-001 | External requests shall have explicit endpoint allowlist, timeouts and response-size limits where feasible. | environment_layers, airspace_geometry | HTTP failure tests |
| NFR-002 | API credentials shall be handled as secrets and not embedded in source or export metadata. | aviation_basemap, map_workspace | Security review; tile key exposure concern |
| NFR-003 | Performance shall remain usable for bounded grids and polygons without repeated full Leaflet reconstruction. | radar_core limits; persistent Leaflet | Load and memory tests needed |
| NFR-004 | Changes shall be checked by Python tests, JS syntax and full CI before release. | GitHub Actions workflows | Targeted checks green; general suite not green |
| NFR-005 | Source licensing, uncertainty and reference units shall be available to downstream users. | layer attributes, UI captions, exports | Artifact inspection / legal terms review needed |

## Acceptance scenarios

### AC-01 — Map-only, no DEM
Given no radar result, open POZICE, input ICAO, load runway geometry, import CTR/TMA GeoJSON or OpenAIP vectors, load OSM 2 km (if provider reachable), open MAPA export and select KMZ. **Pass:** doc.kml contains independent folders and geometries; no radar calculation is invoked. **Fallback:** unavailable source does not delete prior overlays.

### AC-02 — Radar report preservation
Given a valid radar result, open MAPA → EXPORTNÍ CENTRUM and access PDF 600 DPI, PNG per level, QuickReport and ZIP. **Pass:** expected outputs created, page count/metadata validated and no regression to old presets. The new standalone position-layer export remains available simultaneously.

### AC-03 — PAR low altitude
Given PAR at a site with nonzero terrain, select 50 ft AGL then 50 ft AMSL. **Pass:** outputs use explicitly different vertical references, and 50 ft AMSL below terrain is not confused with map render failure.

### AC-04 — Cached obstacle iteration
Given a completed result and existing DEM, add a new obstacle and recalculate from cached terrain. **Pass:** last result persists if calculation raises; successful version can show BEFORE vs AFTER, without DEM download; saved .cdproj survives restart.

### AC-05 — Provider resilience
Simulate first Overpass Connection refused, then success on a second allowlisted host. **Pass:** objects load, no stale deletion. Simulate all failed endpoints. **Pass:** actionable diagnostic + earlier layers unchanged. Simulate OpenAIP 403. **Pass:** message refers to Core Data API authorization/OPENAIP_DATA_API_KEY and never exposes the key.

### AC-06 — Aviation source caution
Display airport runway and CTR/TMA data derived from public community sources. **Pass:** source/provenance and limitations are visible and preserved in exports; no statement that values are verified AIP/certified operational data.

## Evidence and release gate

Automated tests located under tests/. Relevant cases: test_airport_geometry.py, test_airspace_geometry.py, test_position_export.py, test_cached_par_recompute.py, test_par_altitude_reference.py, test_par_3d_detection.py, test_provider_recovery.py. GitHub Actions focused workflow is airport-par-regression.yml. Broad workflow failures described in SOURCE_CODE_REVIEW.md must be resolved and documented before a **production-qualified** release declaration.

**Approval fields pending:** requirement owner, verification owner, date, immutable baseline commit, independent numerical reference datasets, signoff and risk acceptance.
