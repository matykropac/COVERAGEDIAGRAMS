"""Truthful RF-frequency inventory for the current coverage solvers.

No user-interface change here may imply a transmit channel is simulated when
the coverage engine never consumes it. The two SSR carriers are consumed by
GenericSSRPattern.link_ranges_km via the Friis free-space equation. PSR and
ASR use the RL-2000 geometric/relative-gain model with no carrier frequency.
PAR Y8600 channel sets are documented references only; there is no configured
RF-channel selection in the current coverage solver.
"""
from __future__ import annotations

from par_y8600_spec import FREQUENCY_SET_1_MHZ, FREQUENCY_SET_2_MHZ
from radar_core import SSR_ASSUMPTIONS

RADAR_UI_MODES=("PSR","SSR","ASR","PAR")


def frequency_report(mode: str) -> dict:
    """Return source-backed, UI-friendly frequencies and actual usage."""
    if mode not in RADAR_UI_MODES:
        raise ValueError(f"Neznámý radarový systém: {mode!r}")
    if mode=="SSR":
        uplink=float(SSR_ASSUMPTIONS["uplink_mhz"])
        downlink=float(SSR_ASSUMPTIONS["downlink_mhz"])
        return {
            "headline":f"{uplink:g} / {downlink:g} MHz",
            "method":"AKTIVNÍ VÝPOČET · Friis, dva jednosměrné spoje",
            "rows":(
                ("Dotazovač → odpovídač",f"{uplink:g} MHz",
                 "Používá se v modelovém útlumu / maximálním dosahu uplinku."),
                ("Odpovídač → radar",f"{downlink:g} MHz",
                 "Používá se v modelovém útlumu / maximálním dosahu downlinku."),
            ),
            "note":(
                "Frekvence jsou skutečně dosazeny do rovnic. Výkon, zisky "
                "a citlivosti však pocházejí z ilustračních SSR_ASSUMPTIONS, "
                "nikoli z kalibrovaných dat konkrétního radaru."
            ),
        }
    if mode=="PAR":
        one=tuple(int(f) for f in FREQUENCY_SET_1_MHZ)
        two=tuple(int(f) for f in FREQUENCY_SET_2_MHZ)
        return {
            "headline":"9,11–9,28 GHz · Y8600",
            "method":"DOKUMENTOVANÉ KANÁLY · NEPOUŽITÉ V RF ROVNICI",
            "rows":(
                ("Y8600 · sada 1",", ".join(map(str,one))+" MHz",
                 "Dokumentované kanály, aktuálně bez výběru pro solver."),
                ("Y8600 · sada 2",", ".join(map(str,two))+" MHz",
                 "Dokumentované kanály, aktuálně bez výběru pro solver."),
            ),
            "note":(
                "Krytí PAR počítá relativní 3D anténní vzor a modelové "
                "propagační ztráty. Jednotlivé nosné frekvence se nepřepínají "
                "a frekvenčně specifický RF link-budget není kalibrován."
            ),
        }
    return {
        "headline":"Nosná frekvence není nastavena",
        "method":"GEOMETRICKÝ MODEL · bez nosné frekvence v rovnici",
        "rows":(
            ("Model", "RL-2000 · relativní anténní vzor",
             "Výpočet horizontu, terénního LOS a relativní obálky pokrytí."),
        ),
        "note":(
            ("ASR je zatím samostatný ovládací profil stejného PSR solveru. "
             if mode=="ASR" else "")
            +"Nelze tvrdit, že je používána konkrétní nosná PSR/ASR "
            "frekvence nebo frekvenčně závislá radarová rovnice."
        ),
    }
