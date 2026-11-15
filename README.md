# Agricultural Decision Support System — DRC (NASA Space Apps)

A local, offline system featuring: **a digital twin, a single SQLite database (`data/simulation.db`), five AI models, a CLI entry point (`main.py`), and a demonstration interface (`app.py`)**.

The interface launches a lightweight local server restricted to `127.0.0.1`; no remote server, cloud service, or external API is required to generate recommendations using the pre-existing data.

```bash
python main.py --region kananga --soil ferralsol_scl --slope 8 --prev bean --demo

```

**Output format example:** *Recommended crop / Why? / Expected yield / Confidence / Alternative*.

## Local Demo Interface

With the database and models pre-configured, double-click `Lancer_la_demo.bat` on Windows. The script checks the environment, starts the server, and `app.py` automatically opens `[http://127.0.0.1:8000](http://127.0.0.1:8000)`.

The console window must remain open during the demonstration; press `Ctrl+C` to stop the server. From the command line, `python app.py` is also available.

If port 8000 is already occupied by a previous demonstration instance, the application automatically selects an available local port and opens the correct address in the browser without terminating the existing session.

Only the user-facing interface is in English for the jury, while documentation and the CLI remain in French. The application loads no external libraries, maps, or fonts from the internet.

Once initialized, the local server reads the project's SQLite databases and ONNX models completely offline, transmitting no data to external services. Downloaded databases must be placed in `data/simulation.db` prior to offline demonstration.

The user interface uses the six cities as reference points, rather than macro-regions or plot-level measurements.

Yield figures remain estimations based on models trained on simulations: this interface is a hackathon prototype and does not constitute validated agricultural advice.

---

## Rotation Comparator

The demo also offers a separate comparison between the declared recent practice, a maize-legume alternation, and a diversified maize-legume-cassava rotation. The new local endpoint `/api/rotations` invokes `core/rotation_model.py`, which utilizes the existing digital twin, offline daily NASA POWER weather data, and available local soil profiles (SoilGrids where present, otherwise archetypes).

Calculations simulate three main annual seasons based on three complete weather years, applying identical default conditions and practices across each strategy. An additional weather period is retained to accommodate the harvest of the final crop, specifically cassava. Three repetitions using different pest seed conditions display the simulator's sensitivity range; this is neither a statistical confidence interval nor a formal validation. The 0–100 ranking is relative to the three evaluated options and weighted according to five adjustable farmer priorities: soil organic carbon, erosion reduction, nitrogen fixation, water use efficiency, and food energy; it does not represent a probability of success.

The baseline practice depends on the last recorded crop and, if known, the second-to-last recorded crop; the underlying assumption is displayed in the results. Detailed explanations break down the contribution of soil, water, and nutritional scores as well as the simulated differences relative to the baseline. The page also displays annual anomalies in rainfall and temperature for the simulated years compared to the 1991–2020 NASA POWER multi-year annual average. This comparison is based on a single point and a three-year window; it does not constitute a climate trend, forecast, or plot observation.

Daily NASA POWER inputs and the utilized soil profile feed the digital twin. GPM, SMAP, and MODIS data available in the database can appear as contextual satellite information but do not alter the ranking. The results sheet details the role of each data source and the ranking formula. In the absence of observed crop yields, rotations, and plot analyses from the DRC, the output remains exploratory simulation data. No DEM/SRTM data is used: city coordinates do not describe field-level slope geometry. Market prices, market access, crop varieties, input availability, and farm-specific management calendars are not modeled. The calorie-per-harvest proxy measures neither human nutrition, farm income, nor household food security.

Targeted offline verification checks from `agri_ai/`:

```bash
python -m unittest discover -s tests -p test_webapp.py
python -m unittest discover -s tests -p test_rotation_model.py
python tests/test_adapters.py

```

---

## Project Structure

```text
main.py                 Entry point: Climate AI -> Soil AI -> Crop AI -> Yield AI -> Recommendation AI (sequential pipeline)
app.py                  Local HTTP server and demo API (standard Python library)
web/index.html          Responsive English interface for users and the jury
core/                   Digital twin (twin, climate, crops, regions, events, features, schema) + rotation comparator + db + mlkit (+ policy, decide, explain)
models/<model>/         climate, soil, crop, yield, recommendation: ONLY train.py, predict.py, model.onnx
adapters/               One adapter per source: power, smap, gpm, modis, soilgrids, faostat
data/make_datasets.py   Digital twin dataset generator (ds_* tables in simulation.db)
scripts/                create_db.py, download_all.py, train_all.sh
audit/                  audit.py (automated audit), audit_twin.py (twin audit), validate.py (scientific validation)
tests/test_adapters.py  Adapter unit tests using mock payloads
reports/                audit_report.md, validation_report.md, twin_checks.md

```

---

## Single SQLite Database

Tables: `weather`, `soil`, `soil_moisture`, `vegetation`, `yield_reference`, `crop`, `recommendation` — each containing a `source` column (`sim`, `archetype`, `nasa_power`, `gpm`, `smap`, `modis`, `soilgrids`, `faostat`, `literature`).

Training datasets produced by the digital twin (`ds_main`, `ds_climate`) are stored within the **same** database.

Each model directory contains only 3 files: metadata (variables, diagnostics, calibration, out-of-domain references) are embedded directly within `model.onnx`.

---

## Rebuilding from Scratch

```bash
python scripts/create_db.py                        # Database + soil archetypes + crop parameters
python data/make_datasets.py                       # Digital twin dataset generation (~6 min, 1 core)
bash scripts/train_all.sh                          # 5 models (independent train.py scripts)
python audit/audit_twin.py && python audit/audit.py # Audits -> reports/

```

---

## Transitioning to Real Data (Without Architecture Changes)

1. `python scripts/download_all.py kananga 2015-01-01 2024-12-31` (Requires internet access; SMAP/MODIS requires `EARTHDATA_USER`, `EARTHDATA_PASS`) populates the database.
2. `python audit/validate.py` generates calibration and external validation reports ("UNREALIZED" until real data lines are supplied).
3. Adjust `core/regions.py` (normals) based on the calibration report, then re-run `make_datasets.py` and `train_all.sh`.
4. `python main.py --mode real ...` prioritizes reading `nasa_power` / `soilgrids`, falling back to simulated data.

---

## Importing Manually Downloaded Files (API-Free)

```bash
python scripts/import_csv.py power pt_0.2987_23.9756 POWER_Point_Monthly_....csv    # Monthly POWER: calibration only (not read by twin)
python scripts/import_csv.py power kananga POWER_Daily_....csv                    # Daily POWER: 7 mandatory parameters (PRECTOTCORR, T2M, T2M_MAX, T2M_MIN, ALLSKY_SFC_SW_DWN, RH2M, WS2M)
python scripts/import_csv.py faostat FAOSTAT_data_en_....csv                    # FAOSTAT export (kg/hg or hg/ha), preserving quality flags
python scripts/import_provincial_yields.py path/to/crop_data.csv                 # CCSAP/SIG: Provincial harvest records

```

The digital twin reads exclusively **daily** weather data (`nasa_power`, `sim` sources). Monthly files are reserved for calibration and validation reporting.

CCSAP/SIG observations remain separate from FAOSTAT within `yield_provincial_reference`: the CSV contains yields and production quantities by province for 2013–2016, but not plot-level measurements. Provinces are provisionally linked to the six hubs (Kinshasa, Mbandaka, Kisangani, Bukavu, Kananga, and Lubumbashi); this indicative grouping does not constitute an official administrative or agro-ecological zoning. The report highlights coverage and anomalies requiring verification. Yields display high repetition, and 19 values fall outside a broad exploratory threshold; consequently, aggregates for the six zones are not presented as formal results until sources and units are verified. No predictive error metrics are calculated without model outputs matched to observations.

---

## Uncertainty and Confidence

For each target variable, every model returns: a prediction (`_mid`), an 80% conformal-calibrated interval (`_lo`, `_hi`), an uncertainty score (`_unc`), a confidence score (`_conf`), and flags for `ood_flag` / `unseen_features` (out-of-domain or unseen data). Wider intervals or unusual conditions lower the confidence score.

Final confidence is calculated as the minimum model confidence multiplied by the probability that the first crop outperforms the second; it is capped at 85% until real data is incorporated (with a maximum ceiling of 95% thereafter).

---

## Known Limitations

* All models are trained on **simulations**: their scores measure agreement with the digital twin, not real-world ground truth.
* The rotation comparator is a transparent, separate simulation model rather than a machine-learning model trained on observed DRC rotations or harvests.
* Crop utility rules (`core/policy.py`: calories/ha/100 days, soil and water penalties) reflect a design choice and can be modified; market prices are not utilized.
* Adapters have **never been tested against live services** (network access disabled during development); their `parse()` methods are tested exclusively against mock payloads.
* Refer to `reports/audit_report.md` and `reports/validation_report.md` for detailed metrics and points of attention.
