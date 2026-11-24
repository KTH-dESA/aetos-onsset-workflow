"""Write AETOS-derived grid parameters into the ScenarioParameters sheet of each country's specs workbook.

Reads metrics_period.csv (aetos_metrics.py) and sets, on every row of ScenarioParameters (rows are the
tier/demand levels: the runner reads these columns with scenario_parameters[col][tier_index]):
    GridGenerationCost, GridEmissionFactor, GridCapacityInvestmentCost, GridRenShare   (no carbon tax)
    the same four with the suffix _CT                                                    (carbon tax)
Mapping: GridGenerationCost <- LCOE incl. imports, GridEmissionFactor <- g/kWh incl. imports,
         GridCapacityInvestmentCost <- USD/kW, GridRenShare <- share incl. imports.
Duplicate header: GEP specs have two `GridGenerationCost` columns and pandas reads the FIRST one (the runner too).
The first is overwritten with the seed; the other is renamed `GridGenerationCost_gep2023` (kept for reference).
Countries without metrics (e.g. Madagascar) keep their specs unchanged.

    python scripts/write_grid_seeds.py --metrics data/metrics/unnz_africa_all/metrics_period.csv --specs onsset/specs
                                       [--metrics-ct <metrics_period.csv with carbon tax>] [--dry-run]
"""
import argparse
import os

import openpyxl
import pandas as pd

MAP = {"GridGenerationCost": "GridGenerationCost", "GridEmissionFactor": "GridEmissionFactor",
       "GridCapacityInvestmentCost": "GridCapacityInvestmentCost", "GridRenShare": "GridRenShare",
       "GridRenShareEnergy": "ren_share_grid_energy"}   # GridRenShare = capacity-based, ...Energy = generation-based incl. imports

ap = argparse.ArgumentParser()
ap.add_argument("--metrics", required=True)
ap.add_argument("--metrics-ct", default=None, help="defaults to --metrics (placeholder until carbon-tax runs exist)")
ap.add_argument("--specs", required=True)
ap.add_argument("--suffix", default="-1-specs.xlsx",
                help="which workbooks to write: -1-specs.xlsx = the onsset-1 specs made by refresh_specs.py (default; "
                     "rerun this script AFTER refresh_specs.py, which resets the seeds); -3-specs.xlsx = staged GEP books")
ap.add_argument("--years", nargs="+", type=int, default=[2030, 2035, 2040],
                help="model years that get their own GridEmissionFactor<year>, GridRenShare<year>, GridRenShareEnergy<year>")
ap.add_argument("--step-metrics", nargs="*", default=[], metavar="YEAR=metrics_period.csv",
                help="per-step LCOE and capacity cost: aetos_metrics.py run with the window 2025..YEAR, e.g. "
                     "2030=data/metrics/pn_w2030/metrics_period.csv 2035=... 2040=... -> GridGenerationCost<YEAR>, "
                     "GridCapacityInvestmentCost<YEAR>")
ap.add_argument("--step-metrics-ct", nargs="*", default=None, help="same for the carbon-tax runs (default: --step-metrics)")
ap.add_argument("--half-window", type=int, default=2,
                help="per-year values are averages over year-H..year+H of the AETOS yearly metrics (2 = five-year window)")
ap.add_argument("--dry-run", action="store_true")
ap.add_argument("--log", default="onsset/grid_seeds_log.csv")
a = ap.parse_args()

read = lambda p: pd.read_csv(p, keep_default_na=False).set_index("country")
m, mct = read(a.metrics), read(a.metrics_ct or a.metrics)
def yfile(p):
    t = pd.read_csv(os.path.join(os.path.dirname(p), "metrics_yearly.csv"), keep_default_na=False)
    for c in t.columns.drop("country"):
        t[c] = pd.to_numeric(t[c], errors="coerce").fillna(0.0)
    return t
yr, yrct = yfile(a.metrics), yfile(a.metrics_ct or a.metrics)
def smooth(src, c, y, col):
    """Centred window y-half..y+half (clipped to the years AETOS has), weighted so that the result is a proper average:
    EF and the energy share by energy supplied (generation + imports), the capacity share as sum(renewable)/sum(total)."""
    w = src[(src.country == c) & (src.y >= y - a.half_window) & (src.y <= y + a.half_window)]
    supplied = w.gen_GWh + w.imports_GWh
    if col == "ren_share_cap":
        return float(w.ren_cap_GW.sum() / w.cap_GW.sum())
    return float((w[col] * supplied).sum() / supplied.sum())


steps = lambda L: {int(x.split("=")[0]): read(x.split("=", 1)[1]) for x in L}
st, stct = steps(a.step_metrics), steps(a.step_metrics_ct if a.step_metrics_ct is not None else a.step_metrics)
log = []
for f in sorted(os.listdir(a.specs)):
    if not f.endswith(a.suffix):
        continue
    cc = f.split("-")[0].upper()
    if cc not in m.index or cc not in mct.index:
        log.append((cc, "no metrics: unchanged"))
        continue
    path = os.path.join(a.specs, f)
    wb = openpyxl.load_workbook(path)
    ws = wb["ScenarioParameters"]
    heads = {}
    for c in range(1, ws.max_column + 1):
        heads.setdefault(ws.cell(1, c).value, []).append(c)
    for dup in heads.get("GridGenerationCost", [])[1:]:
        ws.cell(1, dup).value = "GridGenerationCost_gep2023"
    for suffix, src in (("", m), ("_CT", mct)):
        for name, col in MAP.items():
            header = name + suffix
            cols = heads.get(header)
            if not cols:
                ws.cell(1, ws.max_column + 1).value = header
                cols = [ws.max_column]
            for r in range(2, ws.max_row + 1):
                if ws.cell(r, 1).value is None and all(ws.cell(r, c).value is None for c in range(1, 6)):
                    continue
                ws.cell(r, cols[0]).value = float(src.loc[cc, col])
    # per-year values (time-step specific), read by the runner as <name><year>[_CT]; fall back to the seed if absent
    for suffix, src in (("", yr), ("_CT", yrct)):
        for y in a.years:
            vals = {"GridEmissionFactor": "EF_grid_gCO2_kWh", "GridRenShare": "ren_share_cap",
                    "GridRenShareEnergy": "ren_share_grid"}
            for name, col in vals.items():
                header = f"{name}{y}{suffix}"
                cols = heads.get(header)
                if not cols:
                    ws.cell(1, ws.max_column + 1).value = header
                    cols = [ws.max_column]
                    heads[header] = cols
                v = smooth(src, cc[:2], y, col)
                for r in range(2, ws.max_row + 1):
                    if ws.cell(r, 1).value is None and all(ws.cell(r, c).value is None for c in range(1, 6)):
                        continue
                    ws.cell(r, cols[0]).value = v
    for suffix, src in (("", st), ("_CT", stct)):
        for y, tab in src.items():
            for name in ("GridGenerationCost", "GridCapacityInvestmentCost"):
                header = f"{name}{y}{suffix}"
                cols = heads.get(header)
                if not cols:
                    ws.cell(1, ws.max_column + 1).value = header
                    cols = [ws.max_column]
                    heads[header] = cols
                for r in range(2, ws.max_row + 1):
                    if ws.cell(r, 1).value is None and all(ws.cell(r, c).value is None for c in range(1, 6)):
                        continue
                    ws.cell(r, cols[0]).value = float(tab.loc[cc, name])
    if not a.dry_run:
        wb.save(path)
    log.append((cc, f"written: cost {m.loc[cc,'GridGenerationCost']:.3f}, EF {m.loc[cc,'GridEmissionFactor']:.0f}, "
                    f"capex {m.loc[cc,'GridCapacityInvestmentCost']:.0f}, ren {m.loc[cc,'GridRenShare']:.2f}"))
pd.DataFrame(log, columns=["country", "result"]).to_csv(a.log, index=False)
print("\n".join(f"{c}: {r}" for c, r in log))
