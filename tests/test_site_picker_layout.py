"""Check the location picker UX and settings hierarchy stay wired in place."""
import ast
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1].joinpath('streamlit_app.py').read_text(encoding='utf-8')


def test_map_picker_draws_persistent_precise_point_and_crosshair():
    assert 'cursor: crosshair !important;' in SOURCE
    assert "st.session_state['site_picker_selection'] = new_selection" in SOURCE
    assert "st.rerun(scope='fragment')" in SOURCE
    assert 'list(selected), radius=4' in SOURCE
    assert "returned_objects=['last_clicked', 'center', 'zoom']" in SOURCE


def test_project_controls_appear_below_all_settings_panels():
    module = ast.parse(SOURCE)
    settings = next(
        node for node in module.body if isinstance(node, ast.With)
        and isinstance(node.items[0].context_expr, ast.Name)
        and node.items[0].context_expr.id == 'settings'
    )
    positions = {}
    for index, node in enumerate(settings.body):
        if not isinstance(node, ast.With):
            continue
        context = node.items[0].context_expr
        if isinstance(context, ast.Name):
            positions[context.id] = index
        if isinstance(context, ast.Call) and isinstance(context.func, ast.Attribute):
            if context.func.attr == 'expander':
                positions['projects'] = index
    assert all(panel in positions for panel in ('location', 'parameters', 'preview', 'execution', 'projects'))
    assert positions['projects'] > positions['execution']
