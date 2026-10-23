"""Smoke-test the initial Streamlit page, not just Python compilation.

This catches startup failures in widget construction, session state, and
the selected Streamlit library version before they reach Cloud.
"""
from pathlib import Path
from streamlit.testing.v1 import AppTest


def test_streamlit_app_initial_render():
    app_file = Path(__file__).resolve().parents[1] / "streamlit_app.py"
    app = AppTest.from_file(str(app_file), default_timeout=90).run()
    assert len(app.exception) == 0, "\n".join(str(item.message) for item in app.exception)
