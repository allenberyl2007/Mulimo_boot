"""Importe les récoltes provinciales CCSAP/SIG dans simulation.db.
Usage : python scripts/import_provincial_yields.py chemin/vers/crop_data.csv"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from adapters import provincial_yield
from core.db import connect


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    con = connect()
    try:
        count = provincial_yield.load_csv(con, sys.argv[1])
        print(f"{count} observations provinciales importées dans yield_provincial_reference.")
    finally:
        con.close()
