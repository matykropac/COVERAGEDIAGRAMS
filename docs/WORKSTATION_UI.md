# COVERAGEDIAGRAMS Workstation UI · Design & UX Specification

## Scope
This document defines the 2026 workstation redesign. It is a presentation
layer over the existing engineering engine: calculations, DEM sampling,
coverage polygons, obstacles, KML/KMZ and legacy reports remain in place.

## Visual identity
- Brand: COVERAGEDIAGRAMS / GEOSPATIAL ENGINEERING PLATFORM
- Primary ink: `#0B1626`; navigation: `#10243B`; panel: `#14283F`
- Accent cyan: `#63C9EF`; muted labels `#98B3CA`; high-contrast white text
- Radar emblem is an inline vector SVG maintained in `workspace_theme.py`.
- NIGHT is the default; map basemaps remain independently selectable.

## EDITOR workstation
- Top: brand/header + current project/radar and calculation status
- Left: six-icon rail for MAPA, RADAR, TERÉN, VRSTVY, AVIATION, EXPORT
- Beside the rail: context-sensitive controls; old controls are not deleted
- Right/main: one persistent map across all contextual tools
- Project actions: OPEN/SAVE CDPROJ remain near VIEWER entry.
- DEM options and actual coverage calculation retain existing radar engine.
- Selected presentation preferences are stored in CDPROJ metadata.

## VIEWER cartographic studio
- LEFT: condensed visibility/name/count grid; fixed-height scrolling for
  dozens of layers. No per-layer widgets stacked vertically.
- CENTER: 2D map / 3D hypsometry with always-visible map canvas.
- RIGHT: inspector for selected layer color, opacity and line width; presets,
  base map, custom title, legend and compass; print studio.
- Editor snapshot integrates available flight levels and sampled terrain.
- OpenTopography DEM dialog remains available for a separate 3D terrain source.
- PNG/PDF studio creates deliberate *vector-only* print compositions at
  300/600 DPI. Online map imagery is not embedded in those outputs.
- 2D/3D HTML exports remain available separately.

## File responsibilities
- `.cdproj`: reproducible radar matrices, sampled terrain, obstacle data
  and selected EDITOR visual preferences. Existing archive structure retained.
- `.cdview`: a separate compressed presentation workspace with imported
  vector features, style parameters and 2D/3D view state. It does not embed
  a DEM raster or API credentials.
- `.kml/.kmz/.geojson`: interoperability formats for geometry and coverage.
- `.png/.pdf`: customer-facing print products.

## Non-regression priorities
1. Never change `radar_core.solve` engineering semantics in a visual PR.
2. Preserve existing exports (including high-resolution coverage reports).
3. Keep OpenTopography API credentials in environment/session settings only.
4. No silent terrain synthesis: 3D surfaces require uploaded, downloaded or
   editor-sampled DEM data.
5. Test layer styling with 30+ layers and large polygon sets.
6. Validate Streamlit and Windows/macOS builds after UI changes.

## Relevant modules
- `workspace_theme.py`: shared colors, typography, SVG brand mark
- `map_workspace.py`: EDITOR rail, contextual tools and map
- `coverage_viewer.py`: VIEWER three-panel studio and 3D
- `viewer_export.py`: standalone print vector composer
- `viewer_workspace_file.py`: portable CDVIEW save/load
- `viewer_bridge.py`: secure per-session EDITOR-to-VIEWER data handoff
