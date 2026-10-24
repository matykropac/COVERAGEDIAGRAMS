"""User-friendly Streamlit editor for georeferenced radar obstacles."""
from html import escape

import folium
import pandas as pd
import streamlit as st
from folium.plugins import Fullscreen, Draw
from pyproj import Geod
from streamlit_folium import st_folium

import radar_core as core
from obstacles import arc_parameters, obstacle_polygon, validate_obstacle
from wind_turbines import load_wind_turbines, add_wind_layer

GEOD = Geod(ellps='WGS84')
MAX_OBSTACLES = 100


def _label(o, i):
    return str(o.get('name') or f'Překážka {i+1:02d}')


def _description(o, radar_lat, radar_lon):
    if o.get('kind') == 'arc':
        bearing, span, r1, r2 = arc_parameters(o, radar_lat, radar_lon)
        return f'{bearing:.1f}° → {(bearing+span)%360:.1f}° CW · {r1:.0f}–{r2:.0f} m'
    if o.get('kind') == 'polygon':
        return f'{len(o["coordinates"])} vrcholů · vlastní půdorys'
    az, _, dist = GEOD.inv(radar_lon, radar_lat, o['lon'], o['lat'])
    return f'{az%360:.1f}° · {dist:.0f} m'


def render_obstacle_editor(radar_lat, radar_lon):
    st.subheader('OBSTACLES / Správa překážek')
    st.caption('Překážky do 20 km od radaru. Výška v metrech nad místním terénem (AGL). '
               'Změny se projeví po dalším výpočtu krytí v NASTAVENÍ.')
    obstacles = st.session_state.setdefault('obstacles', [])
    st.caption(f'Zaznamenáno: **{len(obstacles)} / {MAX_OBSTACLES}**')

    # Compact control rail (~200 px at typical desktop width) + flexible map.
    rail, map_panel = st.columns([1, 5], gap='medium')
    with rail:
        st.markdown('**01 / Přidat překážku**')
        mode = st.radio('Způsob vložení', ['Nakreslit polygon do mapy',
                                          'Kliknout do mapy · objekt 10 × 10 m',
                                          'Zadat koncové body · oblouk CW'],
                        horizontal=True, key='obstacle_insert_mode')
        height = st.number_input('Výška nové překážky [m AGL]', 0.1, 1000.0,
                                 value=20.0, step=1.0, key='obstacle_new_height')

        if mode.startswith('Zadat'):
            st.caption('Úhlový oblouk od bodu A k B **po směru hodinových ručiček kolem radaru**. '
                       'Vzdálenost se mezi body lineárně mění; překážka má pás šířky 10 m. '
                       'Nejde o výseč sahající k radaru.')
            start_lon, start_lat, _ = GEOD.fwd(radar_lon, radar_lat, 350, 350)
            end_lon, end_lat, _ = GEOD.fwd(radar_lon, radar_lat, 10, 350)
            with st.form('new_obstacle_arc', clear_on_submit=False):
                new_name = st.text_input('Název obloukové překážky', value='Oblouková překážka')
                a, b = st.columns(2)
                with a:
                    st.markdown('**Bod A — začátek**')
                    a_lat = st.number_input('A · LAT [°]', -90.0, 90.0, float(start_lat),
                                            format='%.6f')
                    a_lon = st.number_input('A · LON [°]', -180.0, 180.0, float(start_lon),
                                            format='%.6f')
                with b:
                    st.markdown('**Bod B — konec (CW)**')
                    b_lat = st.number_input('B · LAT [°]', -90.0, 90.0, float(end_lat),
                                            format='%.6f')
                    b_lon = st.number_input('B · LON [°]', -180.0, 180.0, float(end_lon),
                                            format='%.6f')
                add_arc = st.form_submit_button('Přidat oblouk', type='primary',
                                                 disabled=len(obstacles) >= MAX_OBSTACLES)
            if add_arc:
                item = dict(kind='arc', name=new_name.strip() or 'Oblouková překážka',
                            start_lat=a_lat, start_lon=a_lon, end_lat=b_lat,
                            end_lon=b_lon, height_m=height)
                try:
                    validate_obstacle(item, radar_lat, radar_lon)
                except (ValueError, TypeError, KeyError) as exc:
                    st.error(str(exc))
                else:
                    obstacles.append(item)
                    st.session_state['obstacle_selected_index'] = len(obstacles)-1
                    st.session_state['obstacle_list_rev'] = st.session_state.get('obstacle_list_rev', 0)+1
                    st.session_state.pop('obstacle_confirm_delete', None)
                    st.rerun()
        elif mode.startswith('Kliknout'):
            st.info('Nastav výšku a klikni na mapu. Vloží se překážka 10 × 10 m. '
                    'Na existující překážku lze kliknout pro zobrazení popisu.')

        else:
            st.info('V mapě vyber nástroj polygon (ikona pětiúhelníku), naklikej vrcholy a dvojklikem dokonči. '
                    'Polygon se uloží s výškou nastavenou výše (m AGL).')

        st.markdown('**Větrné elektrárny · 100 km**')
        show_wind = st.checkbox('Zobrazit větrné turbíny v mapě', value=True,
                                key='obstacle_show_wind')
        wind_data = []
        if show_wind:
            try:
                with st.spinner('Načítám větrné turbíny v okruhu 100 km…'):
                    wind_data = load_wind_turbines(round(radar_lat, 6), round(radar_lon, 6))
                st.success(f'Načteno {len(wind_data)} větrných turbín z OpenStreetMap.')
            except Exception as exc:
                st.warning('Turbíny se nyní nepodařilo načíst. Zkus znovu později.')
                st.error(f'Diagnostika Overpass: {str(exc)[:900]}')
            st.caption('Žluté značky jsou pouze informativní; do překážek se nepřidávají.')
        if st.button('🔄 Znovu načíst turbíny', key='refresh_wind_turbines'):
            load_wind_turbines.clear()
            st.rerun()

    if '_obstacle_next_selected' in st.session_state:
        st.session_state['obstacle_selected_index'] = st.session_state.pop('_obstacle_next_selected')
    selected_idx = min(st.session_state.get('obstacle_selected_index', 0),
                       max(0, len(obstacles)-1))
    st.session_state['obstacle_selected_index'] = selected_idx

    with map_panel:
        om = folium.Map(location=[radar_lat, radar_lon], zoom_start=11,
                        tiles=None, control_scale=True)
        for name, provider in core.BASEMAP_PROVIDERS.items():
            folium.TileLayer(provider['url'], name=name, attr=provider['attribution'],
                             max_zoom=provider['max_zoom'], overlay=False,
                             show=name == 'OpenStreetMap').add_to(om)
        if show_wind and wind_data:
            add_wind_layer(om, wind_data)
        folium.Marker([radar_lat, radar_lon], tooltip='Radar',
                      icon=folium.Icon(color='orange', icon='signal')).add_to(om)
        for i, item in enumerate(obstacles):
            label = _label(item, i)
            chosen = i == selected_idx
            folium.Polygon(
                obstacle_polygon(item, radar_lat, radar_lon),
                color='#39c9ef' if chosen else '#ff7043', weight=3 if chosen else 2,
                fill=True, fill_opacity=.7 if chosen else .45,
                tooltip=f'#{i+1} · {escape(label)} · {item["height_m"]:g} m AGL',
                popup=folium.Popup(escape(label) + ' · ' +
                                   escape(_description(item, radar_lat, radar_lon)),
                                   max_width=320),
                bubbling_mouse_events=False
            ).add_to(om)
        if mode.startswith('Nakreslit'):
            Draw(export=False, draw_options={'polyline': False, 'rectangle': False,
                 'circle': False, 'circlemarker': False, 'marker': False,
                 'polygon': {'allowIntersection': False, 'showArea': True}},
                 edit_options={'edit': False, 'remove': False}).add_to(om)
        folium.LayerControl().add_to(om)
        Fullscreen().add_to(om)
        map_data = st_folium(om, height=690, use_container_width=True,
                             key='obstacle_map', returned_objects=['last_clicked', 'last_active_drawing'])
        drawing = (map_data or {}).get('last_active_drawing')
        if mode.startswith('Nakreslit') and drawing and drawing.get('geometry', {}).get('type') == 'Polygon':
            ring = drawing['geometry']['coordinates'][0]
            coords = [[float(lat), float(lon)] for lon, lat in ring[:-1] if len(ring) > 1]
            signature = tuple(tuple(pair) for pair in coords)
            if signature and signature != st.session_state.get('obstacle_last_drawing'):
                st.session_state['obstacle_last_drawing'] = signature
                if len(obstacles) >= MAX_OBSTACLES:
                    st.error('Nejvýše 100 překážek.')
                else:
                    item = dict(kind='polygon', name=f'Polygon {len(obstacles)+1:02d}',
                                coordinates=coords, height_m=float(height))
                    try:
                        validate_obstacle(item, radar_lat, radar_lon)
                    except (ValueError, TypeError, KeyError) as exc:
                        st.error(str(exc))
                    else:
                        obstacles.append(item)
                        st.session_state['obstacle_selected_index'] = len(obstacles)-1
                        st.session_state['obstacle_list_rev'] = st.session_state.get('obstacle_list_rev', 0)+1
                        st.rerun()
        clicked = (map_data or {}).get('last_clicked')
        if mode.startswith('Kliknout') and clicked and clicked != st.session_state.get('obstacle_last_click'):
            st.session_state['obstacle_last_click'] = clicked
            if len(obstacles) >= MAX_OBSTACLES:
                st.error('Nejvýše 100 překážek.')
            else:
                item = dict(kind='point', name=f'Překážka {len(obstacles)+1:02d}',
                            lat=float(clicked['lat']), lon=float(clicked['lng']),
                            height_m=float(height))
                try:
                    validate_obstacle(item, radar_lat, radar_lon)
                except (ValueError, TypeError, KeyError) as exc:
                    st.error(str(exc))
                else:
                    obstacles.append(item)
                    st.session_state['obstacle_selected_index'] = len(obstacles)-1
                    st.session_state['obstacle_list_rev'] = st.session_state.get('obstacle_list_rev', 0)+1
                    st.rerun()

    st.markdown('**02 / Seznam uložených překážek**')
    if not obstacles:
        st.info('Zatím žádné překážky. Klikni na mapu nebo vlož dva koncové body.')
        return
    rows = [{
        '#': i+1,
        'Název': _label(o, i),
        'Typ': 'Polygon' if o.get('kind') == 'polygon' else ('Oblouk CW' if o.get('kind') == 'arc' else 'Objekt 10×10 m'),
        'Výška [m AGL]': float(o['height_m']),
        'Poloha vzhledem k radaru': _description(o, radar_lat, radar_lon),
    } for i, o in enumerate(obstacles)]
    selection = st.dataframe(
        pd.DataFrame(rows), hide_index=True, use_container_width=True,
        height=min(460, 36*(len(rows)+1)+8),
        on_select='rerun', selection_mode='single-row',
        key=f'obstacle_table_{st.session_state.get("obstacle_list_rev", 0)}')
    if selection.selection.rows:
        clicked_row = int(selection.selection.rows[0])
        if clicked_row < len(obstacles) and clicked_row != selected_idx:
            st.session_state['obstacle_selected_index'] = clicked_row
            st.rerun()
    st.caption('Klikni na řádek v tabulce pro výběr, nebo použij seznam níže.')

    chosen_index = st.selectbox(
        'Vybrat překážku pro úpravu', list(range(len(obstacles))),
        format_func=lambda i: f'#{i+1:02d} · {_label(obstacles[i], i)} · '
                              f'{"Polygon" if obstacles[i].get("kind") == "polygon" else ("Oblouk" if obstacles[i].get("kind") == "arc" else "Objekt")} · '
                              f'{obstacles[i]["height_m"]:g} m',
        key='obstacle_selected_index'
    )
    item = obstacles[chosen_index]
    revision = st.session_state.get('obstacle_editor_rev', 0)
    st.markdown('**03 / Upravit vybranou překážku**')
    with st.form(f'obstacle_edit_{chosen_index}_{revision}', clear_on_submit=False):
        edit_name = st.text_input('Název', value=_label(item, chosen_index))
        edit_height = st.number_input('Výška [m AGL]', 0.1, 1000.0,
                                      value=float(item['height_m']), step=1.0)
        if item.get('kind') == 'arc':
            c1, c2 = st.columns(2)
            with c1:
                edit_start_lat = st.number_input('Začátek LAT [°]', -90., 90.,
                                                  float(item['start_lat']), format='%.6f')
                edit_start_lon = st.number_input('Začátek LON [°]', -180., 180.,
                                                  float(item['start_lon']), format='%.6f')
            with c2:
                edit_end_lat = st.number_input('Konec LAT [°]', -90., 90.,
                                                float(item['end_lat']), format='%.6f')
                edit_end_lon = st.number_input('Konec LON [°]', -180., 180.,
                                                float(item['end_lon']), format='%.6f')
        elif item.get('kind') == 'polygon':
            st.caption('Tvar polygonu je uložený v mapě. Výšku a název můžeš upravit zde; '
                       'pro změnu půdorysu polygon smaž a nakresli znovu.')
        else:
            c1, c2 = st.columns(2)
            with c1:
                edit_lat = st.number_input('LAT [°]', -90., 90.,
                                           float(item['lat']), format='%.6f')
            with c2:
                edit_lon = st.number_input('LON [°]', -180., 180.,
                                           float(item['lon']), format='%.6f')
        submitted = st.form_submit_button('Uložit změny', type='primary')
    if submitted:
        updated = dict(item, name=edit_name.strip() or _label(item, chosen_index),
                       height_m=edit_height)
        if item.get('kind') == 'arc':
            updated.update(start_lat=edit_start_lat, start_lon=edit_start_lon,
                           end_lat=edit_end_lat, end_lon=edit_end_lon)
        elif item.get('kind') != 'polygon':
            updated.update(lat=edit_lat, lon=edit_lon)
        try:
            validate_obstacle(updated, radar_lat, radar_lon)
        except (ValueError, TypeError, KeyError) as exc:
            st.error(str(exc))
        else:
            obstacles[chosen_index] = updated
            st.session_state['obstacle_editor_rev'] = revision + 1
            st.session_state.pop('obstacle_confirm_delete', None)
            st.rerun()

    if st.button('🗑️ Smazat vybranou překážku', key='obstacle_delete_request'):
        st.session_state['obstacle_confirm_delete'] = chosen_index
    if st.session_state.get('obstacle_confirm_delete') == chosen_index:
        st.warning('Opravdu smazat ' + _label(item, chosen_index) + '?')
        yes, no = st.columns(2)
        with yes:
            if st.button('Ano, smazat', type='primary', key='obstacle_delete_confirm'):
                obstacles.pop(chosen_index)
                st.session_state.pop('obstacle_confirm_delete', None)
                st.session_state.pop('obstacle_last_click', None)
                st.session_state['_obstacle_next_selected'] = max(0, chosen_index-1)
                st.session_state['obstacle_list_rev'] = st.session_state.get('obstacle_list_rev', 0)+1
                st.session_state['obstacle_editor_rev'] = revision+1
                st.rerun()
        with no:
            if st.button('Zrušit', key='obstacle_delete_cancel'):
                st.session_state.pop('obstacle_confirm_delete', None)
                st.rerun()
