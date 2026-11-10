# PAR-NG antenna-channel selection (Y8600-based provisional model)

## UI

`RADAR → Nastavení radaru → 02 ANTÉNA → Výpočetní antény PAR-NG`:
- **HORIZONTAL · AZ** – evaluates the previous supplied 9 GHz gain grid.
- **VERTICAL · EL** – evaluates a separate, provisional electronically
  steered elevation channel in the Y8600 -1° .. +14° scanning window.
- **OBĚ · AZ + EL** – intersects the separate channel range envelopes
  (logical AND). No summation of SNR, power, gain or Pd.

The selection is part of `source_ui.par_model.channel_mode` in CDPROJ,
included in settings change detection and engineering calculation metadata.
Legacy CDPROJ archives that omitted this field are reopened in AZ-only mode
to preserve the historical single-pattern calculation semantics.

## Physical assumptions and major limitation

Y8600 documents two physical antennas: AZ with ≤0.9° horizontal HPBW
and cosecant-shaped vertical gain, and EL with ≤0.65° vertical HPBW and
broad horizontal gain. The operational full-scale scanner sectors are
±15° azimuth and -1° .. +14° elevation.

Only one source 3D gain grid is currently available. The application assumes
that it describes AZ (this attribution still requires evidence). The EL
channel is therefore an *uncalibrated, optimistic ideal electronic scan*:
0 dB normalized gain inside Y8600's instrumental scanning sector and
effectively no coverage outside. Beamwidth is not converted into fictitious
signal loss when steering actively follows the target. The EL approximation
uses the same provisional reference 40-km margin rather than verified
independent RF parameters.

`FIXED_3D` with EL or BOTH is rejected until an independent measured EL
gain grid is available. `TRACKING` is allowed but remains only a preliminary
geometric/relative-gain approximation. Neither mode establishes guaranteed
PAR target detection or acceptable ICAO detection probabilities.

## Further work for physical verification

Acquire the independent AZ and EL angular/frequency-dependent Tx/Rx antenna
patterns, verified frequency assignments, peak/average transmit power per
channel, channel-specific receiver noise/bandwidth and processing gains,
RCS reference, dwell/scan schedules, true scan losses and propagation
attenuation budgets. Replace the EL surrogate only with validated inputs.

The effective-earth DEM horizon and terrain LOS are still applied to the
selected channel(s). Atmospheric gas/rain loss, diffraction, fading and clutter
are not included in the current normalized channel calculation.
