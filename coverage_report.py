"""Independent English customer PDF atlas for computed COVERAGEDIAGRAMS results.

Does not modify the selectable ZIP presets or recompute radar visibility.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
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
    c.setFillColor(NAVY)
    c.rect(0, PAGE_H - 35, PAGE_W, 35, fill=1, stroke=0)
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(WHITE)
    c.drawString(MARGIN, PAGE_H - 23, "COVERAGEDIAGRAMS  /  RADAR COVERAGE REPORT")
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 19)
    c.drawString(MARGIN, PAGE_H - 69, title)
    c.setFont("Helvetica", 9)
    c.setFillColor(MUTED)
    c.drawString(MARGIN, 24, project[:95])
    c.drawRightString(PAGE_W - MARGIN, 24, f"{page_number:02d}")
    c.setStrokeColor(colors.HexColor("#DDE7EE"))
    c.line(MARGIN, 37, PAGE_W - MARGIN, 37)


def _paragraph(c, body, x, y, width, size=9.4, leading=14.0, bold=False):
    style = ParagraphStyle(
        "report", fontName="Helvetica-Bold" if bold else "Helvetica",
        fontSize=size, leading=leading, textColor=NAVY,
        alignment=TA_LEFT, spaceAfter=0,
    )
    p = Paragraph(body, style)
    _, height = p.wrap(width, PAGE_H)
    p.drawOn(c, x, y - height)
    return y - height


def _intro_page(c, project):
    _page(c, "Coverage Maps", project, 1)
    y = PAGE_H - 91
    y = _paragraph(c, INTRO[0], MARGIN, y, PAGE_W - 2 * MARGIN, 10, 15) - 15
    y = _paragraph(c, "Coverage Prediction, Preliminary", MARGIN, y,
                   PAGE_W - 2 * MARGIN, 13, 17, bold=True) - 10
    for item in INTRO[1:]:
        y = _paragraph(c, item, MARGIN, y, PAGE_W - 2 * MARGIN, 9.4, 13.5) - 11
    if y < 46:
        raise ValueError("Report introduction does not fit the page.")
    c.showPage()


def _summary_page(c, result, metrics, project):
    _page(c, "Coverage Analysis Summary", project, 2)
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
    box = (MARGIN - 8, 62, PAGE_W - 2 * MARGIN + 16, PAGE_H - 145)
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
    # Fetch/reproject once: all maps share precisely the same AEQD geometry.
    basemap = core.load_basemap(result["config"], out_size=(1300, 1300),
                                provider=options.basemap)
    if basemap is None or basemap.get("image") is None:
        raise ValueError("Esri basemap is unavailable. Report not generated.")
    buffer = BytesIO()
    pdf = Canvas(buffer, pagesize=(PAGE_W, PAGE_H), pageCompression=1)
    pdf.setTitle(f"Coverage Maps - {project}")
    pdf.setAuthor("COVERAGEDIAGRAMS")
    pdf.setSubject("Preliminary engineering radar coverage prediction")
    _intro_page(pdf, project)
    _summary_page(pdf, result, metrics, project)
    with TemporaryDirectory(prefix="cd_coverage_report_") as temp:
        png = Path(temp) / "figure.png"
        core.export_map_image(png, result, "Terén", dpi=options.dpi,
                              english=True, theme="light", alpha=1.0)
        _image_page(pdf, "Terrain Model Used for Coverage Calculation",
                    project, 3, png,
                    f"Terrain sampled by the radar model. DEM: {str(result.get('source', 'not recorded'))[:90]}. Elevation in metres AMSL.")
        for n, item in enumerate(metrics, start=4):
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
