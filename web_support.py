"""Web projection, point queries and session-local downloadable exports."""
import json
from pathlib import Path
import tempfile

import numpy as np
from pyproj import Geod, Transformer
from shapely.geometry import mapping
from shapely.ops import transform
from branca.element import MacroElement, Template
import radar_core as core

EXPORTS = ('GeoPackage · vektory', 'GeoTIFF · rastr', 'RAW · NPZ',
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


def export_bytes(kind, result, levels, index, dpi, alpha, level_alphas=None):
    with tempfile.TemporaryDirectory(prefix='radar_export_') as directory:
        root = Path(directory)
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
