"""Dimensionally checked free-space radar equations for PSR/PAR and SSR.

These equations are physically explicit, but a resulting detection probability
is NOT certified: propagation, RCS fluctuations, clutter, CFAR and processing
losses are external to the ideal thermal-noise calculation. Input parameters
must be sourced; this module intentionally contains no invented radar presets.
"""
from dataclasses import dataclass
import math

C_M_S = 299_792_458.0
BOLTZMANN_J_K = 1.380649e-23


def _positive(name, value):
    v = float(value)
    if not math.isfinite(v) or v <= 0:
        raise ValueError(f"{name} musí být kladné konečné číslo.")
    return v


def _finite(name, value):
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{name} musí být konečné číslo.")
    return v


def db(value):
    return 10.0 * math.log10(_positive("Výkonový poměr", value))


def friis_received_dbm(tx_dbm, tx_gain_dbi, rx_gain_dbi, frequency_hz,
                       range_m, loss_db=0.0):
    """One-way free-space Friis link, e.g. SSR 1030/1090 MHz."""
    f = _positive("Frekvence", frequency_hz)
    r = _positive("Vzdálenost", range_m)
    return (_finite("Pt", tx_dbm) + _finite("Gtx", tx_gain_dbi)
            + _finite("Grx", rx_gain_dbi)
            - 20.0 * math.log10(4.0 * math.pi * r * f / C_M_S)
            - _finite("Ztráty", loss_db))


def friis_max_range_m(tx_dbm, tx_gain_dbi, rx_gain_dbi, rx_threshold_dbm,
                      frequency_hz, loss_db=0.0):
    """Analytic one-way free-space reach at specified receiver threshold."""
    f = _positive("Frekvence", frequency_hz)
    numerator = (_finite("Pt", tx_dbm) + _finite("Gtx", tx_gain_dbi)
                 + _finite("Grx", rx_gain_dbi)
                 - _finite("Prahový výkon", rx_threshold_dbm)
                 - _finite("Ztráty", loss_db))
    return C_M_S / (4.0 * math.pi * f) * 10.0 ** (numerator / 20.0)


@dataclass(frozen=True)
class MonostaticBudget:
    """Absolute thermal-noise SNR from the standard monostatic radar equation.

    tx_gain_dbi and rx_gain_dbi are *absolute* gains, not normalized patterns.
    system_loss_db is a total two-way/instrument loss in dB (not one-way/km).
    integration_gain_db is net post-processing SNR gain or loss measured/assumed
    relative to one pulse. Pulses are not implicitly multiplied by their count.
    """
    transmit_power_w: float
    frequency_hz: float
    tx_gain_dbi: float
    rx_gain_dbi: float
    rcs_m2: float
    receiver_bandwidth_hz: float
    system_noise_temperature_k: float = 290.0
    noise_figure_db: float = 0.0
    system_loss_db: float = 0.0
    integration_gain_db: float = 0.0

    def validate(self):
        for name in ("transmit_power_w", "frequency_hz", "rcs_m2",
                     "receiver_bandwidth_hz", "system_noise_temperature_k"):
            _positive(name, getattr(self, name))
        for name in ("tx_gain_dbi", "rx_gain_dbi", "noise_figure_db",
                     "system_loss_db", "integration_gain_db"):
            _finite(name, getattr(self, name))
        if self.noise_figure_db < 0 or self.system_loss_db < 0:
            raise ValueError("NF a ztráty musí být nezáporné.")
        return self

    def received_power_dbw(self, slant_range_m, tx_pattern_db=0.0,
                           rx_pattern_db=0.0, propagation_loss_db=0.0):
        self.validate()
        r = _positive("Šikmá vzdálenost", slant_range_m)
        wavelength = C_M_S / self.frequency_hz
        return (db(self.transmit_power_w)
                + self.tx_gain_dbi + _finite("Tx pattern", tx_pattern_db)
                + self.rx_gain_dbi + _finite("Rx pattern", rx_pattern_db)
                + 20.0 * math.log10(wavelength)
                + db(self.rcs_m2)
                - 30.0 * math.log10(4.0 * math.pi)
                - 40.0 * math.log10(r)
                - self.system_loss_db
                - _finite("Propagace", propagation_loss_db))

    def noise_power_dbw(self):
        self.validate()
        return (db(BOLTZMANN_J_K * self.system_noise_temperature_k
                   * self.receiver_bandwidth_hz) + self.noise_figure_db)

    def snr_db(self, slant_range_m, tx_pattern_db=0.0,
               rx_pattern_db=0.0, propagation_loss_db=0.0):
        return (self.received_power_dbw(slant_range_m, tx_pattern_db,
                                        rx_pattern_db, propagation_loss_db)
                - self.noise_power_dbw() + self.integration_gain_db)

    def detection_margin_db(self, slant_range_m, required_snr_db,
                            tx_pattern_db=0.0, rx_pattern_db=0.0,
                            propagation_loss_db=0.0):
        return (self.snr_db(slant_range_m, tx_pattern_db, rx_pattern_db,
                            propagation_loss_db)
                - _finite("Minimální SNR", required_snr_db))
