"""Independent English customer PDF atlas for computed COVERAGEDIAGRAMS results.

Does not modify the selectable ZIP presets or recompute radar visibility.
"""
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from io import BytesIO
from html import escape
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Sequence

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from PIL import Image
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph

import radar_core as core
from customer_delivery import customer_metrics

NAVY = colors.HexColor("#17354F")
BLUE = colors.HexColor("#236EAB")
MUTED = colors.HexColor("#597185")
PALE = colors.HexColor("#EAF2F8")
WHITE = colors.white
PAGE_W, PAGE_H = landscape(A4)
MARGIN = 43

INTRO = (
    "The prediction of MSSR coverage in the local environment is a complex task due to "
    "the terrain, rapidly changing weather conditions, and the presence of mountainous "
    "areas and coastal effects.",
    "For initial coverage assessment, we use digital elevation models (DEM), such as "
    "SRTM data, combined with radar system parameters and engineering-based calculation "
    "methods. This allows us to model terrain influence, identify shadowing areas, and "
    "estimate the achievable radar coverage.",
    "It is important to note that datasets such as SRTM, although standard in the "
    "industry, have inherent limitations. The data resolution is limited, coverage is "
    "not fully homogeneous, and some areas may contain inaccuracies. In addition, "
    "these models do not include local obstacles (e.g. buildings, vegetation) and "
    "do not fully reflect real propagation conditions over complex terrain.",
    "Therefore, the presented coverage maps shall be considered as preliminary "
    "engineering models, representing a conservative and realistic estimation of "
    "radar performance based on available data.",
    "Despite these limitations, the performed analysis clearly demonstrates that "
    "the proposed system can fulfil the coverage requirements defined upon details "
    "gathered on site survey. The system design, including antenna characteristics, "
    "transmitted power, and signal processing, is selected to ensure that the required "
    "coverage is achieved with sufficient margin.",
    "We can adapt and optimize the system configuration according to the specific "
    "site conditions identified during the detailed survey phase. The final "
    "verification of coverage performance will be performed during the later stages "
    "of the project, including detailed site survey, system tuning, and on-site "
    "measurements (e.g. during commissioning, FAT and SAT).",
    "These activities will confirm full compliance with the contractual requirements.",
)


@dataclass(frozen=True)
class CoverageReportOptions:
    project_name: str = "Radar Coverage Study"
    flight_levels_ft: Sequence[int] = ()
    basemap: str = "Satelitní · Esri"
    dpi: int = 600


def _page(c, title, project, page_number):
    page_w, page_h = c._pagesize
    c.setFillColor(NAVY)
    c.rect(0, page_h - 35, page_w, 35, fill=1, stroke=0)
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(WHITE)
    c.drawString(MARGIN, page_h - 23, "COVERAGEDIAGRAMS  /  RADAR COVERAGE REPORT")
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 19)
    c.drawString(MARGIN, page_h - 69, title)
    c.setFont("Helvetica", 9)
    c.setFillColor(MUTED)
    c.drawString(MARGIN, 24, project[:95])
    c.drawRightString(page_w - MARGIN, 24, f"{page_number:02d}")
    c.setStrokeColor(colors.HexColor("#DDE7EE"))
    c.line(MARGIN, 37, page_w - MARGIN, 37)


def _paragraph(c, body, x, y, width, size=9.4, leading=14.0, bold=False):
    style = ParagraphStyle(
        "report", fontName="Helvetica-Bold" if bold else "Helvetica",
        fontSize=size, leading=leading, textColor=NAVY,
        alignment=TA_LEFT, spaceAfter=0,
    )
    p = Paragraph(body, style)
    _, height = p.wrap(width, c._pagesize[1])
    p.drawOn(c, x, y - height)
    return y - height


def _intro_page(c, project):
    c.setPageSize(A4)
    w, h = c._pagesize
    _page(c, "Coverage Maps", project, 1)
    y = h - 100
    y = _paragraph(c, escape(INTRO[0]), MARGIN, y, w - 2 * MARGIN, 10, 15) - 18
    y = _paragraph(c, "Coverage Prediction, Preliminary", MARGIN, y,
                   w - 2 * MARGIN, 13, 17, bold=True) - 13
    for item in INTRO[1:]:
        y = _paragraph(c, escape(item), MARGIN, y, w - 2 * MARGIN, 9.4, 13.5) - 13
    if y < 48:
        raise ValueError("Report introduction does not fit the portrait page.")
    c.showPage()



# Every parameter below is taken from the stored computation result.
# Editing the workspace after a calculation does not change the report's record.
_PARAM_LABELS = {
    "lat": ("Radar latitude", "deg WGS84"),
    "lon": ("Radar longitude", "deg WGS84"),
    "radar_mode": ("Radar mode", ""),
    "antenna_agl": ("Antenna centre height", "m AGL"),
    "range_km": ("Modelled range", "km"),
    "step_m": ("Radial sampling step", "m"),
    "az_step": ("Configured azimuth step", "deg"),
    "k": ("Effective Earth radius factor (k)", ""),
    "min_elev": ("Minimum elevation", "deg"),
    "max_elev": ("Maximum elevation", "deg"),
    "antenna_tilt_deg": ("Antenna tilt", "deg"),
    "beam_mode": ("Antenna beam mode", ""),
    "csc_enabled": ("CSC / antenna pattern enabled", ""),
    "csc_ref_deg": ("CSC reference elevation", "deg"),
    "csc_range_km": ("CSC reference range", "km"),
    "target_m": ("Configured target altitude", "m"),
    "reference": ("Target altitude reference", ""),
    "bearing_deg": ("Radar bearing / sector axis", "deg"),
}


def _fmt_value(value):
    if isinstance(value, bool):
        return "Enabled" if value else "Disabled"
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return str(value)


def _technical_pages(c, result, project, start_page=2):
    """Portrait A4 settings and complete computed obstacle inventory."""
    c.setPageSize(A4)
    w, h = c._pagesize
    num = start_page
    y = 0

    def start(title):
        nonlocal y, num
        _page(c, title, project, num)
        num += 1
        y = h - 100

    def ensure(needed, title):
        nonlocal y
        if y - needed < 60:
            c.showPage()
            c.setPageSize(A4)
            start(title)

    def line(label, value, *, indent=0):
        nonlocal y
        label = str(label)
        value = str(value)
        content = (f"<b>{escape(label)}</b>  {escape(value)}")
        # Properly wrap long vertex lists, names and source provenance.
        style = ParagraphStyle("tech-row", fontName="Helvetica", fontSize=8.4,
                               leading=12.2, textColor=NAVY)
        paragraph = Paragraph(content, style)
        _, height = paragraph.wrap(w - 2 * MARGIN - indent, h)
        ensure(height + 6, "Computation Settings & Obstacles (continued)")
        paragraph.drawOn(c, MARGIN + indent, y - height)
        y -= height + 6

    start("Computation Settings & Obstacles")
    y = _paragraph(c, "The following values describe the actual stored computation, "
                   "not subsequent edits to the project settings.",
                   MARGIN, y, w - 2 * MARGIN, 9, 13) - 16
    y = _paragraph(c, "Radar and Propagation Configuration",
                   MARGIN, y, w - 2 * MARGIN, 12, 16, bold=True) - 13
    cfg = result["config"]
    for key, value in asdict(cfg).items():
        label, unit = _PARAM_LABELS.get(key, (key.replace("_", " ").title(), ""))
        line(label + ":", f"{_fmt_value(value)} {unit}".strip())
    y -= 10
    ensure(70, "Computation Settings & Obstacles (continued)")
    y = _paragraph(c, "Calculation Data & Grid", MARGIN, y,
                   w - 2 * MARGIN, 12, 16, bold=True) - 11
    source = result.get("source", "Not recorded")
    line("Terrain / DEM source:", source)
    line("Site elevation:", f"{_fmt_value(result.get('site_height', 'N/A'))} m AMSL")
    line("Antenna centre elevation:", f"{_fmt_value(result.get('antenna', 'N/A'))} m AMSL")
    line("Actual azimuth samples:", len(result["az"]))
    line("Actual radial samples:", len(result["distance"]))
    line("Total radar grid samples:", len(result["az"]) * len(result["distance"]))
    line("Actual azimuth step:", f"{core.actual_azimuth_step(result):g} deg")
    line("Actual radial step:", f"{float(result['distance'][0]):g} m")
    line("Calculation completed (UTC):", result.get("completed_at", "Not recorded"))
    line("Calculation time:", f"{_fmt_value(result.get('duration_s', 'N/A'))} s")
    line("Height reference for coverage pages:", "Feet AMSL")
    line("Terrain data gaps:", "Excluded from coverage percentage over known terrain")
    y -= 10

    obstacles = result.get("obstacles", [])
    ensure(70, "Computation Settings & Obstacles (continued)")
    y = _paragraph(c, "Obstacles Included in the Calculation",
                   MARGIN, y, w - 2 * MARGIN, 12, 16, bold=True) - 10
    line("Active calculated obstacles:", len(obstacles))
    if not obstacles:
        line("Obstacle model:", "No additional obstacles were included. Terrain DEM only.")
    for index, o in enumerate(obstacles, start=1):
        ensure(80, "Calculated Obstacles (continued)")
        y -= 5
        line(f"Obstacle {index}:", str(o.get("name") or f"Obstacle {index}"))
        line("Type:", o.get("kind", "point"), indent=13)
        line("Height above local ground:", f"{_fmt_value(o.get('height_m', 'N/A'))} m AGL", indent=13)
        if o.get("kind", "point") == "point":
            line("Position (WGS84):", f"{o.get('lat', 'N/A')}, {o.get('lon', 'N/A')}", indent=13)
        elif o.get("kind") == "polygon":
            coords = o.get("coordinates") or []
            line("Polygon vertices:", len(coords), indent=13)
            for j, vertex in enumerate(coords, start=1):
                if isinstance(vertex, (list, tuple)) and len(vertex) == 2:
                    line(f"Vertex {j} (lat, lon):", f"{vertex[0]}, {vertex[1]}", indent=13)
        elif o.get("kind") == "arc":
            line("Start (lat, lon):", f"{o.get('start_lat')}, {o.get('start_lon')}", indent=13)
            line("End (lat, lon):", f"{o.get('end_lat')}, {o.get('end_lon')}", indent=13)
        # Include any optional metadata without repeating geometry/fields.
        known = {"name", "kind", "height_m", "lat", "lon",
                 "coordinates", "start_lat", "start_lon", "end_lat", "end_lon"}
        for key, value in o.items():
            if key not in known:
                line(key.replace("_", " ").title() + ":", value, indent=13)
    y -= 9
    ensure(48, "Calculated Obstacles (continued)")
    line("Scope:", "Only obstacles stored in the calculated result are listed. "
         "Informational geodata and wind turbines are excluded unless explicitly "
         "converted to active calculation obstacles.")
    c.showPage()
    return num  # next available page number


def _summary_page(c, result, metrics, project, page_number):
    c.setPageSize(landscape(A4))
    _page(c, "Coverage Analysis Summary", project, page_number)
    cfg = result["config"]
    y = PAGE_H - 92
    c.setFont("Helvetica", 9)
    c.setFillColor(MUTED)
    lines = [
        f"Radar mode: {cfg.radar_mode}     Site: {cfg.lat:.6f}, {cfg.lon:.6f} WGS84"
        f"     Range: {cfg.range_km:g} km / {cfg.range_km / 1.852:.1f} NM",
        f"Antenna: {cfg.antenna_agl:g} m AGL     Tilt: {cfg.antenna_tilt_deg:+g} deg"
        f"     DEM: {str(result.get('source', 'Source not recorded'))[:45]}",
    ]
    for line in lines:
        c.drawString(MARGIN, y, line)
        y -= 15
    y -= 11
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(NAVY)
    c.drawString(MARGIN, y, "Area-weighted coverage [% of known DEM area]")
    y -= 16
    if not metrics:
        raise ValueError("No flight levels were selected.")
    available = y - 79
    bar_h = min(19, available / len(metrics))
    if bar_h < 7.5:
        raise ValueError("Too many flight levels for a single summary page.")
    left, x0, x1 = MARGIN, MARGIN + 105, PAGE_W - MARGIN - 54
    chart_width = x1 - x0
    for record in metrics:
        ft = record["flight_level_ft_amsl"]
        pct = record["coverage_pct_of_known_area"]
        pct_total = record["coverage_pct_of_total_domain"]
        c.setFillColor(NAVY)
        c.setFont("Helvetica", 8 if bar_h >= 12 else 6.5)
        c.drawString(left, y - bar_h + 5, f"{ft:,} ft AMSL")
        c.setFillColor(PALE)
        c.roundRect(x0, y - bar_h + 3, chart_width, max(3, bar_h - 5), 2, fill=1, stroke=0)
        if pct is not None:
            c.setFillColor(BLUE)
            c.roundRect(x0, y - bar_h + 3, chart_width * pct / 100,
                        max(3, bar_h - 5), 2, fill=1, stroke=0)
        c.setFillColor(NAVY)
        c.setFont("Helvetica-Bold", 8 if bar_h >= 12 else 6.5)
        c.drawRightString(PAGE_W - MARGIN, y - bar_h + 5,
                          "N/A" if pct is None else f"{pct:.1f}%")
        y -= bar_h
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 8)
    c.drawString(MARGIN, 55, "Known DEM coverage is the denominator; missing terrain data is excluded.")
    c.drawString(MARGIN, 44, "Preliminary geometric prediction, not measured detection probability or contractual acceptance.")
    c.showPage()


def _image_page(c, title, project, page_number, image, caption):
    _page(c, title, project, page_number)
    # Compress embedded map image to print-resolution JPEG to avoid huge PDFs.
    with Image.open(image) as source:
        reduced = source.convert("RGB")
        reduced.thumbnail((6600, 4600), Image.Resampling.LANCZOS)
        encoded = BytesIO()
        reduced.save(encoded, format="JPEG", quality=95, optimize=True, subsampling=0)
        encoded.seek(0)
    reader = ImageReader(encoded)
    width, height = reader.getSize()
    # Give the map graphic virtually the entire printable landscape page.
    box = (MARGIN - 23, 59, PAGE_W - 2 * MARGIN + 46, PAGE_H - 129)
    x, y, w, h = box
    scale = min(w / width, h / height)
    render_w, render_h = width * scale, height * scale
    c.drawImage(reader, x + (w - render_w) / 2, y + (h - render_h) / 2,
                width=render_w, height=render_h, mask="auto")
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 8)
    c.drawString(MARGIN, 50, caption[:150])
    c.showPage()


def generate_coverage_report_pdf(result: dict, options: CoverageReportOptions) -> bytes:
    """Build one PDF independently of ZIP, KML and raster exports."""
    if result is None or "config" not in result:
        raise ValueError("Compute radar coverage before generating the report.")
    levels = sorted({int(ft) for ft in options.flight_levels_ft}, reverse=True)
    if not levels or any(ft <= 0 for ft in levels):
        raise ValueError("Select at least one valid flight altitude.")
    if options.basemap not in ("Satelitní · Esri", "Esri · Topographic (legacy)"):
        raise ValueError("Unsupported Esri basemap selection.")
    if options.dpi not in (300, 600):
        raise ValueError("DPI must be 300 or 600.")
    project = (options.project_name or "Radar Coverage Study").strip()[:95]
    metrics = customer_metrics(result, levels)
    # Match the basemap viewport to the full exported plot, including the
    # outer reference range ring. Otherwise a 60 NM radar produces a 60 NM
    # square of tiles inside a plot expanded to the 100 NM reference ring.
    config = result["config"]
    radar_mode = str(config.radar_mode).upper()
    if radar_mode == "PAR-NG":
        view_radius_km = float(config.range_km)
    else:
        outer_ring_nm = 260 if "SSR" in radar_mode else 100
        view_radius_km = max(float(config.range_km), outer_ring_nm * 1.852) * 1.035
    viewport = (-view_radius_km, view_radius_km,
                -view_radius_km, view_radius_km)
    # Fetch/reproject once: all report maps share the same AEQD geometry.
    basemap = core.load_basemap(config, viewport=viewport, out_size=(1300, 1300),
                                provider=options.basemap)
    if basemap is None or basemap.get("image") is None:
        raise ValueError("Esri basemap is unavailable. Report not generated.")
    buffer = BytesIO()
    pdf = Canvas(buffer, pagesize=(PAGE_W, PAGE_H), pageCompression=1)
    pdf.setTitle(f"Coverage Maps - {project}")
    pdf.setAuthor("COVERAGEDIAGRAMS")
    pdf.setSubject("Preliminary engineering radar coverage prediction")
    _intro_page(pdf, project)
    next_page = _technical_pages(pdf, result, project, start_page=2)
    _summary_page(pdf, result, metrics, project, page_number=next_page)
    next_page += 1
    with TemporaryDirectory(prefix="cd_coverage_report_") as temp:
        png = Path(temp) / "figure.png"
        core.export_map_image(png, result, "Terén", dpi=options.dpi,
                              english=True, theme="light", alpha=1.0)
        _image_page(pdf, "Terrain Model Used for Coverage Calculation",
                    project, next_page, png,
                    f"Terrain sampled by the radar model. DEM: {str(result.get('source', 'not recorded'))[:90]}. Elevation in metres AMSL.")
        for n, item in enumerate(metrics, start=next_page + 1):
            level = item["flight_level_ft_amsl"]
            core.export_map_image(png, result, "Vybrané výšky",
                                  basemap=basemap, levels_ft=(level,),
                                  alpha=0.43, dpi=options.dpi,
                                  english=True, theme="light", report_layout=True)
            coverage = item["coverage_pct_of_known_area"]
            caption = (f"Altitude: {level:,} ft AMSL  |  Area-weighted coverage: "
                       + ("N/A" if coverage is None else f"{coverage:.2f}%")
                       + f"  |  Map: {options.basemap}  |  " + str(basemap.get("attribution", "Esri")))
            _image_page(pdf, f"Coverage Diagram - {level:,} ft AMSL",
                        project, n, png, caption)
    pdf.save()
    return buffer.getvalue()
