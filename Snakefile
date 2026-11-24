# Soft-link workflow OnSSET <-> AETOS-Africa (OnSSET run 1 -> AETOS demand -> grid seeds -> OnSSET run 2).  Run from this folder, in the gep_workflow environment:
#     (copy config.example.yaml to config.yaml and edit the paths first)
#     snakemake -n  <target>            dry run
#     snakemake -c 6 <target> --retries 2 --keep-going --rerun-triggers mtime --resources mem_gb=60
# Every stage has a target, so you can stop part-way:
#   stage_specs      refresh_specs -> runs/specs (onstove scalars, projections, WB carbon price)
#   stage_calibrate  rank calibration, one job per country
#   stage_baseline   AETOS PN solve -> metrics (+ 3 step windows) -> grid seeds written into runs/specs
#   stage_run1       OnSSET run 1, one job per (country, demand level, CT): tax-free codes 1_1_0_0_1_0 / 2_0_0_0_1_0
#   stage_demand     new-user grid demand per (level, CT) -> runs/run1/demand_<level>_ct<CT>.csv
#   stage_aetos      12 AETOS runs (level x tax x CT): scenario data -> LP -> solve -> metrics
#   stage_run2       final OnSSET, one job per (country, level, tax, CT), seeded by the matching AETOS runs
#   all              everything

# Windows: Snakemake would run shell lines in cmd.exe; every rule is written for bash (mkdir -p, cp globs, &&)
import os as _os
_bash = config.get("bash")                              # Windows only: path of Git's bash.exe; leave unset on Linux/macOS
if _bash and _os.path.exists(_bash):
    shell.executable(_bash)
    shell.prefix("export PATH=/usr/bin:/bin:$PATH; ")   # coreutils (mkdir, cp, ...) are not on PATH in a non-login bash
# paths the scripts read from the environment (set in config.yaml, never hard-coded in scripts)
_os.environ["ONSSET1_REPO"] = config.get("onsset1_repo", "")
_os.environ["ONSSET_RESOURCES_DIR"] = config.get("onsset_resources_dir", "")
_os.environ["MAP_CLUSTERS_DIR"] = config.get("clusters_dir", "")
# Memory: --resources mem_gb=60 is a shared budget (LP build 26, solve 30, OnSSET job 8 GB), so e.g. two solves fit at once.
# Subsets (loop over fewer wildcards):  --config cts=[1] dems=[low] taxes=[0] countries=[ZMB]
# Reuse an existing baseline instead of solving it:  --config baseline_metrics=data/metrics   (folders pn_africa_all, pn_w2030, ...)
# Two environments: scripts that need OnSSET/pandas pins run with the onsset python of config.yaml (PY), the AETOS side
# (otoole, glpsol, gurobipy) with the python of this environment.

configfile: "config.yaml"                                   # copy config.example.yaml to config.yaml first

PY    = config["onsset_python"]
AETOS = config["aetos_repo"] + "/AETOS_Runner"
CTS   = config.get("cts", [1, 2, 3])
DEM   = config.get("dems", ["low", "high"])      # low = U4R1 residential only (codes 1_1_*), high = U5R3 + productive (2_0_*)
TAX   = config.get("taxes", [0, 1])
COUNTRIES = config.get("countries", ["NGA", "ZMB"])          # final run only
STEPS = [2030, 2035, 2040]
R = "runs"
ALL_ISO = sorted(glob_wildcards("onsset/clusters/{iso}_gis_inputs_updated.gz").iso)   # run 1: every country with a cluster file
CODE1 = {"low": "1_1_0_0_1_0", "high": "2_0_0_0_1_0"}                                 # tax-free (3rd digit 0)
CODE2 = lambda dem, tax: ("1_1_" if dem == "low" else "2_0_") + f"{tax}_0_1_0"        # tier_productive_gridCT_pv_cap_rollout
RUNS  = [f"{d}_t{t}_ct{c}" for d in DEM for t in TAX for c in CTS]
BASE_EXT = config.get("baseline_metrics")
DEMAND_COMPONENT = config.get("demand_component", "all")   # all = every grid settlement (paper); extension = only newly connected settlements

wildcard_constraints:
    run = "baseline|(low|high)_t[01]_ct[123]",
    dem = "low|high", tax = "[01]", ct = "[123]", iso = "[A-Z]{3}"

def data_dir(run):
    return "data/aetos_africa_pn" if run == "baseline" else f"{R}/{run}/data"

# ------------------------------------------------------------------------------------------------ targets ------------
rule all:
    input: expand(R + "/run2/jobs/{iso}_{dem}_t{tax}_ct{ct}.done", iso=COUNTRIES, dem=DEM, tax=TAX, ct=CTS)
rule stage_specs:
    input: R + "/specs/refresh_log.csv"
rule stage_calibrate:
    input: expand(R + "/run1/{iso}/calibration/{iso}_calibrated.csv", iso=ALL_ISO)
rule stage_baseline:
    input: R + "/specs_seeded.flag"
rule stage_run1:
    input: expand(R + "/run1/jobs/{iso}_{dem}_ct{ct}.done", iso=ALL_ISO, dem=DEM, ct=CTS)
rule stage_demand:
    input: expand(R + "/run1/demand_{dem}_ct{ct}.csv", dem=DEM, ct=CTS)
rule stage_aetos:
    input: expand(R + "/{r}/metrics/metrics_period.csv", r=RUNS)
rule stage_run2:
    input: expand(R + "/run2/jobs/{iso}_{dem}_t{tax}_ct{ct}.done", iso=COUNTRIES, dem=DEM, tax=TAX, ct=CTS)

# ------------------------------------------------------------------------------------- 1. specs, calibration ----------
rule specs_fresh:                                       # onstove scalars + projections + WB carbon price per year, all countries
    output: R + "/specs/refresh_log.csv"
    shell: "{PY} scripts/refresh_specs.py --out-dir {R}/specs"

rule calibrate:                                         # rank method; one job per country (calibration does not depend on the seeds)
    input: R + "/specs/refresh_log.csv"
    output: csv = R + "/run1/{iso}/calibration/{iso}_calibrated.csv", report = R + "/run1/calibration_reports/{iso}.csv"
    shell:
        "{PY} scripts/calibrate_all.py --countries {wildcards.iso} --method rank --specs-dir {R}/specs "
        "--work-dir {R}/run1 --report {output.report}"

# ------------------------------------------------------------------------------------- 2. AETOS baseline (PN) ----------
# Generic AETOS rules: {run} = baseline or <dem>_t<tax>_ct<ct>.
rule aetos_lp:                                          # CSV dataset -> OSeMOSYS datafile -> LP (both deleted after the solve)
    input: lambda w: data_dir(w.run)
    output: lp = temp(R + "/{run}/model.lp"), txt = temp(R + "/{run}/model.txt")
    resources: mem_gb = 26                              # GLPK needed ~24 GB for the Africa-only build
    shell:
        'otoole convert csv datafile {input} {output.txt} "{AETOS}/config_otoole_AETOS.yaml" && '
        'glpsol -m "{AETOS}/model/osemosys_fast_AETOS.txt" -d {output.txt} --wlp {output.lp} --check'

SOLVER = config.get("solver", "gurobi")                 # gurobi (used in the study) | highs (open source) | cplex (licence needed)
assert SOLVER in ("gurobi", "highs", "cplex"), "config: solver must be gurobi, highs or cplex"

rule aetos_solve:                                       # memory is a shared budget: --resources mem_gb=60
    input: lp = R + "/{run}/model.lp", data = lambda w: data_dir(w.run)
    output: sol = R + "/{run}/solve.sol", res = directory(R + "/{run}/results")
    threads: 10
    resources: mem_gb = config.get("solver_mem_gb", 30)  # also the solver's own limit; two solves fit in mem_gb=60, one at 56: --config solver_mem_gb=56
    params: solver = SOLVER
    shell:
        "python scripts/solve_{params.solver}.py {input.lp} {output.sol} --threads {threads} --memlimit {resources.mem_gb} && "
        "python scripts/gurobi_sol_to_results.py {output.sol} {output.res} --data {input.data}"

rule aetos_metrics:                                     # whole window + the three step windows (2025..2030/35/40) for the per-step seeds
    input: res = R + "/{run}/results", data = lambda w: data_dir(w.run)
    output:
        period = R + "/{run}/metrics/metrics_period.csv", yearly = R + "/{run}/metrics/metrics_yearly.csv",
        windows = expand(R + "/{{run}}/metrics_w{y}/metrics_period.csv", y=STEPS)
    shell:
        "python scripts/aetos_metrics.py --results {input.res} --data {input.data} --out {R}/{wildcards.run}/metrics --countries && "
        "python scripts/aetos_metrics.py --results {input.res} --data {input.data} --out {R}/{wildcards.run}/metrics_w2030 --countries --window 2025 2030 && "
        "python scripts/aetos_metrics.py --results {input.res} --data {input.data} --out {R}/{wildcards.run}/metrics_w2035 --countries --window 2025 2035 && "
        "python scripts/aetos_metrics.py --results {input.res} --data {input.data} --out {R}/{wildcards.run}/metrics_w2040 --countries --window 2025 2040"

def _baseline_inputs(w):
    if BASE_EXT:                                        # existing metrics folders (data/metrics/pn_africa_all, pn_w2030, ...)
        return dict(main = f"{BASE_EXT}/pn_africa_all/metrics_period.csv",
                    steps = [f"{BASE_EXT}/pn_w{y}/metrics_period.csv" for y in STEPS])
    return dict(main = f"{R}/baseline/metrics/metrics_period.csv",
                steps = [f"{R}/baseline/metrics_w{y}/metrics_period.csv" for y in STEPS])

rule seeds_baseline:                                    # seeds in the specs that run 1 reads: grid LCOE, capex, EF, renewable shares per step
    input: unpack(_baseline_inputs), specs_log = R + "/specs/refresh_log.csv"
    output: touch(R + "/specs_seeded.flag")
    params: steps = lambda w, input: " ".join(f"{y}={p}" for y, p in zip(STEPS, input.steps))
    shell:
        "{PY} scripts/write_grid_seeds.py --metrics {input.main} --specs {R}/specs --log {R}/seeds_baseline.csv "
        "--step-metrics {params.steps}"

# ------------------------------------------------------------------------------------- 3. OnSSET run 1 -----------------
rule run1:                                              # one job = one scenario (country, demand level, CT), tax-free
    input: calib = R + "/run1/{iso}/calibration/{iso}_calibrated.csv", seeds = R + "/specs_seeded.flag"
    output: touch(R + "/run1/jobs/{iso}_{dem}_ct{ct}.done")
    params: code = lambda w: CODE1[w.dem]
    resources: mem_gb = 8                               # budget estimate; Nigeria and Ethiopia are the largest
    shell:
        "{PY} scripts/run_onsset1.py --iso3 {wildcards.iso} --ct {wildcards.ct} --specs-dir {R}/specs "
        "--work-dir {R}/run1 --codes {params.code} --tag {wildcards.dem}_ct{wildcards.ct}"

rule demand_table:                                      # cumulative grid demand of newly connected people, PJ: CC,YEAR,VALUE
    input: lambda w: expand(R + "/run1/jobs/{iso}_{dem}_ct{ct}.done", iso=ALL_ISO, dem=w.dem, ct=w.ct)
    output: R + "/run1/demand_{dem}_ct{ct}.csv"
    shell: "{PY} scripts/make_demand.py --run1 {R}/run1 --level {wildcards.dem} --ct {wildcards.ct} --component {DEMAND_COMPONENT} --out {output}"

# ------------------------------------------------------------------------------------- 4. the 12 AETOS runs -----------
rule aetos_data:                                        # option C: AETOS demand + OnSSET new users; carbon price if tax=1; CT cost multipliers
    input: dem = R + "/run1/demand_{dem}_ct{ct}.csv", price = "data/carbon_price_wb_high_2021usd.csv"
    output: directory(R + "/{dem}_t{tax}_ct{ct}/data")
    params: tax = lambda w: "--carbon-tax" if w.tax == "1" else ""
    shell:
        'python scripts/make_gep_scenario.py data/aetos_africa_pn {output} --baseline aetos '
        '--new-demand {input.dem} --carbon-price-csv {input.price} {params.tax} && '
        'python scripts/apply_ct_multipliers.py {output} --ct {wildcards.ct}'     # grid/renewable CAPEX multipliers from 2025 (CT1: no-op)

# ------------------------------------------------------------------------------------- 5. final OnSSET ----------------
rule specs_final:                                       # per (level, CT): non-CT seeds from the tax-free AETOS run, _CT seeds from the tax run
    input:
        base = R + "/specs_seeded.flag",
        no  = R + "/{dem}_t0_ct{ct}/metrics/metrics_period.csv", tax = R + "/{dem}_t1_ct{ct}/metrics/metrics_period.csv",
        no_w  = expand(R + "/{{dem}}_t0_ct{{ct}}/metrics_w{y}/metrics_period.csv", y=STEPS),
        tax_w = expand(R + "/{{dem}}_t1_ct{{ct}}/metrics_w{y}/metrics_period.csv", y=STEPS)
    output: R + "/run2/specs_{dem}_ct{ct}/seeds.csv"
    params:
        d = R + "/run2/specs_{dem}_ct{ct}",
        no_steps  = lambda w, input: " ".join(f"{y}={p}" for y, p in zip(STEPS, input.no_w)),
        tax_steps = lambda w, input: " ".join(f"{y}={p}" for y, p in zip(STEPS, input.tax_w))
    shell:      # [a-z][a-z] in the cp pattern skips Excel's ~$ lock files
        "mkdir -p {params.d} && cp {R}/specs/[a-z][a-z]-1-specs.xlsx {params.d}/ && "
        "{PY} scripts/write_grid_seeds.py --metrics {input.no} --metrics-ct {input.tax} --specs {params.d} "
        "--log {output} --step-metrics {params.no_steps} --step-metrics-ct {params.tax_steps}"

rule run2:                                              # one job = one scenario (country, level, tax, CT); reuses run 1's calibration
    input:
        specs = R + "/run2/specs_{dem}_ct{ct}/seeds.csv", calib = R + "/run1/{iso}/calibration/{iso}_calibrated.csv"
    output: touch(R + "/run2/jobs/{iso}_{dem}_t{tax}_ct{ct}.done")
    params: code = lambda w: CODE2(w.dem, w.tax), specs = R + "/run2/specs_{dem}_ct{ct}", work = R + "/run2/{dem}_ct{ct}"
    resources: mem_gb = 8
    shell:
        "{PY} scripts/run_onsset1.py --iso3 {wildcards.iso} --ct {wildcards.ct} --specs-dir {params.specs} "
        "--work-dir {params.work} --calib-work-dir {R}/run1 --codes {params.code} "
        "--tag {wildcards.dem}_t{wildcards.tax}_ct{wildcards.ct}"

# ------------------------------------------------------------------------------------- 6. figures and maps -------------
# Not part of `all`. Targets:  stage_plots (capacity/generation bars, all 12 runs x NG/ZM)
#                              stage_maps  (maps of the 4 base scenarios under CT1: low/high x tax 0/1, countries listed under `maps:` in config.yaml)
#   snakemake -c 2 stage_maps stage_plots --rerun-triggers mtime
ONSET_ENV = _os.path.dirname(PY)          # DLL / GDAL / PROJ locations of the onsset env, needed when its python is called directly
ENVX = (f'export PATH="{ONSET_ENV}:{ONSET_ENV}/Library/bin:{ONSET_ENV}/Library/mingw-w64/bin:{ONSET_ENV}/Scripts:$PATH"; '
        f'export GDAL_DATA="{ONSET_ENV}/Library/share/gdal" PROJ_LIB="{ONSET_ENV}/Library/share/proj"; ')
# per country (ISO3): `name` as in the cluster shapefile <name>_final_clusters.shp and `boundary` geojson, from config.yaml (maps:)
# the ISO2 code (lower case) of the run-2 file names comes from onsset/iso_codes.csv
import csv as _csv
_iso2 = {r["Alpha-3"]: r["Alpha-2"].lower() for r in _csv.DictReader(open("onsset/iso_codes.csv", encoding="utf-8", newline=""))}     if _os.path.exists("onsset/iso_codes.csv") else {}
MAPS = {k: dict(name=v["name"], cc=_iso2.get(k, k[:2].lower()), bnd=v["boundary"]) for k, v in config.get("maps", {}).items()}
MAP_YEARS = config.get("map_years", [2025, 2030, 2035, 2040])        # --config "map_years=[2040]" = last year only
CLUSTERS_DIR = config.get("clusters_dir", "")               # folder with <name>_final_clusters.shp (a local copy is faster than a synced drive)

rule stage_plots:
    input: expand(R + "/figures/{run}/.done", run=RUNS)
rule stage_maps:
    input: expand(R + "/maps/{iso}_{dem}_t{tax}_ct1_2040.png", iso=[c for c in COUNTRIES if c in MAPS], dem=DEM, tax=TAX)

rule plot_mix:                                          # capacity + generation bars of one AETOS run, both countries
    input: R + "/{run}/metrics/metrics_period.csv"
    output: touch(R + "/figures/{run}/.done")
    params: cc = " ".join(_iso2[c].upper() for c in COUNTRIES if c in _iso2), names = " ".join(f"{_iso2[k].upper()}={v['name']}" for k, v in MAPS.items() if k in _iso2)
    shell: ENVX + "{PY} scripts/plot_mix.py --runs {R} --out {R}/figures --only {wildcards.run} --countries {params.cc} --names {params.names}"

rule map:                                               # one OnSSET run-2 scenario: PNG per year + slim settlement CSV for QGIS
    input: R + "/run2/jobs/{iso}_{dem}_t{tax}_ct{ct}.done"
    output: R + "/maps/{iso}_{dem}_t{tax}_ct{ct}_2040.png"
    params:
        res = lambda w: f"{R}/run2/{w.dem}_ct{w.ct}/{w.iso}/results_ct{w.ct}/{MAPS[w.iso]['cc']}-1-{CODE2(w.dem, w.tax)}.csv",
        bnd = lambda w: MAPS[w.iso]["bnd"], country = lambda w: MAPS[w.iso]["name"],
        title = lambda w: f"{MAPS[w.iso]['name']} with {w.dem} demand" + (" and carbon tax" if w.tax == "1" else "")   # CT only in the file name
    resources: mem_gb = 10
    shell:
        ENVX + "{PY} scripts/plot_map.py --results {params.res} --boundary \"{params.bnd}\" --country {params.country} "
        "--clusters-dir \"" + CLUSTERS_DIR + "\" --out {R}/maps --tag {wildcards.iso}_{wildcards.dem}_t{wildcards.tax}_ct{wildcards.ct} "
        "--years " + " ".join(str(y) for y in MAP_YEARS) + " --title \"{params.title}\""
