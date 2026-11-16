"""Static integration contracts for the optional Viewer Studio UI."""
from viewer_studio_extensions import enhance_page
from viewer_fullscreen import _HTML


def test_studio_ui_is_wired_without_changing_native_geojson():
    enhanced = enhance_page(_HTML)
    for marker in (
        'id="studio-fl-button"',
        'id="studio-preset"',
        'id="studio-views"',
        'id="studio-area"',
        'function studioStepFL()',
        'function studioGeometryAreaKm2(g)',
        'function studioSaveView()',
        'function studioMove(name,dir)',
    ):
        assert marker in enhanced
    assert enhanced.count("function setup(){") == 1
    assert enhanced.count("setup();") == 1
    assert 'studioSnapshotsKey' in enhanced
    assert 'studioAreaCache' in enhanced
    assert 'o.features' in enhanced
    assert 'const studioOldSyncAll=syncAll;' in enhanced


def test_studio_enhancement_keeps_native_inspector_and_import():
    page = enhance_page(_HTML)
    for marker in (
        'function loadFile(file)',
        'function showStandaloneInspection()',
        'function saveCDView()',
        'function smoothedGeometry(g,radiusM)',
        'function selectedCoverageLevel(layerName)',
    ):
        assert marker in page
