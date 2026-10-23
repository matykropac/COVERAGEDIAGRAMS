"""Configuration-to-widget mapping: shared by UI and non-UI regression tests."""
import radar_core as core


def restored_widget_values(config, meta):
    """One complete mapping from saved Config to actual Streamlit widget keys."""
    mode = {'RL-2000': 'PSR', 'PAR-NG': 'PAR', 'SSR': 'SSR'}[config.radar_mode]
    values = {
        'radar': mode,
        'lat': float(config.lat), 'lon': float(config.lon),
        'agl': float(config.antenna_agl), 'bearing': float(config.bearing_deg),
        'azstep': float(config.az_step), 'k_factor': float(config.k),
        'min_elev': float(config.min_elev), 'max_elev': float(config.max_elev),
        'tilt': float(config.antenna_tilt_deg),
        'beam': config.beam_mode, 'target': float(config.target_m),
        'reference': config.reference,
        'step_' + config.radar_mode: int(config.step_m),
        'levels': list(meta['levels']),
        'source': meta.get('source_ui', {}).get('source', 'Syntetické demo'),
        'analysis_layer_mode': meta.get('display', {}).get('mode', 'Jedna hladina'),
        'analysis_global_opacity': float(meta.get('display', {}).get('opacity', .45)),
    }
    if mode == 'PSR':
        values['psr_range_nm'] = min(core.PSR_RANGES_NM,
            key=lambda nm: abs(nm * core.NM_TO_KM - config.range_km))
    if mode == 'SSR':
        values['ssr_pattern'] = meta.get('source_ui', {}).get('ssr_pattern', 'Measured SSR.txt')
    dataset = meta.get('source_ui', {}).get('dataset', 'COP30')
    if dataset in core.DATASETS:
        values['dataset_' + config.radar_mode] = dataset
    return values

