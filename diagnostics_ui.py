"""Simple 360-degree radial coverage viewer."""
import numpy as np
import streamlit as st
from matplotlib.figure import Figure
import radar_core as core
from coverage_diagnostics import native_azimuth, obstacle_intersections


def radial_figure(result, index, requested):
    c = result["config"]
    x = np.asarray(result["distance"], dtype=float) / 1000.0
    terrain = np.asarray(result["terrain"][index], dtype=float)
    lower = np.asarray(result["lower"][index], dtype=float)
    known = np.asarray(result["known"][index], dtype=bool)
    antenna = float(result["antenna"])
    valid = known & np.isfinite(terrain) & np.isfinite(lower)
    hits = obstacle_intersections(result, index)

    finite = terrain[np.isfinite(terrain)]
    ground_min = float(np.min(finite)) if finite.size else antenna - 100
    # Display the modeled lower coverage envelope, not an invented straight ray.
    finite_lower = lower[valid]
    top = max(antenna + 1000, float(np.nanpercentile(finite_lower, 95)) + 600
              if finite_lower.size else antenna + 1000)
    bottom = min(ground_min, antenna) - 150
    if top <= bottom:
        top = bottom + 1500

    fig = Figure(figsize=(14, 6), dpi=140, facecolor="#071b2d", layout="constrained")
    ax = fig.subplots()
    ax.set_facecolor("#0b263b")
    ax.fill_between(x, bottom, terrain, where=np.isfinite(terrain),
                    color="#55776d", alpha=0.9, label="Terén (DEM)")
    ax.plot(x, terrain, color="#a1d4c0", lw=1.5)
    # The lower boundary already accounts for modeled terrain and obstacles.
    ax.fill_between(x, lower, top, where=valid & (lower <= top),
                    color="#24b8ce", alpha=0.24, label="Oblast nad spodní hranicí")
    ax.plot(x, np.where(valid, lower, np.nan), color="#5fe3f2",
            lw=2.2, label="Spodní hranice geometrického krytí")
    for n, hit in enumerate(hits):
        ax.vlines(hit["distance_m"] / 1000, hit["base_m"], hit["top_m"],
                  color="#ffb454", lw=3, label="Překážky" if n == 0 else None)
    ax.scatter([0], [antenna], s=100, color="#ffffff", marker="^", zorder=10)
    ax.annotate("RADAR", (0, antenna), xytext=(10, 12),
                textcoords="offset points", color="#ffffff", weight="bold")
    ax.set_xlim(0, float(x[-1]))
    ax.set_ylim(bottom, top)
    ax.set_xlabel("Vzdálenost od radaru [km]", color="#dcecf5", fontsize=11)
    ax.set_ylabel("Výška [m AMSL]", color="#dcecf5", fontsize=11)
    ax.set_title("RADIÁLNÍ ŘEZ  /  AZIMUT {:.0f}°  (výpočet {:.2f}°)".format(
        requested, float(result["az"][index]) % 360),
        loc="left", color="white", weight="bold", fontsize=15, pad=18)
    ax.grid(color="#6e9cb0", alpha=0.16, linewidth=0.7)
    ax.tick_params(colors="#dcecf5")
    for spine in ax.spines.values():
        spine.set_color("#37617a")
    leg = ax.legend(loc="upper right", facecolor="#102f46",
                    edgecolor="#37617a", fontsize=9)
    for label in leg.get_texts():
        label.set_color("#eaf6fa")
    return fig


def render_diagnostics(result):
    st.subheader("RADIÁLNÍ ŘEZY / 360°")
    st.caption("Kosekantní model a terén po jednotlivých azimutech. "
               "Zobrazená spodní hranice zahrnuje modelované překážky; "
               "zastíněná oblast nad ní není zárukou detekce — "
               "dosah vyzařovacího diagramu může krytí dále omezit.")
    bearing = st.slider("Azimut [°]", min_value=0, max_value=359,
                        value=0, step=1, key="radial_view_bearing")
    index, native, inside = native_azimuth(result, bearing)
    if not inside:
        st.info("Tento azimut leží mimo vypočtený sektor radaru.")
        return
    fig = radial_figure(result, index, bearing)
    st.pyplot(fig, use_container_width=True)
    fig.clear()
    if abs(((native - bearing + 180) % 360) - 180) > 0.01:
        st.caption("Nejbližší skutečně vypočtený radiál: {:.2f}°.".format(native))
