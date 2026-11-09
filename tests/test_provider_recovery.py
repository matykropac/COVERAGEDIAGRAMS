"""Provider recovery must not report temporary network failures as empty geodata."""
import io
import json
import unittest
import sys
from types import ModuleType
from urllib.error import URLError, HTTPError
from unittest.mock import patch

st = ModuleType("streamlit")
st.cache_data = lambda **kwargs: (lambda f: f)
with patch.dict(sys.modules, {"streamlit": st}):
    from environment_layers import _overpass_json_with_fallback
from airspace_geometry import _http_get


class FakeResponse:
    def __init__(self, value):
        self.stream=io.BytesIO(value)
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def read(self, n):
        return self.stream.read(n)


class ProviderRecoveryTests(unittest.TestCase):
    def test_second_overpass_host_recovers(self):
        urls=[]
        def opener(request, timeout):
            urls.append(request.full_url)
            if len(urls)==1:
                raise URLError("connection refused")
            return FakeResponse(b'{"elements":[{"type":"way"}]}')
        result=_overpass_json_with_fallback(
            b'data',opener=opener,endpoints=(
                "https://overpass-api.de/api/interpreter",
                "https://overpass.private.coffee/api/interpreter"))
        self.assertEqual(len(result["elements"]),1)
        self.assertEqual(len(urls),2)

    def test_all_providers_fail_with_actionable_message(self):
        def fail(request,timeout):
            raise URLError("blocked")
        with self.assertRaisesRegex(RuntimeError,"GeoJSON"):
            _overpass_json_with_fallback(b'data',opener=fail,endpoints=(
                "https://overpass-api.de/api/interpreter",))

    def test_invalid_response_tries_next_host(self):
        n=[0]
        def opener(request,timeout):
            n[0]+=1
            return FakeResponse(b"<html>oops</html>" if n[0]==1 else b'{"elements":[]}')
        result=_overpass_json_with_fallback(b'data',opener=opener,endpoints=(
            "https://overpass-api.de/api/interpreter","https://overpass.private.coffee/api/interpreter"))
        self.assertEqual(result["elements"],[])

    def test_core_api_forbidden_has_dedicated_message_without_key(self):
        def forbidden(req,timeout):
            raise HTTPError(req.full_url,403,"Forbidden",{},None)
        with patch("airspace_geometry.urlopen",side_effect=forbidden):
            with self.assertRaisesRegex(PermissionError,"OPENAIP_DATA_API_KEY") as ctx:
                _http_get("https://api.core.openaip.net/api/airspaces","secret-value")
        self.assertNotIn("secret-value",str(ctx.exception))


if __name__=="__main__":
    unittest.main()
