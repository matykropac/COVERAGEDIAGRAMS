"""V2 sensor registry and 3D antenna pattern import regression tests."""
import unittest

import numpy as np
from engineering_contracts import SensorDefinition, SensorType
from sensor_registry import add_sensor, revise_sensor, from_rows, to_rows
from antenna_pattern_3d import read_3d_csv, half_power_beamwidth, MAX_UPLOAD_BYTES


def sample_pattern():
    rows=["az_deg,el_deg,gain_db"]
    for a in (0,10,20,30,40):
        for e in (-2,0,2):
            rows.append(f"{a},{e},{-abs(a-20)*.6-abs(e)}")
    return ("\n".join(rows)+"\n").encode("utf-8")


class RegistryTests(unittest.TestCase):
    def test_add_revise_roundtrip(self):
        s=SensorDefinition("PSR-X",SensorType.PSR,50,15,260,20,90)
        r=add_sensor({},s)
        self.assertEqual(r["PSR-X"].revision,1)
        changed=revise_sensor(r,"PSR-X",orientation_deg_true=92)
        self.assertEqual(r["PSR-X"].orientation_deg_true,90)
        self.assertEqual(changed["PSR-X"].revision,2)
        self.assertEqual(from_rows(to_rows(changed)),changed)

    def test_duplicate_sensor_ids_rejected(self):
        s=SensorDefinition("SSR-X",SensorType.SSR,50,15,200,10,0)
        with self.assertRaisesRegex(ValueError,"exists"):
            add_sensor(add_sensor({},s),s)


class Antenna3DTests(unittest.TestCase):
    def test_valid_complete_grid_and_provenance(self):
        p=read_3d_csv(sample_pattern(),source_name="lab.csv",origin="MEASURED")
        self.assertEqual(p.gain_db.shape,(5,3))
        self.assertEqual(p.origin,"MEASURED")
        self.assertEqual(len(p.source_sha256),64)
        az,gain,used=p.az_cut(0)
        self.assertEqual(used,0)
        self.assertEqual(float(az[np.argmax(gain)]),20.)

    def test_missing_and_duplicate_az_el_rejected(self):
        rows=sample_pattern().decode().splitlines()
        with self.assertRaisesRegex(ValueError,"kompletní|duplicitní"):
            read_3d_csv("\n".join(rows[:-1]).encode())
        with self.assertRaisesRegex(ValueError,"kompletní|duplicitní"):
            read_3d_csv("\n".join(rows+[rows[-1]]).encode())

    def test_bad_header_rejected(self):
        with self.assertRaisesRegex(ValueError,"hlavičku"):
            read_3d_csv(sample_pattern().replace(b"az_deg",b"azimuth"))

    def test_hpbw_interpolated(self):
        axis=np.array([-4.,-2.,0.,2.,4.])
        gain=np.array([-12.,-3.01029995664,0.,-3.01029995664,-12.])
        self.assertAlmostEqual(half_power_beamwidth(axis,gain),4.,places=5)

    def test_restricted_size(self):
        self.assertEqual(MAX_UPLOAD_BYTES,200*1024*1024)
        with self.assertRaisesRegex(ValueError,"provenance"):
            read_3d_csv(sample_pattern(),origin="INVALID")


if __name__=="__main__":
    unittest.main()
