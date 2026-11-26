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

def load_a4_basemap(config):
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
    size = (1600, round(1600 * HEIGHT / WIDTH))
    base = core.load_basemap(config, viewport=viewport, out_size=size,
                             provider="Esri · Streets (legacy)")
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
            aviation = core.load_basemap(config, viewport=viewport,
                                         out_size=size, provider=provider)
        finally:
            core.BASEMAP_PROVIDERS.pop(provider, None)
    if aviation is None or aviation.get("image") is None or not np.any(aviation["image"][..., 3]):
        raise ValueError("OpenAIP returned no visible aviation tiles.")
    background = Image.fromarray(base["image"], "RGBA")
    chart = Image.fromarray(aviation["image"], "RGBA")
    chart.putalpha(chart.getchannel("A").point(lambda v: int(v * .88)))
    base["image"] = np.asarray(Image.alpha_composite(background, chart))
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
