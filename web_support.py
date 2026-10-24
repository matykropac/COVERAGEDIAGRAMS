"""Web projection, point queries and session-local downloadable exports."""
import json
from pathlib import Path
import tempfile
from zipfile import ZipFile, ZIP_STORED
from io import BytesIO
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
import xml.etree.ElementTree as ET

import numpy as np
from pyproj import Geod, Transformer
from shapely.geometry import mapping
from shapely.ops import transform
from branca.element import MacroElement, Template
import radar_core as core
from obstacles import obstacle_polygon

EXPORTS = ('QuickReport · ZIP (600 DPI)', 'KML · všechny vrstvy (polygony)', 'GeoPackage · vektory', 'GeoTIFF · rastr', 'RAW · NPZ',
           'Profil · CSV', 'Metadata · JSON', 'Obrázek · PNG')


def coverage_geojson(result, ft):
    status = result['status'] if ft is None else core.status_at_height(result, ft * core.FT_TO_M)
    project = Transformer.from_crs(core.local_crs(result['config']), 'EPSG:4326', always_xy=True)
    label = 'Krytí cíle' if ft is None else core.level_label(ft)
    return {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'geometry': mapping(transform(project.transform, poly)),
         'properties': {'hladina': label}}
        for poly in core.coverage_polygons(result, status)]}


def clicked_point(result, lat, lon, levels):
    c = result['config']
    bearing, _, distance = Geod(ellps='WGS84').inv(c.lon, c.lat, lon, lat)
    x = np.sin(np.deg2rad(bearing)) * distance / 1000
    y = np.cos(np.deg2rad(bearing)) * distance / 1000
    detail = core.point_detail(result, x, y, levels)
    index, inside = core.azimuth_indices(result['az'], c, bearing % 360)
    return detail, (int(index) if inside and distance <= c.range_km * 1000 else None), distance / 1000


def hover_payload(result):
    def array(key):
        arr = np.asarray(result[key], dtype=float)
        return np.where(np.isfinite(arr), np.round(arr, 1), None).tolist()
    c = result['config']
    return dict(lat=c.lat, lon=c.lon, radius=c.range_km, sector=c.radar_mode == 'PAR-NG',
                bearing=c.bearing_deg, az=result['az'].tolist(), distance=result['distance'].tolist(),
                terrain=array('terrain'), lower=array('lower'), status=array('status'))


class HoverDetail(MacroElement):
    """Client-side nearest-sample preview; clicks use exact WGS84 geodesics on server."""
    def __init__(self, result):
        super().__init__()
        self._name = 'RadarHover'
        self.payload = json.dumps(hover_payload(result), allow_nan=False, separators=(',', ':'))
        self._template = Template(r'''
{% macro script(this, kwargs) %}
(function() {
const map = {{this._parent.get_name()}}, d = {{this.payload | safe}};
const control = L.control({position: 'bottomleft'});
control.onAdd = function() {
 this.box = L.DomUtil.create('div');
 this.box.style.cssText = 'background:#07111bef;color:#e9f2f8;padding:9px;border-radius:6px;font:12px sans-serif;max-width:330px;pointer-events:none';
 this.box.textContent = 'Pohyb kurzoru: náhled vzorku · klik: přesný detail';
 return this.box;
}; control.addTo(map);
let last = 0;
map.on('mousemove', function(e) {
 if (performance.now() - last < 45) return; last = performance.now();
 const rad = Math.PI/180, p1=d.lat*rad, p2=e.latlng.lat*rad, dl=(e.latlng.lng-d.lon)*rad;
 const h=Math.sin((p2-p1)/2)**2 + Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;
 const range=6371.0088*2*Math.asin(Math.min(1,Math.sqrt(h)));
 const bearing=(Math.atan2(Math.sin(dl)*Math.cos(p2),Math.cos(p1)*Math.sin(p2)-Math.sin(p1)*Math.cos(p2)*Math.cos(dl))/rad+360)%360;
 const delta=((bearing-d.bearing+540)%360)-180;
 let text=e.latlng.lat.toFixed(5)+'°, '+e.latlng.lng.toFixed(5)+'° · ~'+range.toFixed(2)+' km';
 if (range>d.radius || (d.sector && Math.abs(delta)>20)) {control.box.textContent=text+' · mimo výpočet';return;}
 if (range*1000<d.distance[0]/2) {control.box.textContent=text+' · před prvním vzorkem';return;}
 let ai=0, best=Infinity;
 for(let i=0;i<d.az.length;i++) {const diff=Math.abs(((bearing-d.az[i]+540)%360)-180);if(diff<best){best=diff;ai=i;}}
 const step=d.distance[0], ri=Math.min(d.distance.length-1,Math.max(0,Math.round(range*1000/step)-1));
 const height=v=>v===null?'neznámá':Math.round(v)+' m';
 text+=' · terén '+height(d.terrain[ai][ri])+' AMSL · spodní hranice '+height(d.lower[ai][ri])+' AMSL';
 text+=' · cíl: '+(d.status[ai][ri]===null?'neznámé':d.status[ai][ri]===1?'krytý':'nekrytý');
 control.box.textContent=text+' (přibližný výběr vzorku)';
});
})();
{% endmacro %}''')




class ClickMeasure(MacroElement):
    """Leaflet-only point selection with compact terrain cross-section (no rerun)."""
    def __init__(self, result):
        super().__init__()
        self._name = 'ClickMeasure'
        config = result['config']
        self.site_lat = float(config.lat)
        self.site_lon = float(config.lon)
        # Downsample only for the miniature chart; the calculation is untouched.
        az = np.asarray(result['az'], dtype=float)
        distance = np.asarray(result['distance'], dtype=float) / 1000.0
        terrain = np.asarray(result['terrain'], dtype=float)
        step = max(1, int(np.ceil(len(distance) / 160)))
        terrain = terrain[:, ::step]
        self.profile_data = json.dumps({
            'az': np.round(az, 3).tolist(),
            'distance': np.round(distance[::step], 3).tolist(),
            'terrain': np.where(np.isfinite(terrain), np.round(terrain, 1), None).tolist(),
        }, separators=(',', ':'), allow_nan=False)
        self._template = Template(r'''
{% macro script(this, kwargs) %}
(function() {
 const map = {{this._parent.get_name()}};
 const site = L.latLng({{this.site_lat}}, {{this.site_lon}});
 const profiles = {{this.profile_data | safe}};
 let marker = null, line = null;
 const panel = L.control({position:'bottomright'});
 panel.onAdd = function() {
   this.box = L.DomUtil.create('div');
   this.box.style.cssText = 'display:none;align-items:center;gap:12px;background:#071b2df2;color:#e9f7ff;padding:10px 13px;border:1px solid #3d7897;border-radius:9px;box-shadow:0 4px 16px #0008;font:12px sans-serif;line-height:1.6;width:min(1050px,92vw);max-width:92vw';
   this.box.innerHTML = '<div id="measure-info" style="width:230px;min-width:185px;flex-shrink:0"><b style="color:#5fe3f2">VYBRANÝ BOD</b><br>Klikni do mapy pro měření</div><div style="flex:1;min-width:0"><div style="color:#5fe3f2;font-weight:bold">PROFIL TERÉNU</div><canvas id="measure-profile" width="780" height="112" style="width:100%;height:112px;display:block"></canvas></div>';
   L.DomEvent.disableClickPropagation(this.box);
   L.DomEvent.disableScrollPropagation(this.box);
   return this.box;
 };
 panel.addTo(map);
 // The wide measuring panel belongs to fullscreen/standalone views only.
 // In the embedded map it would be clipped and obstruct navigation.
 function updatePanelVisibility() {
   const fullscreen = !!(map._isFullscreen || (map.getContainer().matches && map.getContainer().matches(':fullscreen')) || document.fullscreenElement);
   const standalone = window.self === window.top;
   panel.box.style.display = (fullscreen || standalone) ? 'flex' : 'none';
 }
 updatePanelVisibility();
 map.on('fullscreenchange', updatePanelVisibility);
 document.addEventListener('fullscreenchange', updatePanelVisibility);
 const info = panel.box.querySelector('#measure-info');
 const canvas = panel.box.querySelector('#measure-profile');
 const ctx = canvas.getContext('2d');
 function draw(bearing, selectedKm) {
   const az = profiles.az, dist = profiles.distance;
   let best = Infinity, index = 0;
   for(let i=0;i<az.length;i++) {
     const delta = Math.abs(((bearing-az[i]+540)%360)-180);
     if(delta<best){best=delta;index=i;}
   }
   const values=profiles.terrain[index];
   ctx.clearRect(0,0,canvas.width,canvas.height);
   if(!values || !dist.length) return;
   const maxDist=dist[dist.length-1]||1;
   // A sliding terrain window follows the click. The chosen point is always
   // at the horizontal center, including near the radar or range boundary.
   const span=Math.max(10,maxDist*.30);
   const start=selectedKm-span/2, finish=selectedKm+span/2;
   const left=7,right=canvas.width-7,top=10,bottom=canvas.height-20;
   const x=d=>left+(right-left)*(d-start)/span;
   const visible=values.filter((v,i)=>v!==null && Number.isFinite(v) && dist[i]>=start && dist[i]<=finish);
   if(!visible.length) {
     ctx.fillStyle='#c4dce9';ctx.font='12px sans-serif';
     ctx.fillText('V této vzdálenosti nejsou dostupná terénní data.',12,55);
     return;
   }
   const low=Math.min(...visible),high=Math.max(...visible);
   const padding=Math.max(20,(high-low)*.15);
   const min=low-padding,max=high+padding;
   const y=v=>bottom-(v-min)/(max-min)*(bottom-top);
   ctx.strokeStyle='#35566b';ctx.lineWidth=1;
   for(let j=0;j<3;j++){const yy=top+(bottom-top)*j/2;ctx.beginPath();ctx.moveTo(left,yy);ctx.lineTo(right,yy);ctx.stroke();}
   ctx.save();ctx.beginPath();ctx.rect(left,top,right-left,bottom-top);ctx.clip();
   ctx.beginPath();let started=false;
   for(let i=0;i<values.length;i++){
     const v=values[i],d=dist[i];
     if(v===null || !Number.isFinite(v)){started=false;continue;}
     if(!started){ctx.moveTo(x(d),y(v));started=true;}else ctx.lineTo(x(d),y(v));
   }
   ctx.strokeStyle='#5fe3f2';ctx.lineWidth=2;ctx.stroke();
   const xx=x(selectedKm);
   ctx.setLineDash([3,3]);ctx.strokeStyle='#ffb454';ctx.beginPath();ctx.moveTo(xx,top);ctx.lineTo(xx,bottom);ctx.stroke();ctx.setLineDash([]);
   if(selectedKm>=0 && selectedKm<=maxDist){
     let near=0;for(let i=1;i<dist.length;i++)if(Math.abs(dist[i]-selectedKm)<Math.abs(dist[near]-selectedKm))near=i;
     if(values[near]!==null && Number.isFinite(values[near])){
       ctx.fillStyle='#ffb454';ctx.beginPath();ctx.arc(xx,y(values[near]),4,0,Math.PI*2);ctx.fill();
     }
   }
   ctx.restore();
   ctx.font='10px sans-serif';ctx.fillStyle='#c4dce9';
   ctx.fillText(start.toFixed(1)+' km',left,canvas.height-5);
   ctx.textAlign='center';ctx.fillStyle='#ffb454';ctx.fillText(selectedKm.toFixed(1)+' km',xx,canvas.height-5);
   ctx.textAlign='right';ctx.fillStyle='#c4dce9';ctx.fillText(finish.toFixed(1)+' km',right,canvas.height-5);ctx.textAlign='left';
 }
 map.on('click', function(e) {
   const point=e.latlng;
   const rad=Math.PI/180,p1=site.lat*rad,p2=point.lat*rad,dl=(point.lng-site.lng)*rad;
   const a=Math.sin((p2-p1)/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;
   const distance=6371.0088*2*Math.asin(Math.min(1,Math.sqrt(a)));
   const bearing=(Math.atan2(Math.sin(dl)*Math.cos(p2),Math.cos(p1)*Math.sin(p2)-Math.sin(p1)*Math.cos(p2)*Math.cos(dl))/rad+360)%360;
   if(marker)map.removeLayer(marker);
   if(line)map.removeLayer(line);
   marker=L.circleMarker(point,{radius:7,color:'#fff',weight:2,fillColor:'#ffb454',fillOpacity:1}).addTo(map);
   line=L.polyline([site,point],{color:'#ffb454',weight:2,opacity:.85,dashArray:'6 5',interactive:false}).addTo(map);
   info.innerHTML='<b style="color:#5fe3f2">VYBRANÝ BOD</b><br>Vzdálenost od stanoviště:<br><b>'+distance.toFixed(2)+' km</b><br>Azimut od stanoviště:<br><b>'+bearing.toFixed(1)+'°</b><br><small>'+point.lat.toFixed(5)+'°, '+point.lng.toFixed(5)+'°</small>';
   draw(bearing,distance);
 });
})();
{% endmacro %}''')


KML_NS = 'http://www.opengis.net/kml/2.2'
ET.register_namespace('', KML_NS)


def _kml_element(parent, name, value=None):
    child = ET.SubElement(parent, '{' + KML_NS + '}' + name)
    if value is not None:
        child.text = str(value)
    return child


def _kml_polygon(parent, rings):
    """Write WGS84 Polygon with optional interior rings (KML expects lon,lat)."""
    polygon = _kml_element(parent, 'Polygon')
    _kml_element(polygon, 'tessellate', '1')
    _kml_element(polygon, 'altitudeMode', 'clampToGround')
    for i, ring in enumerate(rings):
        boundary = _kml_element(polygon, 'outerBoundaryIs' if i == 0 else 'innerBoundaryIs')
        linear = _kml_element(boundary, 'LinearRing')
        coords = list(ring)
        if coords and coords[0] != coords[-1]:
            coords.append(coords[0])
        _kml_element(linear, 'coordinates',
                     ' '.join(f'{float(x):.8f},{float(y):.8f},0' for x, y in coords))


def _kml_geometry(parent, geometry):
    if geometry['type'] == 'Polygon':
        _kml_polygon(parent, geometry['coordinates'])
    elif geometry['type'] == 'MultiPolygon':
        multi = _kml_element(parent, 'MultiGeometry')
        for rings in geometry['coordinates']:
            _kml_polygon(multi, rings)
    else:
        raise ValueError('KML podporuje pouze polygonové vrstvy.')


def _kml_style(parent, color, opacity='88'):
    style = _kml_element(parent, 'Style')
    line = _kml_element(style, 'LineStyle')
    _kml_element(line, 'color', 'ff' + color[5:7] + color[3:5] + color[1:3])
    _kml_element(line, 'width', '1.2')
    poly = _kml_element(style, 'PolyStyle')
    _kml_element(poly, 'color', opacity + color[5:7] + color[3:5] + color[1:3])


def export_kml(result, levels):
    """One KML file: separate polygon folders for target + every requested FL + obstacles."""
    from matplotlib.colors import to_hex
    root = ET.Element('{' + KML_NS + '}kml')
    doc = _kml_element(root, 'Document')
    _kml_element(doc, 'name', 'COVERAGEDIAGRAMS · všechny vrstvy')
    _kml_element(doc, 'description',
                 'Polygonové krytí WGS84, přepínatelné hladiny; vodorovné plochy, ne 3D objemy.')
    for flight_level in [None] + list(dict.fromkeys(levels)):
        label = 'Krytí cíle' if flight_level is None else core.level_label(flight_level)
        folder = _kml_element(doc, 'Folder')
        _kml_element(folder, 'name', label)
        color = '#22d3c5' if flight_level is None else to_hex(core.level_color(flight_level))
        features = coverage_geojson(result, flight_level)['features']
        for i, feature in enumerate(features, 1):
            pm = _kml_element(folder, 'Placemark')
            _kml_element(pm, 'name', f'{label} · polygon {i}')
            _kml_style(pm, color)
            _kml_geometry(pm, feature['geometry'])
    if result.get('obstacles'):
        folder = _kml_element(doc, 'Folder')
        _kml_element(folder, 'name', 'Překážky')
        c = result['config']
        for i, o in enumerate(result['obstacles'], 1):
            pm = _kml_element(folder, 'Placemark')
            _kml_element(pm, 'name', o.get('name') or f'Překážka {i}')
            _kml_element(pm, 'description', f'{o["height_m"]:g} m AGL · půdorys překážky')
            _kml_style(pm, '#ff7043', 'bb')
            latlon = obstacle_polygon(o, c.lat, c.lon)
            ring = [[lon, lat] for lat, lon in latlon]
            _kml_polygon(pm, [ring])
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def export_quickreport(result, *, flight_levels=None):
    """Create a single ZIP containing the antenna plot, terrain and every flight level at 600 DPI.

    All images use the application's print renderer. Images are rendered one at a time;
    the raw matrices are not recalculated and the archive has one directory per section.
    """
    c = result['config']
    all_levels = tuple(core.flight_levels_for(c.radar_mode))
    requested = all_levels if flight_levels is None else tuple(dict.fromkeys(flight_levels))
    if any(level not in all_levels for level in requested):
        raise ValueError('Nepodporovaná letová hladina pro zvolený radar.')

    manifest = {
        'format': 'COVERAGEDIAGRAMS_QUICKREPORT',
        'radar': c.radar_mode,
        'source': result.get('source'),
        'completed_at': result.get('completed_at'),
        'image_dpi': 600,
        'flight_levels_ft_amsl': list(requested),
        'terrain': '01_Teren/terrain_600dpi.png',
        'antenna_diagram': '02_Vyzarovaci_diagram/antenna_diagram_600dpi.png',
        'flight_level_directory': '03_Letove_hladiny/',
        'note': 'Vypočtené geometrické krytí; rozlišení zdrojového DEM se zvýšením DPI nemění.',
    }
    with tempfile.TemporaryDirectory(prefix='radar_quickreport_') as directory:
        root = Path(directory)
        png = root / 'page.png'
        # PNG files are already compressed. Store entries directly without further CPU-heavy ZIP deflation.
        archive_bytes = BytesIO()
        with ZipFile(archive_bytes, 'w', compression=ZIP_STORED, allowZip64=True) as archive:
            core.export_map_image(png, result, 'Terén', dpi=600, alpha=1.0)
            archive.write(png, manifest['terrain'])

            fig = Figure(figsize=(13, 9), dpi=600, facecolor=core.PLOT_BG)
            FigureCanvasAgg(fig)
            try:
                core.technical_plot(fig, result=result)
                fig.text(.07, .975, 'ELDIS · ANTENNA DIAGRAM',
                         color=core.UI_TEXT, fontsize=18, weight='bold', va='top')
                fig.savefig(png, dpi=600, format='png', facecolor=fig.get_facecolor())
            finally:
                fig.clear()
            archive.write(png, manifest['antenna_diagram'])

            for level in requested:
                # One altitude per page keeps the established print layout and readable legend.
                core.export_map_image(png, result, 'Vybrané výšky',
                                      levels_ft=(level,), alpha=0.74, dpi=600)
                archive.write(png, f'03_Letove_hladiny/{int(level):05d}ft_AMSL_600dpi.png')
            archive.writestr('report_manifest.json',
                             json.dumps(manifest, ensure_ascii=False, indent=2))
            archive.writestr(
                'README.txt',
                'COVERAGEDIAGRAMS / QuickReport\\n'
                f'Radar: {c.radar_mode}\\n'
                '01_Teren: terénní model\\n'
                '02_Vyzarovaci_diagram: diagram antény a technická obálka\\n'
                f'03_Letove_hladiny: {len(requested)} jednotlivých hladin ft AMSL\\n'
                'Každá grafika 600 DPI; obrázky nejsou mapová ortofota.\\n'
                'Vyšší tiskové DPI nezvyšuje přesnost zdrojových dat DEM.\\n'
            )
        return archive_bytes.getvalue()


def export_bytes(kind, result, levels, index, dpi, alpha, level_alphas=None):
    with tempfile.TemporaryDirectory(prefix='radar_export_') as directory:
        root = Path(directory)
        if kind == 'QuickReport · ZIP (600 DPI)':
            return export_quickreport(result), 'COVERAGEDIAGRAMS_QuickReport_600dpi.zip', 'application/zip'
        if kind == 'KML · všechny vrstvy (polygony)':
            return export_kml(result, levels), 'coverage_all_layers.kml', 'application/vnd.google-earth.kml+xml'
        if kind == 'GeoPackage · vektory':
            path, mime = root/'coverage.gpkg', 'application/geopackage+sqlite3'
            core.export_gpkg(path, result, levels)
        elif kind == 'GeoTIFF · rastr':
            path, mime = root/'coverage.tif', 'image/tiff'
            core.export_tiff(path, result, levels)
        elif kind == 'RAW · NPZ':
            path, mime = root/'coverage_raw.npz', 'application/octet-stream'
            core.export_raw_npz(path, result)
        elif kind == 'Profil · CSV':
            path, mime = root/'radial_profile.csv', 'text/csv'
            core.export_profile_csv(path, result, index, levels)
        elif kind == 'Metadata · JSON':
            path, mime = root/'calculation.json', 'application/json'
            path.write_text(json.dumps(core.calculation_metadata(result), ensure_ascii=False, indent=2), encoding='utf-8')
        elif kind == 'Obrázek · PNG':
            path, mime = root/f'coverage_{dpi}dpi.png', 'image/png'
            core.export_map_image(path, result, 'Vybrané výšky' if levels else 'Krytí cíle',
                                  levels_ft=levels, alpha=alpha, dpi=dpi, level_alphas=level_alphas)
        else:
            raise ValueError('Neznámý formát exportu.')
        return path.read_bytes(), path.name, mime
