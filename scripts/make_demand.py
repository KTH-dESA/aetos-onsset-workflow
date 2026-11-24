"""OnSSET run 1 -> additional grid electricity demand of newly connected people, per country and model year (option C).

For one demand level (low = code 1_1_0_0_1_0, high = 2_0_0_0_1_0) and one cost trajectory:
  1. per step (2030, 2035, 2040): sum of `EnergyPerSettlement<year>` over the settlements whose `FinalElecCode<year>`
     is grid (1 = existing grid, i.e. densification, 2 = new grid). EnergyPerSettlement is INCREMENTAL: new connections of
     that step x household demand (+ productive loads for settlements that were unelectrified before the step).
     Off-grid steps (stand-alone, mini-grid) are written to the steps file but are not grid demand.
     --component extension: only settlements that were NOT on grid at the previous step (FinalElecCode<prev> not in 1, 2;
     prev = 2025 before 2030) and are on grid now: new grid extension to unconnected settlements, counted once, in the step they
     connect. Households added in settlements already on grid (population growth, densification) are left to the AETOS demand
     to limit double counting. --component all (default, the full increment used in the paper) = every settlement with code 1 or 2.
  2. cumulative over the steps = demand of all people connected since 2025 (stock). 0 in 2025.
  3. yearly values for the AETOS model years: linear between 2025 (0), 2030, 2035, 2040; after 2040 held flat
     (--post flat) or continued at the 2035-2040 slope (--post trend).
Output (PJ, the unit of AETOS SpecifiedAnnualDemand): CC (ISO2), YEAR, VALUE. make_gep_scenario.py adds it to AETOS's own
demand of the country (the AETOS baseline is kept as it is: option C).  <out>_steps.csv has the per-step numbers.

    python scripts/make_demand.py --run1 runs/run1 --level low --ct 1 --out runs/run1/demand_low_ct1.csv
"""
import argparse
import glob
import os
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

CODES = {"low": "1_1_0_0_1_0", "high": "2_0_0_0_1_0"}
KWH_TO_PJ = 3.6e-9          # 1 kWh = 3.6 MJ
GRID = (1, 2)


def read_steps(job):
    iso3, path, years, start, component = job
    prev = dict(zip(years, [start] + list(years[:-1])))
    cols = [f"{p}{y}" for y in years for p in ("FinalElecCode", "EnergyPerSettlement")] + [f"FinalElecCode{start}"]
    for _ in range(4):                                  # the shared drive sometimes fails mid-read
        try:
            t = pd.read_csv(path, usecols=cols)
            break
        except OSError:
            time.sleep(5)
    else:
        return iso3, None
    out = {}
    for y in years:
        e, c = t[f"EnergyPerSettlement{y}"].fillna(0.0), t[f"FinalElecCode{y}"]
        g = c.isin(GRID)
        if component == "extension":
            g = g & ~t[f"FinalElecCode{prev[y]}"].isin(GRID)
        out[y] = (float(e[g].sum()), float(e[~c.isin(GRID)].sum()))
    return iso3, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run1", default="runs/run1")
    ap.add_argument("--level", choices=list(CODES), required=True)
    ap.add_argument("--ct", type=int, default=1)
    ap.add_argument("--out", required=True)
    ap.add_argument("--steps", nargs="+", type=int, default=[2030, 2035, 2040])
    ap.add_argument("--start-year", type=int, default=2025)
    ap.add_argument("--model-years", nargs=2, type=int, default=[2021, 2045])
    ap.add_argument("--component", choices=["extension", "all"], default="all",
                    help="extension: only settlements newly connected in the step; all: every grid settlement (code 1 or 2)")
    ap.add_argument("--post", choices=["flat", "trend"], default="flat", help="after the last step")
    ap.add_argument("--iso-codes", default="onsset/iso_codes.csv")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()

    iso = pd.read_csv(a.iso_codes, keep_default_na=False).set_index("Alpha-3")["Alpha-2"]
    code = CODES[a.level]
    jobs = []
    for d in sorted(glob.glob(os.path.join(a.run1, "*", f"results_ct{a.ct}"))):
        f = glob.glob(os.path.join(d, f"*-1-{code}.csv"))
        if f:
            jobs.append((os.path.basename(os.path.dirname(d)), f[0], a.steps, a.start_year, a.component))
    print(f"{len(jobs)} countries, level {a.level} ({code}), CT{a.ct}, component {a.component}", flush=True)
    with ProcessPoolExecutor(a.workers) as ex:
        res = list(ex.map(read_steps, jobs))

    rows, yearly = [], []
    years = list(range(a.model_years[0], a.model_years[1] + 1))
    for iso3, out in res:
        if out is None:
            print(f"{iso3}: unreadable, skipped")
            continue
        grid = np.array([out[y][0] for y in a.steps]) * KWH_TO_PJ
        off = np.array([out[y][1] for y in a.steps]) * KWH_TO_PJ
        for y, g, o in zip(a.steps, grid, off):
            rows.append(dict(iso3=iso3, step=y, grid_PJ=g, offgrid_PJ=o))
        cum = np.cumsum(grid)
        xs, ys = [a.start_year] + a.steps, [0.0] + list(cum)
        slope = (cum[-1] - cum[-2]) / (a.steps[-1] - a.steps[-2]) if len(cum) > 1 else 0.0
        for y in years:
            v = float(np.interp(y, xs, ys))
            if y > a.steps[-1] and a.post == "trend":
                v = float(cum[-1] + slope * (y - a.steps[-1]))
            if iso3 in iso.index:
                yearly.append(dict(CC=iso[iso3], YEAR=y, VALUE=round(v, 6)))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    steps = pd.DataFrame(rows)
    steps.to_csv(a.out.replace(".csv", "_steps.csv"), index=False)
    pd.DataFrame(yearly).to_csv(a.out, index=False)
    tot = (steps.groupby("step")[["grid_PJ", "offgrid_PJ"]].sum() * 1000 / 3.6).rename(columns=lambda c: c.replace("_PJ", "_GWh"))
    print("incremental energy per step, all countries (GWh):")
    print(tot.round(0).to_string())
    print("-> ", a.out)


if __name__ == "__main__":
    main()
