"""RF carriers verified against manufacturer's system descriptions.

PSR: Y7252A RL-2000, Main Parameters (four-frequency diversity).
SSR: ZG017A MSSR-1, transmitter / receiver sections.
PAR: Y8600 PAR-NG, Table 1 (two alternative four-frequency sets).

Never pass a documentation carrier into the terrain-LOS solver pretending it
makes it a calibrated detection model. It does not. Model outputs explicitly
separate REAL frequency-driven radar-equation diagnostics from relative
geometric coverage and unprovided calibration terms.
"""
from __future__ import annotations

import math

from par_y8600_spec import FREQUENCY_SET_1_MHZ,FREQUENCY_SET_2_MHZ
from radar_core import SSR_ASSUMPTIONS
from radar_equations import C_M_S,MonostaticBudget

RADAR_UI_MODES=("PSR","SSR","ASR","PAR")
PSR_RL2000_CARRIERS_MHZ=(2812,2828,2844,2860)
PSR_RL2000_BAND_MHZ=(2700,2900)
PSR_RL2000_CARRIER_TOLERANCE_MHZ=1
PSR_RL2000_PEAK_POWER_W=25_000.0
PSR_RL2000_LOW_BEAM_GAIN_DBI=34.3
PSR_RL2000_HIGH_BEAM_GAIN_DBI=33.3
PSR_REFERENCE_RCS_M2=2.0
SSR_INTERROGATION_MHZ=1030.0
SSR_REPLY_MHZ=1090.0
PAR_BAND_MHZ=(9100,9300)


def wavelength_m(frequency_mhz):
    """Free-space wavelength from the physical carrier, not a band midpoint."""
    frequency=float(frequency_mhz)
    if not math.isfinite(frequency) or frequency<=0:
        raise ValueError("Nosná frekvence musí být kladná.")
    return C_M_S/(frequency*1e6)


def radar_echo_power_dbw(frequency_mhz,slant_range_km,*,power_w,
                         tx_gain_dbi,rx_gain_dbi,rcs_m2=2.0):
    """Ideal monostatic received power before unknown system losses.

    The documented frequency, power, and nominal gain are inserted into
    the radar equation. This is NOT Pd or measured received power; no
    calibrated noise, pulse-compression gain or losses are supplied.
    """
    budget=MonostaticBudget(
        transmit_power_w=power_w,frequency_hz=frequency_mhz*1e6,
        tx_gain_dbi=tx_gain_dbi,rx_gain_dbi=rx_gain_dbi,
        rcs_m2=rcs_m2,receiver_bandwidth_hz=1.0)
    return budget.received_power_dbw(slant_range_km*1000)


def frequency_report(mode):
    if mode not in RADAR_UI_MODES:
        raise ValueError(f"Neznámý radarový systém: {mode!r}")
    if mode=="SSR":
        uplink=float(SSR_ASSUMPTIONS["uplink_mhz"])
        downlink=float(SSR_ASSUMPTIONS["downlink_mhz"])
        return {
            "headline":f"{uplink:g} / {downlink:g} MHz · MSSR-1",
            "method":"AKTIVNÍ VÝPOČET · Friis, dva jednosměrné spoje",
            "rows":(
                ("Vysílání / dotazování",f"{uplink:g} MHz",
                 f"λ = {wavelength_mhz_to_cm(uplink):.3f} cm · skutečně použito ve Friis uplinku."),
                ("Příjem / odpověď",f"{downlink:g} MHz",
                 f"λ = {wavelength_mhz_to_cm(downlink):.3f} cm · skutečně použito ve Friis downlinku."),
            ),
            "note":"ZG017A: vysílání 1030 MHz, příjem 1090 MHz. "
                   "Výkony a citlivosti modelu SSR jsou stále ilustrační "
                   "(SSR_ASSUMPTIONS), nikoli kalibrovaný MSSR-1.",
        }
    if mode=="PAR":
        one=tuple(int(f) for f in FREQUENCY_SET_1_MHZ)
        two=tuple(int(f) for f in FREQUENCY_SET_2_MHZ)
        return {
            "headline":"9100–9300 MHz · PAR-NG Y8600",
            "method":"FREKVENČNÍ FYZIKA · vlnová délka; krytí zatím relativní",
            "rows":(
                ("Y8600 · sada 1",", ".join(map(str,one))+" MHz",
                 "λ: "+", ".join(f"{wavelength_mhz_to_cm(f):.3f}" for f in one)+" cm"),
                ("Y8600 · sada 2",", ".join(map(str,two))+" MHz",
                 "λ: "+", ".join(f"{wavelength_mhz_to_cm(f):.3f}" for f in two)+" cm"),
            ),
            "note":"Y8600 uvádí 9100–9300 MHz, sadu 1 a alternativní sadu 2. "
                   "Výkon cca 300 W (lineární) / 600 W (eliptická). "
                   "Vzdálenostní terénní krytí není kalibrovaný Pd/SNR RF rozpočet: "
                   "chybí absolutní kalibrace AZ/EL antén a konkrétní ztráty.",
        }
    channels=PSR_RL2000_CARRIERS_MHZ
    samples=tuple(radar_echo_power_dbw(f,80*1.852,
        power_w=PSR_RL2000_PEAK_POWER_W,
        tx_gain_dbi=PSR_RL2000_LOW_BEAM_GAIN_DBI,
        rx_gain_dbi=PSR_RL2000_LOW_BEAM_GAIN_DBI,
        rcs_m2=PSR_REFERENCE_RCS_M2) for f in channels)
    rows=(
        ("RL-2000 · 4× frekvence",", ".join(map(str,channels))+" MHz",
         "±1 MHz jednotlivě · 2,7–2,9 GHz, jiné sady na objednávku"),
        ("Vlnové délky",", ".join(f"{wavelength_mhz_to_cm(f):.3f}" for f in channels)+" cm",
         "λ = c/f, skutečné čtyři frekvence"),
        ("Ideální echo na 80 NM / RCS 2 m²",
         ", ".join(f"{p:.2f}" for p in samples)+" dBW",
         "Výpočet monostatickou radarovou rovnicí: 25 kW, LOW 34,3 dBi "
         "na TX/RX; BEZ neznámých systémových ztrát a clutteru."),
    )
    return {
        "headline":"RL-2000 · 2812 / 2828 / 2844 / 2860 MHz",
        "method":"RF ROVNICE · skutečné 4 nosné pro ideální echo; krytí geometrické",
        "rows":rows,
        "note":("ASR zde představuje pouze PSR složku RL-2000, nikoliv "
                "integrovaný PSR+SSR model. " if mode=="ASR" else "")
               +"Y7252A dokládá 25 kW a LOW 34,3 dBi. "
               "Ideální echo není detekční pravděpodobnost, a proto dosavadní "
               "mapu terénního krytí svévolně nepřekalibrováváme.",
    }


def wavelength_mhz_to_cm(frequency_mhz):
    return wavelength_m(frequency_mhz)*100.0
