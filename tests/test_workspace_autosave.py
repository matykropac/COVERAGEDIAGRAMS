"""RADAR draft recoverability and no-heavy-preview UI regression."""
import json
import tempfile
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import patch

import workspace_autosave as draft


class DraftRecoveryTests(TestCase):
    def test_save_restore_and_unchanged_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(
                "os.environ",{"COVERAGEDIAGRAMS_DRAFT_DIR":temp}):
            token=draft.new_token()
            original={
                "ws_radar":"PAR-NG","ws_lat":41.421,
                "ws_lon":19.534,"ws_agl":12.5,
                "ws_levels":[2000,2100,2200,6500],
                "ws_par_channels":"BOTH",
                "ws_par_quality":"ENGINEERING",
                "_par_levels_initialized":True,
                "OPENAIP_API_KEY":"secret-not-for-disk",
                "ws_result":"binary-matrix-must-not-save",
            }
            self.assertTrue(draft.save_draft(token,original))
            self.assertFalse(draft.save_draft(token,original))
            loaded=draft.read_draft(token)
            self.assertEqual(loaded["fields"]["ws_levels"],[2000,2100,2200,6500])
            self.assertEqual(loaded["fields"]["ws_par_channels"],"BOTH")
            self.assertNotIn("OPENAIP_API_KEY",loaded["fields"])
            self.assertNotIn("ws_result",loaded["fields"])
            self.assertTrue(draft.save_draft(token,{**original,"ws_agl":19.0}))
            self.assertEqual(draft.read_draft(token)["fields"]["ws_agl"],19.0)
            self.assertEqual(len(list(Path(temp).glob("*.json"))),1)
            self.assertFalse(list(Path(temp).glob("*.tmp")))

    def test_portable_backup_round_trip(self):
        values={"ws_radar":"PAR-NG","ws_levels":[2000,2100,6000,6250],
                "ws_par_channels":"BOTH","OPENAIP_API_KEY":"SECRET"}
        data=draft.export_draft(values)
        self.assertNotIn(b"SECRET",data)
        restored=draft.import_draft(data)
        self.assertEqual(restored["ws_levels"],[2000,2100,6000,6250])
        self.assertEqual(restored["ws_par_channels"],"BOTH")
        with self.assertRaises(ValueError):
            draft.import_draft(b"not-json")

    def test_invalid_ids_and_tampered_json_are_rejected(self):
        for token in ("../etc/passwd","x","hello/world",None):
            with self.subTest(token=token),self.assertRaises(ValueError):
                draft.path_for(token)
        with tempfile.TemporaryDirectory() as temp, patch.dict(
                "os.environ",{"COVERAGEDIAGRAMS_DRAFT_DIR":temp}):
            token=draft.new_token()
            draft.save_draft(token,{"ws_radar":"PAR-NG"})
            path=draft.path_for(token)
            content=json.loads(path.read_text(encoding="utf-8"))
            content["fields"]["OPENAIP_API_KEY"]="secret"
            path.write_text(json.dumps(content),encoding="utf-8")
            with self.assertRaises(ValueError):
                draft.read_draft(token)

    def test_invalid_values_excluded_from_save(self):
        payload=draft.capture({
            "ws_radar":"PAR-NG","ws_lat":float("nan"),
            "ws_levels":[2000,3.5,6000],
            "ws_step":500,
            "ws_agl":object(),
        })
        self.assertEqual(payload,{"ws_radar":"PAR-NG","ws_step":500})

    def test_separate_radar_profiles_survive_draft_round_trip(self):
        profiles={
            "PSR":{"ws_radar":"RL-2000","ws_psr_nm":100,"ws_step":25},
            "SSR":{"ws_radar":"SSR","ws_agl":27.0},
            "ASR":{"ws_radar":"RL-2000","ws_psr_nm":60},
            "PAR":{"ws_radar":"PAR-NG","ws_bearing":187.45,
                   "ws_par_channels":"BOTH"}
        }
        with tempfile.TemporaryDirectory() as temp, patch.dict(
                "os.environ",{"COVERAGEDIAGRAMS_DRAFT_DIR":temp}):
            token=draft.new_token()
            self.assertTrue(draft.save_draft(token,{
                "ws_radar_ui_mode":"PAR","_radar_mode_profiles":profiles}))
            loaded=draft.read_draft(token)["fields"]
            self.assertEqual(loaded["ws_radar_ui_mode"],"PAR")
            self.assertEqual(loaded["_radar_mode_profiles"],profiles)
            self.assertEqual(
                draft.import_draft(draft.export_draft(loaded))
                ["_radar_mode_profiles"]["PAR"]["ws_bearing"],187.45)

    def test_workspace_autosaves_before_expensive_preview(self):
        source=(Path(__file__).resolve().parents[1]/
                "map_workspace.py").read_text(encoding="utf-8")
        self.assertIn('def _draft_begin():',source)
        self.assertIn('def _draft_checkpoint():',source)
        self.assertIn('st.query_params["draft"]=token',source)
        self.assertIn('key="ws_radar_preview_enabled"',source)
        self.assertIn('if preview:',source)
        self.assertIn('    _remember_radar_form()\n    if st.session_state.get("_workspace_draft_error"):',source)


if __name__=="__main__":
    main()
