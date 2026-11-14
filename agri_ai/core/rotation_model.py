"""Compare three-year crop rotations with the digital twin and local NASA data.

This transparent scenario model is deliberately separate from the ONNX yield
predictors: there are no observed DRC field rotations or harvests to train a
rotation ranker without teaching it simulated truth as if it were measured.
"""
import numpy as np
import pandas as pd

from .crops import CROPS
from .db import read_weather
from .policy import KCAL_PER_KG
from .regions import REGIONS, SoilType, TOPSOIL_MASS_KG
from .schema import validate_weather
from .twin import DigitalTwin, Management, Site

HORIZON_YEARS = 3
REPLICATES = 3
PRIORITY_KEYS = ("soil_carbon", "erosion", "nitrogen", "water", "food")
PRIORITY_LABELS = {
    "soil_carbon": "Soil carbon",
    "erosion": "Erosion protection",
    "nitrogen": "Nitrogen fixation",
    "water": "Water use",
    "food": "Food energy",
}
DEFAULT_MANAGEMENT = dict(
    n_kg=0.0,
    p_kg=0.0,
    k_kg=0.0,
    lime_t=0.0,
    residue_return=0.3,
    pest_control=0.0,
    seed_quality=0.5,
    weeding=0.6,
)

STRATEGIES = {
    "baseline": {
        "name": "Continue your recent crop pattern",
        "rationale": "Repeats the one- or two-crop pattern you reported as a reference.",
        "benefits": ["Provides a comparison with the recent practice you entered."],
        "risks": ["Repeating crops can maintain crop-family pest pressure and nutrient demand."],
    },
    "cereal_legume": {
        "name": "Maize and legume rotation",
        "rationale": "Alternates maize with your selected bean or groundnut crop.",
        "benefits": ["Legumes can fix atmospheric nitrogen when nodulation and management are adequate."],
        "risks": ["Nitrogen fixation is simulated, not measured; a legume still needs suitable soil and management."],
    },
    "diversified": {
        "name": "Diversified maize, legume and cassava rotation",
        "rationale": "Cycles among maize, a selected legume and cassava to diversify crop families.",
        "benefits": ["Uses three crop types and includes a legume; modeled soil, water and crop outcomes are shown below."],
        "risks": ["Cassava has a longer crop cycle; local planting calendars, varieties and markets are not represented."],
    },
}


def _soil_profile(con, region):
    rows = pd.read_sql_query(
        "SELECT * FROM soil WHERE site=? AND source IN ('soilgrids','archetype') "
        "ORDER BY CASE source WHEN 'soilgrids' THEN 0 ELSE 1 END",
        con,
        params=(region,),
    )
    if rows.empty:
        raise ValueError(f"No soil profile is available for {region}.")
    row = rows.iloc[0]
    profile = SoilType(
        name=f"{region}_{row['source']}",
        wp=float(row["wp"]),
        fc=float(row["fc"]),
        sat=float(row["sat"]),
        drain=float(row["drain"]),
        cn=float(row["cn"]),
        k_erod=float(row["k_erod"]),
        soc=float(row["soc_pct"]),
        ph=float(row["ph"]),
        p_bray=float(row["p_bray"]),
        k_exch=float(row["k_exch"]),
        cec=float(row["cec"]),
        p_fix=float(row["p_fix"]),
    )
    note = str(row["notes"]) if pd.notna(row["notes"]) else ""
    return profile, str(row["source"]), note


def _historical_weather(con, region):
    all_weather = read_weather(con, region, "1984-01-01", "2100-01-01", ("nasa_power",))
    if all_weather.empty:
        raise ValueError(f"No NASA POWER weather is available for {region}.")
    all_weather["date"] = pd.to_datetime(all_weather["date"])
    year_counts = all_weather.groupby(all_weather["date"].dt.year)["date"].nunique()
    complete_years = sorted(
        int(year)
        for year, count in year_counts.items()
        if count == (366 if pd.Timestamp(year=int(year), month=12, day=31).is_leap_year else 365)
    )
    latest_date = all_weather["date"].max()
    for end_year in reversed(complete_years):
        years = list(range(end_year - HORIZON_YEARS + 1, end_year + 1))
        if not all(year in complete_years for year in years):
            continue
        harvest_buffer_end = pd.Timestamp(year=end_year, month=12, day=31) + pd.Timedelta(days=365)
        if latest_date < harvest_buffer_end:
            continue
        start = f"{years[0]}-01-01"
        weather = all_weather[all_weather["date"] >= start].reset_index(drop=True)
        quality = validate_weather(weather)
        if len(weather) >= sum(
            366 if pd.Timestamp(year=year, month=12, day=31).is_leap_year else 365
            for year in years
        ) and quality["ok"]:
            return weather, years
    raise ValueError(
        "Three consecutive complete planting years and at least one additional harvest year "
        "of valid NASA POWER weather are required."
    )


def _annual_climate_comparison(weather, baseline, years):
    baseline = baseline.copy()
    baseline["date"] = pd.to_datetime(baseline["date"])
    baseline_by_year = baseline.groupby(baseline["date"].dt.year)
    normal_rows = []
    for year, rows in baseline_by_year:
        expected = 366 if pd.Timestamp(year=int(year), month=12, day=31).is_leap_year else 365
        if len(rows) == expected and validate_weather(rows)["ok"]:
            normal_rows.append(
                {
                    "rain_mm": float(rows["PRECTOTCORR"].sum()),
                    "temperature_c": float(rows["T2M"].mean()),
                }
            )
    if len(normal_rows) < 25:
        return {
            "baseline_period": "1991-2020",
            "complete_baseline_years": len(normal_rows),
            "years": [],
        }

    normal_rain = float(np.mean([row["rain_mm"] for row in normal_rows]))
    normal_temperature = float(np.mean([row["temperature_c"] for row in normal_rows]))
    annual_weather = weather.copy()
    annual_weather["date"] = pd.to_datetime(annual_weather["date"])
    summaries = []
    for year in years:
        rows = annual_weather[annual_weather["date"].dt.year == year]
        expected = 366 if pd.Timestamp(year=year, month=12, day=31).is_leap_year else 365
        if len(rows) != expected or not validate_weather(rows)["ok"]:
            continue
        annual_rain = float(rows["PRECTOTCORR"].sum())
        annual_temperature = float(rows["T2M"].mean())
        summaries.append(
            {
                "year": year,
                "rain_mm": round(annual_rain, 1),
                "rain_anomaly_mm": round(annual_rain - normal_rain, 1),
                "rain_anomaly_pct": round(
                    100.0 * (annual_rain - normal_rain) / normal_rain,
                    1,
                )
                if normal_rain
                else None,
                "temperature_mean_c": round(annual_temperature, 2),
                "temperature_anomaly_c": round(annual_temperature - normal_temperature, 2),
            }
        )
    return {
        "baseline_period": "1991-2020",
        "complete_baseline_years": len(normal_rows),
        "normal_annual_rain_mm": round(normal_rain, 1),
        "normal_annual_temperature_c": round(normal_temperature, 2),
        "years": summaries,
    }


def _future_sequence(pattern, last_crop, count):
    if last_crop in pattern:
        start = (pattern.index(last_crop) + 1) % len(pattern)
    else:
        start = 0
    return [pattern[(start + offset) % len(pattern)] for offset in range(count)]


def _plans(last_crop, crop_before_last, legume_crop):
    history = [crop_before_last, last_crop] if crop_before_last else [last_crop]
    baseline = [history[index % len(history)] for index in range(HORIZON_YEARS)]
    legume_cycle = ["maize", legume_crop]
    cereal_legume = _future_sequence(legume_cycle, last_crop, HORIZON_YEARS)
    if cereal_legume == baseline:
        first_crop = legume_cycle[(legume_cycle.index(cereal_legume[0]) + 1) % len(legume_cycle)]
        cereal_legume = [
            legume_cycle[(legume_cycle.index(first_crop) + offset) % len(legume_cycle)]
            for offset in range(HORIZON_YEARS)
        ]
    diverse_cycle = ["maize", legume_crop, "cassava"]
    diversified = _future_sequence(diverse_cycle, last_crop, HORIZON_YEARS)
    return {
        "baseline": baseline,
        "cereal_legume": cereal_legume,
        "diversified": diversified,
    }


def _simulate_strategy(region, soil, slope, weather, sequence):
    plan = [
        Management(
            crop=crop,
            year=year,
            season=0,
            **DEFAULT_MANAGEMENT,
        )
        for year, crop in enumerate(sequence)
    ]
    results = []
    for seed in range(REPLICATES):
        output = DigitalTwin(Site(region, soil.name, slope_pct=slope, soil_obj=soil)).run(
            weather,
            plan,
            seed=seed,
        )
        seasons = output["seasons"]
        if len(seasons) != HORIZON_YEARS or (seasons["skipped"] != 0).any():
            raise RuntimeError(f"The digital twin did not simulate every planned crop: {sequence}")
        if seasons["crop"].tolist() != sequence:
            raise RuntimeError(f"The digital twin returned an unexpected crop sequence: {sequence}")
        results.append(seasons)
    return results


def _scenario_metrics(results):
    run_metrics = []
    for seasons in results:
        crop_energy = [
            float(row.yield_t_ha) * 1000.0 * KCAL_PER_KG[row.crop]
            for row in seasons.itertuples()
        ]
        run_metrics.append(
            {
                "yield_t_ha_year": float(seasons["yield_t_ha"].mean()),
                "yield_t_ha_low": float(seasons["yield_t_ha"].min()),
                "yield_t_ha_high": float(seasons["yield_t_ha"].max()),
                "food_energy_mkcal_ha_year": float(np.mean(crop_energy)) / 1_000_000.0,
                "water_use_mm_year": float((seasons["transp_mm"] + seasons["evap_mm"]).mean()),
                "water_stress_pct": float((1.0 - seasons["ks_mean"].mean()) * 100.0),
                "soil_carbon_change_t_ha": float(
                    (seasons.iloc[-1]["soc_end_pct"] - seasons.iloc[0]["soc_start_pct"])
                    * TOPSOIL_MASS_KG
                    / 100_000.0
                ),
                "erosion_t_ha_year": float(seasons["erosion_t_ha"].mean()),
                "nitrogen_fixed_kg_ha_year": float(seasons["N_fixed"].mean()),
                "disease_loss_pct": float(seasons["dis_loss"].mean() * 100.0),
            }
        )

    frame = pd.DataFrame(run_metrics)
    metrics = {}
    for column in frame.columns:
        values = frame[column].to_numpy(float)
        metrics[column] = {
            "median": round(float(np.median(values)), 2),
            "p10": round(float(np.quantile(values, 0.1)), 2),
            "p90": round(float(np.quantile(values, 0.9)), 2),
        }
    return metrics


def _normalize(values, higher_is_better):
    values = np.asarray(values, dtype=float)
    low, high = float(np.min(values)), float(np.max(values))
    if np.isclose(low, high):
        return np.full(len(values), 0.5)
    score = (values - low) / (high - low)
    return score if higher_is_better else 1.0 - score


def _strategy_explanations(strategy, reference):
    baseline = reference["metrics"]
    metrics = strategy["metrics"]

    def difference(metric):
        return round(metrics[metric]["median"] - baseline[metric]["median"], 2)

    weights = strategy["score_weights"]
    crop_families = [CROPS[crop].family for crop in strategy["crops"]]
    contribution_values = {
        key: weights[key] * strategy["objective_scores"][key] for key in PRIORITY_KEYS
    }
    contributions = {key: round(value, 1) for key, value in contribution_values.items()}
    return {
        "score_contributions": contributions,
        "why_it_ranked": [
            f"{PRIORITY_LABELS[key]}: {strategy['objective_scores'][key]}/100 × "
            f"{weights[key]:.2%} priority = {contributions[key]} score points."
            for key in PRIORITY_KEYS
        ],
        "versus_reference": {
            "food_energy_mkcal_ha_year": difference("food_energy_mkcal_ha_year"),
            "water_use_mm_year": difference("water_use_mm_year"),
            "water_stress_pct": difference("water_stress_pct"),
            "soil_carbon_change_t_ha": difference("soil_carbon_change_t_ha"),
            "erosion_t_ha_year": difference("erosion_t_ha_year"),
            "nitrogen_fixed_kg_ha_year": difference("nitrogen_fixed_kg_ha_year"),
            "disease_loss_pct": difference("disease_loss_pct"),
        },
        "crop_families": crop_families,
        "family_changes": sum(
            first != second for first, second in zip(crop_families, crop_families[1:])
        ),
    }


def _remote_sensing_context(con, region, start, end, weather):
    context = {}
    gpm = pd.read_sql_query(
        "SELECT date, PRECTOTCORR, source FROM weather "
        "WHERE region=? AND source IN ('gpm_gee', 'gpm') AND date BETWEEN ? AND ? "
        "ORDER BY date, CASE source WHEN 'gpm_gee' THEN 0 ELSE 1 END",
        con,
        params=(region, start, end),
    )
    if len(gpm) >= 30:
        gpm = gpm.drop_duplicates("date", keep="first").drop(columns="source")
        gpm["date"] = pd.to_datetime(gpm["date"])
        power_weekly = weather.set_index("date")["PRECTOTCORR"].resample("W").sum()
        gpm_weekly = gpm.set_index("date")["PRECTOTCORR"].resample("W").sum()
        paired = pd.concat([power_weekly.rename("power"), gpm_weekly.rename("gpm")], axis=1).dropna()
        if len(paired) >= 8 and paired["power"].std() > 0 and paired["gpm"].std() > 0:
            context["gpm_weekly_rain_correlation"] = round(float(paired["power"].corr(paired["gpm"])), 2)
            context["gpm_power_week_count"] = int(len(paired))

    smap = pd.read_sql_query(
        "SELECT value, source, date FROM soil_moisture "
        "WHERE region=? AND source IN ('smap_gee', 'smap') "
        "AND kind='smap_surface' AND date BETWEEN ? AND ? "
        "ORDER BY date, CASE source WHEN 'smap_gee' THEN 0 ELSE 1 END",
        con,
        params=(region, start, end),
    )
    if len(smap):
        smap = smap.drop_duplicates("date", keep="first")
        context["smap_surface_moisture_m3_m3_median"] = round(float(smap["value"].median()), 3)
        context["smap_observation_count"] = int(len(smap))

    modis = pd.read_sql_query(
        "SELECT ndvi, source, date FROM vegetation "
        "WHERE region=? AND source IN ('modis_gee', 'modis') AND date BETWEEN ? AND ? "
        "ORDER BY date, CASE source WHEN 'modis_gee' THEN 0 ELSE 1 END",
        con,
        params=(region, start, end),
    )
    if len(modis):
        modis = modis.drop_duplicates("date", keep="first")
        context["modis_ndvi_median"] = round(float(modis["ndvi"].median()), 3)
        context["modis_observation_count"] = int(len(modis))
    return context


def compare_rotations(
    con,
    region,
    slope,
    last_crop,
    crop_before_last=None,
    legume_crop="bean",
    priorities=None,
):
    """Rank the declared current pattern and two alternatives over three years.

    Scores are relative to the three evaluated scenarios; they are not
    calibrated probabilities, yield confidence, or field validation.
    """
    if region not in REGIONS:
        raise ValueError("Choose one of the six available reference cities.")
    if last_crop not in CROPS:
        raise ValueError("Select the most recently grown crop to define the baseline rotation.")
    if crop_before_last is not None and crop_before_last not in CROPS:
        raise ValueError("Select a valid crop or leave the earlier crop unknown.")
    if legume_crop not in ("bean", "groundnut"):
        raise ValueError("The rotation legume must be beans or groundnuts.")
    if not np.isfinite(slope) or not 0 <= slope <= 100:
        raise ValueError("Slope must be a number between 0 and 100.")

    priorities = priorities or {key: 1.0 for key in PRIORITY_KEYS}
    if set(priorities) != set(PRIORITY_KEYS):
        raise ValueError("Choose priorities for soil carbon, erosion, nitrogen, water, and food.")
    priorities = {key: float(value) for key, value in priorities.items()}
    if any(not np.isfinite(value) or value < 0 for value in priorities.values()):
        raise ValueError("Priority weights must be finite non-negative numbers.")
    total_priority = sum(priorities.values())
    if total_priority <= 0:
        raise ValueError("At least one farmer priority must be greater than zero.")
    priorities = {
        key: round(priorities[key] / total_priority, 4)
        for key in PRIORITY_KEYS
    }
    last_priority = PRIORITY_KEYS[-1]
    priorities[last_priority] = round(
        priorities[last_priority] + 1.0 - sum(priorities.values()),
        4,
    )

    soil, soil_source, soil_note = _soil_profile(con, region)
    weather, years = _historical_weather(con, region)
    climate_baseline = read_weather(con, region, "1991-01-01", "2020-12-31", ("nasa_power",))
    climate_context = _annual_climate_comparison(weather, climate_baseline, years)
    sequences = _plans(last_crop, crop_before_last, legume_crop)
    metrics = {
        key: _scenario_metrics(_simulate_strategy(region, soil, slope, weather, sequence))
        for key, sequence in sequences.items()
    }

    strategy_keys = list(STRATEGIES)
    indicator_scores = {
        "soil_carbon": _normalize(
            [metrics[key]["soil_carbon_change_t_ha"]["median"] for key in strategy_keys],
            True,
        ),
        "erosion": _normalize(
            [metrics[key]["erosion_t_ha_year"]["median"] for key in strategy_keys],
            False,
        ),
        "nitrogen": _normalize(
            [metrics[key]["nitrogen_fixed_kg_ha_year"]["median"] for key in strategy_keys],
            True,
        ),
        "water": (
            0.75
            * _normalize(
                [metrics[key]["water_use_mm_year"]["median"] for key in strategy_keys],
                False,
            )
            + 0.25
            * _normalize(
                [metrics[key]["water_stress_pct"]["median"] for key in strategy_keys],
                False,
            )
        ),
        "food": _normalize(
            [metrics[key]["food_energy_mkcal_ha_year"]["median"] for key in strategy_keys],
            True,
        ),
    }

    normalized_weights = priorities
    ranked = []
    for index, key in enumerate(strategy_keys):
        strategy = dict(STRATEGIES[key])
        strategy.update(
            id=key,
            crops=sequences[key],
            crop_names=[CROPS[crop].name for crop in sequences[key]],
            metrics=metrics[key],
            objective_scores={
                key: round(float(indicator_scores[key][index]) * 100, 1)
                for key in PRIORITY_KEYS
            },
            score_weights=normalized_weights,
            relative_score=round(
                100.0
                * sum(
                    priorities[key] * indicator_scores[key][index]
                    for key in PRIORITY_KEYS
                ),
                1,
            ),
        )
        ranked.append(strategy)
    ranked.sort(key=lambda strategy: strategy["relative_score"], reverse=True)
    baseline_strategy = next(strategy for strategy in ranked if strategy["id"] == "baseline")
    for strategy in ranked:
        strategy["explanations"] = _strategy_explanations(
            strategy,
            baseline_strategy,
        )

    start = str(weather["date"].iloc[0].date())
    end = str(weather["date"].iloc[-1].date())
    evidence = _remote_sensing_context(con, region, start, end, weather)
    data_notes = [
        f"NASA POWER historical daily weather drives the three-year scenarios ({start} to {end}).",
        f"Soil inputs are a {soil_source} reference profile for {region}; this is a city proxy, not a field test.",
        "The digital twin simulates one main planting season per year, using the same weather, soil, slope and default management across all scenarios.",
        "The reference repeats the last reported crop when the earlier crop is unknown; otherwise it repeats the reported two-crop pattern.",
        "Three pest-seed replicates provide a model sensitivity range, not a statistical confidence interval or validation against observed harvests.",
        "Local crop prices, market access, farm inputs, parcel boundaries and observed DRC harvests are unavailable; they are not scored.",
        "The 0–100 scenario score is normalized across these three options and the selected priorities; it is not a probability of success.",
        "Yield, water, carbon, erosion, nitrogen and disease indicators are digital-twin outputs under shared scenario assumptions, not field observations.",
        "The food-energy indicator is a crop-calorie proxy per harvest; it is not dietary nutrition, household food security, or income.",
        "Soil carbon, erosion protection and nitrogen fixation each have separate farmer-selected weights; water combines relative water use and modeled crop water stress.",
        "The seasonal planting calendar is an approximate city-level window, not a locally surveyed farm calendar.",
        "Annual rainfall and temperature anomalies compare the selected historical years with the same NASA POWER city point's 1991-2020 average; three years do not establish a climate trend.",
    ]
    if soil_source == "soilgrids":
        data_notes.append("SoilGrids does not provide the phosphorus and potassium values used here; those remain regional soil-archetype estimates.")
    if soil_note:
        data_notes.append(soil_note)
    if evidence:
        data_notes.append("GPM, SMAP and MODIS summaries are supporting satellite context only; they do not adjust the rotation scores.")
    return {
        "region": region,
        "reference_location": REGIONS[region].name,
        "reference_coordinates": {
            "latitude": REGIONS[region].lat,
            "longitude": REGIONS[region].lon,
        },
        "planting_years": years,
        "weather_period": {"start": start, "end": end},
        "horizon_years": HORIZON_YEARS,
        "baseline_assumption": (
            f"The reference repeats the reported two-crop pattern ({CROPS[crop_before_last].name}, "
            f"{CROPS[last_crop].name}), starting with the crop before last."
            if crop_before_last
            else f"The reference assumes {CROPS[last_crop].name} is repeated because the earlier crop was not provided."
        ),
        "priority_weights": normalized_weights,
        "score_method": {
            "normalization": "Each indicator is min-max scaled only across the three scenarios in this comparison.",
            "indicators": {
                "soil_carbon": "Higher modeled soil-carbon change is preferred.",
                "erosion": "Lower modeled erosion is preferred.",
                "nitrogen": "Higher modeled biological nitrogen fixation is preferred.",
                "water": "75% lower simulated water use and 25% lower simulated crop water stress.",
                "food": "Higher food-energy proxy per harvest is preferred.",
            },
            "food_component": "Food-energy proxy per harvest; median modeled yield multiplied by crop kcal/kg.",
            "final_score": "Weighted average of the five relative indicators using the displayed normalized farmer priorities. These scores are only comparable within this run.",
        },
        "data_sources": [
            {
                "name": "NASA POWER daily",
                "role": "Scenario driver",
                "use": (
                    "Daily weather input to the digital twin at the reference-city point "
                    f"({REGIONS[region].lat:.4f}, {REGIONS[region].lon:.4f})."
                ),
                "period": {"start": start, "end": end},
            },
            {
                "name": "SoilGrids" if soil_source == "soilgrids" else "Regional soil archetype",
                "role": "Scenario driver",
                "use": "Reference soil profile for the city; it is not a parcel measurement.",
                "notes": soil_note,
            },
            {
                "name": "GPM, SMAP and MODIS",
                "role": "Context only",
                "use": "Available rainfall, surface-moisture and vegetation summaries; none affects the scenario scores.",
            },
        ],
        "evidence": evidence,
        "historical_climate_context": climate_context,
        "strategies": ranked,
        "limitations": data_notes,
    }
