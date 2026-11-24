"""Calibrate and run onsset-1 for one country (smoke test / building block for the Snakemake rule).

    python run_onsset1.py --iso3 ZMB [--ct 1] [--specs-dir onsset/specs_onsset1] [--work-dir onsset/runs]
                          [--recalibrate] [--onsset-repo <path to onsset-1>]

1. calibration (once; skipped if the calibrated files exist): cluster file + specs -> calibrated specs + CSV
2. scenarios in the specs' ScenarioInfo sheet, with the cost-trajectory multipliers of --ct.
Run it with the `onsset_empg_25` environment. Resource files are read from the IEA folder (read-only).
"""
import argparse
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ONSSET1_REPO = os.environ.get("ONSSET1_REPO", "")   # folder containing the onsset package (onsset-1 repo); set by the Snakefile from config.yaml
IEA = os.environ.get("ONSSET_RESOURCES_DIR", "")   # OnSSET resource files (Solar_Wind/, MV_lines/); set by the Snakefile from config.yaml
# multipliers: grid (T&D + connections), ren (PV/wind/hydro/batteries), diesel capex, diesel opex
CT = {1: dict(grid=1.0, ren=1.0, diesel_capex=1.0, diesel_opex=1.0),
      2: dict(grid=1.5, ren=0.5, diesel_capex=1.0, diesel_opex=1.3),
      3: dict(grid=2.0, ren=0.35, diesel_capex=1.2, diesel_opex=1.5)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iso3", required=True)
    ap.add_argument("--ct", type=int, default=1, choices=[1, 2, 3])
    ap.add_argument("--specs-dir", default=os.path.join(ROOT, "onsset", "specs_onsset1"))
    ap.add_argument("--clusters-dir", default=os.path.join(ROOT, "onsset", "clusters"))
    ap.add_argument("--work-dir", default=os.path.join(ROOT, "onsset", "runs"))
    ap.add_argument("--iso-codes", default=os.path.join(ROOT, "onsset", "iso_codes.csv"))
    ap.add_argument("--codes", nargs="*", default=None,
                    help="run only these ScenarioInfo codes (e.g. 1_1_0_0_1_0 2_0_0_0_1_0); default = all rows")
    ap.add_argument("--calib-work-dir", default=None,
                    help="folder whose <ISO3>/calibration holds the calibration (default = --work-dir); lets the final run "
                         "reuse run 1's calibration while writing its results elsewhere")
    ap.add_argument("--tag", default="run", help="name of this job's private copy of the calibrated workbook")
    ap.add_argument("--grid-cap-index", type=int, default=None,
                    help="override ScenarioInfo Grid_connection_cap for all scenarios (0 = row 0 of GridConnectionsLimitThousands = 9999, i.e. no cap)")
    ap.add_argument("--recalibrate", action="store_true")
    ap.add_argument("--min-ntl", type=float, default=0.05)
    ap.add_argument("--min-pop", type=float, default=100)
    ap.add_argument("--max-mv-dist", type=float, default=3)
    ap.add_argument("--buffer", action="store_true")
    ap.add_argument("--onsset-repo", default=ONSSET1_REPO, help="folder that contains the onsset package (onsset-1 repo)")
    a = ap.parse_args()
    if a.onsset_repo:
        sys.path.insert(0, a.onsset_repo)
    import pandas as pd
    from onsset import runner
    print("onsset-1 loaded from", sys.modules["onsset"].__file__)

    cc = pd.read_csv(a.iso_codes, keep_default_na=False).set_index("Alpha-3").loc[a.iso3, "Alpha-2"].lower()
    specs = os.path.join(a.specs_dir, f"{cc}-1-specs.xlsx")
    clusters = os.path.join(a.clusters_dir, f"{a.iso3}_gis_inputs_updated.gz")
    base = os.path.join(a.work_dir, a.iso3)
    cal_dir = os.path.join(a.calib_work_dir or a.work_dir, a.iso3, "calibration")     # calibration is shared, read-only here
    res_dir = os.path.join(base, f"results_ct{a.ct}")
    sum_dir = os.path.join(base, f"summaries_ct{a.ct}")
    for d in (cal_dir, res_dir, sum_dir):
        os.makedirs(d, exist_ok=True)
    specs_cal = os.path.join(cal_dir, f"{cc}-1-specs-calib.xlsx")
    csv_cal = os.path.join(cal_dir, f"{a.iso3}_calibrated.csv")

    t0 = time.time()
    if a.recalibrate or not (os.path.exists(specs_cal) and os.path.exists(csv_cal)):
        print("calibrating ... (use scripts/calibrate_all.py first to tune thresholds for all countries)")
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from calibrate_all import calibrate_one
        settings = dict(onsset_repo=a.onsset_repo, specs_dir=a.specs_dir, clusters_dir=a.clusters_dir, work_dir=a.work_dir,
                        min_ntl=a.min_ntl, min_pop=a.min_pop, max_mv_dist=a.max_mv_dist,
                        max_transformer_dist=2, buffer=a.buffer)
        print(calibrate_one((a.iso3, cc, settings)))
        print(f"calibration done in {time.time() - t0:.0f} s")
        sd = pd.read_excel(specs_cal, sheet_name="SpecsDataCalib")
        print(sd.iloc[0][["UrbanRatioStartYear", "UrbanRatioModelled", "ElecActual", "ElecModelled",
                          "urban_elec_ratio_modelled", "rural_elec_ratio_modelled"]].to_string())
    else:
        print("using existing calibration in", cal_dir)

    pv = f"{IEA}/Solar_Wind/{cc}-2-pv.csv"
    wind = f"{IEA}/Solar_Wind/{cc}-2-wind.csv"
    mv = f"{IEA}/MV_lines/{a.iso3}/{a.iso3}_mv_lines.shp"
    for f in (pv, wind, mv):
        assert os.path.exists(f), f"missing resource file {f}"
    # the calibrated workbook holds a copy of the scenario sheets from calibration time: refresh them from the current
    # specs so new grid seeds / scenario levers apply without recalibrating (the calibration itself is untouched)
    # Each job works on its own copy of the calibrated workbook (jobs of the same country run in parallel).
    job_specs = os.path.join(base, f"{cc}-1-specs-job_{a.tag}.xlsx")
    shutil.copy(specs_cal, job_specs)
    with pd.ExcelWriter(job_specs, engine="openpyxl", mode="a", if_sheet_exists="replace") as w:
        for sheet in ("ScenarioInfo", "ScenarioParameters"):
            t = pd.read_excel(specs, sheet_name=sheet)
            if sheet == "ScenarioInfo" and a.grid_cap_index is not None:      # sensitivity: pick another row of GridConnectionsLimitThousands
                t["Grid_connection_cap"] = a.grid_cap_index
                print(f"Grid_connection_cap forced to row {a.grid_cap_index} of ScenarioParameters")
            t.to_excel(w, sheet_name=sheet, index=False)
    # Senegal's cluster file is an older format without Commercial_Multiplier (needed when productive uses are ON).
    # Fallback: 0.412 = median of the West-African neighbours that have it (GHA 0.412, CIV 0.412, BFA 0.412, GIN 0.412,
    # per-settlement range 0.3-0.6, mean 0.38-0.43). Written into the calibrated CSV once; flagged here and in NOTES.md.
    if "Commercial_Multiplier" not in pd.read_csv(csv_cal, nrows=1).columns:
        cal = pd.read_csv(csv_cal)
        cal["Commercial_Multiplier"] = 0.412
        cal.to_csv(csv_cal, index=False)
        print("WARNING: no Commercial_Multiplier in the cluster file; filled with the neighbour median 0.412")
    t1 = time.time()
    runner.scenario(job_specs, csv_cal, res_dir, sum_dir, pv, wind, mv, cost_multipliers=CT[a.ct], only_codes=a.codes)
    print(f"scenarios done in {time.time() - t1:.0f} s; results in {res_dir}")


if __name__ == "__main__":
    main()
