"""Run: streamlit run streamlit_app.py"""
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import tempfile
import threading
import time

import folium
from branca.element import Element
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
from obstacles import apply_obstacles, obstacle_polygon, obstacle_signature
from project_file import save_project, load_project
from project_widgets import restored_widget_values
from obstacle_ui import render_obstacle_editor
from diagnostics_ui import render_diagnostics
from site_picker import coordinates_from_map_click
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
from web_support import EXPORTS, HoverDetail, ClickMeasure, clicked_point, coverage_geojson, export_bytes

st.set_page_config(page_title='ELDIS · Radar Coverage', page_icon='📡', layout='wide')

# A dialog rerun must stage coordinates until the next whole-app rerun.
# Mutating the lat/lon widget keys after their rendering raises a Streamlit error.
_pending_radar_site = st.session_state.pop('_pending_radar_site', None)
if _pending_radar_site is not None:
    st.session_state['lat'], st.session_state['lon'] = _pending_radar_site
    st.session_state['site_picker_notice'] = (
        f"Nové stanoviště: {_pending_radar_site[0]:.6f}°, "
        f"{_pending_radar_site[1]:.6f}° (WGS 84). Pro nové krytí spusť výpočet."
    )
    st.session_state['project_notice'] = ''

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


def antenna_preview(config, pattern):
    """Roomy, transparent two-panel preview within the ATM dashboard card.

    This changes presentation only. Engineering coverage limits and diagram
    interpolation are still handled by radar_core.
    """
    with plot_lock():
        fig = Figure(figsize=(9.0, 7.4), facecolor='none')
        try:
            gain_ax, envelope_ax = core.technical_plot(
                fig, config=config, pattern=pattern
            )
            fig.patch.set_alpha(0.0)
            for ax in (gain_ax, envelope_ax):
                ax.set_facecolor('none')
                ax.patch.set_alpha(0.0)
                ax.tick_params(labelsize=8, pad=3)
                ax.title.set_fontsize(9)
                ax.title.set_wrap(True)
                ax.xaxis.label.set_size(8)
                ax.yaxis.label.set_size(8)
            # Preserve the engineering ranges, but show the useful gain range
            # rather than dedicating most of the plot to near-zero antenna gain.
            gain_ax.set_xlim(config.min_elev, config.max_elev)
            gain_ax.set_ylim(-65, 5)
            gain_ax.margins(x=0.01)
            # The fixed two-plot layout previously left insufficient room for
            # long antenna labels, legends and axis ticks in a narrow column.
            fig.subplots_adjust(left=.16, right=.985, bottom=.085,
                                top=.93, hspace=.56)
            st.pyplot(fig, use_container_width=True, transparent=True)
        finally:
            fig.clear()


def figure(draw, **kwargs):
    with plot_lock():
        fig = Figure(figsize=(7, 5), facecolor=core.PLOT_BG)
        try:
            draw(fig, **kwargs)
            st.pyplot(fig, use_container_width=True)
        finally:
            fig.clear()


@st.dialog('Vybrat stanoviště radaru z mapy', width='large')
def choose_radar_site_from_map(initial_lat, initial_lon, map_id):
    """Confirming a map click queues WGS84 coordinates for the next app rerun."""
    st.caption('Přibliž mapu a klikni na místo, kde má radar stát. '
               'Současná poloha je označena oranžově. Změna se provede až po potvrzení.')

    selected = st.session_state.get('site_picker_selection')
    # Keep the current viewport when redrawing the selected location.
    # Without this a click on a panned/zoomed map could hide the new marker.
    view = st.session_state.get('site_picker_view')
    map_center = [view[0], view[1]] if view else [initial_lat, initial_lon]
    map_zoom = view[2] if view else 11
    map_view = folium.Map(
        location=map_center, zoom_start=map_zoom,
        tiles=None, control_scale=True, prefer_canvas=True,
        zoom_animation=False, fade_animation=False,
    )
    # This CSS is rendered inside the Folium iframe, so only this map has
    # a precise crosshair instead of Leaflet's default grab / pointer hand.
    map_view.get_root().header.add_child(Element('''
        <style>
        .leaflet-container, .leaflet-container.leaflet-grab,
        .leaflet-container.leaflet-grabbing, .leaflet-interactive {
            cursor: crosshair !important;
        }
        </style>
    '''))
    for name, provider in core.BASEMAP_PROVIDERS.items():
        folium.TileLayer(provider['url'], name=name, attr=provider['attribution'],
                         max_zoom=provider['max_zoom'], overlay=False,
                         show=name == 'OpenStreetMap').add_to(map_view)
    folium.Marker(
        [initial_lat, initial_lon], tooltip='Aktuální stanoviště',
        icon=folium.Icon(color='orange', icon='signal')
    ).add_to(map_view)
    if selected is not None:
        # Two concentric circles create an unambiguous point: the white dot
        # is centered exactly on the stored WGS84 click, without marker offset.
        folium.CircleMarker(
            list(selected), radius=12, color='#1cd6f6', weight=2,
            fill=True, fill_color='#0c3852', fill_opacity=.35,
            interactive=False,
        ).add_to(map_view)
        folium.CircleMarker(
            list(selected), radius=4, color='#073349', weight=1,
            fill=True, fill_color='#ffffff', fill_opacity=1,
            tooltip='Vybrané stanoviště – klikni jinam pro změnu',
            interactive=False,
        ).add_to(map_view)
    folium.LayerControl(collapsed=True).add_to(map_view)
    Fullscreen().add_to(map_view)
    selection_event = st_folium(
        map_view, height=510, use_container_width=True,
        key=f'radar_site_map_{map_id}',
        returned_objects=['last_clicked', 'center', 'zoom']
    )
    if selection_event and selection_event.get('center') and selection_event.get('zoom') is not None:
        current_center = selection_event['center']
        st.session_state['site_picker_view'] = (
            float(current_center['lat']), float(current_center['lng']),
            int(selection_event['zoom'])
        )
    last_click = selection_event.get('last_clicked') if selection_event else None
    if last_click:
        try:
            new_selection = coordinates_from_map_click(last_click)
            if new_selection != selected:
                st.session_state['site_picker_selection'] = new_selection
                # Dialogs are fragments; redraw now so the selected point
                # appears immediately and persists through further interactions.
                st.rerun(scope='fragment')
        except ValueError as exc:
            st.error(str(exc))

    if selected is not None:
        st.success(f'Vybráno: {selected[0]:.6f}°, {selected[1]:.6f}° (WGS 84)')
    else:
        st.info('Kliknutím na mapu vyber novou polohu.')

    if st.button('Použít souřadnice', type='primary',
                 disabled=selected is None, use_container_width=True,
                 key='confirm_radar_site'):
        st.session_state['_pending_radar_site'] = selected
        st.session_state.pop('site_picker_selection', None)
        st.rerun()


st.markdown('''<div class="atm-hero">
  <div><div class="atm-eyebrow"></div>
  <div class="atm-title"></div>
  <div class="atm-description"></div></div>
  <div class="atm-brand">ELDIS<small></small></div>
</div>''', unsafe_allow_html=True)
def open_project_callback():
    upload = st.session_state.get('project_upload')
    if upload is None:
        return
    try:
        result, meta = load_project(upload.getvalue())
        c = result['config']
        values = restored_widget_values(c, meta)
        result['antenna_pattern'] = antenna(c.radar_mode, values.get('ssr_pattern', 'Measured SSR.txt'))
        # Change widget identities for values that were previously displayed
        # with Streamlit's stale widget state after an upload.
        epoch = int(st.session_state.get('project_restore_epoch', 0)) + 1
        st.session_state['project_restore_epoch'] = epoch
        for field in ('agl', 'bearing', 'tilt'):
            values[f'{field}_restored_{epoch}'] = values[field]
        st.session_state.update(values)
        st.session_state.update(
            obstacles=meta['obstacles'], result=result, geometry={},
            profile_index=len(result['az'])//2 if c.radar_mode == 'PAR-NG' else 0,
            loaded_project=True, project_error='', site_picker_notice='',
            project_notice='Projekt načten včetně všech parametrů a vypočteného krytí.',
        )
        for key in ('export', 'selected_point', 'last_map_click', 'last_map_click_obstacle'):
            st.session_state.pop(key, None)
        # The restored result stays authoritative even when its original DEM file
        # is no longer accessible. Configuration comparison still detects edits.
        st.session_state['source_signature'] = (
            values['source'], meta.get('source_ui', {}).get('dataset', 'COP30'), None
        )
    except Exception as exc:
        st.session_state['project_error'] = str(exc)



settings, obstacles_tab, analysis, diagnostics_tab, raw = st.tabs(['NASTAVENÍ', 'OBSTACLES', 'MAPA / ANALÝZA', 'DIAGNOSTIKA', 'DATA / EXPORTY'])

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
        if st.button('📍 Vybrat z mapy', key='open_radar_site_map', use_container_width=True):
            st.session_state['site_picker_selection'] = None
            st.session_state.pop('site_picker_view', None)
            st.session_state['site_picker_version'] = st.session_state.get('site_picker_version', 0) + 1
            choose_radar_site_from_map(lat, lon, st.session_state['site_picker_version'])
        if st.session_state.get('site_picker_notice'):
            st.caption(st.session_state['site_picker_notice'])
        agl = st.number_input('Anténa [m AGL]', .1, 5000., 20., key=f"agl_restored_{st.session_state.get('project_restore_epoch', 0)}")
        bearing = st.number_input('Azimut osy [°]', 0., 359.99, 0., disabled=not par, key=f"bearing_restored_{st.session_state.get('project_restore_epoch', 0)}")
        if par:
            st.caption('PAR-NG: ±15° od osy · 40 km · vestavěný diagram')
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
        azstep = st.select_slider('Krok azimutu [°]', [.25, .5, 1., 2., 2.5, 5.], value=1., key='azstep')
        k = st.number_input('Efektivní poloměr Země · k', .5, 3., 4/3, format='%.4f', key='k_factor')
        min_elev = st.number_input('Minimální elevace [°]', -5., 88., -1.0, key='min_elev')
        max_elev = st.number_input('Maximální elevace [°]', -4., 89., 45., key='max_elev')
        tilt = st.number_input('Tilt antény [°]', -15., 15., -1.0, key=f"tilt_restored_{st.session_state.get('project_restore_epoch', 0)}")
        beam = st.selectbox('Svazek', ['COMBINED', 'LOW', 'HIGH'], disabled=par or ssr, key='beam')
        target = st.number_input('Výška cíle [m]', -500., 30000., 1000., key='target')
        reference = st.selectbox('Reference cíle', ['AMSL', 'AGL'], key='reference')
    c = core.Config(lat=lat, lon=lon, antenna_agl=agl, radar_mode=radar, bearing_deg=bearing,
                    range_km=40. if par else radius_input, csc_range_km=40. if par else range_ref_input,
                    step_m=float(step), az_step=float(azstep), k=k, min_elev=min_elev, max_elev=max_elev,
                    antenna_tilt_deg=tilt, beam_mode='COMBINED' if par or ssr else beam,
                    target_m=target, reference=reference, csc_enabled=True)
    with preview:
        st.subheader('03 / Vyzařovací diagram')
        try:
            c.validate()
            antenna_preview(c, antenna(radar, ssr_pattern))
            st.caption('Náhled: orientační výška stanoviště 200 m AMSL.')
        except ValueError as exc:
            st.warning(str(exc))
    with execution:
        st.subheader('04 / Výpočet a stav')
        st.caption('Zvol hladiny, spusť výpočet a sleduj průběh jednotlivých kroků.')
        levels = st.multiselect('Výškové řezy [ft AMSL] · nominální ISA', core.flight_levels_for(radar),
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
                    new_result['obstacles_signature'] = obstacle_signature(st.session_state.get('obstacles', []))
                    new_result.update(source=provenance, completed_at=datetime.now(timezone.utc).isoformat(),
                                      duration_s=round(time.perf_counter()-start, 3))
                    st.session_state.result = new_result
                    st.session_state.loaded_project = False
                    st.session_state.pop('site_picker_notice', None)
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


    # Project controls belong below the four settings cards.
    with st.expander('PROJEKTY / Uložit a otevřít', expanded=False):
        st.file_uploader('Otevřít projekt COVERAGEDIAGRAMS (.cdproj)',
                         type=['cdproj'], key='project_upload',
                         on_change=open_project_callback)
        if st.session_state.get('project_error'):
            st.error(st.session_state['project_error'])
        if st.session_state.get('project_notice'):
            st.success(st.session_state['project_notice'])
        st.caption('Soubor obsahuje parametry, překážky, vybrané hladiny, výsledek a vzorkovaný DEM. '
                   'Přihlašovací klíče se neukládají.')
    

# The obstacle editor manages both 10 × 10 m point objects and clockwise arcs.
with obstacles_tab:
    render_obstacle_editor(lat, lon)

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
        if (asdict(c) != asdict(rc) or (not st.session_state.get('loaded_project') and source_signature != st.session_state.source_signature)
                or result.get('obstacles_signature') != obstacle_signature(st.session_state.obstacles)):
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
            st.caption('Kliknutí měří přímo v mapě, bez překreslení aplikace — funguje i na celou obrazovku.')
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
                folium.Polygon(obstacle_polygon(obs, rc.lat, rc.lon), color='#ff7043',
                               weight=1, fill=True, fill_opacity=.65,
                               tooltip=f"Překážka {obs['height_m']:g} m AGL").add_to(m)
            folium.Marker([rc.lat, rc.lon], tooltip=f'{rc.radar_mode} · radar',
                          icon=folium.Icon(color='orange', icon='signal')).add_to(m)
            if par := (rc.radar_mode == 'PAR-NG'):
                from pyproj import Geod
                bearings = np.linspace(rc.bearing_deg-15, rc.bearing_deg+15, 81)
                xs, ys, _ = Geod(ellps='WGS84').fwd(np.full(81,rc.lon),np.full(81,rc.lat),bearings,np.full(81,40000.))
                folium.PolyLine([[rc.lat,rc.lon]]+list(zip(ys,xs))+[[rc.lat,rc.lon]],
                                color='#8ca4b5',dash_array='5 5',weight=1,tooltip='Sektor PAR-NG ±15° / 40 km').add_to(m)
            ClickMeasure(rc.lat, rc.lon).add_to(m)
            # Layer selection is handled by stable Streamlit controls; Leaflet
            # keeps only basemap switching, without coverage layer animations.
            folium.LayerControl(collapsed=True).add_to(m)
            Fullscreen().add_to(m)
            MeasureControl(primary_length_unit='kilometers').add_to(m)
            HoverDetail(result).add_to(m)
            # Leaflet handles clicks without Streamlit reruns in fast mode.
            sync_click = st.session_state.get('sync_map_click', False)
            event = st_folium(m, height=540, use_container_width=True,
                             key='coverage_'+result['completed_at'],
                             returned_objects=['last_clicked'] if sync_click else [])
            click = event.get('last_clicked') if (sync_click and event) else None
            if click and click != st.session_state.get('last_map_click'):
                st.session_state.last_map_click = click
                st.session_state.selected_point = click
                from pyproj import Geod
                selected_az, _, _ = Geod(ellps='WGS84').inv(rc.lon, rc.lat, click['lng'], click['lat'])
                st.session_state.radial_view_bearing = int(round(selected_az)) % 360
                _, idx, _ = clicked_point(result, click['lat'], click['lng'], active)
                if idx is not None:
                    st.session_state.profile_index = idx
            st.download_button(
                '↗ Samostatná mapa (HTML)',
                data=m.get_root().render().encode('utf-8'),
                file_name='coverage_map.html', mime='text/html',
                help='Stáhni HTML a otevři jej v samostatném okně prohlížeče.',
                key='download_standalone_map'
            )
            st.caption('Samostatná mapa: otevři stažený HTML soubor v prohlížeči. Podkladové dlaždice vyžadují internet.')
        with profile:
            st.toggle('Přenášet kliknutí z mapy do diagnostiky (pomalejší)',
                      value=False, key='sync_map_click',
                      help='Zapne aktualizaci radiálního profilu. Vypnuto = rychlé klikání i ve fullscreen.')
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
        st.subheader('Projekt COVERAGEDIAGRAMS')
        try:
            payload = save_project(
                result, levels=levels, obstacles=st.session_state.obstacles,
                display={'mode': st.session_state.get('analysis_layer_mode', 'Jedna hladina'),
                         'opacity': st.session_state.get('analysis_global_opacity', .45)},
                source_ui={'source': source, 'dataset': dataset, 'ssr_pattern': ssr_pattern}
            )
            st.download_button('Uložit kompletní projekt (.cdproj)', data=payload,
                               file_name='radar_coverage.cdproj',
                               mime='application/octet-stream', type='primary')
            st.caption('Po načtení souboru se obnoví vypočtené krytí i podkladový terén bez volání API.')
        except Exception as exc:
            st.error('Projekt nelze uložit: ' + str(exc))
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
            quickreport = kind.startswith('QuickReport')
            if quickreport:
                st.info('QuickReport: ZIP s vyzařovacím diagramem, terénem a všemi '
                        'letovými hladinami pro vypočtený radar. '
                        'Každá stránka je samostatné PNG při 600 DPI. '
                        'Příprava většího balíku může být výpočetně náročná.')
            dpi = st.selectbox('Rozlišení PNG [DPI]', [300,600],
                               index=1 if quickreport else 0, disabled=quickreport)
            export_levels = st.multiselect('Exportované hladiny [ft AMSL]',
                                          core.flight_levels_for(rc.radar_mode),
                                          default=[v for v in levels if v in core.flight_levels_for(rc.radar_mode)],
                                          format_func=core.level_label, disabled=quickreport)
            if st.button('Vygenerovat QuickReport ZIP' if quickreport else 'Připravit export',
                         key='prepare_export', type='primary' if quickreport else 'secondary'):
                try:
                    with st.spinner('Připravuji soubor…'), plot_lock():
                        blob, filename, mime = export_bytes(kind, result,
                            core.flight_levels_for(rc.radar_mode) if kind.startswith('KML') else export_levels,
                            index, dpi, alpha, alphas)
                        st.session_state.export = (blob, filename, mime,
                            (kind, tuple(core.flight_levels_for(rc.radar_mode) if kind.startswith('KML') else export_levels),
                             index, dpi, alpha, tuple(sorted(alphas.items()))))
                except Exception as exc:
                    st.error('Export se nepodařil: '+str(exc))
            export = st.session_state.get('export')
            signature = (kind, tuple(core.flight_levels_for(rc.radar_mode) if kind.startswith('KML') else export_levels),
                         index, dpi, alpha, tuple(sorted(alphas.items())))
            if export and export[3] == signature:
                st.download_button('Stáhnout '+export[1], export[0], export[1], export[2])
        with right:
            st.markdown('''**QuickReport:** ZIP s diagramem antény, mapou terénu a jednotlivými výškovými řezy všech dostupných FL v PNG 600 DPI. Každá hladina má vlastní obrázek.\n\n**KML:** všechny vybrané výpočetní hladiny a krytí cíle jako samostatné polygonové složky v Google Earth; také půdorysy překážek.

**GeoPackage:** vektorové plochy a hraniční křivky pro QGIS, bez převodu na pixely.

**GeoTIFF:** rastrové vrstvy. **NPZ:** úplné výpočetní matice a použitý diagram.

**CSV:** právě vybraný radiální profil. **JSON:** parametry a původ výpočtu.

**PNG:** tiskový graf krytí při 300 nebo 600 DPI, bez online mapového podkladu.

Přesnost křivek určuje krok výpočtu a rozlišení DEM. Vyšší DPI nezvyšuje přesnost terénu.''')


with diagnostics_tab:
    if result is None:
        st.info('Nejprve vypočítej krytí nebo načti projekt (.cdproj).')
    else:
        render_diagnostics(result)
