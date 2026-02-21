import unittest

from unified_view.azimuth import azimuth_deg, minimal_covering_arc


class AzimuthTests(unittest.TestCase):
    def test_cartographic_azimuth(self):
        self.assertAlmostEqual(azimuth_deg(0, 0, 0, 1), 0.0)
        self.assertAlmostEqual(azimuth_deg(0, 0, 1, 0), 90.0)
        self.assertAlmostEqual(azimuth_deg(0, 0, 0, -1), 180.0)

    def test_minimal_arc_wraparound(self):
        az_min, az_max, fov = minimal_covering_arc([350.0, 5.0, 20.0])
        self.assertAlmostEqual(az_min, 350.0)
        self.assertAlmostEqual(az_max, 20.0)
        self.assertAlmostEqual(fov, 30.0)

    def test_single_angle_arc(self):
        az_min, az_max, fov = minimal_covering_arc([123.0])
        self.assertEqual(az_min, 123.0)
        self.assertEqual(az_max, 123.0)
        self.assertEqual(fov, 0.0)


if __name__ == "__main__":
    unittest.main()
