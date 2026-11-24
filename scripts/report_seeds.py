"""One-table report of every grid/carbon seed the OnSSET run reads from the specs workbooks.

Rows: country x scenario-parameter row (0 = none, 1 = low demand / tax row, 2 = high demand) x model year.
Columns: GridGenerationCost, GridCapacityInvestmentCost, GridEmissionFactor, GridRenShare, GridRenShareEnergy, CarbonTax,
each with the no-tax value and the _CT (carbon-tax) value. A column falls back to the single-value seed when the
per-year column does not exist (the runner does the same).

    python scripts/report_seeds.py [--specs runs/specs] [--out runs/seeds_report.csv] [--years 2030 2035 2040]
"""
import argparse
import os

import pandas as pd

NAMES = ["GridGenerationCost", "GridCapacityInvestmentCost", "GridEmissionFactor", "GridRenShare", "GridRenShareEnergy",
         "CarbonTax"]

ap = argparse.ArgumentParser()
ap.add_argument("--specs", default="runs/specs")
ap.add_argument("--out", default="runs/seeds_report.csv")
ap.add_argument("--years", nargs="+", type=int, default=[2030, 2035, 2040])
ap.add_argument("--row", type=int, default=0,
                help="ScenarioParameters row to report: the tax-free run-1 codes (3rd digit 0) read row 0, tax codes read row 1")
a = ap.parse_args()

rows = []
for f in sorted(os.listdir(a.specs)):
    if not f.endswith("-1-specs.xlsx"):
        continue
    p = pd.read_excel(os.path.join(a.specs, f), sheet_name="ScenarioParameters")
    for y in a.years:
        r = {"country": f.split("-")[0].upper(), "year": y}
        for n in NAMES:
            for sfx in ("", "_CT"):
                if n == "CarbonTax" and sfx:
                    continue
                col = f"{n}{y}{sfx}"
                single, src = f"{n}{sfx}", "year"
                if col not in p:
                    col, src = single, "single"
                r[f"{n}{sfx}"] = float(p[col].iloc[a.row]) if col in p else None
                r[f"{n}{sfx}_src"] = src if col in p else "missing"
        rows.append(r)
out = pd.DataFrame(rows)
out.to_csv(a.out, index=False)
print(f"{len(out)} rows -> {a.out}")
print(out.query("country in ['ZM', 'NG']").round(3).T.to_string())
