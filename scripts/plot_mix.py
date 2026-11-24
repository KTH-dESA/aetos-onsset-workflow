"""Installed-capacity and generation-mix bar charts (stacked columns by year) for the study countries, one set per AETOS run.

Same layout and technology colours as TEMBA_GEP/scripts/graphs.py (Installed capacity, Electricity generation), drawn with matplotlib.
Capacity: TotalCapacityAnnual (GW) of the generation categories + storage (+ interconnector is left out; supply, T&D and
backstop technologies are not capacity of the power system). Generation: generation_mix.csv (GWh) + net imports from metrics_yearly.csv.
Every chart also lands as a CSV (the numbers behind the bars).

    python scripts/plot_mix.py [--runs runs] [--out runs/figures] [--countries NG ZM] [--years 2025 2040]
"""
import argparse
import glob
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

NAMES = {}      # optional pretty names {AETOS 2-letter code: name} for the titles; default = the code itself
LEVEL = {"low": "Low demand", "high": "High demand"}
TAX = {"t0": "without carbon tax", "t1": "with carbon tax"}
CT = {"ct1": "cost trajectory 1", "ct2": "cost trajectory 2", "ct3": "cost trajectory 3"}
# colours of TEMBA_GEP graphs.py; the order is the stacking order (bottom -> top)
COL = {"Coal": "#323232", "Oil": "#9e9e9e", "Gas": "#dc143c", "Nuclear": "#add8e6", "Biomass": "#2e8b57", "Geothermal": "#800080",
       "Hydro": "#00ced1", "Wind": "#bc8f8f", "Solar PV": "#ffa500", "Solar CSP": "#ffd27f", "Storage": "#6a5acd", "Imports": "#d9d9d9",
       "Stand-alone PV (off-grid electrification)": "#ffe680", "Mini-grid PV hybrid (off-grid electrification)": "#e628a0",
       "Mini-grid wind hybrid (off-grid electrification)": "#1b8f4d", "Mini-grid hydro (off-grid electrification)": "#28e66d"}   # off-grid, only with --offgrid


def bars(df, ycol, ylabel, title, path):
    wide = df.pivot_table(index="y", columns="cat", values=ycol, aggfunc="sum").reindex(columns=[c for c in COL if c in df.cat.unique()])
    wide = wide.loc[:, wide.abs().sum() > 1e-6 * wide.abs().sum().sum()]          # drop empty categories
    fig, ax = plt.subplots(figsize=(7, 4))
    wide.plot.bar(stacked=True, ax=ax, color=[COL[c] for c in wide.columns], width=0.85, edgecolor="none")
    ax.set_xlabel("Year")
    ax.set_ylabel(ylabel)
    ax.set_title(title, fontsize=10, loc="left")
    ax.legend(fontsize=7, ncol=3, frameon=False, bbox_to_anchor=(0.5, -0.24), loc="upper center")
    ax.spines[["top", "right"]].set_visible(False)
    ax.yaxis.grid(True, color="#d0d0d0", linewidth=0.6)
    ax.set_axisbelow(True)
    plt.xticks(rotation=90, fontsize=8)
    ax.set_xlabel("Year", labelpad=2)
    fig.tight_layout()
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return wide


def _iso3():
    """AETOS 2-letter country code -> ISO3, from onsset/iso_codes.csv"""
    d = pd.read_csv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "onsset", "iso_codes.csv"), keep_default_na=False)
    return dict(zip(d["Alpha-2"], d["Alpha-3"]))


ISO3 = _iso3()


def offgrid(folder, cc, dem, tax, ct, y0, y1):
    """(capacity GW, energy TWh) tables with columns y, cat, value for the two off-grid categories."""
    ol = pd.read_csv(os.path.join(folder, "onsset_long.csv"))
    ex = pd.read_csv(os.path.join(folder, "onsset_extras.csv"))
    ol = ol[(ol.iso == ISO3[cc]) & (ol.dem == dem) & (ol.tax == tax) & (ol.ct == ct)].set_index("step")
    ex = ex[(ex.iso == ISO3[cc]) & (ex.dem == dem) & (ex.tax == tax) & (ex.ct == ct)]
    steps = [2030, 2035, 2040]
    cap = {"Stand-alone PV (off-grid electrification)": ol.Capacity_sa_pv, "Mini-grid PV hybrid (off-grid electrification)": ol.Capacity_mg_pv,
           "Mini-grid wind hybrid (off-grid electrification)": ol.Capacity_mg_wind, "Mini-grid hydro (off-grid electrification)": ol.Capacity_mg_hydro}
    codes = {"Stand-alone PV (off-grid electrification)": 3, "Mini-grid PV hybrid (off-grid electrification)": 5, "Mini-grid wind hybrid (off-grid electrification)": 6, "Mini-grid hydro (off-grid electrification)": 7}
    en = {k: ex[ex.code == c].groupby("step").energy_kWh.sum() for k, c in codes.items()}
    out = []
    for cat in cap:
        for tab, ser, div in ((0, cap[cat], 1e6), (1, en[cat], 1e9)):             # kW -> GW, kWh -> TWh
            cum = [0.0] + list(ser.loc[steps].fillna(0).cumsum() / div)
            for y in range(y0, y1 + 1):
                out.append(dict(tab=tab, y=y, cat=cat, value=float(np.interp(y, [2025] + steps, cum))))
    o = pd.DataFrame(out)
    return o[o.tab == 0].drop(columns="tab"), o[o.tab == 1].drop(columns="tab")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="runs")
    ap.add_argument("--out", default="runs/figures")
    ap.add_argument("--countries", nargs="+", default=["NG", "ZM"], help="AETOS 2-letter codes")
    ap.add_argument("--names", nargs="*", default=[], help="optional CODE=Name pairs for the titles, e.g. NG=Nigeria ZM=Zambia")
    ap.add_argument("--offgrid", default=None, help="folder with onsset_long.csv + onsset_extras.csv: adds the "
                    "OnSSET stand-alone PV and mini-grids on top; the bars are cumulative new off-grid capacity / energy of the matching "
                    "OnSSET run-2 scenario, linear from 0 in 2025 through the 2030/35/40 steps")
    ap.add_argument("--only", default=None, help="a single run folder name, e.g. low_t0_ct1")
    ap.add_argument("--years", nargs=2, type=int, default=[2025, 2040])
    a = ap.parse_args()
    y0, y1 = a.years
    NAMES.update(dict(n.split("=", 1) for n in a.names))
    for d in sorted(glob.glob(os.path.join(a.runs, a.only or "*_t?_ct?"))):
        run = os.path.basename(d)
        lvl, tax, ct = run.split("_")
        label = f"{LEVEL[lvl]}, {TAX[tax]}, {CT[ct]}"
        cats = pd.read_csv(os.path.join(d, "metrics", "tech_categories.csv"), keep_default_na=False)
        cap = pd.read_csv(os.path.join(d, "results", "TotalCapacityAnnual.csv")).merge(cats, on="t")
        cap = cap[cap.cat.isin(COL) & (cap.cat != "Imports")]
        gen = pd.read_csv(os.path.join(d, "metrics", "generation_mix.csv"), keep_default_na=False)
        imp = pd.read_csv(os.path.join(d, "metrics", "metrics_yearly.csv"), keep_default_na=False)[["country", "y", "imports_GWh"]]
        imp = imp.rename(columns={"imports_GWh": "GWh"}).assign(cat="Imports")
        gen = pd.concat([gen, imp[gen.columns]])
        for cc in a.countries:
            out = os.path.join(a.out, run)
            os.makedirs(out, exist_ok=True)
            c = cap[(cap.country == cc) & cap.y.between(y0, y1)].rename(columns={"TotalCapacityAnnual": "GW"})
            g = gen[(gen.country == cc) & gen.y.between(y0, y1)].copy()
            g["TWh"] = g.GWh / 1000
            if a.offgrid:
                oc, og = offgrid(a.offgrid, cc, lvl, int(tax[1]), int(ct[2]), y0, y1)
                c = pd.concat([c, oc.rename(columns={"value": "GW"})])
                g = pd.concat([g, og.rename(columns={"value": "TWh"})])
            wc = bars(c, "GW", "Installed capacity (GW)", f"Installed capacity - {NAMES.get(cc, cc)}\n{label}", os.path.join(out, f"{cc}_capacity.png"))
            wg = bars(g, "TWh", "Electricity generation (TWh)", f"Electricity generation - {NAMES.get(cc, cc)}\n{label}", os.path.join(out, f"{cc}_generation.png"))
            wc.round(4).to_csv(os.path.join(out, f"{cc}_capacity.csv"))
            wg.round(4).to_csv(os.path.join(out, f"{cc}_generation.csv"))
        print(run, "done", flush=True)


if __name__ == "__main__":
    main()
