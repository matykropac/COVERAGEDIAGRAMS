# VIEWER Studio 2.0 · staged upgrade

## Architectural invariants

- Keep one Leaflet map instance and the existing Streamlit handoff.
- Never mutate original imported GeoJSON or radar calculation arrays.
- Rendering changes are reversible and never evidence of new RF coverage.
- Retain existing CDVIEW import/export, DEM LOS inspector, and vector print export.
- Avoid introducing new mandatory CDNs beyond the current Leaflet/JSZip dependencies.

## Phase 1 · implemented on this branch

- **Advanced Layer Styling**: technical/presentation/monochrome presets; per-layer
  editor, including outline smoothing (default 0 NM), remains available.
- **Layer Z-order**: move layers up/down via adjacent buttons; order is reflected
  in active Leaflet vector stacking.
- **FL Animation**: cycles existing RADAR / ... ft layer names, preserving other
  layers, and restores visibility on stop. No new coverage computations.
- **Coverage Statistics (initial)**: estimated spherical area for polygon and
  multipolygon geometries, subtracting holes. Values are sums of individual
  polygons, **not** spatial union, and overlapping regions are double-counted.
  Do not interpret these numbers as coverage percentage.
- **Snapshots**: stores camera, background selection and layer style references
  in browser localStorage (max 20); never stores underlying geodata.

## Phase 2 · implementation specification

1. **Coverage Compare**: choose baseline/target from the *same AMSL FL* and
   compatible coordinate/reference systems; compute intersection, symmetric
   difference, gained and lost with validated topology (GEOS/Shapely server-side).
   Keep derived features in a separate read-only namespace and track source IDs.
2. **Statistics**: use equal-area reprojection (or geodesic polygon area), spatial
   union to prevent double-counting, and AZ/RANGE radial intersections for
   sector completeness. Report explicit analysis bounds and no-data separately.
3. **Inspector**: retain native computed masks and DEM LOS, add source provenance,
   original-vs-smoothed boundary indication, obstacle details where available.
   Never infer RF detection from a DEM-only profile.

## Phase 3 · implementation specification

1. **Map Composer**: extend existing viewer_export.py to paper size and orientation,
   map grid, north arrow, legend, range scale and metadata. Export 300/600 dpi
   raster + vector PDF; maintain correct attribution and offline tile limitations.
2. **Cartographic Tools**: geodesic azimuth and distance, selectable WGS84
   coordinate grid and editable annotations stored apart from coverage geometry.
3. **Offline**: locally packaged Leaflet + optional user-owned legal offline
   basemap tiles (MBTiles/PMTiles or equivalent). A snapshot alone is *not* a
   standalone offline map.
4. **Quality**: browser-based end-to-end checks on large KML/KMZ, polygon holes,
   multiple radars, hundreds of FL layers, repeated import/remove/play cycles.

## Deployment gate

This branch is an incremental implementation and requires CI plus browser
smoke testing before merging into main. It does not claim Phase 2/3 completed.
