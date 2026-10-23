"""Run: streamlit run streamlit_app.py"""
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import tempfile
import threading
import time

import folium
from folium.plugins import Fullscreen, MeasureControl
import matplotlib
matplotlib.use('Agg')
from matplotlib.figure import Figure
from matplotlib.colors import to_hex
import numpy as np
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

import radar_core as core
from ssr_custom import load_measured_ssr
from obstacles import apply_obstacles, square_corners
# Fail with a useful diagnostic if Streamlit Cloud has mixed deployment revisions.
_REQUIRED_CORE_API = ('PSR_RANGES_NM', 'radar_preset', 'generic_ssr_pattern', 'SSR_RANGE_KM')
_missing_core_api = [name for name in _REQUIRED_CORE_API if not hasattr(core, name)]
if _missing_core_api:
    import importlib
    importlib.invalidate_caches()
    core = importlib.reload(core)
    _missing_core_api = [name for name in _REQUIRED_CORE_API if not hasattr(core, name)]
    if _missing_core_api:
        raise RuntimeError(
            "Radar core and Streamlit app are from different revisions. "
            f"Missing: {', '.join(_missing_core_api)}. "
            f"Loaded radar_core from: {getattr(core, '__file__', '?')}. "
            "Reboot the Streamlit Cloud app to deploy all files from the same commit."
        )
from web_support import EXPORTS, HoverDetail, clicked_point, coverage_geojson, export_bytes

st.set_page_config(page_title='ELDIS · Radar Coverage', page_icon='📡', layout='wide')
# Centralized ATM stylesheet. Keep widget spacing and colors in one place.
st.markdown('<style>' + (Path(__file__).resolve().parent / 'assets' / 'atm-theme.css').read_text(encoding='utf-8') + '</style>', unsafe_allow_html=True)


@st.cache_resource
def plot_lock():
    return threading.RLock()


# Antenna patterns must not be cached across Streamlit hot-reloads:
# stale class instances can outlive updates to radar_core / ssr_custom.
def antenna(mode, ssr_pattern='Measured SSR.txt'):
    if mode == 'SSR':
        return load_measured_ssr() if ssr_pattern == 'Measured SSR.txt' else core.generic_ssr_pattern()
    return core.builtin_par_pattern() if mode == 'PAR-NG' else core.rl2000_dual_beam_pattern()


def figure(draw, **kwargs):
    with plot_lock():
        fig = Figure(figsize=(7, 5), facecolor=core.PLOT_BG)
        try:
            draw(fig, **kwargs)
            st.pyplot(fig, use_container_width=True)
        finally:
            fig.clear()


st.markdown('''<div class="atm-hero">
  <div><div class="atm-eyebrow">RADAR SYSTEMS · ENGINEERING WORKSTATION</div>
  <div class="atm-title">RADAR COVERAGE ANALYSIS</div>
  <div class="atm-description">PSR / PAR / SSR &nbsp;·&nbsp; Terrain visibility &nbsp;·&nbsp; ATM evaluation</div></div>
  <div class="atm-brand">ELDIS<small>RADAR SYSTEMS</small></div>
</div>''', unsafe_allow_html=True)
settings, obstacles_tab, analysis, raw = st.tabs(['NASTAVENÍ', 'OBSTACLES', 'MAPA / ANALÝZA', 'DATA / EXPORTY'])

with settings:
    location, parameters, preview, execution = st.columns([22, 22, 34, 22], gap='small')
    with location:
        st.subheader('01 / Radar a stanoviště')
        radar_label = st.selectbox('Radar', ['PSR', 'PAR', 'SSR'], key='radar')
        radar = {'PSR': 'RL-2000', 'PAR': 'PAR-NG', 'SSR': 'SSR'}[radar_label]
        ssr = radar == 'SSR'
        par = radar == 'PAR-NG'
        ssr_pattern = st.selectbox('SSR antenna diagram', ['Measured SSR.txt', 'Generic Gaussian'], disabled=not ssr, key='ssr_pattern')
        lat = st.number_input('Zeměpisná šířka [°]', -80., 80., 50.034, format='%.6f', key='lat')
        lon = st.number_input('Zeměpisná délka [°]', -180., 180., 15.781, format='%.6f', key='lon')
        agl = st.number_input('Anténa [m AGL]', .1, 5000., 20.)
        bearing = st.number_input('Azimut osy [°]', 0., 359.99, 0., disabled=not par)
        if par:
            st.caption('PAR-NG: ±20° od osy · 40 km · vestavěný diagram')
        elif ssr:
            st.caption('SSR: 360° · pevný limit 256 NM · obecný orientační model')
            with st.expander('Předpoklady SSR modelu'):
                st.markdown('''Dotaz **1030 MHz** a odpověď **1090 MHz** se posuzují samostatně.
Krytí omezuje slabší spoj, šikmá dálka 256 NM a viditelnost nad terénem.

Idealizovaná anténa: zisk 27 dBi, maximum 8° před tiltem, šířka 20° při −3 dB.
Dotazovač 1 kW / transpondér přibližně 126 W; prahy −74 / −82 dBm.
Anténa letadla 0 dBi; každý spoj má ztráty 3 dB a rezervu 6 dB.

**Ilustrační předpoklady, nikoli parametry konkrétního radaru.**
Bez multipath, difrakce, rušení, garblingu, SLS a výpočtu pravděpodobnosti detekce.''')
        else:
            st.caption('PSR: RL-2000 · 360° · vestavěný LOW / HIGH diagram')
        source = st.selectbox('Zdroj terénu', ['Syntetické demo', 'Nahrát DEM', 'OpenTopography'], key='source')
        uploaded = None
        api_key = ''
        dataset = 'COP30'
        if source == 'Nahrát DEM':
            uploaded = st.file_uploader('GeoTIFF / DTED / SRTM', type=['tif', 'tiff', 'dt0', 'dt1', 'dt2', 'hgt'])
        elif source == 'OpenTopography':
            dataset = st.selectbox('Výškový model', ('COP90', 'SRTMGL3') if ssr else core.DATASETS, key='dataset_'+radar)
            if ssr:
                st.caption('Pro oblast 256 NM používáme 90m DEM kvůli limitu velikosti OpenTopography.')
            import os
            api_key = os.environ.get('OPENTOPOGRAPHY_API_KEY', '').strip()
            if not api_key:
                try:
                    api_key = str(st.secrets.get('OPENTOPOGRAPHY_API_KEY', '')).strip()
                except (FileNotFoundError, KeyError):
                    api_key = ''
            if api_key:
                st.caption('OpenTopography API klíč je automaticky načten ze zabezpečeného nastavení aplikace.')
            else:
                api_key = st.text_input('OpenTopography API klíč', type='password', key='opentopo_key')
                st.caption('Pro trvalé automatické načítání nastav OPENTOPOGRAPHY_API_KEY v Streamlit Cloud Secrets.')
        else:
            st.caption('Demo používá umělý terén, nikoli skutečné okolí stanoviště.')
    with parameters:
        st.subheader('02 / Parametry výpočtu')
        if radar == 'RL-2000':
            psr_nm = st.selectbox('Dosah PSR [NM]', core.PSR_RANGES_NM, index=2, key='psr_range_nm')
        else:
            psr_nm = 100
        radius_input = range_ref_input = core.radar_preset(radar, psr_nm)
        st.caption(f'Dosah: {radius_input:g} km · stejný limit referenční šikmé dálky')
        step = st.select_slider('Radiální krok [m]', [25, 50, 100, 250, 500, 1000, 2000],
                               value=1000 if ssr else (250 if par else 500), key='step_'+radar)
        azstep = st.select_slider('Krok azimutu [°]', [.25, .5, 1., 2., 2.5, 5.], value=1.)
        k = st.number_input('Efektivní poloměr Země · k', .5, 3., 4/3, format='%.4f')
        min_elev = st.number_input('Minimální elevace [°]', -5., 88., -1.0, key='min_elev')
        max_elev = st.number_input('Maximální elevace [°]', -4., 89., 45., key='max_elev')
        tilt = st.number_input('Tilt antény [°]', -15., 15., -1.0)
        beam = st.selectbox('Svazek', ['COMBINED', 'LOW', 'HIGH'], disabled=par or ssr)
        target = st.number_input('Výška cíle [m]', -500., 30000., 1000.)
        reference = st.selectbox('Reference cíle', ['AMSL', 'AGL'])
    c = core.Config(lat=lat, lon=lon, antenna_agl=agl, radar_mode=radar, bearing_deg=bearing,
                    range_km=40. if par else radius_input, csc_range_km=40. if par else range_ref_input,
                    step_m=float(step), az_step=float(azstep), k=k, min_elev=min_elev, max_elev=max_elev,
                    antenna_tilt_deg=tilt, beam_mode='COMBINED' if par or ssr else beam,
                    target_m=target, reference=reference, csc_enabled=True)
    with preview:
        st.subheader('03 / Vyzařovací diagram')
        try:
            c.validate()
            figure(core.technical_plot, config=c, pattern=antenna(radar, ssr_pattern))
            st.caption('Náhled: orientační výška stanoviště 200 m AMSL.')
        except ValueError as exc:
            st.warning(str(exc))
    with execution:
        st.subheader('04 / Výpočet a stav')
        st.caption('Zvol hladiny, spusť výpočet a sleduj průběh jednotlivých kroků.')
        levels = st.multiselect('Výškové řezy [ft AMSL] · nominální ISA', core.FLIGHT_LEVELS_LIST,
                                default=[3000, 10000], format_func=core.level_label, key='levels')
        calculate = st.button('Vypočítat krytí', type='primary', key='calculate', use_container_width=True)
        log_view = st.empty()
        log_messages = []
        def log(message):
            stamp = datetime.now().strftime('%H:%M:%S')
            entry = str(message)
            if not log_messages or log_messages[-1][1] != entry:
                log_messages.append((stamp, entry))
            log_view.code('\n'.join(f'[{t}] {m}' for t, m in log_messages[-16:]), language=None)
        if not calculate and st.session_state.get('last_compute_log'):
            log_view.code(st.session_state['last_compute_log'], language=None)
        if calculate:
            progress = st.empty()
            try:
                c.validate()
                az, distance = core.axes(c)
                if len(az) * len(distance) > 250_000:
                    raise ValueError('Webová verze: nejvýše 250 000 bodů. Zvětši krok pro plynulou mapu.')
                start = time.perf_counter()
                def report(message, *args):
                    log(message)
                    progress.info(message)
                log(f'Počáteční kontrola OK · {len(az) * len(distance):,} vzorků')
                with st.spinner('Počítám terén a krytí…'):
                    log('Připravuji digitální model terénu…')
                    if source == 'Syntetické demo':
                        terrain, ground = core.demo_terrain(c)
                        provenance = 'SYNTHETIC DEMO'
                    elif source == 'Nahrát DEM':
                        if uploaded is None:
                            raise ValueError('Nejprve nahraj soubor DEM.')
                        with tempfile.TemporaryDirectory(prefix='radar_dem_') as directory:
                            path = Path(directory) / ('terrain' + Path(uploaded.name).suffix.lower())
                            content = uploaded.getvalue()
                            path.write_bytes(content)
                            terrain, ground = core.sample(path, c, report)
                            provenance = 'DEM upload · SHA256 ' + hashlib.sha256(content).hexdigest()
                    else:
                        path = core.download(c, api_key, dataset, report)
                        terrain, ground = core.sample(path, c, report)
                        provenance = 'OpenTopography · ' + dataset
                    log(f'Terén připraven · výška stanoviště {ground:.1f} m AMSL')
                    log('Počítám terénní horizont a radarové krytí…')
                    new_result = core.solve(c, terrain, ground, antenna(radar, ssr_pattern))
                    log(f"Započítávám překážky: {len(st.session_state.get('obstacles', []))}")
                    apply_obstacles(new_result, st.session_state.get('obstacles', []))
                    new_result['obstacles_signature'] = tuple((o['lat'], o['lon'], o['height_m']) for o in st.session_state.get('obstacles', []))
                    new_result.update(source=provenance, completed_at=datetime.now(timezone.utc).isoformat(),
                                      duration_s=round(time.perf_counter()-start, 3))
                    st.session_state.result = new_result
                    st.session_state.geometry = {}
                    st.session_state.pop('export', None)
                    st.session_state.pop('selected_point', None)
                    st.session_state.pop('last_map_click', None)
                    st.session_state.profile_index = len(az)//2 if par else 0
                    st.session_state.source_signature = (source, dataset, uploaded.file_id if uploaded is not None else None)
                log(f"Hotovo · {new_result['duration_s']:.2f} s")
                st.success('Výpočet dokončen. Výsledek je v záložce MAPA / ANALÝZA.')
            except Exception as exc:
                # The download routine already redacts API credentials from its errors.
                message = str(exc).replace(api_key, '[skryto]') if api_key else str(exc)
                log('CHYBA: ' + message)
                st.error('Výpočet se nepodařil: ' + message)
            finally:
                st.session_state['last_compute_log'] = '\n'.join(f'[{t}] {m}' for t, m in log_messages[-30:])
                progress.empty()


# Obstacles are stored per browser session. Placement is independent of the
# coverage sampling grid, so a 10 m object is not lost in a 500 m grid cell.
with obstacles_tab:
    st.subheader('OBSTACLES / Překážky v blízkosti radaru')
    st.caption('Přibliž mapu a kliknutím vlož překážku 10 × 10 m. Výška je nad místním terénem. '
               'Po úpravě spusť znovu Vypočítat krytí v NASTAVENÍ.')
    if 'obstacles' not in st.session_state:
        st.session_state.obstacles = []
    height_input, count_col = st.columns([1, 2])
    with height_input:
        obstacle_height = st.number_input('Výška nové překážky [m AGL]', min_value=0.1,
                                          max_value=1000.0, value=20.0, step=1.0)
    with count_col:
        st.caption(f"Počet překážek: {len(st.session_state.obstacles)} / 100")
    om = folium.Map(location=[lat, lon], zoom_start=17, tiles=None, control_scale=True)
    for name, provider in core.BASEMAP_PROVIDERS.items():
        folium.TileLayer(provider['url'], name=name, attr=provider['attribution'],
                         max_zoom=provider['max_zoom'], overlay=False,
                         show=name=='OpenStreetMap').add_to(om)
    folium.Marker([lat, lon], tooltip='Radar', icon=folium.Icon(color='orange', icon='signal')).add_to(om)
    for i, item in enumerate(st.session_state.obstacles):
        folium.Polygon(square_corners(item['lat'], item['lon']),
                       color='#ff7043', weight=2, fill=True, fill_opacity=.5,
                       tooltip=f"#{i+1}: 10 × 10 m, {item['height_m']:g} m AGL").add_to(om)
    folium.LayerControl().add_to(om)
    Fullscreen().add_to(om)
    oe = st_folium(om, height=465, use_container_width=True, key='obstacle_map',
                   returned_objects=['last_clicked'])
    oc = (oe or {}).get('last_clicked')
    if oc and oc != st.session_state.get('obstacle_last_click'):
        st.session_state.obstacle_last_click = oc
        if len(st.session_state.obstacles) < 100:
            st.session_state.obstacles.append(dict(lat=float(oc['lat']), lon=float(oc['lng']),
                                                    height_m=float(obstacle_height)))
            st.rerun()
        else:
            st.warning('Maximum je 100 překážek.')
    if st.session_state.obstacles:
        names = [f"#{i+1} · {o['height_m']:g} m · {o['lat']:.6f}, {o['lon']:.6f}"
                 for i,o in enumerate(st.session_state.obstacles)]
        edit_col, h_col, delete_col = st.columns([3, 1, 1])
        with edit_col:
            selected = st.selectbox('Upravit překážku', range(len(names)),
                                    format_func=lambda idx: names[idx])
        with h_col:
            new_height = st.number_input('Výška [m]', min_value=.1, max_value=1000.,
                                          value=float(st.session_state.obstacles[selected]['height_m']),
                                          key=f"height_edit_{selected}")
            if abs(new_height-st.session_state.obstacles[selected]['height_m']) > 1e-8:
                st.session_state.obstacles[selected]['height_m'] = new_height
                st.rerun()
        with delete_col:
            if st.button('Odstranit', key='remove_obstacle'):
                st.session_state.obstacles.pop(selected)
                st.session_state.pop('obstacle_last_click', None)
                st.rerun()

result = st.session_state.get('result')
if result is None:
    with analysis:
        st.info('V záložce NASTAVENÍ zvol radar a zdroj DEM a spusť výpočet.')
    with raw:
        st.info('Data a exporty se objeví po úspěšném výpočtu.')
else:
    rc = result['config']
    source_signature = (source, dataset, uploaded.file_id if uploaded is not None else None)
    with analysis:
        if (asdict(c) != asdict(rc) or source_signature != st.session_state.source_signature
                or result.get('obstacles_signature') != tuple((o['lat'], o['lon'], o['height_m']) for o in st.session_state.obstacles)):
            st.warning('Nastavení se změnilo. Mapa a exporty stále patří k poslednímu úspěšnému výpočtu.')
        if result['source'] == 'SYNTHETIC DEMO':
            st.warning('SYNTETICKÝ TERÉN — NEJDE O SKUTEČNÉ KRYTÍ STANOVIŠTĚ.')
        st.caption(f"{rc.radar_mode} · {rc.lat:.6f}°, {rc.lon:.6f}° · {rc.range_km:g} km · "
                   f"{result['completed_at']} · {result['duration_s']:g} s")
        legend, mapcol, profile = st.columns([20, 55, 25])
        with legend:
            st.subheader('DISPLAY CONTROL / Hladiny')
            # One selected layer by default: no duplicated opacity sliders and
            # no animated layer toggles that shift the entire sidebar.
            available_levels = list(levels)
            display_mode = st.radio('Zobrazení', ['Jedna hladina', 'Porovnání', 'Cíl'],
                                    horizontal=False, key='analysis_layer_mode')
            alpha = st.slider('Průhlednost vrstev', 0., 1., .45, .05,
                              key='analysis_global_opacity')
            active = []
            show_target = display_mode == 'Cíl'
            if display_mode == 'Jedna hladina':
                if available_levels:
                    chosen = st.selectbox('Zobrazená hladina', available_levels,
                                          format_func=core.level_label,
                                          key='analysis_single_level')
                    active = [chosen]
                    st.caption('Přepnutím hladiny se změní pouze zobrazení; krytí se nepřepočítává.')
                else:
                    st.info('V NASTAVENÍ nejprve vyber výškové hladiny.')
            elif display_mode == 'Porovnání':
                active = st.multiselect('Zobrazené hladiny', available_levels,
                                        default=available_levels[:3],
                                        format_func=core.level_label,
                                        key='analysis_comparison_levels')
                st.caption('Pro čitelnost mapy doporučuji 2–3 hladiny.')
            else:
                st.caption('Zobrazuje krytí cílové výšky nastavené ve výpočtu.')
            alphas = {ft: alpha for ft in active}
            st.caption(f'Aktivní vrstvy: {len(active) + int(show_target)}')
            st.caption('Kliknutí do mapy zobrazí radiální profil. Podklad změň v ovladači vrstev.')
        with mapcol:
            m = folium.Map(location=[rc.lat, rc.lon], zoom_start=8 if rc.range_km<=100 else 7,
                           tiles=None, control_scale=True, prefer_canvas=True,
                           zoom_animation=False, fade_animation=False, marker_zoom_animation=False)
            for name, provider in core.BASEMAP_PROVIDERS.items():
                folium.TileLayer(provider['url'], name=name, attr=provider['attribution'],
                                 max_zoom=provider['max_zoom'], overlay=False, show=name=='OpenStreetMap').add_to(m)
            # Session-local contours: changes to opacity never repeat the coverage calculation.
            for ft in ([None] if show_target else []) + active:
                if ft not in st.session_state.geometry:
                    st.session_state.geometry[ft] = coverage_geojson(result, ft)
                geo = st.session_state.geometry[ft]
                color = '#22d3c5' if ft is None else to_hex(core.level_color(ft))
                opacity = alpha
                if geo['features']:
                    folium.GeoJson(geo, name='Cíl' if ft is None else core.level_label(ft),
                        style_function=lambda feature, color=color, opacity=opacity:
                            dict(color=color, weight=1.5, fillColor=color, fillOpacity=opacity),
                        tooltip=folium.GeoJsonTooltip(fields=['hladina'], labels=False)).add_to(m)
            for obs in result.get('obstacles', []):
                folium.Polygon(square_corners(obs['lat'], obs['lon']), color='#ff7043',
                               weight=1, fill=True, fill_opacity=.65,
                               tooltip=f"Překážka {obs['height_m']:g} m AGL").add_to(m)
            folium.Marker([rc.lat, rc.lon], tooltip=f'{rc.radar_mode} · radar',
                          icon=folium.Icon(color='orange', icon='signal')).add_to(m)
            if par := (rc.radar_mode == 'PAR-NG'):
                from pyproj import Geod
                bearings = np.linspace(rc.bearing_deg-20, rc.bearing_deg+20, 81)
                xs, ys, _ = Geod(ellps='WGS84').fwd(np.full(81,rc.lon),np.full(81,rc.lat),bearings,np.full(81,40000.))
                folium.PolyLine([[rc.lat,rc.lon]]+list(zip(ys,xs))+[[rc.lat,rc.lon]],
                                color='#8ca4b5',dash_array='5 5',weight=1,tooltip='Sektor PAR-NG ±20° / 40 km').add_to(m)
            # Layer selection is handled by stable Streamlit controls; Leaflet
            # keeps only basemap switching, without coverage layer animations.
            folium.LayerControl(collapsed=True).add_to(m)
            Fullscreen().add_to(m)
            MeasureControl(primary_length_unit='kilometers').add_to(m)
            HoverDetail(result).add_to(m)
            event = st_folium(m, height=540, use_container_width=True,
                             key='coverage_'+result['completed_at'], returned_objects=['last_clicked'])
            click = event.get('last_clicked') if event else None
            if click and click != st.session_state.get('last_map_click'):
                st.session_state.last_map_click = click
                st.session_state.selected_point = click
                _, idx, _ = clicked_point(result, click['lat'], click['lng'], active)
                if idx is not None:
                    st.session_state.profile_index = idx
        with profile:
            st.subheader('RADIAL PROFILE / Radiální profil')
            idx = st.select_slider('Azimut [°]', options=list(range(len(result['az']))),
                                   format_func=lambda i:f"{result['az'][i]%360:.2f}°", key='profile_index')
            point = st.session_state.get('selected_point')
            selected_distance = None
            if point:
                detail, point_idx, dist = clicked_point(result, point['lat'], point['lng'], active)
                st.caption(detail)
                if idx == point_idx:
                    selected_distance = dist
            figure(core.profile_plot, result=result, index=idx, selected=selected_distance, levels_ft=active)
            with st.expander('Terén a spodní hranice · technický rastr'):
                mode = st.selectbox('Veličina', ['Terén', 'Spodní hranice'])
                figure(core.map_plot, result=result, mode=mode)
    with raw:
        st.subheader('Aktuální výpočet')
        st.json(core.calculation_metadata(result), expanded=False)
        st.caption('RAW tabulka obsahuje nezměněné vzorky vybraného radiálního profilu. Celou matici stáhneš jako NPZ.')
        index = st.session_state.profile_index
        st.dataframe(pd.DataFrame({'distance_m':result['distance'],
                    'terrain_amsl_m':result['terrain'][index], 'lower_amsl_m':result['lower'][index],
                    'upper_amsl_m':result['upper'][index], 'known':result['known'][index],
                    'target_visible':result['status'][index]}), use_container_width=True, height=280)
        left, right = st.columns([1,2])
        with left:
            kind = st.selectbox('Formát exportu', EXPORTS)
            dpi = st.selectbox('Rozlišení PNG [DPI]', [300,600])
            export_levels = st.multiselect('Exportované hladiny [ft AMSL]', core.FLIGHT_LEVELS_LIST,
                                          default=levels, format_func=core.level_label)
            if st.button('Připravit export', key='prepare_export'):
                try:
                    with st.spinner('Připravuji soubor…'), plot_lock():
                        blob, filename, mime = export_bytes(kind, result, export_levels, index, dpi, alpha, alphas)
                        st.session_state.export = (blob, filename, mime,
                            (kind, tuple(export_levels), index, dpi, alpha, tuple(sorted(alphas.items()))))
                except Exception as exc:
                    st.error('Export se nepodařil: '+str(exc))
            export = st.session_state.get('export')
            signature = (kind, tuple(export_levels), index, dpi, alpha, tuple(sorted(alphas.items())))
            if export and export[3] == signature:
                st.download_button('Stáhnout '+export[1], export[0], export[1], export[2])
        with right:
            st.markdown('''**GeoPackage:** vektorové plochy a hraniční křivky pro QGIS, bez převodu na pixely.

**GeoTIFF:** rastrové vrstvy. **NPZ:** úplné výpočetní matice a použitý diagram.

**CSV:** právě vybraný radiální profil. **JSON:** parametry a původ výpočtu.

**PNG:** tiskový graf krytí při 300 nebo 600 DPI, bez online mapového podkladu.

Přesnost křivek určuje krok výpočtu a rozlišení DEM. Vyšší DPI nezvyšuje přesnost terénu.''')
