import tempfile
import unittest
from pathlib import Path

from unified_view.io import load_turbines


class LoadTurbinesCsvTests(unittest.TestCase):
    def test_load_csv_with_utf8_bom_header(self):
        csv_text = "\ufeffturbine_id;x;y;name\nT01;100;200;Test\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "turbines.csv"
            path.write_text(csv_text, encoding="utf-8")

            turbines, crs = load_turbines(str(path))

        self.assertIsNone(crs)
        self.assertEqual(len(turbines), 1)
        self.assertEqual(turbines[0].turbine_id, "T01")
        self.assertEqual(turbines[0].x, 100.0)
        self.assertEqual(turbines[0].y, 200.0)

    def test_load_csv_with_spaced_headers(self):
        csv_text = " turbine_id ; x ; y ; name \nT02;110;210;Test 2\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "turbines.csv"
            path.write_text(csv_text, encoding="utf-8")

            turbines, _ = load_turbines(str(path))

        self.assertEqual(turbines[0].turbine_id, "T02")
        self.assertEqual(turbines[0].x, 110.0)
        self.assertEqual(turbines[0].y, 210.0)


if __name__ == "__main__":
    unittest.main()
