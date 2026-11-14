"""Provincial crop-harvest observations -> separate local reference table."""
import pandas as pd


PROVINCE_TO_ZONE = {
    "Kinshasa": "kinshasa",
    "Kongo-Central": "kinshasa",
    "Kwango": "kinshasa",
    "Kwilu": "kinshasa",
    "Mai-Ndombe": "kinshasa",
    "Equateur": "mbandaka",
    "Mongala": "mbandaka",
    "North Ubangi": "mbandaka",
    "South Ubangi": "mbandaka",
    "Tshuapa": "mbandaka",
    "Bas-Uele": "kisangani",
    "Haut-Uele": "kisangani",
    "Ituri": "kisangani",
    "Tshopo": "kisangani",
    "Maniema": "bukavu",
    "North Kivu": "bukavu",
    "South Kivu": "bukavu",
    "Kasai": "kananga",
    "Kasai-Central": "kananga",
    "Kasai-Oriental": "kananga",
    "Lomami": "kananga",
    "Sankuru": "kananga",
    "Haut-Katanga": "lubumbashi",
    "Haut-Lomami": "lubumbashi",
    "Lualaba": "lubumbashi",
    "Tanganyika": "lubumbashi",
}

PRODUCT_TO_CROP = {
    "Cassava": "cassava",
    "Cooking Banana (unspecified)": "cooking_banana",
    "Maize (Corn)": "maize",
    "Rice (Paddy)": "rice_paddy",
}


def parse(df):
    """Pair yield and production rows without treating province data as parcel data."""
    required = ["admin_1", "indicator", "value", "product", "unit", "season_year", "source_document", "id"]
    missing = set(required) - set(df.columns)
    if missing:
        raise ValueError(f"Missing required provincial-crop columns: {', '.join(sorted(missing))}")

    d = df[list(required)].copy()
    if d.empty or d[["admin_1", "product", "indicator", "unit", "season_year"]].isna().any().any():
        raise ValueError("Provincial-crop data contains no rows or missing key values")
    d["province"] = d["admin_1"].astype(str).str.strip()
    unknown = sorted(set(d["province"]) - set(PROVINCE_TO_ZONE))
    if unknown:
        raise ValueError(f"Province names need an explicit zone mapping: {', '.join(unknown)}")
    d["zone"] = d["province"].map(PROVINCE_TO_ZONE)

    products = sorted(set(d["product"].dropna()) - set(PRODUCT_TO_CROP))
    if products:
        raise ValueError(f"Unsupported crop products: {', '.join(products)}")
    d["crop"] = d["product"].map(PRODUCT_TO_CROP)
    d["year"] = pd.to_numeric(d["season_year"].astype(str).str.extract(r"(\d{4})$")[0], errors="coerce")
    d["value"] = pd.to_numeric(d["value"], errors="coerce")
    if d["year"].isna().any() or d["value"].isna().any():
        raise ValueError("Invalid season year or crop value in provincial-crop data")
    d["year"] = d["year"].astype(int)

    d["indicator"] = d["indicator"].astype(str).str.strip()
    if not set(d["indicator"]) <= {"Yield", "Quantity Produced"}:
        raise ValueError("Only Yield and Quantity Produced indicators are supported")
    yields = d[d["indicator"] == "Yield"]
    quantities = d[d["indicator"] == "Quantity Produced"]
    if yields.empty or quantities.empty:
        raise ValueError("Both Yield and Quantity Produced rows are required")
    if not (yields["unit"] == "MT/ha").all() or not (quantities["unit"] == "t").all():
        raise ValueError("Expected Yield in MT/ha and Quantity Produced in t")

    keys = ["province", "crop", "year"]
    if yields.duplicated(keys).any() or quantities.duplicated(keys).any():
        raise ValueError("Duplicate province/crop/year indicator rows")
    paired = yields[keys + ["zone", "value", "source_document", "id"]].merge(
        quantities[keys + ["value", "id"]], on=keys, suffixes=("_yield", "_production"),
        how="outer", validate="one_to_one", indicator=True,
    )
    if not (paired["_merge"] == "both").all():
        raise ValueError("Every observation must have both yield and production values")
    if (paired["value_yield"] <= 0).any() or (paired["value_production"] <= 0).any():
        raise ValueError("Yield and production values must be positive")

    paired["yield_t_ha"] = paired["value_yield"]
    paired["production_t"] = paired["value_production"]
    paired["harvested_area_ha"] = paired["production_t"] / paired["yield_t_ha"]
    paired["source"] = "ccsap_sig_provincial"
    paired["source_record_id"] = paired["id_yield"].astype(str) + "|" + paired["id_production"].astype(str)
    return paired[[
        "province", "zone", "crop", "year", "yield_t_ha", "production_t",
        "harvested_area_ha", "source", "source_document", "source_record_id",
    ]]


def load_csv(con, path):
    """Import a downloaded provincial CSV idempotently into its own table."""
    observations = parse(pd.read_csv(path, encoding="utf-8-sig"))
    columns = list(observations.columns)
    placeholders = ",".join("?" for _ in columns)
    con.executemany(
        f"INSERT OR REPLACE INTO yield_provincial_reference ({','.join(columns)}) VALUES ({placeholders})",
        observations.itertuples(index=False, name=None),
    )
    con.commit()
    return len(observations)


def aggregate_zones(observations):
    """Calculate area-weighted zone yields from paired province production and yield."""
    grouped = observations.groupby(["zone", "crop", "year"], as_index=False).agg(
        production_t=("production_t", "sum"),
        harvested_area_ha=("harvested_area_ha", "sum"),
        province_count=("province", "nunique"),
    )
    grouped["yield_t_ha"] = grouped["production_t"] / grouped["harvested_area_ha"]
    return grouped
