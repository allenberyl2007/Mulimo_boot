"""Mise à jour des observations GPM, MODIS et SMAP par le client Earth Engine existant."""
import os
import subprocess
import sys
import tempfile

import pandas as pd

from core.db import put
from core.regions import REGIONS

DEFAULT_PROJECT = "braided-facet-513415-e8"
DEFAULT_DOWNLOADER = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "scripts",
    "telecharger_donnees_satellites.py",
)
DOWNLOAD_TIMEOUT_SECONDS = 4 * 60 * 60
SOURCES = ("gpm", "modis", "smap")
REGION_NAMES = {name.casefold(): name for name in REGIONS}
SOURCE_FILES = {
    "gpm": ("gpm_precip_mm_day", "weather", "gpm_gee"),
    "modis": ("modis_ndvi", "vegetation", "modis_gee"),
    "smap": (("smap_soil_moisture_am", "smap_soil_moisture_pm"), "soil_moisture", "smap_gee"),
}


def resolve_downloader():
    configured = os.environ.get("EARTH_ENGINE_DOWNLOADER")
    if configured:
        path = os.path.abspath(configured)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Earth Engine downloader not found: {path}")
        return path
    if os.path.isfile(DEFAULT_DOWNLOADER):
        return DEFAULT_DOWNLOADER
    raise FileNotFoundError(
        "The Earth Engine downloader is unavailable. "
        "Set EARTH_ENGINE_DOWNLOADER to its path."
    )


def _read_csv(path, required, date_column="date"):
    frame = pd.read_csv(path, encoding="utf-8-sig")
    missing = set(required) - set(frame.columns)
    if missing:
        raise ValueError(f"{os.path.basename(path)} is missing columns: {sorted(missing)}")
    if "region" not in frame or date_column not in frame:
        raise ValueError(f"{os.path.basename(path)} has no region/date columns.")
    frame = frame.copy()
    frame["region"] = frame["region"].astype(str).str.strip().str.casefold().map(REGION_NAMES)
    frame["date"] = pd.to_datetime(frame[date_column], errors="coerce")
    return frame.dropna(subset=["region", "date"])


def parse_outputs(paths):
    results = {}
    for source in paths:
        if source not in SOURCE_FILES:
            raise ValueError(f"Unknown Earth Engine source: {source}")
        columns, table, db_source = SOURCE_FILES[source]
        required = columns if isinstance(columns, tuple) else (columns,)
        frame = _read_csv(paths[source], required)

        if source == "gpm":
            values = pd.to_numeric(frame[columns], errors="coerce")
            data = frame.loc[values.between(0, 1000), ["region", "date"]].copy()
            data["PRECTOTCORR"] = values.loc[data.index]
        elif source == "modis":
            values = pd.to_numeric(frame[columns], errors="coerce")
            data = frame.loc[values.between(-0.2, 1.0), ["region", "date"]].copy()
            data["ndvi"] = values.loc[data.index]
        else:
            measurements = frame[list(columns)].apply(pd.to_numeric, errors="coerce")
            valid = measurements.where(measurements.ge(0.0) & measurements.le(0.8))
            values = valid.mean(axis=1)
            data = frame.loc[values.notna(), ["region", "date"]].copy()
            data["value"] = values.loc[data.index]
            data["kind"] = "smap_surface"

        if data.empty:
            raise ValueError(f"Earth Engine returned no valid {source.upper()} observations.")
        results[source] = (table, db_source, data)
    return results


def load(con, start, end, project=None, downloader=None, regions=None):
    """Télécharge les trois capteurs avec le jeton Earth Engine déjà mémorisé par le compte Windows."""
    project = project or os.environ.get("EE_PROJECT") or DEFAULT_PROJECT
    downloader = downloader or resolve_downloader()
    failures = []
    counts = {}

    with tempfile.TemporaryDirectory(prefix="mulimo-earth-engine-") as temp_dir:
        prefix = os.path.join(temp_dir, "satellites")
        for source in SOURCES:
            command = [
                sys.executable,
                downloader,
                "--project",
                project,
                "--start-date",
                start,
                "--end-date",
                end,
                "--output",
                prefix,
                "--source",
                source,
            ]
            try:
                result = subprocess.run(
                    command,
                    cwd=os.path.dirname(downloader),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=DOWNLOAD_TIMEOUT_SECONDS,
                    check=False,
                )
                if result.returncode:
                    detail = (result.stderr or result.stdout).strip()[-1000:]
                    raise RuntimeError(
                        f"Earth Engine {source.upper()} download failed "
                        f"(exit {result.returncode}): {detail}"
                    )

                path = f"{prefix}_{source}.csv"
                output = parse_outputs({source: path})[source]
                table, db_source, data = output
                if regions is not None:
                    selected = {region.casefold() for region in regions}
                    unknown = selected - {region.casefold() for region in REGIONS}
                    if unknown:
                        raise ValueError(f"Unknown Earth Engine regions: {sorted(unknown)}")
                    data = data[data["region"].str.casefold().isin(selected)]
                    if data.empty:
                        raise ValueError(
                            f"Earth Engine returned no valid {source.upper()} observations "
                            f"for {sorted(selected)}."
                        )
                put(con, table, data, db_source)
                counts[source] = len(data)
            except Exception as exc:
                failures.append(f"{source.upper()}: {type(exc).__name__}: {exc}")

    if failures:
        raise RuntimeError("Earth Engine update incomplete: " + " | ".join(failures))
    return counts
