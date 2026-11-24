"""Copy the OnSSET inputs into this folder so the workflow no longer depends on the original locations.

    onsset/clusters/<ISO3>_gis_inputs_updated.gz   IEA settlement files (2024), uncalibrated (calibration regenerates them)
    onsset/specs/<cc>-3-specs.xlsx                 GEP Climate specs (gep-onsset layout, incl. the *_CT grid columns)
    onsset/onstove_country_inputs_SSA.csv          2025 scalars (population, urban share, electrification, household size)
    onsset/iso_codes.csv                           ISO2 <-> ISO3

Sources come from config.yaml. Existing files are skipped unless --overwrite.
    python scripts/stage_onsset_inputs.py [--config config.yaml] [--overwrite]
"""
import argparse
import os
import shutil

import pandas as pd
import yaml

ap = argparse.ArgumentParser()
ap.add_argument("--config", default="config.yaml")
ap.add_argument("--out", default="onsset")
ap.add_argument("--overwrite", action="store_true")
a = ap.parse_args()
cfg = yaml.safe_load(open(a.config))
iso = pd.read_csv(cfg["iso_codes_csv"], keep_default_na=False)
to2 = dict(zip(iso["Alpha-3"], iso["Alpha-2"]))


def copy(src, dst):
    if os.path.exists(dst) and not a.overwrite:
        return "skipped"
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    return "copied"


os.makedirs(a.out, exist_ok=True)
iso.to_csv(os.path.join(a.out, "iso_codes.csv"), index=False)
print("onstove csv:", copy(cfg["onstove_csv"], os.path.join(a.out, "onstove_country_inputs_SSA.csv")))
log = []
for f in sorted(os.listdir(cfg["iea_clusters_dir"])):
    if f.endswith("_gis_inputs_updated.gz"):
        iso3 = f.split("_")[0]
        s = copy(os.path.join(cfg["iea_clusters_dir"], f), os.path.join(a.out, "clusters", f))
        log.append((iso3, to2.get(iso3, "?"), "cluster", s))
        print(iso3, "cluster", s, flush=True)
for iso3, cc in sorted(to2.items()):
    src = os.path.join(cfg["gep_specs_dir"], f"{cc.lower()}-3-specs.xlsx")
    if os.path.exists(src) and os.path.exists(os.path.join(a.out, "clusters", f"{iso3}_gis_inputs_updated.gz")):
        log.append((iso3, cc, "specs", copy(src, os.path.join(a.out, "specs", os.path.basename(src)))))
pd.DataFrame(log, columns=["iso3", "iso2", "file", "status"]).to_csv(os.path.join(a.out, "staged_files.csv"), index=False)
have = {l[0] for l in log if l[2] == "specs"}
miss = sorted({l[0] for l in log if l[2] == "cluster"} - have)
print(f"{len(have)} countries with cluster + specs. Clusters without GEP specs: {miss}")
