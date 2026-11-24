"""Health check of the 12 AETOS runs: solve status, unmet demand (backstop), demand against the CMP ceilings.

CMP end points (compare_cmp.py): reference 941 TWh (2021) -> 2,504 (2040); universal access 878 -> 3,421 (2040); geometric interpolation.
Demand = SpecifiedAnnualDemand of every country's E3 fuel in the run's own dataset (AETOS baseline + OnSSET new users).

    python scripts/overview_aetos.py [--runs runs] [--out runs/aetos_overview.csv]
"""
import argparse
import glob
import json
import os

import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--runs", default="runs")
ap.add_argument("--out", default="runs/aetos_overview.csv")
a = ap.parse_args()

geo = lambda y, y0, v0, y1, v1: v0 * (v1 / v0) ** ((y - y0) / (y1 - y0))
YEARS = (2025, 2030, 2035, 2040)
rows = []
for d in sorted(glob.glob(os.path.join(a.runs, "*_t?_ct?"))):
    run = os.path.basename(d)
    st = json.load(open(os.path.join(d, "solve_status.json")))
    sd = pd.read_csv(os.path.join(d, "data", "SpecifiedAnnualDemand.csv"))
    sd = sd[sd.FUEL.str.endswith("E3")].groupby("YEAR").VALUE.sum() / 3.6          # PJ -> TWh
    my = pd.read_csv(os.path.join(d, "metrics", "metrics_yearly.csv"), keep_default_na=False)
    r = dict(run=run, status=st["status"], objective_MUSD=round(st["objective"]), solve_min=round(st["total_seconds"] / 60, 1))
    r["backstop_GWh_2021_2045"] = round(my.backstop_GWh.sum(), 3)
    r["backstop_GWh_2025_2040"] = round(my[(my.y >= 2025) & (my.y <= 2040)].backstop_GWh.sum(), 3)
    for y in YEARS:
        ref, acc = geo(y, 2021, 941, 2040, 2504), geo(y, 2021, 878, 2040, 3421)
        r[f"demand_{y}_TWh"] = round(sd[y], 1)
        r[f"over_CMP_ref_{y}"] = round(sd[y] / ref, 3)
        r[f"over_CMP_access2040_{y}"] = round(sd[y] / acc, 3)
    rows.append(r)
o = pd.DataFrame(rows)
o["max_over_CMP_access2040"] = o[[f"over_CMP_access2040_{y}" for y in YEARS]].max(axis=1)
o.to_csv(a.out, index=False)
pd.set_option("display.width", 250)
print(o[["run", "status", "objective_MUSD", "solve_min", "backstop_GWh_2025_2040"]].to_string(index=False))
print()
print(o[["run"] + [f"demand_{y}_TWh" for y in YEARS] + [f"over_CMP_access2040_{y}" for y in (2030, 2040)] + ["over_CMP_ref_2040"]].to_string(index=False))
print(f"\nceiling check: every run <= CMP access-2040 path in every year: {bool((o.max_over_CMP_access2040 <= 1).all())}")
