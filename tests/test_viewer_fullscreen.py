"""Regression checks for the browser-managed fullscreen VIEWER."""
import ast
from pathlib import Path
import re
import shutil
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]


class FullscreenViewerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=(ROOT/"viewer_fullscreen.py").read_text(encoding="utf-8")
        tree=ast.parse(cls.source)
        html_nodes=[n.value for n in tree.body if isinstance(n,ast.Assign)
                    and any(isinstance(t,ast.Name) and t.id=="_HTML" for t in n.targets)]
        assert len(html_nodes)==1 and isinstance(html_nodes[0],ast.Constant)
        cls.html=html_nodes[0].value

    def test_floating_workspace_and_import_support(self):
        for text in ('id="map"','id="panel"','id="layer-list"',
                     'id="file"','id="search"','id="base"',
                     '.cdview','.kmz','.kml','.geojson','function syncOne(o)'):
            self.assertIn(text,self.html)

    def test_no_streamlit_update_for_layer_changes(self):
        self.assertNotIn("setComponentValue",self.html)
        self.assertNotIn("postMessage(",self.html)
        self.assertIn("L.canvas",self.html)

    def test_entrypoint_uses_fullscreen_viewer(self):
        source=(ROOT/"coverage_viewer.py").read_text(encoding="utf-8")
        self.assertIn("from viewer_fullscreen import render_fullscreen_viewer",source)
        self.assertIn('st.query_params.get("viewer3d") != "1"',source)

    def test_embedded_javascript_syntax(self):
        if not shutil.which("node"):
            self.skipTest("Node.js unavailable")
        match=re.search(r"<script>\s*(.*?)\s*</script>",self.html,re.S)
        self.assertIsNotNone(match)
        result=subprocess.run(["node","--check"],input=match.group(1),
                              text=True,capture_output=True,check=False)
        self.assertEqual(result.returncode,0,result.stderr)


if __name__=="__main__":
    unittest.main()
