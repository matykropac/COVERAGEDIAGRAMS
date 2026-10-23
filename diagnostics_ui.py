"""Streamlit presentation of every selectable compass bearing and blind-spot causes."""
import numpy as np
import pandas as pd
import streamlit as st
from matplotlib.figure import Figure
from pyproj import Geod

import radar_core as core
from coverage_diagnostics import (
    azimuth_coverage_stats, diagnose, native_azimuth, obstacle_intersections,
)

GEOD = Geod(ellps="WGS84")


def side_view(result, diagnosis):
    """Plot one native radial; 360 integer headings select the nearest sampled radial."""
    i = diagnosis["index"]
    rc = result["config"]
    x = np.asarray(result["distance"], dtype=float)/1000
    terrain = np.asarray(result["terrain"][i], dtype=float)
    lower = np.asarray(result["lower"][i], dtype=float)
    y_target = diagnosis["height_m"]
    d_target = diagnosis["distance_km"]
    limit = float(np.nanmax(terrain)) if np.isfinite(terrain).any() else result["site_height"]
    y_high = max(y_target, limit, result["antenna"]) + max(250, .12*abs(y_target-limit))
    y_low = min(float(np.nanmin(terrain)) if np.isfinite(terrain).any() else result["site_height"],
                result["site_height"]) - max(80, .04*(y_high-y_target))

    fig = Figure(figsize=(12, 5.5), layout="constrained")
    ax = fig.subplots()
    ax.fill_between(x, y_low, terrain, where=np.isfinite(terrain),
                    color="#8b9b8c", alpha=.40, label="Terén (DEM)")
    ax.plot(x, terrain, color="#39584a", linewidth=1.7)
    # Lower envelope already includes the effect of manually entered obstacles.
    envelope = np.where(np.isfinite(lower) & (lower < y_high*2), lower, np.nan)
    ax.plot(x, envelope, color="#e0a12f", linewidth=1.5, linestyle="--",
            label="Spodní geometrická hranice krytí")

    obstacles = obstacle_intersections(result, i)
    for n, item in enumerate(obstacles):
        ax.vlines(item["distance_m"]/1000, item["base_m"], item["top_m"],
                  color="#d75a54", linewidth=3, alpha=.9,
                  label="Zadané překážky" if n == 0 else None)
        if n < 8:
            ax.annotate(item["name"], (item["distance_m"]/1000, item["top_m"]),
                        xytext=(3, 7), textcoords="offset points",
                        fontsize=7, rotation=30, color="#bf514b")

    endpoint_angle = float(core.apparent_angle(
        d_target*1000, y_target, result["antenna"], rc.k))
    ray_x = np.r_[0., x[x < d_target], d_target]
    # Curved-Earth k-model line of sight: not a straight chord on an AMSL plot.
    ray_height = core.height_at_angle(ray_x*1000, endpoint_angle, result["antenna"], rc.k)
    ax.plot(ray_x, ray_height, color="#ce4265", linewidth=2,
            label="Paprsek radar → zvolený cíl")
    ax.scatter([0, d_target], [result["antenna"], y_target],
               s=[70, 65], color=["#117cba", "#ce4265"], zorder=8)
    ax.axhline(y_target, color="#ce4265", linewidth=.8, alpha=.35, linestyle=":")
    ax.annotate("RADAR", (0, result["antenna"]), xytext=(7, 12),
                textcoords="offset points", fontsize=9, weight="bold")
    ax.annotate("CÍL", (d_target, y_target), xytext=(6, 10),
                textcoords="offset points", fontsize=9, weight="bold")
    blocker = diagnosis.get("blocker")
    if blocker and blocker["distance_m"]/1000 <= d_target:
        ax.scatter([blocker["distance_m"]/1000], [blocker["top_m"]],
                   marker="x", color="#b52922", s=100, linewidths=2.5, zorder=10,
                   label="Nejvyšší horizont na trase")

    ax.set(xlim=(0, x[-1]), ylim=(y_low, y_high),
           xlabel="Vzdálenost od radaru [km]", ylabel="Výška [m AMSL]",
           title="Boční řez: požadovaný azimut {:.0f}°  /  skutečně vypočtený {:.2f}°".format(
               diagnosis["requested_deg"], diagnosis["azimuth_deg"]))
    ax.grid(True, alpha=.18)
    ax.legend(loc="upper right", fontsize=8, framealpha=.9)
    return fig


def render_diagnostics(result):
    """Interactive 0..359 heading selector, radial cross section and ranked shadow sectors."""
    c = result["config"]
    st.subheader("LINE OF SIGHT / Diagnostika slepých míst")
    st.caption("360 volitelných kompasových směrů. Boční profil se vykreslí na požádání "
               "z již vypočtených dat, nikoli jako 360 souborů PNG. "
               "Při kroku azimutu nad 1° je použit nejbližší skutečný výpočetní radiál.")
    key = str(result.get("completed_at", "current"))
    selected_point = st.session_state.get("selected_point")
    if selected_point is not None:
        if st.button("📍 Použít bod vybraný na mapě", key="diag_point_" + key):
            az, _, meters = GEOD.inv(c.lon, c.lat,
                                     float(selected_point["lng"]),
                                     float(selected_point["lat"]))
            st.session_state["diag_az_"+key] = int(np.rint(az)) % 360
            st.session_state["diag_distance_"+key] = float(np.clip(
                meters/1000, result["distance"][0]/1000, result["distance"][-1]/1000))
            st.rerun()

    opts = core.flight_levels_for(c.radar_mode)
    default_level = 3000 if 3000 in opts else opts[0]
    left, middle, right = st.columns([1, 1.15, 1.05])
    with left:
        level = st.selectbox("Letová výška [ft AMSL]", opts,
                             index=opts.index(default_level),
                             format_func=core.level_label, key="diag_fl_"+key)
    with middle:
        bearing = st.slider("Azimut řezu [°]", 0, 359, 0, 1, key="diag_az_"+key)
    with right:
        limit_km = float(result["distance"][-1]/1000)
        distance = st.number_input(
            "Vzdálenost cíle [km]",
            min_value=float(result["distance"][0]/1000),
            max_value=limit_km,
            value=float(min(50, limit_km)),
            step=float(max(0.25, result["distance"][0]/1000)),
            key="diag_distance_"+key)

    info = diagnose(result, bearing, distance, level)
    if info["state"] == "outside":
        st.warning("Požadovaný směr je mimo sektor skenování nebo mimo dosah radaru. "
                   "Jiný azimut za něj nepovažujeme.")
    else:
        chart, explanation = st.columns([7, 3], gap="medium")
        with chart:
            fig = side_view(result, info)
            st.pyplot(fig, use_container_width=True)
            fig.clear()
        with explanation:
            state = {"covered": "KRYTÝ", "blocked": "NEKRYTÝ",
                     "unknown": "NEZNÁMÉ DEM"}[info["state"]]
            st.metric("Krytí zvoleného cíle", state)
            st.write("**Příčina / omezení:**")
            for cause in info["causes"] or ["Žádné omezení v geometrickém modelu"]:
                st.write("• " + cause)
            blocker = info.get("blocker")
            if blocker:
                st.write("**Nejvyšší horizont na trase (nemusí blokovat)**")
                st.write("{} · {:.2f} km od radaru".format(
                    blocker["name"], blocker["distance_m"]/1000))
                st.write("Vrchol {:.1f} m AMSL · zdánlivý úhel {:.3f}°".format(
                    blocker["top_m"], blocker["angle_deg"]))
                st.write("Výšková rezerva v cíli: **{:+.1f} m**".format(
                    blocker["clearance_m"]))
                st.caption("Podklad překážek AGL se odvozuje interpolací DEM; "
                           "nejde o geodeticky zaměřenou výšku.")
            if info["state"] != "unknown":
                st.caption("Cíl: {:.1f} km · {:.2f}° elevace · {:.1f} km šikmý dosah. "
                           "Vzorkováno v azimutu {:.2f}°.".format(
                               info["distance_km"], info["apparent_deg"],
                               info["slant_km"], info["azimuth_deg"]))
                if info["allowed_slant_km"] is not None:
                    st.caption("Limit šikmého dosahu podle diagramu: {:.1f} km."
                               .format(info["allowed_slant_km"]))
        st.caption("Růžový paprsek představuje dráhu k vybranému cíli v modelu efektivní "
                   "Země (faktor k); oranžová čárkovaná čára ukazuje minimální geometrickou "
                   "výšku. Anténní diagram navíc může některé body vyloučit.")

    with st.expander("NEJHORŠÍ AZIMUTY / Pokrytí v dané letové výšce", expanded=True):
        a, b = st.columns(2)
        max_km = float(result["distance"][-1]/1000)
        with a:
            from_km = st.number_input("Od vzdálenosti [km]", min_value=0.0,
                                      max_value=max_km, value=0.0, key="diag_from_"+key)
        with b:
            to_km = st.number_input("Do vzdálenosti [km]", min_value=0.0,
                                    max_value=max_km, value=max_km, key="diag_to_"+key)
        if from_km >= to_km:
            st.warning("Horní hranice vzdálenosti musí být větší než dolní.")
        else:
            try:
                stats = azimuth_coverage_stats(result, level, from_km, to_km)
            except ValueError as exc:
                st.warning(str(exc))
            else:
                frame = pd.DataFrame(stats).rename(columns={
                    "azimuth_deg": "Azimut [°]",
                    "covered_pct": "Kryto [%]",
                    "unknown_pct": "Neznámé DEM [%]"})
                st.dataframe(frame.sort_values(["Kryto [%]", "Azimut [°]"],
                                                na_position="last").head(25),
                             use_container_width=True, hide_index=True)
                st.download_button("Stáhnout všechna hodnocená radiála (CSV)",
                    frame.to_csv(index=False).encode("utf-8-sig"),
                    file_name="coverage_blind_azimuths.csv", mime="text/csv",
                    key="diag_csv_"+key)
                st.caption("Pokrytí je vážené plochou prstenců na daném radiálu; "
                           "neznámé DEM je vykazováno samostatně, nikoli jako kryté. "
                           "Pro PAR se hodnotí pouze vypočtený sektor.")

    st.info("Výsledek je deterministická geometrická analýza nad použitým DEM "
            "a diagramem antény; není to pravděpodobnost detekce Pd/Pfa ani "
            "ověření skutečné radarové funkce. Přesnost určuje DEM a krok vzorkování.")
