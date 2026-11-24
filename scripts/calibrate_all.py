"""Calibrate onsset-1 for many countries with adjustable thresholds and report modelled vs actual access.

Mirrors `onsset.runner.calibration` (population/urban calibration, grid-electrification calibration, mini-grid step) but
exposes the calibration thresholds and writes ratios (not populations) to the specs, and a comparison table.

    python calibrate_all.py [--countries all | ZMB NGA ...] [--work-dir onsset/runs] [--report onsset/calibration_report.csv]
                            [--min-ntl 0.05] [--min-pop 100] [--max-mv-dist 3] [--max-transformer-dist 2] [--buffer]
                            [--workers 4] [--onsset-repo <onsset-1 folder>]

Outputs per country: <work-dir>/<ISO3>/calibration/<cc>-1-specs-calib.xlsx and <ISO3>_calibrated.csv (the files
run_onsset1.py reuses). Run with the `onsset_empg_25` environment. Compare settings by using a different --work-dir/--report.
"""
import argparse
import os
import sys
from concurrent.futures import ProcessPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ONSSET1_REPO = os.environ.get("ONSSET1_REPO", "")   # folder containing the onsset package (onsset-1 repo); set by the Snakefile from config.yaml


def calibrate_one(job):
    iso3, cc, a = job
    import pandas as pd
    if a["onsset_repo"]:
        sys.path.insert(0, a["onsset_repo"])
    import onsset as O
    from onsset.specs import (SPE_ELEC, SPE_ELEC_MODELLED, SPE_ELEC_RURAL, SPE_ELEC_URBAN, SPE_POP, SPE_START_YEAR,
                              SPE_URBAN, SPE_URBAN_MODELLED, SPE_COST_NON_SUPLIED_ENERGY)

    specs = os.path.join(a["specs_dir"], f"{cc}-1-specs.xlsx")
    clusters = os.path.join(a["clusters_dir"], f"{iso3}_gis_inputs_updated.gz")
    cal_dir = os.path.join(a["work_dir"], iso3, "calibration")
    os.makedirs(cal_dir, exist_ok=True)
    specs_cal = os.path.join(cal_dir, f"{cc}-1-specs-calib.xlsx")
    csv_cal = os.path.join(cal_dir, f"{iso3}_calibrated.csv")

    # prepared cluster copy: MGDist = 9999 (no existing mini-grids; baseline has no off-grid supply)
    prepared = os.path.join(cal_dir, f"{iso3}_clusters_in.csv.gz")
    cl = pd.read_csv(clusters)
    if "MGDist" not in cl.columns:
        cl["MGDist"] = 9999.0
    cl.to_csv(prepared, index=False)

    sheets = pd.read_excel(specs, sheet_name=None)
    sd = pd.read_excel(specs, sheet_name="SpecsData")
    sp = O.SettlementProcessor(prepared)
    sp.conditioning()
    sp.condition_df()
    sp.df[O.SET_GRID_PENALTY] = 1
    sp.df[O.SET_WINDCF] = sp.calc_wind_cfs(sp.df[O.SET_WINDVEL])

    start_year = int(sd.loc[0, SPE_START_YEAR])
    elec, elec_u, elec_r = sd.loc[0, SPE_ELEC], sd.loc[0, SPE_ELEC_URBAN], sd.loc[0, SPE_ELEC_RURAL]
    pop_mod, urban_mod = sp.calibrate_current_pop_and_urban(sd.loc[0, SPE_POP], sd.loc[0, SPE_URBAN])
    sd.loc[0, SPE_URBAN_MODELLED] = urban_mod
    if a.get("method", "threshold") == "rank":
        res = sp.calibrate_grid_elec_current_rank(elec, elec_u, elec_r, start_year,
                                                  weights=tuple(a.get("weights", (2, 1, 1))),
                                                  max_dist=a.get("max_dist"))
    else:
        res = sp.calibrate_grid_elec_current(elec, elec_u, elec_r, start_year,
                                             min_night_lights=a["min_ntl"], min_pop=a["min_pop"],
                                             max_transformer_dist=a["max_transformer_dist"], max_mv_dist=a["max_mv_dist"],
                                             buffer=a["buffer"])
    mg = sp.mg_elec_current(start_year)

    df = sp.df
    pop = df[O.SET_POP_CALIB]
    ep = df[O.SET_ELEC_POP_CALIB].where(df[O.SET_ELEC_CURRENT] == 1, 0)
    urb = df[O.SET_URBAN] > 1
    m_tot, m_u, m_r = ep.sum() / pop.sum(), ep[urb].sum() / pop[urb].sum(), ep[~urb].sum() / pop[~urb].sum()

    sd.loc[0, SPE_ELEC_MODELLED] = m_tot
    sd.loc[0, "rural_elec_ratio_modelled"] = m_r
    sd.loc[0, "urban_elec_ratio_modelled"] = m_u
    sd["grid_distance_used"] = res[3]
    sd["ntl_limit"] = res[4]
    sd["pop_limit"] = res[5]
    sd["Buffer_used"] = res[6]
    sd["buffer_distance"] = res[7]
    sd["mg_pop_electrified"] = mg
    sd[SPE_COST_NON_SUPLIED_ENERGY] = 0
    with pd.ExcelWriter(specs_cal, engine="openpyxl") as w:
        for name, d in sheets.items():
            d.to_excel(w, sheet_name=name, index=False)
        sd.to_excel(w, sheet_name="SpecsDataCalib", index=False)
    df.to_csv(csv_cal, index=False)
    return dict(iso3=iso3, elec_actual=elec, elec_model=round(m_tot, 3), urban_actual=elec_u, urban_model=round(m_u, 3),
                rural_actual=elec_r, rural_model=round(m_r, 3), urban_ratio_actual=sd.loc[0, SPE_URBAN],
                urban_ratio_model=round(urban_mod, 3), grid_dist_used=res[3], min_ntl=a["min_ntl"],
                min_pop=a["min_pop"], buffer=a["buffer"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--countries", nargs="+", default=["all"])
    ap.add_argument("--specs-dir", default=os.path.join(ROOT, "onsset", "specs_onsset1"))
    ap.add_argument("--clusters-dir", default=os.path.join(ROOT, "onsset", "clusters"))
    ap.add_argument("--work-dir", default=os.path.join(ROOT, "onsset", "runs"))
    ap.add_argument("--iso-codes", default=os.path.join(ROOT, "onsset", "iso_codes.csv"))
    ap.add_argument("--report", default=os.path.join(ROOT, "onsset", "calibration_report.csv"))
    ap.add_argument("--min-ntl", type=float, default=0.05)
    ap.add_argument("--min-pop", type=float, default=100)
    ap.add_argument("--max-mv-dist", type=float, default=3)
    ap.add_argument("--max-transformer-dist", type=float, default=2)
    ap.add_argument("--buffer", action="store_true", help="extend the grid distance in 0.1 km steps until access matches")
    ap.add_argument("--method", choices=["threshold", "rank"], default="threshold",
                    help="threshold = OnSSET's original; rank = per urban/rural class ranking (calibrate_grid_elec_current_rank)")
    ap.add_argument("--weights", type=float, nargs=3, default=[2, 1, 1], metavar=("DIST", "NTL", "POP"),
                    help="rank method score weights (onstove: infrastructure 2, night lights 1, population 1)")
    ap.add_argument("--max-dist", type=float, default=None, help="rank method: km beyond which a cell cannot be grid-electrified")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--onsset-repo", default=ONSSET1_REPO)
    args = ap.parse_args()

    import pandas as pd
    iso = pd.read_csv(args.iso_codes, keep_default_na=False).set_index("Alpha-3")["Alpha-2"]
    if args.countries == ["all"]:
        have = [f.split("-")[0] for f in os.listdir(args.specs_dir) if f.endswith("-1-specs.xlsx")]
        countries = [c for c in iso.index if iso[c].lower() in have]
    else:
        countries = args.countries
    a = dict(vars(args))
    jobs = [(c, iso[c].lower(), a) for c in countries]
    print(f"calibrating {len(jobs)} countries with {args.workers} worker(s)")
    rows = []
    if args.workers > 1:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            for r in ex.map(calibrate_one, jobs):
                rows.append(r)
                print(r["iso3"], r["elec_actual"], "->", r["elec_model"], flush=True)
    else:
        for j in jobs:
            r = calibrate_one(j)
            rows.append(r)
            print(r["iso3"], r["elec_actual"], "->", r["elec_model"], flush=True)
    rep = pd.DataFrame(rows)
    rep["gap_total"] = rep.elec_model - rep.elec_actual
    rep["gap_rural"] = rep.rural_model - rep.rural_actual
    rep["gap_urban"] = rep.urban_model - rep.urban_actual
    rep.to_csv(args.report, index=False)
    pd.set_option("display.width", 200)
    print(rep[["iso3", "elec_actual", "elec_model", "urban_actual", "urban_model", "rural_actual", "rural_model"]]
          .to_string(index=False))
    print("mean gap total %.3f | urban %.3f | rural %.3f ; countries with rural gap < -0.10: %d / %d" % (
        rep.gap_total.mean(), rep.gap_urban.mean(), rep.gap_rural.mean(), (rep.gap_rural < -0.10).sum(), len(rep)))
    print("report:", args.report)


if __name__ == "__main__":
    main()
