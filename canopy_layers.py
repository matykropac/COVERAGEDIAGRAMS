"""Visualize georeferenced canopy-height raster GeoTIFF (AGL) without changing coverage."""
import io
import base64

import folium
import numpy as np
import streamlit as st
from PIL import Image
from rasterio.io import MemoryFile
from rasterio.warp import reproject, Resampling, transform_bounds
from rasterio.transform import from_bounds

@st.cache_data(ttl=3600, max_entries=4, show_spinner=False)
def _color_raster(raw, low, high):
    if len(raw) > 35_000_000:
        raise ValueError("Raster je větší než 35 MB. Ořízni ho v QGIS na okolí radaru.")
    with MemoryFile(raw) as mem:
        with mem.open() as ds:
            if ds.crs is None:
                raise ValueError("GeoTIFF nemá definované CRS.")
            if ds.width * ds.height > 25_000_000:
                raise ValueError("Raster obsahuje příliš mnoho pixelů. Ořízni ho v QGIS.")
            west, south, east, north = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds)
            if east <= west or north <= south or east - west > 180:
                raise ValueError("Neplatný geografický rozsah GeoTIFF.")
            width = min(900, max(100, ds.width))
            height = min(900, max(100, ds.height))
            values = np.full((height, width), np.nan, dtype=np.float32)
            reproject(source=ds.read(1, masked=True).astype(np.float32).filled(np.nan),
                      destination=values, src_transform=ds.transform,
                      src_crs=ds.crs, dst_transform=from_bounds(west, south, east, north, width, height),
                      dst_crs="EPSG:4326", src_nodata=np.nan, dst_nodata=np.nan,
                      resampling=Resampling.bilinear)
    good = np.isfinite(values) & (values >= low) & (values <= high)
    scaled = np.nan_to_num(np.clip((values - low) / max(high - low, 1.), 0, 1), nan=0.0)
    pixels = np.zeros((height, width, 4), dtype=np.uint8)
    pixels[..., 0] = (205 - 174*scaled).astype(np.uint8)
    pixels[..., 1] = (231 - 113*scaled).astype(np.uint8)
    pixels[..., 2] = (116 - 72*scaled).astype(np.uint8)
    pixels[..., 3] = np.where(good, 190, 0).astype(np.uint8)
    blob = io.BytesIO()
    Image.fromarray(pixels, mode="RGBA").save(blob, format="PNG")
    return blob.getvalue(), [[south, west], [north, east]], int(good.sum())

@st.cache_data(ttl=3600, max_entries=3, show_spinner=False)
def surface_difference(dtm_raw, dsm_raw, low, high):
    """DSM minus DTM in a common WGS84 grid; both inputs must use SAME vertical datum."""
    for raw in (dtm_raw, dsm_raw):
        if len(raw) > 35_000_000:
            raise ValueError("DTM/DSM GeoTIFF max. 35 MB každý. Ořízni v QGIS.")
    arrays = []
    bounds = None
    with MemoryFile(dtm_raw) as a, MemoryFile(dsm_raw) as b:
        with a.open() as dtm, b.open() as dsm:
            if dtm.crs is None or dsm.crs is None:
                raise ValueError("Oba modely musí mít platné CRS.")
            if dtm.width * dtm.height > 25_000_000 or dsm.width * dsm.height > 25_000_000:
                raise ValueError("Zmenši rastry na zvolenou oblast.")
            west_a, south_a, east_a, north_a = transform_bounds(dtm.crs, "EPSG:4326", *dtm.bounds)
            west_b, south_b, east_b, north_b = transform_bounds(dsm.crs, "EPSG:4326", *dsm.bounds)
            west, south, east, north = (max(west_a, west_b), max(south_a, south_b),
                                        min(east_a, east_b), min(north_a, north_b))
            if east <= west or north <= south or east - west > 180:
                raise ValueError("DTM a DSM nemají společné území.")
            bounds = [[south, west], [north, east]]
            width = height = 800
            dst_transform = from_bounds(west, south, east, north, width, height)
            for ds in (dtm, dsm):
                dest = np.full((height, width), np.nan, dtype=np.float32)
                src = ds.read(1, masked=True).astype(np.float32).filled(np.nan)
                reproject(source=src, destination=dest, src_transform=ds.transform,
                          src_crs=ds.crs, dst_transform=dst_transform, dst_crs="EPSG:4326",
                          src_nodata=np.nan, dst_nodata=np.nan, resampling=Resampling.bilinear)
                arrays.append(dest)
    surface = arrays[1] - arrays[0]
    # Negative values are usually alignment/noise, not object heights.
    surface[~np.isfinite(surface) | (surface < 0)] = np.nan
    return _render_height(surface, bounds, low, high)

def _render_height(values, bounds, low, high):
    height, width = values.shape
    good = np.isfinite(values) & (values >= low) & (values <= high)
    scaled = np.nan_to_num(np.clip((values - low) / max(high - low, 1.), 0, 1), nan=0.)
    pixels = np.zeros((height, width, 4), dtype=np.uint8)
    pixels[..., 0] = (205 - 174 * scaled).astype(np.uint8)
    pixels[..., 1] = (231 - 113 * scaled).astype(np.uint8)
    pixels[..., 2] = (116 - 72 * scaled).astype(np.uint8)
    pixels[..., 3] = np.where(good, 190, 0).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(pixels, mode="RGBA").save(buf, format="PNG")
    return buf.getvalue(), bounds, int(good.sum())

def controls(prefix):
    enabled = st.checkbox("Výška korun stromů · GeoTIFF (AGL)", False, key=prefix+"_on")
    if not enabled:
        return None
    mode = st.radio("Zdroj povrchových výšek",
                    ["CHM · výška stromů AGL", "DSM − DTM · výška povrchových objektů"],
                    key=prefix+"_mode")
    low, high = st.slider("Rozsah výšek [m AGL]", 0, 80, (1, 45),
                          key=prefix+"_range")
    try:
        if mode.startswith("CHM"):
            uploaded = st.file_uploader("Canopy Height Model (GeoTIFF, metry AGL)",
                                        type=["tif", "tiff"], key=prefix+"_file")
            if uploaded is None:
                st.caption("Nahraj CHM GeoTIFF v metrech AGL. Jen vizualizace.")
                return None
            image, bounds, count = _color_raster(uploaded.getvalue(), low, high)
        else:
            dtm = st.file_uploader("DTM / DMR – holý terén (GeoTIFF)",
                                   type=["tif", "tiff"], key=prefix+"_dtm")
            dsm = st.file_uploader("DSM / DMP – model povrchu (GeoTIFF)",
                                   type=["tif", "tiff"], key=prefix+"_dsm")
            confirmed = st.checkbox("DTM a DSM jsou ve shodných výškových jednotkách a "
                                    "stejném výškovém referenčním systému.",
                                    False, key=prefix+"_datum")
            if dtm is None or dsm is None or not confirmed:
                st.caption("Rozdíl DSM − DTM zachycuje budovy i vegetaci. "
                           "Bez shodného vertikálního data je rozdíl neplatný.")
                return None
            image, bounds, count = surface_difference(dtm.getvalue(), dsm.getvalue(),
                                                      low, high)
        st.caption(f"Výškový překryv: {count} pixelů v rozsahu {low}–{high} m AGL. "
                   "Jde o informativní vrstvu; radarové výpočty se nemění.")
        return image, bounds, low, high
    except (ValueError, OSError, RuntimeError) as exc:
        st.warning("Povrchový rastr nelze zobrazit: " + str(exc)[:180])
        return None

def add_layer(map_obj, data):
    if data is None:
        return
    image, bounds, low, high = data
    encoded = 'data:image/png;base64,' + base64.b64encode(image).decode('ascii')
    folium.raster_layers.ImageOverlay(image=encoded, bounds=bounds, opacity=0.75,
                                      name=f"Canopy height {low}-{high} m AGL",
                                      show=True, overlay=True).add_to(map_obj)
    from branca.element import Element
    map_obj.get_root().html.add_child(Element(
        '<div style="position:absolute;z-index:9999;right:12px;bottom:26px;'
        'background:rgba(5,26,38,.9);color:white;padding:8px;border-radius:6px;'
        'font:12px system-ui">Canopy height · '
        + str(low) + '–' + str(high) + ' m AGL<br>'
        '<span style="display:inline-block;width:130px;height:10px;'
        'background:linear-gradient(90deg,#cde774,#1f762c)"></span></div>'))
