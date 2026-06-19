from __future__ import annotations

import unittest

from opportunity_radar.cities import city_allowed_for_location, city_from_location, canonical_city_set


class CityTests(unittest.TestCase):
    def test_city_aliases(self) -> None:
        allowed = canonical_city_set(["Beijing", "Dubai", "Shenzhen", "New York", "San Francisco"])
        self.assertEqual(city_from_location("NYC", allowed), "New York")
        self.assertEqual(city_from_location("New York City, NY", allowed), "New York")
        self.assertEqual(city_from_location("SF Bay Area", allowed), "San Francisco")
        self.assertEqual(city_from_location("Shenzen, China", allowed), "Shenzhen")

    def test_remote_requires_city_by_default(self) -> None:
        allowed = canonical_city_set(["New York"])
        ok, city, remote = city_allowed_for_location("Remote - US", allowed_cities=allowed)
        self.assertFalse(ok)
        self.assertEqual(city, "")
        self.assertTrue(remote)

        ok, city, remote = city_allowed_for_location("Remote - New York", allowed_cities=allowed)
        self.assertTrue(ok)
        self.assertEqual(city, "New York")
        self.assertTrue(remote)


if __name__ == "__main__":
    unittest.main()
