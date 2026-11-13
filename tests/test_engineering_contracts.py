"""Contract-only regression tests; no changes to legacy radar solver."""
import unittest
from datetime import datetime, timedelta, timezone

from engineering_contracts import (
    DataOrigin, SensorType, Provenance, SensorDefinition,
    ObservationIdentity, sha256_bytes,
)


class EngineeringContractTests(unittest.TestCase):
    def setUp(self):
        self.utc = datetime(2026, 11, 13, 8, 0, tzinfo=timezone.utc)

    def test_valid_sensor_definition_and_immutable_revision(self):
        s = SensorDefinition("SSR-LATI", SensorType.SSR, 41.418, 19.713,
                             38.5, 20.9, 359.9, 1)
        self.assertEqual(s.kind, SensorType.SSR)
        with self.assertRaises(Exception):
            s.sensor_id = "changed"

    def test_reject_invalid_coordinates(self):
        with self.assertRaisesRegex(ValueError, "latitude"):
            SensorDefinition("A", SensorType.PSR, 95, 16, 10, 20, 0)
        with self.assertRaisesRegex(ValueError, "orientation"):
            SensorDefinition("A", SensorType.PSR, 50, 16, 10, 20, 360)

    def test_origin_is_explicit_and_utc_is_required(self):
        with self.assertRaisesRegex(ValueError, "UTC"):
            Provenance(DataOrigin.MEASURED, "receiver", datetime(2026, 11, 13))
        with self.assertRaisesRegex(ValueError, "UTC"):
            Provenance(DataOrigin.MEASURED, "receiver",
                       datetime(2026, 11, 13, tzinfo=timezone(timedelta(hours=1))))
        provenance = Provenance(DataOrigin.MEASURED, "receiver", self.utc, sha256_bytes(b"sample"))
        self.assertEqual(provenance.origin, DataOrigin.MEASURED)
        self.assertEqual(len(provenance.source_sha256), 64)

    def test_asterix_edition_is_not_guessed(self):
        p = Provenance(DataOrigin.MEASURED, "decoder", self.utc)
        with self.assertRaisesRegex(ValueError, "edition"):
            ObservationIdentity("SSR-LATI", 48, "", 0, self.utc, 5.0, p)
        record = ObservationIdentity("SSR-LATI", 48, "1.32", 0, self.utc, 5.0, p)
        self.assertEqual(record.asterix_category, 48)

    def test_source_integrity_hash(self):
        self.assertEqual(sha256_bytes(b"abc"),
                         "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")


if __name__ == "__main__":
    unittest.main()
