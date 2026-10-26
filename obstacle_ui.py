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
    obstacles = st.session_state.setdefault('obstacles', [])

    map_panel, table_panel = st.columns([2, 1], gap='medium')
    with table_panel:
        height = st.number_input('Výška nové překážky [m AGL]', 0.1, 1000.0,
                                 value=20.0, step=1.0, key='obstacle_new_height')
        show_wind = st.checkbox('Zobrazit větrné elektrárny (100 km)',
                                value=True, key='obstacle_show_wind')
    wind_data = []
    if show_wind:
        try:
            wind_data = load_wind_turbines(round(radar_lat, 6), round(radar_lon, 6))
        except Exception:
            with table_panel:
                st.warning('Vrstva větrných elektráren není momentálně dostupná.')

    selected_idx = st.session_state.get('obstacle_selected_index', -1)
    with map_panel:
        st.markdown('**01 / Mapa překážek**')
        om = folium.Map(location=[radar_lat, radar_lon], zoom_start=11,
                        tiles=None, control_scale=True)
        for name, provider in core.BASEMAP_PROVIDERS.items():
            folium.TileLayer(provider['url'], name=name, attr=provider['attribution'],
                             max_zoom=provider['max_zoom'], overlay=False,
                             show=name == 'Esri · Topographic (legacy)').add_to(om)
        if show_wind and wind_data:
            add_wind_layer(om, wind_data, cluster_points=False)
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
        Draw(export=False, draw_options={'polyline': False, 'rectangle': False,
             'circle': False, 'circlemarker': False, 'marker': False,
             'polygon': {'allowIntersection': False, 'showArea': True}},
             edit_options={'edit': False, 'remove': False}).add_to(om)
        folium.LayerControl().add_to(om)
        Fullscreen().add_to(om)
        map_data = st_folium(om, height=690, use_container_width=True,
                             key='obstacle_map', returned_objects=['last_clicked', 'last_active_drawing'])
        drawing = (map_data or {}).get('last_active_drawing')
        if drawing and drawing.get('geometry', {}).get('type') == 'Polygon':
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
    with table_panel:
        st.markdown('**02 / Překážky · editovatelná tabulka**')
        if not obstacles:
            st.info('Nakresli první polygon v mapě.')
            return

        rows = [{
            'Název': _label(o, i),
            'Výška [m AGL]': float(o['height_m']),
            'Smazat': False,
        } for i, o in enumerate(obstacles)]
        editor_rev = st.session_state.get('obstacle_list_rev', 0)
        edited = st.data_editor(
            pd.DataFrame(rows),
            key=f'obstacle_editor_{editor_rev}',
            hide_index=False,
            use_container_width=True,
            num_rows='fixed',
            height=min(690, max(160, 38 * (len(rows) + 1) + 20)),
            column_config={
                'Název': st.column_config.TextColumn('Název', required=True),
                'Výška [m AGL]': st.column_config.NumberColumn(
                    'Výška [m AGL]', min_value=0.1, max_value=1000.0,
                    step=1.0, format='%.1f'),
                'Smazat': st.column_config.CheckboxColumn('Smazat', default=False),
            },
        )
        if st.button('Uložit změny', type='primary',
                     use_container_width=True, key='obstacle_save_table'):
            updated = []
            try:
                for i, row in edited.iterrows():
                    if bool(row['Smazat']):
                        continue
                    item = dict(obstacles[i])
                    item['name'] = str(row['Název']).strip() or _label(item, i)
                    item['height_m'] = float(row['Výška [m AGL]'])
                    validate_obstacle(item, radar_lat, radar_lon)
                    updated.append(item)
            except (ValueError, TypeError, KeyError) as exc:
                st.error(f'Neplatná úprava: {exc}')
            else:
                obstacles[:] = updated
                st.session_state['obstacle_list_rev'] = editor_rev + 1
                st.rerun()
        st.caption('Uprav název nebo výšku přímo v tabulce. '
                   'Pro odstranění zaškrtni Smazat a ulož. '
                   'Půdorys polygonu upravíš novým nakreslením.')
