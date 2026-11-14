"""Télécharge les sources dans simulation.db (satellites via le compte Google Earth Engine).
Usage : python scripts/download_all.py kananga 2015-01-01 2024-12-31"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.db import connect
from adapters import earth_engine, power, soilgrids, faostat

if len(sys.argv) != 4:
    raise SystemExit(__doc__)

region, start, end = sys.argv[1:4]
con = connect()
failed = False
try:
    for name, fn in (("NASA POWER", lambda: power.load(con, region, start, end)),
                     ("SoilGrids", lambda: soilgrids.load(con, region)),
                     ("FAOSTAT", lambda: faostat.load(con)),
                     ("Google Earth Engine (GPM, MODIS, SMAP)",
                      lambda: earth_engine.load(con, start, end, regions=(region,)))):
        try:
            print(name, "OK", fn() or "")
        except Exception as e:
            failed = True
            print(name, "ÉCHEC :", type(e).__name__, str(e)[:150])
finally:
    con.close()

if failed:
    raise SystemExit(1)
