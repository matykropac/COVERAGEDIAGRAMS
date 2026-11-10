# PAR-NG · AESA Scan and Coverage Engine

## Release scope (2026-11-10)

The PAR-NG application computes *preliminary* electronic scan envelopes with
separate AZ and EL antenna channels. It no longer treats the entire ±15°/−1…14°
instrumented sector as a single, fixed antenna radiation pattern.

Sources: Y8600 system description (pp. 16–19) and a provided
`3Dscan9GHz05deg(2).txt` numeric grid. The grid's actual assignment to AZ
or EL and the absolute antenna calibration are **not** established.

### User-facing modes

| Option | FAST | ENGINEERING |
|---|---|---|
| Angular gain | Precomputed shared AZ/EL lookup table | Direct channel gain evaluation |
| Beam steering | Nearest commanded azimuth/elevation beam | Same steering assumptions evaluated directly |
| Geometry | Common DEM + effective Earth horizon | Same DEM + effective Earth horizon |
| Atmosphere | User-entered two-way attenuation | Same user-entered two-way attenuation |
| Detection | Normalized range margin | Normalized range margin (not validated Pd) |
| Channel combination | AZ / EL / BOTH | AZ / EL / BOTH |
| Calibration | Provisional | Provisional |

ENGINEERING is numerically more direct, **not** validated or certified.
Both modes use the same preliminary RF assumptions and should not be reported
as operational target detection performance.

### Signal model

At each cell with elevation `e`, relative azimuth `a` and actual slant
distance `R`, choose the nearest permitted commanded beam direction along
the relevant scan axis; apply normalized directional gain, assumed scan loss,
range attenuation and an optional assumed detection margin.

For each channel independently, the normalized margin (dB) is

```
M_i = 40 log10(Rref/R)
      + 40 log10(f_i(e,a))  - 2 * (Lgas + Lrain) * R[km] - Lmisc
```

where `f_i` is the channel-specific normalized range factor calculated from
the directionally scanned antenna model. `Rref = 40 km` is an unverified
normalization, not a measured radar detection performance point.
All loss values are editable assumptions, not site weather measurements.
Both-channel coverage means both `M_AZ >= 0` and `M_EL >= 0` with
geometric visibility. **No addition of the channels' SNR or antenna gain.**

### Y8600 beam and steering assumptions

- AZ antenna: electronic horizontal steering ±15°, documented ≤0.9°
  azimuth HPBW and broad cosecant-shaped vertical response.
- EL antenna: electronic vertical steering −1°…+14°, documented ≤0.65°
  elevation HPBW and broad horizontal response.
- AZ pattern: uses the supplied 9 GHz 3D grid as a provisional AZ response.
- EL pattern: **analytic, synthetic** Gaussian narrow-axis beam of 0.65°
  HPBW, with a flat broad-plane assumption. Not calibrated or measured.
- Default command spacing of 0.3° AZ / 0.2° EL is a user-adjustable
  **simulation** sequence, not an actual PAR-NG timing program.
- Actual frequency assignments per channel, the RF link budget, pulse dwell
  timing and beam-dependent scan losses have not yet been validated.

### Computational optimization

1. **Angular LUT:** `par_scan_engine.py` caches 2D normalized range-factor
   surfaces with a signature of antenna source SHA-256, scan, detection and
   steering parameters. Repeated heights use the same interpolated surfaces.
2. **Separate terrain geometry:** one DEM polar grid, terrain horizon,
   upper/lower height bounds and known-data mask across the selected channel.
3. **Independent channel masks:** `par_channel_status_at_height` produces
   AZ, EL, BOTH, each normalized margin, and limiting channel.
4. **Local browser visualization:** map polygon layers update separately from
   radar DEM sampling; no repeated OpenTopography downloads for channel changes.
5. **Direct ENGINEERING evaluation:** bypasses interpolation, allowing numerical
   comparisons to FAST. The engine does *not* replay actual real-time pulses.

### UI and export

- RADAR → CÍL / FL: FAST / ENGINEERING and user-entered gas, rain and
  miscellaneous attenuation.
- RADAR → ANTÉNA: AZ, EL or BOTH; editable commanded beam steps.
- MAPA → PAR VRSTVA KRYTÍ: active setting, AZ, EL, BOTH or LIMITING CHANNEL.
- EXPORT → PAR diagnostic ZIP: AZ, EL, BOTH and 2 limiting-channel GeoJSON
  files plus 2D RF-margin grids in compressed NumPy NPZ, and a manifest with
  data provenance and physical limitations.
- CDPROJ retains model parameters including scan steps, mode, attenuation
  assumptions and active antenna channel. Older projects retain AZ-only
  legacy behavior if they do not carry an antenna-mode field.

### Missing validation inputs before operational use

- Independently verified and correctly assigned AZ and EL beam patterns
  (including measurements at multiple electronically steered directions).
- Absolute antenna gains, frequency mappings, transmitter power per channel,
  receiver NF/temperature/bandwidth, system losses and pulse compression gain.
- Actual steering schedules, dwell time, pulse integration, CFAR/MTD/clutter
  effects and channel decision/association logic.
- Weather profiles and model-based gaseous/rain attenuation, multipath,
  diffraction and terrain-scattering losses.
- Comparison against field measurements or accepted radar performance tests.

**No output should be called guaranteed coverage, validated Pd or Y8600
certification.**
