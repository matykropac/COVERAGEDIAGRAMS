"""Visualize georeferenced canopy-height raster GeoTIFF (AGL) without changing coverage."""
import io

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
            reproject(source=ds.read(1, masked=True).filled(np.nan),
                      destination=values, src_transform=ds.transform,
                      src_crs=ds.crs, dst_transform=from_bounds(west, south, east, north, width, height),
                      dst_crs="EPSG:4326", src_nodata=np.nan, dst_nodata=np.nan,
                      resampling=Resampling.bilinear)
    good = np.isfinite(values) & (values >= low) & (values <= high)
    scaled = np.clip((values - low) / max(high - low, 1.), 0, 1)
    pixels = np.zeros((height, width, 4), dtype=np.uint8)
    pixels[..., 0] = (205 - 174*scaled).astype(np.uint8)
    pixels[..., 1] = (231 - 113*scaled).astype(np.uint8)
    pixels[..., 2] = (116 - 72*scaled).astype(np.uint8)
    pixels[..., 3] = np.where(good, 190, 0).astype(np.uint8)
    blob = io.BytesIO()
    Image.fromarray(pixels, mode="RGBA").save(blob, format="PNG")
    return blob.getvalue(), [[south, west], [north, east]], int(good.sum())

def controls(prefix):
    enabled = st.checkbox("Výška korun stromů · GeoTIFF (AGL)", False, key=prefix+"_on")
    if not enabled:
        return None
    uploaded = st.file_uploader("Canopy Height Model (GeoTIFF, metry AGL)",
                                type=["tif", "tiff"], key=prefix+"_file")
    low, high = st.slider("Rozsah výšky stromů [m AGL]", 0, 80, (1, 45),
                          key=prefix+"_range")
    if uploaded is None:
        st.caption("Nahraj CHM z lokálního datasetu, nikoliv absolutní DSM/DTM. "
                   "Model slouží jen k vizualizaci.")
        return None
    try:
        raw = uploaded.getvalue()
        image, bounds, count = _color_raster(raw, low, high)
        st.caption(f"Canopy overlay: {count} pixelů v rozsahu {low}–{high} m AGL.")
        return image, bounds, low, high
    except (ValueError, OSError, RuntimeError) as exc:
        st.warning("CHM nelze zobrazit: " + str(exc)[:180])
        return None

def add_layer(map_obj, data):
    if data is None:
        return
    image, bounds, low, high = data
    folium.raster_layers.ImageOverlay(image=image, bounds=bounds, opacity=0.75,
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
