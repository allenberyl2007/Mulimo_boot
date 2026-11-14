"""Mise à jour sûre et incrémentale des données de référence.

Usage : python scripts/update_db.py [--force]
Une exécution normale attend 90 jours après la dernière mise à jour complète.
"""
import argparse
import datetime as dt
import logging
from logging.handlers import RotatingFileHandler
import os
import re
import shutil
import sqlite3
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from adapters import earth_engine, faostat, power, soilgrids
from core.db import DB_PATH, connect
from core.regions import REGIONS

INTERVAL_DAYS = 90
INITIAL_LOOKBACK_DAYS = 3652
INITIAL_OBSERVATION_LOOKBACK_DAYS = 1095
CORRECTION_LOOKBACK_DAYS = 30
NASA_DELAY_DAYS = 3
BACKUP_COUNT = 4
UPDATE_TABLE = "maintenance_metadata"
LAST_SUCCESS_KEY = "last_successful_update"
LAST_TRAINING_KEY = "last_successful_training"
MODELS = ("climate", "soil", "crop", "yield", "recommendation")
LOG_PATH = os.path.join(ROOT, "data", "update.log")
BACKUP_DIR = os.path.join(ROOT, "data", "backups")


def configure_logging():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = RotatingFileHandler(LOG_PATH, maxBytes=2_000_000, backupCount=4, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root_logger.handlers[:] = [file_handler, stream_handler]


def metadata_value(db_path, key):
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        exists = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (UPDATE_TABLE,),
        ).fetchone()
        if not exists:
            return None
        row = con.execute(
            f"SELECT value FROM {UPDATE_TABLE} WHERE key=?",
            (key,),
        ).fetchone()
        return row[0] if row else None
    finally:
        con.close()


def last_successful_update(db_path):
    return metadata_value(db_path, LAST_SUCCESS_KEY)


def last_successful_training(db_path):
    return metadata_value(db_path, LAST_TRAINING_KEY)


def update_is_due(last_success, today):
    if not last_success:
        return True
    try:
        last_date = dt.datetime.fromisoformat(last_success).date()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid saved update date: {last_success!r}") from exc
    return (today - last_date).days >= INTERVAL_DAYS


def power_start_date(con, region, end_date):
    return source_start_date(con, "weather", region, "nasa_power", end_date)


def source_start_date(con, table, region, source, end_date, kind=None):
    query = f"SELECT MAX(date) FROM {table} WHERE region=? AND source=?"
    params = [region, source]
    if kind is not None:
        query += " AND kind=?"
        params.append(kind)
    row = con.execute(query, params).fetchone()
    latest = dt.date.fromisoformat(row[0]) if row and row[0] else None
    if latest is None:
        lookback = INITIAL_LOOKBACK_DAYS if source == "nasa_power" else INITIAL_OBSERVATION_LOOKBACK_DAYS
        return end_date - dt.timedelta(days=lookback)
    return latest - dt.timedelta(days=CORRECTION_LOOKBACK_DAYS)


def training_is_due(last_training, last_update, data_due=False):
    if data_due or not last_training or not last_update:
        return True
    try:
        trained_at = dt.datetime.fromisoformat(last_training)
        updated_at = dt.datetime.fromisoformat(last_update)
    except ValueError as exc:
        raise ValueError("Saved update and training timestamps must be ISO dates.") from exc
    if trained_at.tzinfo is None:
        trained_at = trained_at.astimezone()
    if updated_at.tzinfo is None:
        updated_at = updated_at.astimezone()
    return trained_at < updated_at


def _backup_files(backup_dir):
    pattern = re.compile(r"^simulation-\d{8}-\d{6}-\d{6}\.db$")
    return sorted(
        (os.path.join(backup_dir, name) for name in os.listdir(backup_dir)
         if pattern.fullmatch(name)),
        key=os.path.getmtime,
        reverse=True,
    )


def backup_database(db_path, backup_dir=BACKUP_DIR, keep=BACKUP_COUNT):
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup_path = os.path.join(backup_dir, f"simulation-{timestamp}.db")
    source = sqlite3.connect(db_path, timeout=30)
    destination = sqlite3.connect(backup_path)
    try:
        source.backup(destination)
        result = destination.execute("PRAGMA quick_check").fetchone()
        if not result or result[0] != "ok":
            raise sqlite3.DatabaseError(f"Backup integrity check failed: {result}")
    except Exception:
        destination.close()
        source.close()
        if os.path.exists(backup_path):
            os.remove(backup_path)
        raise
    destination.close()
    source.close()

    for old_path in _backup_files(backup_dir)[keep:]:
        os.remove(old_path)
    return backup_path


def _check_integrity(con):
    result = con.execute("PRAGMA quick_check").fetchone()
    if not result or result[0] != "ok":
        raise sqlite3.DatabaseError(f"Database integrity check failed: {result}")


def update_sources(con, today):
    end_date = today - dt.timedelta(days=NASA_DELAY_DAYS)
    failures = []

    for region in REGIONS:
        try:
            count = soilgrids.load(con, region)
            logging.info("SoilGrids %s: OK (%s record)", region, count)
        except Exception as exc:
            failures.append(f"SoilGrids/{region}: {type(exc).__name__}: {exc}")
            logging.exception("SoilGrids %s: update failed", region)

        sources = (
            ("NASA POWER", "weather", "nasa_power", None,
             lambda start, end: power.load(con, region, start, end)),
        )
        for name, table, source, kind, load in sources:
            start_date = source_start_date(con, table, region, source, end_date, kind)
            if start_date > end_date:
                logging.info("%s %s: already current through %s", name, region, end_date)
                continue
            try:
                result = load(start_date.isoformat(), end_date.isoformat())
                logging.info("%s %s: OK (%s)", name, region, result or "")
            except Exception as exc:
                failures.append(f"{name}/{region}: {type(exc).__name__}: {exc}")
                logging.exception("%s %s: update failed", name, region)

    satellite_start = min(
        source_start_date(con, table, region, source, end_date, kind)
        for table, source, kind in (
            ("weather", "gpm_gee", None),
            ("vegetation", "modis_gee", None),
            ("soil_moisture", "smap_gee", "smap_surface"),
        )
        for region in REGIONS
    )
    if satellite_start <= end_date:
        try:
            counts = earth_engine.load(
                con,
                satellite_start.isoformat(),
                end_date.isoformat(),
            )
            logging.info("Google Earth Engine GPM/MODIS/SMAP: OK (%s)", counts)
        except Exception as exc:
            failures.append(f"Google Earth Engine: {type(exc).__name__}: {exc}")
            logging.exception("Google Earth Engine satellite update failed")

    try:
        count = faostat.load(con)
        logging.info("FAOSTAT: OK (%s records)", count)
    except Exception as exc:
        failures.append(f"FAOSTAT: {type(exc).__name__}: {exc}")
        logging.exception("FAOSTAT: update failed")

    return failures


def retrain_models():
    for model in MODELS:
        script = os.path.join(ROOT, "models", model, "train.py")
        try:
            result = subprocess.run(
                [sys.executable, script],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=7200,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"{model} retraining exceeded the two-hour limit.") from exc
        for line in (result.stdout + "\n" + result.stderr).splitlines():
            if line.strip():
                logging.info("%s training: %s", model, line)
        if result.returncode:
            raise RuntimeError(
                f"{model} retraining failed with exit code {result.returncode}."
            )


def _save_metadata(db_path, key, value):
    con = connect(db_path)
    try:
        con.execute(
            f"CREATE TABLE IF NOT EXISTS {UPDATE_TABLE} "
            "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        con.execute(
            f"INSERT OR REPLACE INTO {UPDATE_TABLE} (key, value) VALUES (?, ?)",
            (key, value),
        )
        con.commit()
    finally:
        con.close()


def _timestamp():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def run_update(force=False, today=None, db_path=DB_PATH, backup_dir=BACKUP_DIR):
    today = today or dt.date.today()
    db_path = os.path.abspath(db_path)
    if not os.path.isfile(db_path):
        raise FileNotFoundError(
            f"Database not found: {db_path}. Prepare or restore the project database first."
        )

    last_update = last_successful_update(db_path)
    last_training = last_successful_training(db_path)
    data_due = force or update_is_due(last_update, today)
    training_due = force or training_is_due(last_training, last_update, data_due)
    if not data_due and not training_due:
        logging.info(
            "No work due; last complete data update was %s and last training was %s.",
            last_update,
            last_training,
        )
        return 0

    if data_due:
        check_con = sqlite3.connect(db_path, timeout=30)
        try:
            _check_integrity(check_con)
        finally:
            check_con.close()
        backup_path = backup_database(db_path, backup_dir)
        logging.info("Pre-update database backup: %s", backup_path)

        con = connect(db_path)
        try:
            con.execute(
                f"CREATE TABLE IF NOT EXISTS {UPDATE_TABLE} "
                "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            con.commit()
            failures = update_sources(con, today)
            _check_integrity(con)
            if failures:
                logging.error(
                    "Update incomplete (%s source(s) failed); any successful rows were retained. "
                    "The next scheduled attempt will retry.",
                    len(failures),
                )
                for failure in failures:
                    logging.error("Update failure: %s", failure)
                return 1
            _save_metadata(db_path, LAST_SUCCESS_KEY, _timestamp())
            logging.info("All configured data sources updated successfully.")
        except Exception:
            con.close()
            logging.exception("Database update aborted; restoring the verified pre-update backup.")
            shutil.copy2(backup_path, db_path)
            raise
        finally:
            con.close()

    if training_due:
        try:
            retrain_models()
        except Exception:
            logging.exception(
                "Retraining failed; incumbent models remain available. "
                "The next scheduled attempt will retry."
            )
            return 1
        _save_metadata(db_path, LAST_TRAINING_KEY, _timestamp())
        logging.info("Candidate retraining and performance checks completed.")

    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="run now regardless of the 90-day interval (manual update)",
    )
    args = parser.parse_args(argv)
    configure_logging()
    try:
        return run_update(force=args.force)
    except Exception:
        logging.exception("Database update could not be completed.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
