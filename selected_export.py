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
                       map_html=None, map_bundle=None, customer_name="Radar Coverage Study"):
    """Only create entries checked by the user. Preserve original export routines."""
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    contents = BytesIO()
    with ZipFile(contents, "w", compression=ZIP_STORED, allowZip64=True) as archive:
        if selected.get("project") and project_bytes:
            archive.writestr("00_Project/radar_coverage.cdproj", project_bytes)
        if selected.get("html") and map_html:
            archive.writestr("01_Interactive_Map/map.html", map_html)
        if selected.get("layers") and map_bundle:
            with ZipFile(BytesIO(map_bundle), "r") as source:
                for name in source.namelist():
                    if not name.endswith("/"):
                        archive.writestr("02_Map_Layers/" + name, source.read(name))

        for key, (_, kind, folder) in FORMATS.items():
            if selected.get(key):
                # Geo formats use the user's checked FL set, including KML.
                blob, filename, _ = export_bytes(
                    kind, result, flight_levels, index, 600, alpha,
                    level_alphas, environment_items=environment_items)
                archive.writestr(f"{folder}/{filename}", blob)

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

        if selected.get("terrain") or selected.get("antenna") or selected.get("fl_png"):
            with tempfile.TemporaryDirectory(prefix="cd_selected_zip_") as work:
                image_path = Path(work) / "image.png"
                if selected.get("terrain"):
                    core.export_map_image(
                        image_path, result, "Terén", dpi=600,
                        alpha=1.0, english=True, theme="light",
                        environment_items=environment_items)
                    archive.write(image_path, "03_Images/terrain_600dpi.png")

                if selected.get("antenna"):
                    fig = Figure(figsize=(13, 9), dpi=600, facecolor="white")
                    FigureCanvasAgg(fig)
                    try:
                        core.technical_plot(fig, result=result, english=True)
                        fig.text(.07, .975, "ELDIS · ANTENNA DIAGRAM",
                                 color="#17324c", fontsize=18, weight="bold", va="top")
                        core.style_export_theme(fig, "light")
                        fig.savefig(image_path, dpi=600, format="png",
                                    facecolor=fig.get_facecolor())
                    finally:
                        fig.clear()
                    archive.write(image_path, "03_Images/antenna_diagram_600dpi.png")

                if selected.get("fl_png"):
                    for level in flight_levels:
                        core.export_map_image(
                            image_path, result, "Vybrané výšky",
                            levels_ft=(level,), alpha=0.74, dpi=600,
                            english=True, theme="light",
                            environment_items=environment_items)
                        archive.write(
                            image_path, f"03_Images/Flight_Levels/{int(level):05d}ft_AMSL_600dpi.png")

        # Optional light-only handover products; never alter existing presets.
        if selected.get("customer_pack"):
            from customer_delivery import build_customer_pack
            package=build_customer_pack(result,flight_levels,customer_name)
            with ZipFile(BytesIO(package),"r") as src:
                for filename in src.namelist():
                    if not filename.endswith("/"):
                        archive.writestr("07_Customer_Delivery/"+filename,src.read(filename))

        if selected.get("customer_maps") or selected.get("customer_terrain") or selected.get("customer_antenna"):
            with tempfile.TemporaryDirectory(prefix="cd_customer_maps_") as work:
                img=Path(work)/"customer_export.png"
                if selected.get("customer_maps"):
                    for level in flight_levels:
                        core.export_map_image(
                            img,result,"Vybrané výšky",levels_ft=(level,),
                            alpha=.75,dpi=300,english=True,theme="light",
                            environment_items=environment_items)
                        archive.write(img,f"07_Customer_Delivery/Customer_Pack/Maps_Light/"
                                      f"Coverage_{int(level):05d}ft_AMSL_300dpi.png")
                if selected.get("customer_terrain"):
                    core.export_map_image(img,result,"Terén",alpha=1.,dpi=300,
                                          english=True,theme="light",
                                          environment_items=environment_items)
                    archive.write(img,"07_Customer_Delivery/Customer_Pack/Maps_Light/"
                                  "Terrain_300dpi.png")
                if selected.get("customer_antenna"):
                    fig=Figure(figsize=(12,8),dpi=300,facecolor="white")
                    FigureCanvasAgg(fig)
                    try:
                        core.technical_plot(fig,result=result,english=True)
                        core.style_export_theme(fig,"light")
                        fig.savefig(img,dpi=300,format="png",facecolor="white")
                    finally:
                        fig.clear()
                    archive.write(img,"07_Customer_Delivery/Customer_Pack/Maps_Light/"
                                  "Antenna_Pattern_300dpi.png")

        if selected.get("quickreport"):
            report = export_quickreport(
                result, flight_levels=flight_levels,
                environment_items=environment_items)
            # Integrate individual files rather than embed a second ZIP.
            with ZipFile(BytesIO(report), "r") as source:
                for name in source.namelist():
                    if not name.endswith("/"):
                        archive.writestr("06_QuickReport/" + name, source.read(name))

    return contents.getvalue()
