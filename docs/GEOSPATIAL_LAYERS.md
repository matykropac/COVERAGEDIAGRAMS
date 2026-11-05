# COVERAGEDIAGRAMS — Environmental and aviation data

## Map layers (2026-11-05)

- OpenStreetMap / OpenTopoMap; satellite imagery, topographic/streets (legacy), shaded relief, hillshade, physical and terrain layers from Esri. Raster services can change or be retired without warning.
- OpenStreetMap objects, requested *on demand* through Overpass (0.5–10 km radius). Classes: building, forest/wood, tower/mast/chimney. The OSM data is © OpenStreetMap contributors, licensed ODbL 1.0. Displayed heights use explicit tags when present. Unknown heights are never treated as 0 m.
- OurAirports-derived airport codes open dataset (large, medium, small airports and heliports), information only.
- User-provided GeoJSON feature collections can be used for building, forest or tower footprints; supported properties include kind/class/type, height_m/height, name.
- User-provided canopy height GeoTIFF in **metres AGL** can be rendered as a color overlay. This is visualization only and does not alter the propagation model.
- Live traffic from ADSB.lol/Airplanes.live follows the existing implementation. CSV historical sample analysis supports columns lat, lon, altitude_m (or altitude_ft), optional icao24 and timestamp. This analysis compares **observed positions** to **geometric coverage**, not measured detection performance.

## Filters

Each map has independent type, known-height, unknown-height and distance controls. Source data is cached and is not fetched until requested. A maximum of 6000 environment polygons is drawn per map to keep browsers responsive; the filtered table and exports can contain more. The existing coverage model still supports no more than 1000 **active calculation obstacles** and has a manual conversion command for known-height building/tower polygons. The forest polygons and canopy raster are never automatically applied as opaque radar blockers.

## Exports

The Data/Exports tab has an on-demand ZIP containing a standalone HTML map with layer controls, overlays, legends and displayed coverage, plus filtered GeoJSON/KML/CSV, a PNG legend and optional canopy color raster with bounds metadata. The regular all-layer KML and QuickReport ZIP also include environment objects when they have been filtered in the Analysis tab. Native PNG/GPKG/GeoTIFF calculation exports are not transformed into layered GIS export formats: use the HTML/KML/GeoJSON bundle for those overlays.

## Important technical limitations

- Height sources in OSM and user datasets can be missing, inferred or outdated. The OSM building count is not a certified obstacle survey.
- GeoJSON imported height_m is assumed to be **metres AGL**. Users must verify their data CRS is WGS84 and their heights really are AGL.
- OSM landuse=forest or natural=wood is a *polygon coverage label*, not measured canopy height. CHM estimates depend on their specific provider and cannot be converted to a generic microwave attenuation model without calibration.
- Canopy-height raster is visually reprojected to WGS84 (max 900 × 900 pixels) for display; it is not used in geometric radar visibility.
- A DSM may already include buildings and vegetation: combining DSM with individually modeled obstacles can double-count them.
- Overpass services have rate limits; large-city queries may fail or be truncated. No automated scanning of large regions or background tile prefetch is performed.
- OpenStreetMap public tile usage policy prohibits bulk prefetching. © OpenStreetMap contributors: https://operations.osmfoundation.org/policies/tiles/
- ADS-B data is incomplete for aircraft lacking reception, visibility, transponder use or position reporting. This app is not an aviation safety system.

## Future engineering work (not implemented yet)

- Direct regional Microsoft/Overture footprints API and scalable spatial indexing for nationwide building imports.
- Certified eTOD/aeronautical obstacle dataset where a permitted source/license is available.
- Engineering-grade DTM/DSM/CHM fusion with vertical-datum handling, formal validation, and radar-specific foliage attenuation.
- Automated historical ADS-B archive ingestion, dependent on provider entitlement and archive format.
- Scalable ray/object intersection and performance tests for raising the 100 calculation-obstacle limit.
