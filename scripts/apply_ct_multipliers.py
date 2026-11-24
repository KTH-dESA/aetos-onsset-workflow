"""Apply the cost-trajectory (CT) multipliers to an AETOS dataset (otoole CSV folder), in place.

Multipliers (same table as run_onsset1.CT and the README):       grid    renewable   diesel CAPEX   diesel OPEX
                                                           CT1   1.0       1.0          1.0           1.0
                                                           CT2   1.5       0.5          1.0           1.3
                                                           CT3   2.0       0.35         1.2           1.5
Mapping (data/ct_technology_groups.csv, one row per AETOS technology):
  grid CAPEX       CapitalCost of grid_thermal (coal, gas incl. CCS, heavy fuel oil, nuclear) and interconnector technologies.
                   Distribution/transmission nodes carry no cost in AETOS. Generation CAPEX is scaled here only; T&D and
                   connection costs are scaled in OnSSET only (not both models twice).
  renewable CAPEX  CapitalCost of the renewable group (hydro, solar PV and CSP, wind, geothermal, biomass, batteries) and
                   CapitalCostStorage of all storages (batteries, hydro storage), as OnSSET's renewable multiplier also covers batteries.
  diesel           NOT scaled by default: the study scales diesel only in OnSSET (mini-grid and stand-alone diesel), see NOTES.md.
                   --diesel also scales AETOS's diesel plants (CAPEX, fixed and variable O&M) and the diesel import fuel price (OPEX).
Only years >= --from-year (default 2025, OnSSET's start year) are scaled: 2021-2024 stay at the base-year costs.
Backstops (99999) and fuel supply/import technologies are never scaled.

    python scripts/apply_ct_multipliers.py <dataset dir> --ct 2 [--diesel] [--from-year 2025]
"""
import argparse
import os

import pandas as pd

CT = {1: dict(grid=1.0, ren=1.0, diesel_capex=1.0, diesel_opex=1.0),
      2: dict(grid=1.5, ren=0.5, diesel_capex=1.0, diesel_opex=1.3),
      3: dict(grid=2.0, ren=0.35, diesel_capex=1.2, diesel_opex=1.5)}

ap = argparse.ArgumentParser()
ap.add_argument("data")
ap.add_argument("--ct", type=int, required=True, choices=[1, 2, 3])
ap.add_argument("--groups", default="data/ct_technology_groups.csv")
ap.add_argument("--from-year", type=int, default=2025)
ap.add_argument("--diesel", action="store_true", help="also scale AETOS's diesel plants and diesel fuel price")
a = ap.parse_args()

m = CT[a.ct]
grp = pd.read_csv(a.groups).set_index("technology")["group"]
log = [f"CT{a.ct}: {m}; years >= {a.from_year}; diesel in AETOS: {'yes' if a.diesel else 'no'}"]


def scale(fname, key, factors, label):
    """factors: {group: multiplier}; key = TECHNOLOGY (or STORAGE with factors {'*': m})."""
    p = os.path.join(a.data, fname + ".csv")
    d = pd.read_csv(p)
    f = d[key].map(grp).map(factors) if key == "TECHNOLOGY" else pd.Series(factors["*"], index=d.index)
    f = f.fillna(1.0)
    mask = (d.YEAR >= a.from_year) & (f != 1.0)
    d.loc[mask, "VALUE"] = d.loc[mask, "VALUE"] * f[mask]
    d.to_csv(p, index=False)
    log.append(f"{fname:20s} {label:34s} rows scaled: {int(mask.sum()):6d} of {len(d)}; techs {d.loc[mask, key].nunique()}")


if a.ct != 1:
    scale("CapitalCost", "TECHNOLOGY", {"grid_thermal": m["grid"], "interconnector": m["grid"], "renewable": m["ren"],
                                         **({"diesel": m["diesel_capex"]} if a.diesel else {})}, "grid / renewable (/ diesel) CAPEX")
    scale("CapitalCostStorage", "STORAGE", {"*": m["ren"]}, "storage CAPEX (renewable multiplier)")
    if a.diesel:
        scale("FixedCost", "TECHNOLOGY", {"diesel": m["diesel_opex"]}, "diesel plant fixed O&M")
        scale("VariableCost", "TECHNOLOGY", {"diesel": m["diesel_opex"], "diesel_fuel": m["diesel_opex"]},
              "diesel plant variable O&M + fuel price")
else:
    log.append("CT1: nothing to scale")
with open(os.path.join(a.data, "_ct_log.txt"), "w") as fh:
    fh.write("\n".join(log) + "\n")
print("\n".join(log))
