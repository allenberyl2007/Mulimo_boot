import datetime as dt
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pandas as pd
from scripts import update_db
from adapters import earth_engine, faostat, gpm, modis, power, smap, soilgrids
from core.db import connect
from core.mlkit import _promotion_decision


class DatabaseUpdateTests(unittest.TestCase):
    def test_earth_engine_csvs_map_to_distinct_validated_sources(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = {
                "gpm": os.path.join(temp_dir, "satellites_gpm.csv"),
                "modis": os.path.join(temp_dir, "satellites_modis.csv"),
                "smap": os.path.join(temp_dir, "satellites_smap.csv"),
            }
            pd.DataFrame(
                {
                    "region": ["Kananga", "invalid"],
                    "date": ["2026-10-01", "2026-10-01"],
                    "gpm_precip_mm_day": [12.5, 5.0],
                }
            ).to_csv(paths["gpm"], index=False)
            pd.DataFrame(
                {
                    "region": ["Kananga"],
                    "date": ["2026-10-01"],
                    "modis_ndvi": [0.62],
                }
            ).to_csv(paths["modis"], index=False)
            pd.DataFrame(
                {
                    "region": ["Kananga"],
                    "date": ["2026-10-01"],
                    "smap_soil_moisture_am": [0.24],
                    "smap_soil_moisture_pm": [0.28],
                }
            ).to_csv(paths["smap"], index=False)

            results = earth_engine.parse_outputs(paths)

        self.assertEqual(len(results["gpm"][2]), 1)
        self.assertEqual(results["gpm"][1], "gpm_gee")
        self.assertEqual(results["gpm"][2].iloc[0].PRECTOTCORR, 12.5)
        self.assertEqual(results["modis"][1], "modis_gee")
        self.assertEqual(results["modis"][2].iloc[0].ndvi, 0.62)
        self.assertEqual(results["smap"][1], "smap_gee")
        self.assertAlmostEqual(results["smap"][2].iloc[0].value, 0.26)

    def test_earth_engine_loader_reuses_cached_auth_without_interactive_login(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            downloader = os.path.join(temp_dir, "downloader.py")
            with open(downloader, "w", encoding="utf-8") as script:
                script.write("# test downloader\n")
            con = connect(os.path.join(temp_dir, "test.db"))

            def fake_run(command, **kwargs):
                source = command[command.index("--source") + 1]
                prefix = command[command.index("--output") + 1]
                columns, _, _ = earth_engine.SOURCE_FILES[source]
                measurements = columns if isinstance(columns, tuple) else (columns,)
                pd.DataFrame([
                    {"region": region, "date": "2026-10-01", **{
                        column: 0.25 for column in measurements
                    }}
                    for region in ("Kananga", "Kinshasa")
                ]).to_csv(f"{prefix}_{source}.csv", index=False)
                return type(
                    "Completed",
                    (),
                    {"returncode": 0, "stdout": "", "stderr": ""},
                )()

            try:
                with mock.patch.object(earth_engine.subprocess, "run", side_effect=fake_run) as run:
                    counts = earth_engine.load(
                        con,
                        "2026-10-01",
                        "2026-10-31",
                        project="project-id",
                        downloader=downloader,
                        regions=("KANANGA",),
                    )

                self.assertEqual(counts, {"gpm": 1, "modis": 1, "smap": 1})
                self.assertEqual(run.call_count, 3)
                for call in run.call_args_list:
                    self.assertNotIn("--authenticate", call.args[0])
                    self.assertEqual(call.args[0][call.args[0].index("--project") + 1], "project-id")
                self.assertEqual(
                    con.execute("SELECT COUNT(*) FROM weather WHERE source='gpm_gee'").fetchone()[0],
                    1,
                )
                self.assertEqual(
                    con.execute("SELECT COUNT(*) FROM vegetation WHERE source='modis_gee'").fetchone()[0],
                    1,
                )
                self.assertEqual(
                    con.execute("SELECT COUNT(*) FROM soil_moisture WHERE source='smap_gee'").fetchone()[0],
                    1,
                )
            finally:
                con.close()

    def test_quarterly_schedule_retries_until_ninety_days(self):
        today = dt.date(2026, 11, 14)
        self.assertFalse(update_db.update_is_due("2026-08-17T09:00:00+01:00", today))
        self.assertTrue(update_db.update_is_due("2026-08-16T09:00:00+01:00", today))
        self.assertTrue(update_db.update_is_due(None, today))

    def test_power_update_uses_initial_window_then_overlaps_recent_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            con = sqlite3.connect(os.path.join(temp_dir, "test.db"))
            con.execute(
                "CREATE TABLE weather (region TEXT, date TEXT, source TEXT)"
            )
            today = dt.date(2026, 11, 14)
            end_date = today - dt.timedelta(days=update_db.NASA_DELAY_DAYS)
            self.assertEqual(
                update_db.power_start_date(con, "kananga", end_date),
                end_date - dt.timedelta(days=update_db.INITIAL_LOOKBACK_DAYS),
            )
            con.execute(
                "INSERT INTO weather VALUES (?, ?, ?)",
                ("kananga", "2026-10-01", "nasa_power"),
            )
            self.assertEqual(
                update_db.power_start_date(con, "kananga", end_date),
                dt.date(2026, 9, 1),
            )
            con.close()

    def test_satellite_sources_use_three_year_backfill_and_recent_overlap(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            con = connect(os.path.join(temp_dir, "test.db"))
            end_date = dt.date(2026, 11, 11)
            self.assertEqual(
                update_db.source_start_date(con, "weather", "kananga", "gpm_gee", end_date),
                end_date - dt.timedelta(days=update_db.INITIAL_OBSERVATION_LOOKBACK_DAYS),
            )
            con.execute(
                "INSERT INTO soil_moisture (region, date, value, kind, source) "
                "VALUES ('kananga', '2026-10-01', 0.3, 'smap_surface', 'smap_gee')"
            )
            self.assertEqual(
                update_db.source_start_date(
                    con, "soil_moisture", "kananga", "smap_gee", end_date, "smap_surface"
                ),
                dt.date(2026, 9, 1),
            )
            con.close()

    def test_complete_update_requests_earth_engine_once_for_all_satellites(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            con = connect(os.path.join(temp_dir, "test.db"))
            with (
                mock.patch.object(power, "load", return_value={"ok": True}),
                mock.patch.object(soilgrids, "load", return_value=1) as soil_load,
                mock.patch.object(earth_engine, "load", return_value={"gpm": 1, "modis": 1, "smap": 1}) as ee_load,
                mock.patch.object(faostat, "load", return_value=5) as faostat_load,
            ):
                failures = update_db.update_sources(con, dt.date(2026, 11, 14))
            self.assertEqual(failures, [])
            self.assertEqual(soil_load.call_count, 6)
            ee_load.assert_called_once()
            faostat_load.assert_called_once_with(con)
            con.close()

    def test_training_is_due_after_data_update_or_failed_prior_training(self):
        self.assertTrue(update_db.training_is_due(None, None))
        self.assertTrue(
            update_db.training_is_due(
                "2026-11-14T09:00:00+01:00",
                "2026-11-14T10:00:00+01:00",
            )
        )
        self.assertFalse(
            update_db.training_is_due(
                "2026-11-14T10:00:00+01:00",
                "2026-11-14T09:00:00+01:00",
            )
        )

    def test_model_promotion_requires_improvement_without_regression(self):
        previous = {
            "yield": {"mae": 1.0, "r2": 0.6, "coverage": 0.8},
            "soil": {"mae": 2.0, "r2": 0.7, "coverage": 0.82},
        }
        improved = {
            "yield": {"mae": 0.9, "r2": 0.62, "coverage": 0.8},
            "soil": {"mae": 2.0, "r2": 0.7, "coverage": 0.8},
        }
        self.assertTrue(_promotion_decision(previous, improved)[0])

        regressed = {**improved, "soil": {"mae": 2.1, "r2": 0.7, "coverage": 0.8}}
        self.assertFalse(_promotion_decision(previous, regressed)[0])
        self.assertFalse(_promotion_decision(previous, previous)[0])

    def test_retraining_attempts_all_five_models(self):
        completed = type(
            "Completed",
            (),
            {"stdout": "model status", "stderr": "", "returncode": 0},
        )()
        with mock.patch.object(update_db.subprocess, "run", return_value=completed) as run:
            update_db.retrain_models()

        model_names = [
            os.path.basename(os.path.dirname(call.args[0][1]))
            for call in run.call_args_list
        ]
        self.assertEqual(list(model_names), list(update_db.MODELS))

    def test_backup_is_a_valid_snapshot_and_retention_is_bounded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "simulation.db")
            backup_dir = os.path.join(temp_dir, "backups")
            con = sqlite3.connect(db_path)
            con.execute("CREATE TABLE sample (value TEXT)")
            con.execute("INSERT INTO sample VALUES ('before')")
            con.commit()
            con.close()

            first = update_db.backup_database(db_path, backup_dir, keep=2)
            second = update_db.backup_database(db_path, backup_dir, keep=2)
            third = update_db.backup_database(db_path, backup_dir, keep=2)

            self.assertFalse(os.path.exists(first))
            self.assertTrue(os.path.exists(second))
            self.assertTrue(os.path.exists(third))
            snapshot = sqlite3.connect(third)
            try:
                self.assertEqual(snapshot.execute("PRAGMA quick_check").fetchone()[0], "ok")
                self.assertEqual(snapshot.execute("SELECT value FROM sample").fetchone()[0], "before")
            finally:
                snapshot.close()

    def test_incomplete_update_does_not_mark_quarter_as_complete(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "simulation.db")
            con = sqlite3.connect(db_path)
            con.execute("CREATE TABLE sample (value TEXT)")
            con.commit()
            con.close()

            with (
                mock.patch.object(update_db, "update_sources", return_value=["test failure"]),
                mock.patch.object(update_db, "retrain_models") as retrain,
            ):
                result = update_db.run_update(
                    force=True,
                    today=dt.date(2026, 11, 14),
                    db_path=db_path,
                    backup_dir=os.path.join(temp_dir, "backups"),
                )

            self.assertEqual(result, 1)
            retrain.assert_not_called()
            con = sqlite3.connect(db_path)
            try:
                self.assertIsNone(update_db.last_successful_update(db_path))
            finally:
                con.close()

    def test_complete_update_retrains_and_records_both_successes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "simulation.db")
            con = connect(db_path)
            con.close()

            with (
                mock.patch.object(update_db, "update_sources", return_value=[]),
                mock.patch.object(update_db, "retrain_models") as retrain,
            ):
                result = update_db.run_update(
                    force=True,
                    today=dt.date(2026, 11, 14),
                    db_path=db_path,
                    backup_dir=os.path.join(temp_dir, "backups"),
                )

            self.assertEqual(result, 0)
            retrain.assert_called_once_with()
            self.assertIsNotNone(update_db.last_successful_update(db_path))
            self.assertIsNotNone(update_db.last_successful_training(db_path))

    def test_training_failure_retries_without_redownloading_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "simulation.db")
            con = connect(db_path)
            con.close()

            with (
                mock.patch.object(update_db, "update_sources", return_value=[]) as update_sources,
                mock.patch.object(update_db, "retrain_models", side_effect=RuntimeError("test"))
            ):
                first_result = update_db.run_update(
                    force=True,
                    today=dt.date(2026, 11, 14),
                    db_path=db_path,
                    backup_dir=os.path.join(temp_dir, "backups"),
                )
                self.assertEqual(first_result, 1)
                self.assertIsNotNone(update_db.last_successful_update(db_path))
                self.assertIsNone(update_db.last_successful_training(db_path))

            with (
                mock.patch.object(update_db, "update_sources") as update_sources,
                mock.patch.object(update_db, "retrain_models"),
            ):
                second_result = update_db.run_update(
                    today=dt.date(2026, 11, 15),
                    db_path=db_path,
                    backup_dir=os.path.join(temp_dir, "backups"),
                )
            self.assertEqual(second_result, 0)
            update_sources.assert_not_called()
            self.assertIsNotNone(update_db.last_successful_training(db_path))

    def test_invalid_source_responses_are_rejected_before_database_write(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "simulation.db")
            con = connect(db_path)
            con.execute(
                "INSERT INTO weather (region, date, T2M, T2M_MAX, T2M_MIN, "
                "PRECTOTCORR, ALLSKY_SFC_SW_DWN, RH2M, WS2M, source) "
                "VALUES ('kananga', '2026-01-01', 24, 30, 19, 5, 15, 70, 1.5, 'nasa_power')"
            )
            con.commit()
            invalid_weather = {
                "properties": {
                    "parameter": {
                        "T2M": {"20260102": 35},
                        "T2M_MAX": {"20260102": 30},
                        "T2M_MIN": {"20260102": 19},
                        "PRECTOTCORR": {"20260102": 5},
                        "ALLSKY_SFC_SW_DWN": {"20260102": 15},
                        "RH2M": {"20260102": 70},
                        "WS2M": {"20260102": 1.5},
                    }
                }
            }
            invalid_soil = {
                "properties": {
                    "layers": [
                        {
                            "name": name,
                            "depths": [
                                {"label": depth, "values": {"mean": value}}
                                for depth in ("0-5cm", "5-15cm", "15-30cm")
                            ],
                        }
                        for name, value in (
                            ("phh2o", 52),
                            ("soc", None),
                            ("clay", 300),
                            ("sand", 450),
                            ("cec", 120),
                        )
                    ]
                }
            }
            try:
                with mock.patch.object(power, "http_json", return_value=invalid_weather):
                    with self.assertRaises(ValueError):
                        power.load(con, "kananga", "2026-01-02", "2026-01-02")
                with mock.patch.object(soilgrids, "http_json", return_value=invalid_soil):
                    with self.assertRaises(ValueError):
                        soilgrids.load(con, "kananga")
                with mock.patch.object(
                    faostat,
                    "download",
                    return_value=pd.DataFrame(
                        columns=["Area", "Element", "Item", "Year", "Value"]
                    ),
                ):
                    with self.assertRaises(ValueError):
                        faostat.load(con)
                with self.assertRaises(ValueError):
                    gpm.load(con, "kananga", "2026-01-01", "2026-01-02", text="")
                with self.assertRaises(ValueError):
                    smap.load(
                        con,
                        "kananga",
                        "2026-01-01",
                        "2026-01-02",
                        csv_text="Date,SPL3SMP_E_006_soil_moisture\n",
                    )
                with self.assertRaises(ValueError):
                    modis.load(
                        con,
                        "kananga",
                        "2026-01-01",
                        "2026-01-02",
                        csv_text="Date,NDVI\n",
                    )

                self.assertEqual(
                    con.execute(
                        "SELECT COUNT(*) FROM weather WHERE date='2026-01-02'"
                    ).fetchone()[0],
                    0,
                )
                self.assertEqual(
                    con.execute("SELECT COUNT(*) FROM yield_reference").fetchone()[0],
                    0,
                )
                self.assertEqual(con.execute("SELECT COUNT(*) FROM soil").fetchone()[0], 0)
                self.assertEqual(con.execute("SELECT COUNT(*) FROM vegetation").fetchone()[0], 0)
            finally:
                con.close()

    def test_appeears_failure_is_reported_without_polling_forever(self):
        with mock.patch.dict(smap.os.environ, {"EARTHDATA_USER": "test", "EARTHDATA_PASS": "test"}):
            with mock.patch.object(
                smap,
                "http_json",
                side_effect=[
                    {"token": "token"},
                    {"task_id": "task"},
                    [{"status": "failed"}],
                ],
            ) as request:
                with self.assertRaisesRegex(RuntimeError, "ended with status failed"):
                    smap.point_csv(0, 0, "2026-01-01", "2026-01-02", "product", "layer")
            self.assertEqual(request.call_count, 3)


if __name__ == "__main__":
    unittest.main()
