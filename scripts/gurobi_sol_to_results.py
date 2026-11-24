"""Convert a Gurobi .sol file of the AETOS/OSeMOSYS model into TEMBA-GEP style result tables.

Replaces the CPLEX chain of TEMBA-GEP / AETOS (sed zeros -> transform_31072013.py -> sort -> cplextocbc.py ->
generate_results.py). Gurobi writes plain "name value" lines, e.g.  TotalCapacityAnnual(REGION1,NGNGCCPN1,2030) 1.25

Output follows what generate_results.py produces: one CSV per variable, long format, short index names
(r = region, t = technology, l = timeslice, m = mode, e = emission, f = fuel, y = year) and the value column
named after the variable (NewCapacity.csv -> columns r,t,y,NewCapacity). Zero (and |value| < tol) rows are dropped.

The AETOS "fast" model does not declare ProductionByTechnologyAnnual, UseByTechnologyAnnual or
AnnualTechnologyEmission, which TEMBA's lcoe_and_emissions.py reads, so with --data they are derived:
    Production(r,t,f,y) = sum_m ActivityByMode(r,t,m,y) * OutputActivityRatio(r,t,f,m,y)
    Use(r,t,f,y)        = sum_m ActivityByMode(r,t,m,y) * InputActivityRatio(r,t,f,m,y)
    TechEmission(r,t,e,y) = sum_m ActivityByMode(r,t,m,y) * EmissionActivityRatio(r,t,e,m,y)
(OSeMOSYS definitions; the ratios are time-slice independent in this model.)

    python gurobi_sol_to_results.py <model.sol> <out dir> [--data <otoole CSV dir>] [--tol 1e-9]
                                    [--also RateOfActivity] [--all-variables]
"""
import argparse
import os

import pandas as pd

RENAME = {"REGION": "r", "TECHNOLOGY": "t", "TIMESLICE": "l", "MODE_OF_OPERATION": "m",
          "EMISSION": "e", "FUEL": "f", "YEAR": "y"}

VARIABLES = {
    "NewCapacity": ["r", "t", "y"],
    "TotalCapacityAnnual": ["r", "t", "y"],
    "TotalTechnologyAnnualActivity": ["r", "t", "y"],
    "TotalAnnualTechnologyActivityByMode": ["r", "t", "m", "y"],
    "CapitalInvestment": ["r", "t", "y"],
    "SalvageValue": ["r", "t", "y"],
    "AnnualVariableOperatingCost": ["r", "t", "y"],
    "AnnualFixedOperatingCost": ["r", "t", "y"],
    "DiscountedTechnologyEmissionsPenalty": ["r", "t", "y"],
    "AnnualEmissions": ["r", "e", "y"],
    "RateOfActivity": ["r", "l", "t", "m", "y"],
}
SKIP_BY_DEFAULT = {"RateOfActivity"}   # ~8 M rows
DERIVED = {  # name: (ratio file, key column)
    "ProductionByTechnologyAnnual": ("OutputActivityRatio.csv", "f"),
    "UseByTechnologyAnnual": ("InputActivityRatio.csv", "f"),
    "AnnualTechnologyEmission": ("EmissionActivityRatio.csv", "e"),
}


def _write(df, name, out, tol):
    df = df[df[name].abs() > tol]
    df.to_csv(os.path.join(out, name + ".csv"), index=False)
    print(f"{name}: {len(df)} rows")


def _typed(df):
    for c in ("y", "m"):
        if c in df.columns:
            df[c] = df[c].astype(int)
    return df


def main(sol, out, data=None, tol=1e-9, also=(), all_variables=False):
    os.makedirs(out, exist_ok=True)
    df = pd.read_csv(sol, sep=" ", comment="#", header=None, names=["name", "VALUE"],
                     dtype={"name": str, "VALUE": float})
    parts = df["name"].str.extract(r"^([A-Za-z0-9_]+)\((.*)\)$")
    df["var"], df["args"] = parts[0], parts[1]
    wanted = (set(VARIABLES) - SKIP_BY_DEFAULT) | set(also)
    present = set(df["var"].dropna().unique())
    keep = present if all_variables else wanted & present

    frames = {}
    for v in sorted(keep):
        sub = df[df["var"] == v]
        idx = sub["args"].str.split(",", expand=True)
        cols = VARIABLES.get(v)
        if cols is None or len(cols) != idx.shape[1]:
            cols = [f"i{i}" for i in range(idx.shape[1])]
        idx.columns = cols
        res = _typed(pd.concat([idx, sub["VALUE"].rename(v)], axis=1))
        frames[v] = res
        _write(res, v, out, tol)

    missing = sorted(wanted - present)
    if data:
        act = frames.get("TotalAnnualTechnologyActivityByMode")
        if act is None:
            missing.append("(derived tables need TotalAnnualTechnologyActivityByMode)")
        else:
            for name, (fname, key) in DERIVED.items():
                ratio = pd.read_csv(os.path.join(data, fname)).rename(columns=RENAME)
                ratio = _typed(ratio).rename(columns={"VALUE": "ratio"})
                m = act.merge(ratio, on=["r", "t", "m", "y"])
                m[name] = m["TotalAnnualTechnologyActivityByMode"] * m["ratio"]
                res = m.groupby(["r", "t", key, "y"], as_index=False)[name].sum()
                _write(res, name, out, tol)
    with open(os.path.join(out, "_missing.txt"), "w") as fh:
        fh.write("\n".join(missing))
    if missing:
        print("not in solution:", ", ".join(missing))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("sol")
    ap.add_argument("out")
    ap.add_argument("--data", default=None, help="otoole CSV folder (needed for the derived tables)")
    ap.add_argument("--tol", type=float, default=1e-9)
    ap.add_argument("--also", nargs="*", default=[])
    ap.add_argument("--all-variables", action="store_true")
    a = ap.parse_args()
    main(a.sol, a.out, a.data, a.tol, a.also, a.all_variables)
