# COVERAGEDIAGRAMS VIEWER STUDIO 2.0 — Analysis and Composer

## User workflows

### Coverage Compare (separate Studio route)
1. In VIEWER press MAP COMPOSER / COMPARE to open the studio.
2. Load identical-source comparable polygon layers (KML/KMZ/GeoJSON or imported EDITOR layers).
3. Choose BASELINE and CANDIDATE and confirm both are at the same FL / height reference.
4. Run comparison. Export derived GeoJSON, then import it to fullscreen VIEWER to overlay colors.
5. Do not present geometry change as an RF validation.

**Difference masks:** common = A ∩ B, gained = B − A, lost = A − B. Topology is handled by Shapely/GEOS. Surface area is calculated on the WGS84 ellipsoid; results are rounded. Invalid polygon rings are repaired. Files crossing the antimeridian are not supported.

### Coverage Statistics
Select a polygon layer and optionally set radar LAT/LON, RANGE and azimuth sector count. Computations merge duplicates and overlaps using GEOS, reproject to a local azimuthal-equidistant plane to clip radial sectors and calculate WGS84 ellipsoidal areas for each result. Exact geodesic sector boundary behavior is limited by angular sector sampling. Uncovered regions are not necessarily measured no-data.

### Map Composer
In studio's EXPORT controls, select MAP COMPOSER, paper format A4–A0, page orientation and metadata. Generate a customer-oriented PDF with cover, vector map composition and per-layer statistics. Online basemap tiles are not embedded; full color print uses the existing deterministic map renderer. Atlas map is composed directly as PDF vector paths, preserving line and polygon sharpness on A0–A4. Background tiles are deliberately not embedded.

### Cartographic tools
Fullscreen VIEWER / MAPA offers two-point approximate distance and initial bearing, a WGS84 graticule and draggable annotations exported in GeoJSON. These annotations are deliberately **not** appended to imported radar data or CDVIEW input. The "without online basemap" display suppresses tile fetches. The user can additionally import an **XYZ ZIP** with z/x/y.png, jpg, or webp tiles (max 180 MB compressed, 90,000 members), which are read in-browser with JSZip and rendered with Leaflet without a tile server. Leaflet/JSZip still require initial availability from CDN; this is **not** yet a self-contained offline executable.

## Compatibility / outstanding work
- The browser's locally imported layers are not automatically transferred to Streamlit studio; use KML/KMZ/GeoJSON import on the studio page.
- Print studio currently reuses the existing separate page rather than editing a page within persistent Leaflet iframe.
- Complete disconnected operation still requires package-local Leaflet/JSZip assets, offline hosting/bootstrap, basemap licensing and packaging of user tile sets. Browser-imported ZIP tiles live only in the current page session.
- Print map is true PDF vector geometry; advanced print typography, source-watermarking, page template design and browser end-to-end QA still require refinement.
- Large files and browser drag/drop need end-to-end QA. Existing repo-wide tests have unrelated baseline failures.

## Regression gates
Use focused tests in tests/test_viewer_analysis_studio.py and tests/test_viewer_studio_extensions.py. Verify both print formats and multiple FLs with real coverage samples, plus reload and map-only mode.
