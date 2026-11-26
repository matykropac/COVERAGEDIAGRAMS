"""Compose a user-selected COVERAGEDIAGRAMS export ZIP."""
from io import BytesIO
from pathlib import Path
import tempfile
from zipfile import ZIP_STORED, ZipFile

import radar_core as core
import environment_layers as env
from web_support import export_bytes, export_quickreport


FORMATS = {
    "kml": ("KML · polygony krytí a překážek", "KML · všechny vrstvy (polygony)", "04_Geodata"),
    "gpkg": ("GeoPackage · vektorové vrstvy", "GeoPackage · vektory", "04_Geodata"),
    "tiff": ("GeoTIFF · rastrové vrstvy", "GeoTIFF · rastr", "04_Geodata"),
    "npz": ("RAW · úplná výpočetní data NPZ", "RAW · NPZ", "05_Data"),
    "csv": ("CSV · aktuální radiální profil", "Profil · CSV", "05_Data"),
    "json": ("JSON · metadata výpočtu", "Metadata · JSON", "05_Data"),
}


def build_selected_zip(result, *, selected, flight_levels, index, alpha,
                       level_alphas, environment_items, project_bytes=None,
                       map_html=None, map_bundle=None, customer_name="Radar Coverage Study", progress=None):
    """Only create entries checked by the user. Preserve original export routines."""
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    valid = {"project", "html", "layers", "terrain", "antenna", "fl_png",
             "png_dark", "png_light", "quickreport", "customer_pack", "a4_esri_aip",
             "customer_maps", "customer_terrain", "customer_antenna", *FORMATS}
    active = {key for key, value in selected.items() if value}
    if not active or active - valid:
        raise ValueError("Select valid export products.")
    flight_levels = tuple(dict.fromkeys(flight_levels))
    if active & {"fl_png", "png_dark", "png_light", "quickreport", "customer_pack",
                 "customer_maps", "a4_esri_aip", "kml", "gpkg", "tiff"} and not flight_levels:
        raise ValueError("Select at least one flight altitude.")
    for key, payload in (("project", project_bytes), ("html", map_html), ("layers", map_bundle)):
        if key in active and not payload:
            raise ValueError(f"Selected product is unavailable: {key}")
    total = sum(len(flight_levels) if key in {"fl_png", "customer_maps", "a4_esri_aip"}
                else 4 + 4 * len(flight_levels) + 2 if key == "quickreport"
                else 1 for key in active) + 1
    done = 0
    def notify(message, increment=0):
        nonlocal done
        done += increment
        if progress is not None:
            progress(done, total, message)

    with tempfile.TemporaryFile(mode="w+b") as contents, ZipFile(
            contents, "w", compression=ZIP_STORED, allowZip64=True) as archive:
        notify("Preparing archive")
        if selected.get("project") and project_bytes:
            archive.writestr("00_Project/radar_coverage.cdproj", project_bytes)
            notify("Project completed", 1)
        if selected.get("html") and map_html:
            archive.writestr("01_Interactive_Map/map.html", map_html)
            notify("Interactive map completed", 1)
        if selected.get("layers") and map_bundle:
            with ZipFile(BytesIO(map_bundle), "r") as source:
                for name in source.namelist():
                    if not name.endswith("/"):
                        archive.writestr("02_Map_Layers/" + name, source.read(name))

        if selected.get("layers"):
            notify("Map layers completed", 1)

        for key, (_, kind, folder) in FORMATS.items():
            if selected.get(key):
                # Geo formats use the user's checked FL set, including KML.
                blob, filename, _ = export_bytes(
                    kind, result, flight_levels, index, 600, alpha,
                    level_alphas, environment_items=environment_items)
                archive.writestr(f"{folder}/{filename}", blob)
                notify("Data export completed", 1)

        if selected.get("png_dark") or selected.get("png_light"):
            for theme_key, kind in (
                ("png_dark", "Obrázek · PNG"),
                ("png_light", "Obrázek · PNG (Light)"),
            ):
                if selected.get(theme_key):
                    blob, filename, _ = export_bytes(
                        kind, result, flight_levels, index, 600, alpha,
                        level_alphas, environment_items=environment_items)
                    archive.writestr(f"03_Images/{filename}", blob)
                    notify("Combined map completed", 1)

        if selected.get("terrain") or selected.get("antenna") or selected.get("fl_png"):
            with tempfile.TemporaryDirectory(prefix="cd_selected_zip_") as work:
                image_path = Path(work) / "image.png"
                if selected.get("terrain"):
                    core.export_map_image(
                        image_path, result, "Terén", dpi=500,
                        alpha=1.0, english=True, theme="light",
                        environment_items=environment_items)
                    archive.write(image_path, "03_Images/terrain_500dpi.png")
                    notify("Terrain completed", 1)

                if selected.get("antenna"):
                    fig = Figure(figsize=(13, 9), dpi=500, facecolor="white")
                    FigureCanvasAgg(fig)
                    try:
                        core.technical_plot(fig, result=result, english=True)
                        fig.text(.07, .975, "ELDIS · ANTENNA DIAGRAM",
                                 color="#17324c", fontsize=18, weight="bold", va="top")
                        core.style_export_theme(fig, "light")
                        fig.savefig(image_path, dpi=500, format="png",
                                    facecolor=fig.get_facecolor())
                    finally:
                        fig.clear()
                    archive.write(image_path, "03_Images/antenna_diagram_500dpi.png")
                    notify("Antenna completed", 1)

                if selected.get("fl_png"):
                    for level in flight_levels:
                        core.export_map_image(
                            image_path, result, "Vybrané výšky",
                            levels_ft=(level,), alpha=0.74, dpi=500,
                            english=True, theme="light",
                            environment_items=environment_items)
                        archive.write(
                            image_path, f"03_Images/Flight_Levels/{int(level):05d}ft_AMSL_500dpi.png")
                        notify(f"Coverage FL {level} ft completed", 1)

        # Optional light-only handover products; never alter existing presets.
        if selected.get("customer_pack"):
            from customer_delivery import build_customer_pack
            package=build_customer_pack(result,flight_levels,customer_name)
            with ZipFile(BytesIO(package),"r") as src:
                for filename in src.namelist():
                    if not filename.endswith("/"):
                        archive.writestr("07_Customer_Delivery/"+filename,src.read(filename))

        if selected.get("customer_pack"):
            notify("Customer report completed", 1)

        if selected.get("customer_maps") or selected.get("customer_terrain") or selected.get("customer_antenna"):
            with tempfile.TemporaryDirectory(prefix="cd_customer_maps_") as work:
                img=Path(work)/"customer_export.png"
                if selected.get("customer_maps"):
                    for level in flight_levels:
                        core.export_map_image(
                            img,result,"Vybrané výšky",levels_ft=(level,),
                            alpha=.75,dpi=500,english=True,theme="light",
                            environment_items=environment_items)
                        archive.write(img,f"07_Customer_Delivery/Customer_Pack/Maps_Light/"
                                      f"Coverage_{int(level):05d}ft_AMSL_500dpi.png")
                        notify(f"Customer FL {level} ft completed", 1)
                if selected.get("customer_terrain"):
                    core.export_map_image(img,result,"Terén",alpha=1.,dpi=500,
                                          english=True,theme="light",
                                          environment_items=environment_items)
                    archive.write(img,"07_Customer_Delivery/Customer_Pack/Maps_Light/"
                                  "Terrain_500dpi.png")
                    notify("Customer terrain completed", 1)
                if selected.get("customer_antenna"):
                    fig=Figure(figsize=(12,8),dpi=500,facecolor="white")
                    FigureCanvasAgg(fig)
                    try:
                        core.technical_plot(fig,result=result,english=True)
                        core.style_export_theme(fig,"light")
                        fig.savefig(img,dpi=500,format="png",facecolor="white")
                    finally:
                        fig.clear()
                    archive.write(img,"07_Customer_Delivery/Customer_Pack/Maps_Light/"
                                  "Antenna_Pattern_500dpi.png")
                    notify("Customer antenna completed", 1)

        if selected.get("a4_esri_aip"):
            from a4_aviation_export import load_a4_basemap, render_a4_fl
            notify("Loading Esri Street Map + OpenAIP")
            basemap = load_a4_basemap(result["config"])
            with tempfile.TemporaryDirectory(prefix="cd_a4_aviation_") as work:
                img = Path(work) / "page.png"
                for level in flight_levels:
                    notify(f"Rendering A4 FL {level} ft AMSL")
                    render_a4_fl(img, result, level, basemap,
                                 alpha=(level_alphas or {}).get(level, alpha))
                    archive.write(img, f"08_A4_Esri_OpenAIP/{int(level):05d}ft_AMSL_A4_500dpi.png")
                    notify(f"A4 FL {level} ft completed", 1)

        if selected.get("quickreport"):
            notify("Preparing QuickReport")
            report = export_quickreport(
                result, flight_levels=flight_levels,
                environment_items=environment_items, progress=notify)
            # Integrate individual files rather than embed a second ZIP.
            with ZipFile(BytesIO(report), "r") as source:
                for name in source.namelist():
                    if not name.endswith("/"):
                        archive.writestr("06_QuickReport/" + name, source.read(name))

        notify("Finalizing ZIP")
        archive.close()
        contents.seek(0)
        data = contents.read()
        if progress is not None:
            progress(total, total, "ZIP ready")
        return data
