import os
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.db import connect
from core.rotation_model import _annual_climate_comparison, _normalize, _plans, _remote_sensing_context
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

    def test_remote_sensing_context_prefers_earth_engine_rows_on_overlap(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            con = connect(os.path.join(temp_dir, "test.db"))
            dates = pd.date_range("2026-01-01", periods=120, freq="D")
            rainfall = (np.arange(len(dates)) % 7 + 1).astype(float)
            weather = pd.DataFrame({"date": dates, "PRECTOTCORR": rainfall})
            for date, rain in zip(dates, rainfall):
                con.execute(
                    "INSERT INTO weather (region, date, PRECTOTCORR, source) "
                    "VALUES (?, ?, ?, ?)",
                    ("kananga", date.date().isoformat(), rain * 2, "gpm_gee"),
                )
                con.execute(
                    "INSERT INTO weather (region, date, PRECTOTCORR, source) "
                    "VALUES (?, ?, ?, ?)",
                    ("kananga", date.date().isoformat(), 100, "gpm"),
                )
                con.execute(
                    "INSERT INTO soil_moisture (region, date, value, kind, source) "
                    "VALUES (?, ?, ?, ?, ?)",
                    ("kananga", date.date().isoformat(), 0.25, "smap_surface", "smap_gee"),
                )
                con.execute(
                    "INSERT INTO soil_moisture (region, date, value, kind, source) "
                    "VALUES (?, ?, ?, ?, ?)",
                    ("kananga", date.date().isoformat(), 0.75, "smap_surface", "smap"),
                )
                con.execute(
                    "INSERT INTO vegetation (region, date, ndvi, source) VALUES (?, ?, ?, ?)",
                    ("kananga", date.date().isoformat(), 0.6, "modis_gee"),
                )
                con.execute(
                    "INSERT INTO vegetation (region, date, ndvi, source) VALUES (?, ?, ?, ?)",
                    ("kananga", date.date().isoformat(), -0.1, "modis"),
                )
            con.commit()
            try:
                context = _remote_sensing_context(
                    con,
                    "kananga",
                    dates[0].date().isoformat(),
                    dates[-1].date().isoformat(),
                    weather,
                )
            finally:
                con.close()

        self.assertEqual(context["smap_surface_moisture_m3_m3_median"], 0.25)
        self.assertEqual(context["modis_ndvi_median"], 0.6)
        self.assertEqual(context["gpm_weekly_rain_correlation"], 1.0)


if __name__ == "__main__":
    unittest.main()
