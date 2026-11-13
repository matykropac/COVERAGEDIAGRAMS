# COVERAGEDIAGRAMS 2.0 — Technical Design (PROPOSED)
Date: 2026-11-13. Scope: engineering design only; new advanced modules are not yet delivered.

## Aim
Unify RF prediction, measured surveillance data, independent verification, replay, sensor network analyses and evidence-based SAT reports. Preserve the existing PSR/SSR/PAR solver and CDPROJ V1 compatibility. Inspired by EUROCONTROL SASS-C PREDICT/VERIF and historic RASS-S technical methods; not a certified replacement.

## Core architecture
1. **Sensor Registry:** immutable versioned PSR/SSR/PAR/ADS-B sensor specs, station location, antenna revision, source identifiers and clock properties.
2. **RF & Antenna Engine:** typed 1D and 3D AZ/EL patterns, channel-separated data, genuine measured/simulated classifications, HPBW, sidelobes and F/B; computed visibility never conflated with relative gain.
3. **Surveillance Data Hub:** ASTERIX CAT034/048/021/062, decoder profiles pinned to category **and edition**, raw source hashes, time normalization (UTC) and quality metadata.
4. **Prediction Engine:** legacy radar_core via adapter, deterministic inputs/outputs, versioned terrain/obstacle/antenna assumptions; configurable multi-sensor scenarios.
5. **Verification Engine:** track/reference association, valid detection opportunities, sensor health and uncertainty gating; PASS/FAIL/INCONCLUSIVE, never infer a verified gap from absence of a plot alone.
6. **Scenario/Reporting Engine:** before/after analyses, multi-radar redundancy, RF sensitivity, replay, SAT traceability, one Export Centre.

## Proposed contracts
- SensorDefinition: id/type/location/site_altitude_m_amsl/antenna_height_m_agl/orientation_true_deg/version/source IDs.
- AntennaPattern: id/revision/channel/polarization/az/EL axes/gain units measured vs modeled/source SHA256/assumptions.
- Observation: original ASTERIX record ID/category/edition/source sensor/time UTC/time uncertainty/original polar or Cartesian coordinates/derived WGS84/height reference/quality.
- Scenario: immutable sensor revisions, engine revision, terrain digest, obstacle set, target FL, RF assumption revision.
- Verification: reference track, expected opportunity, matching rules, reported data, confidence interval, result with evidence.
- Provenance: classification MEASURED | SIMULATED | DERIVED | UNKNOWN, producer, source checksum, transform, limitations, UTC timestamp.

## Engineering rules
- Never change legacy `radar_core.solve` or CDPROJ V1 semantics without a baseline/golden regression gate.
- Use explicit ft AMSL vs m AGL, true vs magnetic north, dB vs dBi, 1-way vs 2-way propagation.
- Antenna lab edits are sandboxed and never silently applied to the production radar solver.
- Separate raw immutable ASTERIX bytes from normalized records and user corrections.
- ASTERIX parsing requires independent category/edition definition, FSPEC/UAP/REF/SPF, block-length validation, limits on malformed records and exact decoded/undecoded reconciliation.
- Handle UTC midnight rollovers and clock synchronization uncertainty.
- A 200 MB upload is a transport limit, not permission for arbitrary expansion into memory; use bounded, streaming pipelines and chunked storage.
- Avoid pushing huge plot lists to Leaflet. Temporal/spatial indexing, sampling and LOD must precede display.
- No arbitrary uploaded Python execution on Streamlit server. Experiment expressions remain restricted until an isolated worker exists.
- Use real progress phases, errors and retry logs; do not invent percentage completion.

## Module roadmap / dependencies
### Stage 0 — Regression freeze and contracts
Create golden PSR 60/80/100 NM, SSR 256 NM and PAR +/-15° fixtures; assert FL catalogs, CDPROJ roundtrip, and stable map/export paths. Add contracts and tests.

### Stage 1 — Sensor Registry and Antenna Pattern Engine
Multi-sensor inventory, versioned pattern metadata and verified 1D/3D parser with measured vs model provenance; original raw files remain immutable.

### Stage 2 — ASTERIX ANALYZER and FLIGHT REPLAY
CAT034/048/021/062 framed streaming reads, edition-specific item decoding, WGS84/UTC normalization, chunked indexed data store, bounded replay windows. Raw records must be auditable.

### Stage 3 — COVERAGE VALIDATION, PREDICT VS MEASURED, SENSOR ALIGNMENT
Track association, independent reference and clock model, detection-opportunity gating, residuals by AZ/RANGE/FL, confidence/unknown masks, unbiased sensor alignment estimates.

### Stage 4 — MULTI-RADAR NETWORK, RF PERFORMANCE LAB, OBSTACLE IMPACT, INTERFERENCE
Union/intersection, >=N sensor redundancy, RF assumptions and sensitivity, reproducible before/after scenarios; advisory interference predictions clearly labeled.

### Stage 5 — COMPLIANCE/SAT and RADAR DIGITAL TWIN
Requirement->test->evidence->report audit trail, multi-module orchestrator and scenario versioning.

## Acceptance gates
- Existing solver outputs unchanged within explicitly set numeric tolerances using identical DEM and reference configuration.
- Existing projects load unchanged; new metadata opt-in and backward-readable.
- Source/type/uncertainty and standard edition visible in every derived analysis.
- No invalid ASTERIX record causes denial of service, silent dropping, or fallback to guessed edition.
- Synthetic test demonstrates that no active sensor or missing reference data yields INCONCLUSIVE, not confirmed failed coverage.
- Multi-radar redundancy matches synthetic geometry reference cases.
- Replay deterministic across out-of-order packets and midnight.
- Export Centre reports maintain provenance hashes and independent measured/simulated sections.

## First issues
CD2-001 golden reference outputs & CI; CD2-002 provenance/sensor contracts; CD2-003 sensor registry; CD2-004 3D antenna import; CD2-005 ASTERIX framed reader; CD2-006 timed observation store; CD2-007 replay; CD2-008 verification engine; CD2-009 network overlay; CD2-010 SAT reporting.

## References
- https://www.eurocontrol.int/online-tool/surveillance-analysis-support-system-atc-centres
- https://www.eurocontrol.int/sites/default/files/publication/files/surveillance-standard-document-for-radar-surveillance-in-en-route-airspace-and-major-terminal-areas199703.pdf
- https://www.eurocontrol.int/sites/default/files/2021-09/eurocontrol-ems-spec-ed-4-0.pdf
- https://www.eurocontrol.int/search?keywords=asterix
