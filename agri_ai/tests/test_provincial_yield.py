import unittest

import pandas as pd

from adapters import provincial_yield


def source_row(province, indicator, value, unit, record_id):
    return {
        "admin_1": province,
        "indicator": indicator,
        "value": value,
        "unit": unit,
        "product": "Maize (Corn)",
        "season_year": "Harvest 2013",
        "source_document": "Crop assessment",
        "id": record_id,
    }


class ProvincialYieldTests(unittest.TestCase):
    def test_parse_pairs_provincial_yield_and_production(self):
        frame = pd.DataFrame([
            source_row("Kongo-Central", "Yield", 2.0, "MT/ha", "y1"),
            source_row("Kongo-Central", "Quantity Produced", 100.0, "t", "q1"),
        ])

        parsed = provincial_yield.parse(frame)

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed.iloc[0].zone, "kinshasa")
        self.assertEqual(parsed.iloc[0].crop, "maize")
        self.assertEqual(parsed.iloc[0].harvested_area_ha, 50.0)

    def test_aggregate_zone_yield_is_area_weighted(self):
        observations = pd.DataFrame([
            {"province": "A", "zone": "kinshasa", "crop": "maize", "year": 2013,
             "production_t": 100.0, "harvested_area_ha": 50.0},
            {"province": "B", "zone": "kinshasa", "crop": "maize", "year": 2013,
             "production_t": 30.0, "harvested_area_ha": 10.0},
        ])

        aggregate = provincial_yield.aggregate_zones(observations).iloc[0]

        self.assertAlmostEqual(aggregate.yield_t_ha, 130.0 / 60.0)
        self.assertEqual(aggregate.province_count, 2)

    def test_unknown_province_is_not_silently_discarded(self):
        frame = pd.DataFrame([
            source_row("Unknown Province", "Yield", 2.0, "MT/ha", "y1"),
            source_row("Unknown Province", "Quantity Produced", 100.0, "t", "q1"),
        ])

        with self.assertRaisesRegex(ValueError, "explicit zone mapping"):
            provincial_yield.parse(frame)


if __name__ == "__main__":
    unittest.main()
