"""Electrification-technology map of one OnSSET run-2 scenario + the slim settlement CSV for QGIS.

Reads the (1.4 GB) run-2 result CSV once, writes
  <out>/<tag>_settlements.csv   id, coordinates, population and, per step year, FinalElecCode, Technology and the least-cost
                                code column (MinimumOverallCode, the field style.qml in the QGIS folder is categorised on),
                                so it can be joined to <Country>_final_clusters.shp on `id` in QGIS
  <out>/<tag>_<year>.png        one map per year (2025 = starting point, then the step years). Colours = style.qml, plus grey for
                                settlements still unelectrified (FinalElecCode 99). Mini-grids are drawn last with a black outline.
By default settlements are points (X_deg, Y_deg); with --clusters <shapefile> the cluster POLYGONS are drawn (slow: ~700k polygons;
the shapefile is joined on `id`, only the id column is read).

Settlements are very unequal in size: small ones are numerous, large ones few. Stand-alone PV is many settlements but few
people. The legend therefore shows settlements AND people (ElecPop of the year; 2025: population of grid-connected settlements).

    python scripts/plot_map.py --results runs/run2/low_ct1/NGA/results_ct1/ng-1-1_1_0_0_1_0.csv \
        --boundary "path/to/NGA_boundaries.geojson" \
        --clusters "path/to/clusters/Nigeria_final_clusters.shp" \
        --out runs/maps --tag NGA_low_t0_ct1 --title "Nigeria, residential only, no carbon price, CT1"
Run in the onsset_gep environment (geopandas, matplotlib).
"""
import argparse
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# OnSSET FinalElecCode -> (label, colour, point size, outline width); colours from the QGIS style (style.qml)
TECH = {99: ("Not yet electrified", "#707070", 0.5, 0), 1: ("Existing grid (incl. densification)", "#8f94ec", 0.5, 0),
        2: ("Grid extension", "#1a1fb0", 0.8, 0), 3: ("Stand-alone PV", "#ffc700", 0.5, 0),
        5: ("Mini-grid PV hybrid", "#e628a0", 7, 0.5), 6: ("Mini-grid wind hybrid", "#1b8f4d", 7, 0.5),
        7: ("Mini-grid hydro", "#28e66d", 7, 0.5)}      # point size / outline: raise them in a country with few mini-grids
DRAW_ORDER = [1, 2, 3, 99, 6, 7, 5]          # bottom -> top: unelectrified above stand-alone PV, mini-grids last
LEGEND_ORDER = [99, 1, 2, 3, 6, 7, 5]
# outline (pt, in the fill colour) of the RURAL polygons per technology, so that small cells keep their colour; urban cells have none
OUTLINE = {99: 0.5, 1: 0.5, 2: 0.5, 3: 0.15, 5: 0.6, 6: 0.6, 7: 1.5}      # mini-grid hydro: very few cells, thicker
BACKGROUND = "#f8f8f8"


def draw_map(ax, df, poly, bnd, y):
    """Draw one year of one scenario on `ax`; returns {FinalElecCode: (settlements, people)} of the technologies present."""
    code = df[f"FinalElecCode{y}"].fillna(99).astype(int)
    # 2025 has no grid-extension step: its electrified settlements are the existing grid; people column differs
    people = df["ElecPop2025"] if y == 2025 else df[f"ElecPop{y}"]
    info = {}
    if bnd is not None:
        bnd.plot(ax=ax, color=BACKGROUND, edgecolor="none", linewidth=0, zorder=0)       # very light grey country, no border
    for k in DRAW_ORDER:
        lab, col, size, lw = TECH[k]
        m = code == k
        if not m.any():
            continue
        ppl = people[m].sum() if k != 99 else df.loc[m, f"Pop{y}"].sum()     # unelectrified: their population, not ElecPop
        info[k] = (int(m.sum()), float(ppl / 1e6))
        if poly is not None:
            sub = poly[poly["id"].isin(df.loc[m, "id"])]
            if k in (5, 6, 7):                                   # mini-grids: all cells outlined, drawn last
                sub.plot(ax=ax, color=col, edgecolor=col, linewidth=OUTLINE[k], zorder=4)
            else:                                                # rural cells outlined, urban cells not
                zo = 3 if k == 99 else 2
                rural = sub["IsUrban"].fillna(0) == 0
                if (~rural).any():
                    sub[~rural].plot(ax=ax, color=col, edgecolor="none", linewidth=0, zorder=zo)
                if rural.any():
                    sub[rural].plot(ax=ax, color=col, edgecolor=col, linewidth=OUTLINE[k], zorder=zo)
        else:
            ax.scatter(df.X_deg[m], df.Y_deg[m], s=size, c=col, edgecolors=col if lw else "none", linewidths=lw, zorder=3 if lw else 2)
    ax.set_aspect("equal")
    ax.axis("off")
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--boundary", default=None)
    ap.add_argument("--clusters", default=None, help="cluster polygons (shapefile); default = <--clusters-dir>/<--country>_final_clusters.shp")
    ap.add_argument("--clusters-dir", default=os.environ.get("MAP_CLUSTERS_DIR", ""), help="folder with <Country>_final_clusters.shp (a local copy is faster than a synced drive)")
    ap.add_argument("--country", default=None, help="Nigeria / Zambia: picks the default cluster shapefile")
    ap.add_argument("--points", action="store_true", help="draw settlement points (X_deg, Y_deg) instead of the cluster polygons")
    ap.add_argument("--out", default="runs/maps")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--title", default="")
    ap.add_argument("--years", nargs="+", type=int, default=[2025, 2030, 2035, 2040])
    ap.add_argument("--no-plot", action="store_true", help="only write the CSV")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    slim = os.path.join(a.out, f"{a.tag}_settlements.csv")
    need = ["id", "X_deg", "Y_deg", "IsUrban", "Pop2025", "ElecPop2025", "FinalElecCode2025"]
    for y in a.years:
        need += [f"FinalElecCode{y}", f"Technology{y}", f"MinimumOverallCode{y}", f"ElecPop{y}", f"Pop{y}", f"EnergyPerSettlement{y}",
                 f"NewConnections{y}"]
    df = None
    if os.path.exists(slim) and os.path.getmtime(slim) > os.path.getmtime(a.results):
        df = pd.read_csv(slim)                       # already extracted: skip the 1.4 GB file
        if not all(f"FinalElecCode{y}" in df for y in a.years) or "ElecPop2025" not in df:
            df = None
    if df is None:
        head = pd.read_csv(a.results, nrows=0).columns
        df = pd.read_csv(a.results, usecols=[c for c in need if c in head])
        df.to_csv(slim, index=False)
    print(f"{len(df)} settlements -> {a.tag}_settlements.csv", flush=True)
    if a.no_plot:
        return

    import geopandas as gpd
    bnd = gpd.read_file(a.boundary) if a.boundary else None
    poly = None
    if not a.points and not a.clusters and a.country:
        a.clusters = f"{a.clusters_dir}/{a.country}_final_clusters.shp"
    if a.clusters and not a.points:
        poly = gpd.read_file(a.clusters, columns=["id"])
        poly = poly.merge(df[["id", "IsUrban"] + [c for c in df if c.startswith("FinalElecCode")]], on="id", how="left")
        print(f"{len(poly)} cluster polygons ({poly.geometry.geom_type.iloc[0]}), joined", flush=True)
    for y in a.years:
        fig, ax = plt.subplots(figsize=(7, 7))
        info = draw_map(ax, df, poly, bnd, y)
        handles = {k: ax.scatter([], [], c=TECH[k][1], s=30, label=f"{TECH[k][0]}: {n:,} settlements, {p:.1f} M people")
                   for k, (n, p) in info.items()}
        ax.set_title(f"{a.title}\n{y}", fontsize=10, loc="left")
        leg = ax.legend(handles=[handles[k] for k in LEGEND_ORDER if k in handles], fontsize=7, frameon=False, loc="upper center", bbox_to_anchor=(0.5, 0.02), ncol=1)
        for h in leg.legend_handles:
            h.set_sizes([30])
        fig.tight_layout()
        fig.savefig(os.path.join(a.out, f"{a.tag}_{y}.png"), dpi=220)
        plt.close(fig)
        print(y, {TECH[k][0]: (v[0], round(v[1], 1)) for k, v in info.items()}, flush=True)


if __name__ == "__main__":
    main()
