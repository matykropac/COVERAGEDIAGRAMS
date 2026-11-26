"""Full-bleed A4 landscape aviation coverage maps, one image per altitude."""
from threading import RLock
from urllib.parse import quote
import numpy as np
from PIL import Image
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib import patheffects
import radar_core as core
from aviation_basemap import configured_key, URL

DPI = 500
WIDTH = round(297 / 25.4 * DPI)
HEIGHT = round(210 / 25.4 * DPI)
_PROVIDER_LOCK = RLock()

def _load_print_tiles(config, viewport, provider, progress=None, *, max_zoom=None, max_tiles=512):
    """Disk-backed tile mosaic; warp one channel at a time into print pixels."""
    import tempfile
    from pathlib import Path
    import rasterio
    from rasterio.transform import from_bounds
    from rasterio.warp import reproject, Resampling
    from rasterio.windows import Window

    spec = core.BASEMAP_PROVIDERS[provider]
    z, xmin, xmax, ymin, ymax = core.tile_plan(
        config, viewport, WIDTH, min(spec["max_zoom"], max_zoom) if max_zoom is not None else spec["max_zoom"],
        max_tiles=max_tiles, prefer_detail=True)
    nx, ny = xmax-xmin+1, ymax-ymin+1
    half = np.pi * 6378137.0
    span = 2 * half / 2**z
    src_transform = from_bounds(-half+xmin*span, half-(ymax+1)*span,
                                -half+(xmax+1)*span, half-ymin*span,
                                nx*256, ny*256)
    dst_transform = from_bounds(viewport[0]*1000, viewport[2]*1000,
                                viewport[1]*1000, viewport[3]*1000,
                                WIDTH, HEIGHT)
    if progress:
        progress(f"{provider}: zoom {z}, {nx*ny} tiles")
    with tempfile.TemporaryDirectory(prefix="cd_print_tiles_") as work:
        mosaic = Path(work) / "tiles.tif"
        with rasterio.Env(GDAL_CACHEMAX=32*1024*1024):
            with rasterio.open(mosaic, "w", driver="GTiff", width=nx*256,
                               height=ny*256, count=4, dtype="uint8",
                               crs="EPSG:3857", transform=src_transform,
                               tiled=True, blockxsize=256, blockysize=256,
                               compress="deflate") as dst:
                done = 0
                for y in range(ymin, ymax+1):
                    for x in range(xmin, xmax+1):
                        try:
                            tile = core.fetch_map_tile(z, x, y, provider)
                        except RuntimeError as exc:
                            # Preserve actual failed zoom for whole-layer retry.
                            exc.tile_zoom = z
                            raise
                        dst.write(np.moveaxis(tile, -1, 0),
                                  window=Window((x-xmin)*256, (y-ymin)*256, 256, 256))
                        done += 1
                        if progress and (done % 8 == 0 or done == nx*ny):
                            progress(f"{provider}: tiles {done}/{nx*ny}")
            bands = np.zeros((4, HEIGHT, WIDTH), dtype=np.uint8)
            with rasterio.open(mosaic) as src:
                for band in range(4):
                    reproject(rasterio.band(src, band+1), bands[band],
                              dst_transform=dst_transform, dst_crs=core.local_crs(config),
                              resampling=Resampling.bilinear, num_threads=1,
                              warp_mem_limit=32)
    return dict(image=np.moveaxis(bands, 0, -1), extent=viewport,
                signature=(config.lat, config.lon, config.range_km),
                zoom=z, provider=provider, attribution=spec["attribution"])


def load_a4_basemap(config, progress=None):
    key = configured_key()
    if not key:
        raise ValueError("Esri + OpenAIP export requires OPENAIP_API_KEY.")
    mode = str(config.radar_mode).upper()
    radius = float(config.range_km)
    if mode != "PAR-NG":
        radius = max(radius, (260 if "SSR" in mode else 100) * 1.852)
    radius *= 1.055
    half_width = radius * WIDTH / HEIGHT
    viewport = (-half_width, half_width, -radius, radius)
    base = _load_print_tiles(config, viewport, "Esri · Streets (legacy)", progress)
    if base is None or base.get("image") is None or not np.any(base["image"][..., 3]):
        raise ValueError("Esri Street Map is unavailable.")
    provider = "_a4_openaip_overlay"
    with _PROVIDER_LOCK:
        core.BASEMAP_PROVIDERS[provider] = {
            "cache": "openaip_a4_export",
            "url": URL.format(z="{z}", x="{x}", y="{y}", key=quote(key, safe="")),
            "max_zoom": 18,
            "attribution": "Aeronautical data © OpenAIP",
        }
        try:
            try:
                aviation = _load_print_tiles(config, viewport, provider, progress)
            except RuntimeError as exc:
                failed_zoom = getattr(exc, "tile_zoom", None)
                if failed_zoom is None or failed_zoom <= 1:
                    raise
                if progress:
                    progress(f"OpenAIP temporarily unavailable at zoom {failed_zoom}; retrying complete overlay at zoom {failed_zoom-1}")
                aviation = _load_print_tiles(config, viewport, provider, progress,
                                             max_zoom=failed_zoom-1, max_tiles=256)
        finally:
            core.BASEMAP_PROVIDERS.pop(provider, None)
    if aviation is None or aviation.get("image") is None or not np.any(aviation["image"][..., 3]):
        raise ValueError("OpenAIP returned no visible aviation tiles.")
    # Blend in strips to avoid several additional full-page RGBA allocations.
    if progress:
        progress("Compositing Esri + OpenAIP at A4 print resolution")
    for y in range(0, HEIGHT, 256):
        background = Image.fromarray(base["image"][y:y+256], "RGBA")
        chart = Image.fromarray(aviation["image"][y:y+256], "RGBA")
        chart.putalpha(chart.getchannel("A").point(lambda v: int(v * .88)))
        base["image"][y:y+256] = np.asarray(Image.alpha_composite(background, chart))
    base["aviation_zoom"] = aviation["zoom"]
    del aviation
    base["attribution"] = "Tiles © Esri and its data providers · Aeronautical data © OpenAIP"
    base["provider"] = "Esri Streets + OpenAIP"
    return base

def render_a4_fl(path, result, level, basemap, alpha=.43):
    """Render the actual calculated coverage; no screenshot or resampling of grid."""
    fig = Figure(figsize=(WIDTH / DPI, HEIGHT / DPI), dpi=DPI, facecolor="white")
    FigureCanvasAgg(fig)
    try:
        ax = core.map_plot(fig, result, "Vybrané výšky", basemap,
                           (level,), alpha, english=True)
        core.add_export_range_rings(ax, result["config"], expand_view=False)
        xmin, xmax, ymin, ymax = basemap["extent"]
        ax.set_xlim(xmin, xmax)
        ax.set_ylim(ymin, ymax)
        ax.set_position([0, 0, 1, 1])
        ax.set_aspect("equal", adjustable="box")
        ax.set_axis_off()
        ax.set_title("")
        ax.grid(False)
        if ax.get_legend() is not None:
            ax.get_legend().remove()
        core.style_export_theme(fig, "light")
        ax.text(.99, .035, f"Esri z{basemap['zoom']} · OpenAIP z{basemap['aviation_zoom']}",
                transform=ax.transAxes, ha="right", color="#17354f", fontsize=7,
                bbox=dict(facecolor="white", edgecolor="none", alpha=.85), zorder=30)
        # Compact overlays, with no sidebar or white page margins.
        box = dict(boxstyle="round,pad=.5", facecolor="white", edgecolor="#526779", alpha=.93)
        ax.text(.018, .98, f"RADAR COVERAGE\\n{int(level):,} ft AMSL",
                transform=ax.transAxes, va="top", color="#17354f",
                weight="bold", fontsize=12, bbox=box, zorder=30)
        ax.annotate("N", xy=(.968,.96), xytext=(.968,.89),
                    xycoords="axes fraction", ha="center", va="center",
                    color="#17354f", fontsize=11, weight="bold",
                    arrowprops=dict(arrowstyle="-|>", color="#17354f", lw=1.6),
                    zorder=30, path_effects=[patheffects.withStroke(linewidth=3, foreground="white")])
        # Scale is local radar-centred AEQD distance.
        span = xmax - xmin
        target = span * .12
        power = 10 ** np.floor(np.log10(target))
        length = max(v * power for v in (.1,.2,.5,1,2,5,10) if v * power <= target)
        x = xmin + span * .025
        y = ymin + (ymax-ymin) * .035
        ax.plot([x,x+length],[y,y],color="#17354f",lw=2.5,zorder=30,
                path_effects=[patheffects.withStroke(linewidth=5, foreground="white")])
        ax.text(x+length/2,y+(ymax-ymin)*.012,f"{length:g} km",ha="center",
                color="#17354f",fontsize=9,zorder=30,
                path_effects=[patheffects.withStroke(linewidth=3,foreground="white")])
        fig.savefig(path, dpi=DPI, format="png", facecolor="white", bbox_inches=None)
    finally:
        fig.clear()
