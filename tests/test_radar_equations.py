"""Pure physics reference tests; do not require a measured radar preset."""
import math
import pytest
from radar_equations import (
    MonostaticBudget, friis_received_dbm, friis_max_range_m,
    C_M_S, BOLTZMANN_J_K,
)


def test_monostatic_inverse_fourth_power_range():
    b = MonostaticBudget(1000., 2.8e9, 34., 34., 1.,
                         1e6, noise_figure_db=3., system_loss_db=6.)
    assert b.snr_db(20_000) - b.snr_db(40_000) == pytest.approx(
        40 * math.log10(2), abs=1e-10)


def test_monostatic_absolute_received_power():
    b = MonostaticBudget(1000., 3e9, 30., 30., 1., 1e6)
    r = 10_000.
    lam = C_M_S / 3e9
    watts = 1000. * 10**3 * 10**3 * lam**2 / ((4*math.pi)**3 * r**4)
    assert b.received_power_dbw(r) == pytest.approx(10*math.log10(watts))
    noise_w = BOLTZMANN_J_K * 290. * 1e6
    assert b.noise_power_dbw() == pytest.approx(10*math.log10(noise_w))


def test_tx_rx_off_axis_and_propagation():
    b = MonostaticBudget(500., 9.2e9, 35., 34., 2., 2e6)
    original = b.snr_db(20_000)
    reduced = b.snr_db(20_000, tx_pattern_db=-2., rx_pattern_db=-3.,
                       propagation_loss_db=4.)
    assert reduced == pytest.approx(original - 9.)


def test_friis_downlink_and_inverse():
    distance = friis_max_range_m(51., 0., 27., -82., 1090e6, 9.)
    received = friis_received_dbm(51., 0., 27., 1090e6, distance, 9.)
    assert received == pytest.approx(-82., abs=1e-10)
    assert friis_received_dbm(51., 0., 27., 1090e6, distance * 2, 9.) == pytest.approx(
        received - 20 * math.log10(2.))


@pytest.mark.parametrize("field", ["transmit_power_w", "rcs_m2",
                                  "receiver_bandwidth_hz", "frequency_hz"])
def test_no_zero_missing_physical_inputs(field):
    params = dict(transmit_power_w=100., frequency_hz=3e9,
                  tx_gain_dbi=30., rx_gain_dbi=30., rcs_m2=1.,
                  receiver_bandwidth_hz=1e6)
    params[field] = 0.
    with pytest.raises(ValueError):
        MonostaticBudget(**params).snr_db(1000.)


def test_zero_range_rejected():
    with pytest.raises(ValueError):
        friis_received_dbm(60, 27, 0, 1030e6, 0)
