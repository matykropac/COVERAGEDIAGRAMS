from dataclasses import asdict
import radar_core as core
from project_widgets import restored_widget_values


def test_par_project_restores_all_user_parameters():
    c = core.Config(radar_mode='PAR-NG', range_km=40, csc_range_km=40,
                    antenna_agl=37.5, bearing_deg=213.25,
                    antenna_tilt_deg=-2.75, min_elev=-1.5, max_elev=25.,
                    lat=49.8, lon=15.4, step_m=100, az_step=.5,
                    k=1.2, target_m=850., reference='AMSL')
    values = restored_widget_values(c, {
        'levels': [50, 200, 500],
        'source_ui': {'source':'OpenTopography','dataset':'COP30'},
        'display': {'mode':'Porovnání','opacity':.65}
    })
    assert values['radar'] == 'PAR'
    assert values['agl'] == 37.5
    assert values['bearing'] == 213.25
    assert values['tilt'] == -2.75
    assert values['min_elev'] == -1.5
    assert values['max_elev'] == 25.
    assert values['step_PAR-NG'] == 100
    assert values['azstep'] == .5
    assert values['target'] == 850.
    assert values['levels'] == [50,200,500]


def test_psr_restore_modes():
    c = core.Config(radar_mode='RL-2000', range_km=80*core.NM_TO_KM)
    values = restored_widget_values(c, {'levels':[3000], 'source_ui':{}})
    assert values['radar'] == 'PSR'
    assert values['psr_range_nm'] == 80
    assert values['agl'] == c.antenna_agl
    assert values['tilt'] == c.antenna_tilt_deg
