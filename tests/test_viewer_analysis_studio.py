"""Focused regression tests for the second VIEWER studio stage."""
import io
import json

from viewer_coverage_analysis import compare_coverage, coverage_stats, coverage_union
from viewer_analysis_studio import render_atlas_pdf
from viewer_studio_extensions import enhance_page
from viewer_fullscreen import _HTML


def feature(coords):
    return {"type":"Feature","properties":{"name":"TEST"},
            "geometry":{"type":"Polygon","coordinates":[coords]}}


A=[feature([[14.0,50.0],[14.2,50.0],[14.2,50.2],[14.0,50.2],[14.0,50.0]])]
B=[feature([[14.1,50.0],[14.3,50.0],[14.3,50.2],[14.1,50.2],[14.1,50.0]])]


def test_compare_geometrically_correct():
    data=compare_coverage(A,B)
    m=data["metrics"]
    assert m["common"]>0
    assert m["gained"]>0
    assert m["lost"]>0
    assert abs(m["common"]+m["lost"]-m["baseline"])<0.1
    assert abs(m["common"]+m["gained"]-m["candidate"])<0.1
    assert {f["properties"]["name"] for f in data["features"]}=={"COMMON","GAINED","LOST"}


def test_source_features_unchanged():
    before=json.dumps([A,B],sort_keys=True)
    compare_coverage(A,B)
    assert json.dumps([A,B],sort_keys=True)==before


def test_sector_statistics():
    result=coverage_stats(A,radar_lat=50.1,radar_lon=14.1,sectors=12,range_nm=50)
    assert result["area_km2"]>0
    assert len(result["sectors"])==12
    assert all(0<=s["percent"]<=100.1 for s in result["sectors"])


def test_duplicate_polygons_are_union_not_double_counted():
    a=coverage_stats(A)["area_km2"]
    b=coverage_stats(A+A)["area_km2"]
    assert abs(a-b)<0.001


def test_integrated_viewer_keeps_one_setup_and_original_los():
    html=enhance_page(_HTML)
    assert html.count("function setup(){")==1
    for marker in ("id=\"studio-measure\"","id=\"studio-graticule\"",
                   "id=\"studio-vector-only\"","studioStepFL",
                   "cartoInverse","showStandaloneInspection",
                   "function loadFile(file)"):
        assert marker in html


def test_printed_atlas_is_pdf(monkeypatch):
    import viewer_export
    # Tiny valid PNG avoids generating a full 300 DPI raster in this unit test.
    from PIL import Image
    image=Image.new("RGB",(16,16),"white")
    b=io.BytesIO();image.save(b,format="PNG")
    monkeypatch.setattr(viewer_export,"render_print",lambda *args,**kw:b.getvalue())
    data=render_atlas_pdf({"RADAR / 3000 ft":A},
                          {"RADAR / 3000 ft":{"show":True,"color":"#2277aa"}},
                          "Trial",paper="A4")
    assert data.startswith(b"%PDF")
    assert len(data)>2500
