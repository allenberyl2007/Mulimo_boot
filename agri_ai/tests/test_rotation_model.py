import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.rotation_model import _annual_climate_comparison, _normalize, _plans
from core.schema import WEATHER_COLS


def _weather_year(year, rain, temperature):
    dates = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
    values = {
        "date": dates,
        "T2M": temperature,
        "T2M_MAX": temperature + 5,
        "T2M_MIN": temperature - 5,
        "PRECTOTCORR": rain,
        "ALLSKY_SFC_SW_DWN": 10.0,
        "RH2M": 70.0,
        "WS2M": 2.0,
    }
    return pd.DataFrame(values, columns=["date", *WEATHER_COLS])


class RotationModelTests(unittest.TestCase):
    def test_baseline_repeats_reported_one_or_two_crop_pattern(self):
        self.assertEqual(_plans("bean", None, "groundnut")["baseline"], ["bean", "bean", "bean"])
        self.assertEqual(
            _plans("bean", "maize", "groundnut")["baseline"],
            ["maize", "bean", "maize"],
        )

    def test_alternative_rotation_has_three_crop_seasons(self):
        plans = _plans("maize", None, "groundnut")
        self.assertEqual(plans["cereal_legume"], ["groundnut", "maize", "groundnut"])
        self.assertEqual(
            set(plans["diversified"]),
            {"maize", "groundnut", "cassava"},
        )
        self.assertTrue(all(len(sequence) == 3 for sequence in plans.values()))

    def test_normalization_is_relative_and_handles_ties(self):
        self.assertEqual(_normalize([4, 4, 4], True).tolist(), [0.5, 0.5, 0.5])
        self.assertEqual(_normalize([1, 2, 3], False).tolist(), [1.0, 0.5, 0.0])

    def test_climate_context_compares_each_year_with_complete_historical_normal(self):
        baseline = pd.concat(
            [_weather_year(year, rain=2.0, temperature=25.0) for year in range(1991, 2016)],
            ignore_index=True,
        )
        comparison_years = [2022]
        comparison = _annual_climate_comparison(
            _weather_year(2022, rain=3.0, temperature=26.0),
            baseline,
            comparison_years,
        )

        self.assertEqual(comparison["baseline_period"], "1991-2020")
        self.assertEqual(comparison["complete_baseline_years"], 25)
        self.assertEqual(comparison["normal_annual_rain_mm"], 730.5)
        self.assertEqual(comparison["years"][0]["rain_anomaly_mm"], 364.5)
        self.assertEqual(comparison["years"][0]["temperature_anomaly_c"], 1.0)


if __name__ == "__main__":
    unittest.main()
