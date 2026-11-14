"""Extrait des observations GPM, MODIS et SMAP dans trois bases CSV distinctes.

Les données sont récupérées depuis Google Earth Engine. Il faut un compte
Earth Engine et un projet Google Cloud autorisé.

Collections utilisées :
- GPM IMERG V07 : précipitations à 30 minutes, additionnées par jour.
- MODIS MOD09GA.061 : réflectances rouges/proche infrarouge quotidiennes et NDVI.
- SMAP SPL3SMP_E.005/.006 : humidité du sol AM/PM.

Les jours sans observation restent présents dans le CSV du capteur avec
des champs vides.
"""

import argparse
import csv
import math
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, Optional, Tuple

import ee


REGIONS = {
    "Bukavu": (-2.5083, 28.8608),
    "Kinshasa": (-4.4419, 15.2663),
    "Lubumbashi": (-11.6609, 27.4794),
    "Kananga": (-5.8962, 22.4166),
    "Kisangani": (0.5153, 25.1910),
    "Mbandaka": (0.0487, 18.2603),
}

SOURCE_FIELDS = {
    "gpm": ["gpm_precip_mm_day"],
    "modis": [
        "modis_red_reflectance",
        "modis_nir_reflectance",
        "modis_ndvi",
    ],
    "smap": ["smap_soil_moisture_am", "smap_soil_moisture_pm"],
}

PRODUCT_STARTS = {
    "gpm": date(1998, 1, 1),
    "modis": date(2000, 2, 24),
    "smap": date(2015, 3, 31),
}

POWER_GRID_POINTS = {
    "Lubumbashi": (-11.6323, 27.4606),
    "Mbandaka": (0.0487, 18.2603),
}


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "La date doit respecter le format AAAA-MM-JJ."
        ) from exc


def parse_gpm_repair(value: str) -> Tuple[str, Tuple[int, ...]]:
    try:
        city, year_text = value.split("=", 1)
        region = next(name for name in REGIONS if name.casefold() == city.casefold())
        years = tuple(sorted({int(item.strip()) for item in year_text.split(",")}))
        if not years or any(year < PRODUCT_STARTS["gpm"].year for year in years):
            raise ValueError
    except (ValueError, StopIteration) as exc:
        raise argparse.ArgumentTypeError(
            "Utilisez VILLE=ANNEE,ANNEE (par exemple Bukavu=2001,2004)."
        ) from exc
    return region, years


def months_between(start: date, end_exclusive: date) -> Iterable[Tuple[date, date]]:
    """Découpe l'intervalle en mois pour limiter la taille des requêtes."""
    cursor = start
    while cursor < end_exclusive:
        if cursor.month == 12:
            next_month = date(cursor.year + 1, 1, 1)
        else:
            next_month = date(cursor.year, cursor.month + 1, 1)
        chunk_end = min(next_month, end_exclusive)
        yield cursor, chunk_end
        cursor = chunk_end


def make_points() -> ee.Geometry:
    return ee.Geometry.MultiPoint(
        [[longitude, latitude] for latitude, longitude in REGIONS.values()]
    )


def nearest_region(longitude: float, latitude: float) -> str:
    """Associe le pixel extrait à la ville la plus proche."""
    return min(
        REGIONS,
        key=lambda name: math.hypot(
            REGIONS[name][1] - longitude,
            REGIONS[name][0] - latitude,
        ),
    )


def extract_year(
    collection: ee.ImageCollection,
    points: ee.Geometry,
    scale: int,
    start: date,
    end_exclusive: date,
    records: Dict[Tuple[str, str], Dict[str, Optional[float]]],
) -> None:
    rows = collection.filterDate(
        ee.Date(start.isoformat()), ee.Date(end_exclusive.isoformat())
    ).getRegion(points, scale).getInfo()

    if not rows:
        return

    columns = {name: index for index, name in enumerate(rows[0])}
    for row in rows[1:]:
        if row[columns["time"]] is None:
            continue

        longitude = float(row[columns["longitude"]])
        latitude = float(row[columns["latitude"]])
        region = nearest_region(longitude, latitude)
        observed_date = datetime.fromtimestamp(
            int(row[columns["time"]]) / 1000, tz=timezone.utc
        ).date().isoformat()
        entry = records.get((region, observed_date))
        if entry is None:
            continue

        for field in entry:
            if field in columns and row[columns[field]] is not None:
                entry[field] = float(row[columns[field]])


def extract_with_memory_retry(
    source: str,
    collection_factory: Callable[[date, date], ee.ImageCollection],
    points: ee.Geometry,
    scale: int,
    start: date,
    end_exclusive: date,
    records: Dict[Tuple[str, str], Dict[str, Optional[float]]],
) -> None:
    try:
        collection = collection_factory(start, end_exclusive)
        extract_year(collection, points, scale, start, end_exclusive, records)
    except ee.EEException as error:
        if "memory limit exceeded" not in str(error).lower():
            raise

        days = (end_exclusive - start).days
        if days <= 1:
            raise RuntimeError(
                f"Earth Engine dépasse encore sa mémoire pour {source} le {start}."
            ) from error

        midpoint = start + timedelta(days=days // 2)
        print(f"  Requête {source} trop volumineuse ; nouvelle tentative par demi-période.")
        extract_with_memory_retry(
            source, collection_factory, points, scale, start, midpoint, records
        )
        extract_with_memory_retry(
            source, collection_factory, points, scale, midpoint, end_exclusive, records
        )


def write_source_csv(
    output_path: Path,
    fields: list[str],
    records: Dict[Tuple[str, str], Dict[str, Optional[float]]],
) -> Path:
    try:
        csv_file = output_path.open("w", newline="", encoding="utf-8-sig")
    except PermissionError:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = output_path.with_name(
            f"{output_path.stem}_nouveau_{timestamp}{output_path.suffix}"
        )
        print(
            "Impossible de remplacer le CSV (il est peut-être ouvert dans Excel). "
            f"Écriture dans {output_path}."
        )
        csv_file = output_path.open("w", newline="", encoding="utf-8-sig")

    with csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["region", "date", "latitude", "longitude", *fields])
        for (region, observed_date), values in sorted(records.items()):
            latitude, longitude = REGIONS[region]
            writer.writerow(
                [
                    region,
                    observed_date,
                    latitude,
                    longitude,
                    *(
                        values[field] if values[field] is not None else ""
                        for field in fields
                    ),
                ]
            )
    return output_path


def write_repaired_gpm_csv(
    output_path: Path,
    fieldnames: list[str],
    rows: list[dict[str, str]],
) -> Path:
    try:
        csv_file = output_path.open("w", newline="", encoding="utf-8-sig")
    except PermissionError:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = output_path.with_name(
            f"{output_path.stem}_nouveau_{timestamp}{output_path.suffix}"
        )
        print(
            "Impossible de remplacer le CSV (il est peut-être ouvert dans Excel). "
            f"Écriture dans {output_path}."
        )
        csv_file = output_path.open("w", newline="", encoding="utf-8-sig")

    with csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return output_path


def repair_gpm_rows(
    repairs: list[Tuple[str, Tuple[int, ...]]],
    points: ee.Geometry,
    output_path: Path,
    end_date: date,
) -> Path:
    if not output_path.is_file():
        raise FileNotFoundError(
            f"Le CSV GPM existant est introuvable : {output_path}"
        )

    targets: Dict[str, set[int]] = {}
    for region, years in repairs:
        if any(year > end_date.year for year in years):
            raise ValueError(
                f"Une année demandée pour {region} dépasse la date finale {end_date}."
            )
        targets.setdefault(region, set()).update(years)

    records: Dict[Tuple[str, str], Dict[str, Optional[float]]] = {}
    for region, years in targets.items():
        for year in years:
            day = date(year, 1, 1)
            end_year = date(year + 1, 1, 1)
            while day < end_year:
                records[(region, day.isoformat())] = {
                    "gpm_precip_mm_day": None
                }
                day += timedelta(days=1)

    all_years = sorted({year for years in targets.values() for year in years})
    for year in all_years:
        for chunk_start, chunk_end in months_between(
            date(year, 1, 1), date(year + 1, 1, 1)
        ):
            extract_with_memory_retry(
                "GPM",
                daily_gpm_collection,
                points,
                11132,
                chunk_start,
                chunk_end,
                records,
            )

    existing: Dict[Tuple[str, str], dict[str, str]] = {}
    with output_path.open(encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        required = {"region", "date", "latitude", "longitude", "gpm_precip_mm_day"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ValueError(f"En-têtes GPM manquants dans {output_path}.")
        fieldnames = reader.fieldnames
        for row in reader:
            existing[(row["region"], row["date"])] = row

    missing_rows = set(records).difference(existing)
    if missing_rows:
        raise ValueError(
            f"Le CSV existant ne contient pas {len(missing_rows)} lignes des années ciblées; "
            "aucune écriture n'a été effectuée."
        )

    for key, values in records.items():
        value = values["gpm_precip_mm_day"]
        existing[key]["gpm_precip_mm_day"] = "" if value is None else str(value)

    return write_repaired_gpm_csv(
        output_path,
        fieldnames,
        [existing[key] for key in sorted(existing)],
    )


def modis_collection() -> ee.ImageCollection:
    def prepare(image: ee.Image) -> ee.Image:
        state = image.select("state_1km")
        clear = state.bitwiseAnd(3).eq(0).And(state.bitwiseAnd(1 << 2).eq(0))
        raw = image.select(["sur_refl_b01", "sur_refl_b02"])
        valid = raw.gte(-100).And(raw.lte(16000)).reduce(ee.Reducer.min())
        reflectance = raw.multiply(0.0001).rename(
            ["modis_red_reflectance", "modis_nir_reflectance"]
        )
        red = reflectance.select("modis_red_reflectance")
        nir = reflectance.select("modis_nir_reflectance")
        denominator = nir.add(red)
        ndvi = nir.subtract(red).divide(denominator).rename("modis_ndvi")
        return (
            reflectance.addBands(ndvi)
            .updateMask(clear.And(valid).And(denominator.neq(0)))
            .copyProperties(image, ["system:time_start"])
        )

    return ee.ImageCollection("MODIS/061/MOD09GA").map(prepare)


def smap_collection() -> ee.ImageCollection:
    bands = ["soil_moisture_am", "soil_moisture_pm"]
    output_bands = ["smap_soil_moisture_am", "smap_soil_moisture_pm"]
    older = ee.ImageCollection("NASA/SMAP/SPL3SMP_E/005").select(
        bands, output_bands
    )
    newer = ee.ImageCollection("NASA/SMAP/SPL3SMP_E/006").select(
        bands, output_bands
    )
    return older.merge(newer)


def daily_gpm_collection(start: date, end_exclusive: date) -> ee.ImageCollection:
    half_hourly = ee.ImageCollection("NASA/GPM_L3/IMERG_V07")
    first_day = ee.Date(start.isoformat())
    day_count = (end_exclusive - start).days
    offsets = ee.List.sequence(0, day_count - 1)

    def sum_day(offset: ee.Number) -> ee.Image:
        day = first_day.advance(offset, "day")
        observations = half_hourly.filterDate(day, day.advance(1, "day")).select(
            "precipitation"
        )
        empty = (
            ee.Image.constant(0)
            .rename("gpm_precip_mm_day")
            .updateMask(ee.Image.constant(0))
        )
        daily = ee.Image(
            ee.Algorithms.If(
                observations.size().gt(0),
                observations.sum().multiply(0.5).rename("gpm_precip_mm_day"),
                empty,
            )
        )
        return daily.set("system:time_start", day.millis())

    return ee.ImageCollection.fromImages(offsets.map(sum_day))


def gpm_power_grid_geometry() -> ee.Geometry:
    polygons = []
    for latitude, longitude in POWER_GRID_POINTS.values():
        west, east = longitude - 0.3125, longitude + 0.3125
        south, north = latitude - 0.25, latitude + 0.25
        polygons.append(
            [[
                [west, south],
                [east, south],
                [east, north],
                [west, north],
                [west, south],
            ]]
        )
    return ee.Geometry.MultiPolygon(polygons, proj="EPSG:4326", geodesic=False)


def extract_gpm_power_grid(
    start: date,
    end_exclusive: date,
    geometry: ee.Geometry,
    records: Dict[Tuple[str, str], Dict[str, Optional[float]]],
) -> None:
    collection = daily_gpm_collection(start, end_exclusive)
    rows = collection.getRegion(geometry, 11132).getInfo()
    if not rows:
        return

    columns = {name: index for index, name in enumerate(rows[0])}
    bounds = {
        region: (
            longitude - 0.3125,
            latitude - 0.25,
            longitude + 0.3125,
            latitude + 0.25,
        )
        for region, (latitude, longitude) in POWER_GRID_POINTS.items()
    }
    samples: Dict[Tuple[str, str], list[float]] = {}
    for row in rows[1:]:
        value = row[columns["gpm_precip_mm_day"]]
        if value is None:
            continue
        longitude = float(row[columns["longitude"]])
        latitude = float(row[columns["latitude"]])
        region = next(
            (
                name
                for name, (west, south, east, north) in bounds.items()
                if west <= longitude <= east and south <= latitude <= north
            ),
            None,
        )
        if region is None:
            continue
        observed_date = datetime.fromtimestamp(
            int(row[columns["time"]]) / 1000, tz=timezone.utc
        ).date().isoformat()
        samples.setdefault((region, observed_date), []).append(float(value))

    for key, values in samples.items():
        records[key]["gpm_precip_mm_day_power_grid_mean"] = sum(values) / len(values)


def extract_gpm_power_grid_with_retry(
    start: date,
    end_exclusive: date,
    geometry: ee.Geometry,
    records: Dict[Tuple[str, str], Dict[str, Optional[float]]],
) -> None:
    try:
        extract_gpm_power_grid(start, end_exclusive, geometry, records)
    except ee.EEException as error:
        if "memory limit exceeded" not in str(error).lower():
            raise
        days = (end_exclusive - start).days
        if days <= 1:
            raise RuntimeError(
                f"Earth Engine dépasse sa mémoire pour le {start}."
            ) from error
        midpoint = start + timedelta(days=days // 2)
        print("  Requête spatiale trop volumineuse ; découpage de la période.")
        extract_gpm_power_grid_with_retry(start, midpoint, geometry, records)
        extract_gpm_power_grid_with_retry(midpoint, end_exclusive, geometry, records)


def write_gpm_power_grid_csv(
    output_path: Path,
    start: date,
    end_date: date,
    records: Dict[Tuple[str, str], Dict[str, Optional[float]]],
    point_values: Dict[Tuple[str, str], Optional[str]],
) -> Path:
    rows = []
    for (region, observed_date), values in sorted(records.items()):
        latitude, longitude = POWER_GRID_POINTS[region]
        point_value = point_values.get((region, observed_date))
        mean_value = values["gpm_precip_mm_day_power_grid_mean"]
        rows.append(
            {
                "region": region,
                "date": observed_date,
                "latitude": str(latitude),
                "longitude": str(longitude),
                "gpm_precip_mm_day_point_original": point_value or "",
                "gpm_precip_mm_day_power_grid_mean": (
                    "" if mean_value is None else str(mean_value)
                ),
            }
        )

    return write_repaired_gpm_csv(
        output_path,
        [
            "region",
            "date",
            "latitude",
            "longitude",
            "gpm_precip_mm_day_point_original",
            "gpm_precip_mm_day_power_grid_mean",
        ],
        rows,
    )


def build_gpm_power_grid_dataset(
    output_prefix: Path,
    start: date,
    end_date: date,
) -> Path:
    end_exclusive = end_date + timedelta(days=1)
    records: Dict[Tuple[str, str], Dict[str, Optional[float]]] = {}
    current = start
    while current <= end_date:
        for region in POWER_GRID_POINTS:
            records[(region, current.isoformat())] = {
                "gpm_precip_mm_day_power_grid_mean": None
            }
        current += timedelta(days=1)

    point_values: Dict[Tuple[str, str], Optional[str]] = {}
    original_path = output_prefix.with_name(f"{output_prefix.name}_gpm.csv")
    if original_path.is_file():
        with original_path.open(encoding="utf-8-sig", newline="") as csv_file:
            for row in csv.DictReader(csv_file):
                if row["region"] in POWER_GRID_POINTS:
                    point_values[(row["region"], row["date"])] = row[
                        "gpm_precip_mm_day"
                    ]

    geometry = gpm_power_grid_geometry()
    for chunk_start, chunk_end in months_between(start, end_exclusive):
        print(f"Extraction GPM à l'échelle POWER : {chunk_start:%Y-%m}...")
        extract_gpm_power_grid_with_retry(
            chunk_start, chunk_end, geometry, records
        )

    output_path = output_prefix.with_name(
        f"{output_prefix.name}_gpm_power_grid.csv"
    )
    return write_gpm_power_grid_csv(
        output_path, start, end_date, records, point_values
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Crée trois CSV journaliers séparés (GPM, MODIS et SMAP) "
            "pour six villes de RDC."
        )
    )
    parser.add_argument("--project", default=os.environ.get("EE_PROJECT"))
    parser.add_argument(
        "--start-date",
        type=parse_date,
        help="Date de début facultative; par défaut, début des archives de chaque capteur.",
    )
    parser.add_argument(
        "--end-date",
        type=parse_date,
        default=datetime.now(timezone.utc).date(),
        help="Date finale incluse (par défaut : aujourd'hui, UTC).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("base_donnees_satellites.csv"),
        help=(
            "Préfixe de sortie. Le script ajoute automatiquement _gpm.csv, "
            "_modis.csv et _smap.csv."
        ),
    )
    parser.add_argument(
        "--source",
        choices=SOURCE_FIELDS,
        help="Ne télécharger qu'une source (gpm, modis ou smap).",
    )
    parser.add_argument(
        "--gpm-repair",
        type=parse_gpm_repair,
        action="append",
        metavar="VILLE=ANNEES",
        help=(
            "Retélécharge uniquement les années GPM indiquées pour une ville, "
            "puis remplace leurs lignes dans le CSV existant. Répétable."
        ),
    )
    parser.add_argument(
        "--gpm-power-grid",
        action="store_true",
        help=(
            "Crée un CSV GPM séparé, moyenné sur la maille POWER 0,5 x 0,625° "
            "pour Lubumbashi et Mbandaka; ne modifie pas le CSV GPM original."
        ),
    )
    parser.add_argument(
        "--authenticate",
        action="store_true",
        help="Lance l'authentification Earth Engine avant l'extraction.",
    )
    args = parser.parse_args()

    if not args.project:
        parser.error("indiquez --project ou définissez la variable EE_PROJECT.")
    if args.start_date and args.start_date > args.end_date:
        parser.error("--start-date doit être antérieure ou égale à --end-date.")
    if args.gpm_repair and args.source not in (None, "gpm"):
        parser.error("--gpm-repair ne peut être utilisé qu'avec la source GPM.")
    if args.gpm_repair and args.start_date:
        parser.error("--gpm-repair ne peut pas être combiné avec --start-date.")
    if args.gpm_repair and args.gpm_power_grid:
        parser.error("--gpm-repair et --gpm-power-grid sont incompatibles.")
    if args.gpm_power_grid and args.source not in (None, "gpm"):
        parser.error("--gpm-power-grid ne peut être utilisé qu'avec la source GPM.")

    if args.authenticate:
        ee.Authenticate()
    ee.Initialize(project=args.project)

    points = make_points()
    output_prefix = args.output.with_suffix("")
    if args.gpm_repair:
        output_path = output_prefix.with_name(f"{output_prefix.name}_gpm.csv")
        repaired_path = repair_gpm_rows(
            args.gpm_repair, points, output_path, args.end_date
        )
        print(f"Lignes GPM ciblées mises à jour : {repaired_path.resolve()}")
        return
    if args.gpm_power_grid:
        start = max(
            PRODUCT_STARTS["gpm"],
            args.start_date or PRODUCT_STARTS["gpm"],
        )
        output_path = build_gpm_power_grid_dataset(
            output_prefix, start, args.end_date
        )
        print(f"Base GPM harmonisée à l'échelle POWER : {output_path.resolve()}")
        return

    end_exclusive = args.end_date + timedelta(days=1)
    modis = modis_collection()
    smap = smap_collection()

    selected_sources = (
        {args.source: SOURCE_FIELDS[args.source]}
        if args.source
        else SOURCE_FIELDS
    )
    for source, fields in selected_sources.items():
        start = max(
            PRODUCT_STARTS[source],
            args.start_date or PRODUCT_STARTS[source],
        )
        output_path = output_prefix.with_name(f"{output_prefix.name}_{source}.csv")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if start > args.end_date:
            print(
                f"Aucune période disponible pour {source.upper()} "
                f"avant le {args.end_date}."
            )
            with output_path.open("w", newline="", encoding="utf-8-sig") as csv_file:
                csv.writer(csv_file).writerow(
                    ["region", "date", "latitude", "longitude", *fields]
                )
            continue

        records: Dict[Tuple[str, str], Dict[str, Optional[float]]] = {}
        current = start
        while current <= args.end_date:
            for region in REGIONS:
                records[(region, current.isoformat())] = {
                    field: None for field in fields
                }
            current += timedelta(days=1)

        print(f"Extraction {source.upper()} du {start} au {args.end_date}...")
        if source == "gpm":
            factory = daily_gpm_collection
            scale = 11132
        elif source == "modis":
            factory = lambda start, end: modis.filterDate(
                ee.Date(start.isoformat()), ee.Date(end.isoformat())
            )
            scale = 500
        else:
            factory = lambda start, end: smap.filterDate(
                ee.Date(start.isoformat()), ee.Date(end.isoformat())
            )
            scale = 9000

        for chunk_start, chunk_end in months_between(start, end_exclusive):
            extract_with_memory_retry(
                source.upper(),
                factory,
                points,
                scale,
                chunk_start,
                chunk_end,
                records,
            )

        output_path = write_source_csv(output_path, fields, records)

        print(f"Base créée : {output_path.resolve()}")


if __name__ == "__main__":
    main()
