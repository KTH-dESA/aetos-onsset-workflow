# OnSSET x AETOS soft-link workflow

A [Snakemake](https://snakemake.readthedocs.io) workflow that couples the geospatial electrification model
[OnSSET](https://github.com/onsset/onsset) with the continental power-system model
[AETOS](https://github.com/ekousoulos/AETOS-model) (OSeMOSYS), to study the greenhouse-gas implications of
last-mile electrification pathways. It was built for Nigeria and Zambia, but every stage is country-generic and runs for
any African country that has an OnSSET cluster file.

```
OnSSET run 1 ──> new grid demand per country ──> AETOS-Africa (OSeMOSYS) ──> grid cost, emission factor,
 (grid-only seeds)        (12 runs)                                           capacity cost, renewable share
       ^                                                                                   │
       └───────────────────────────── seeds written back to the OnSSET specs <─────────────┘
                                              │
                                    OnSSET run 2 (final pathways, maps, tables)
```

* **Demand scenarios:** low (residential) and high (residential + social + productive uses)
* **Carbon price:** none / World Bank shadow price (2021 USD)
* **Cost trajectories:** CT1, CT2, CT3 (multipliers on grid, renewable and diesel costs)
* AETOS demand is kept; the extra demand of people newly connected to the grid in OnSSET is added, interpolated by year.

## Requirements
| | |
|---|---|
| Environments | `envs/workflow.yaml` (Snakemake, otoole, GLPK) and `envs/onsset.yaml` (OnSSET side, geopandas) |
| OnSSET | the `onsset-1` repository, branch/release given in `versions.yaml` |
| AETOS | the unmodified `AETOS-model` repository, release given in `versions.yaml` |
| LP solver | Gurobi (used for the study; academic licences are free), or HiGHS (open source, no licence), or CPLEX |
| Memory | about 60 GB RAM for the Africa-wide LP build and solve (GLPK build ~25 GB, one solve ~30 GB) |
| Input data | OnSSET cluster files (`<ISO3>_gis_inputs_updated.gz`), GEP specs workbooks, onstove country inputs (see `config.example.yaml`). Not redistributed here. |

## Setup
```bash
conda env create -f envs/workflow.yaml
conda env create -f envs/onsset.yaml
cp config.example.yaml config.yaml          # edit the paths; this is the only file with machine-specific settings
python scripts/stage_onsset_inputs.py       # copies the input data listed in config.yaml into onsset/
```
Run everything from the repository folder inside the `gep_workflow` environment. On Windows set `bash:` in the
config (Git's `bash.exe`), since the shell lines are bash.

Pick the solver with `solver: gurobi | highs | cplex` in `config.yaml`. The study used Gurobi (barrier, no crossover);
`highs` is the free route but is untested on the full Africa-wide model and may be slow. The free CPLEX Community
Edition is too small for AETOS.

## Included data (`data/`)
* `aetos_africa_pn/`: the African block of the AETOS scenario used as baseline, as an otoole CSV folder
  (made with `scripts/extract_africa.py` from the AETOS dataset; the cut-off rules are in that script's docstring).
* `ct_technology_groups.csv`: classification of every AETOS technology into the cost-trajectory groups
  (`scripts/make_tech_groups.py`), used by `scripts/apply_ct_multipliers.py`.
* `carbon_price_wb_high_2021usd.csv`: carbon price series in constant 2021 USD (`scripts/make_carbon_price.py`).

## Running
```bash
snakemake -n                                                                  # dry run
snakemake -c 6 --retries 2 --keep-going --rerun-triggers mtime --resources mem_gb=60   # everything for `countries:`
```
Stages (each a target, so you can stop part-way): `stage_specs`, `stage_calibrate`, `stage_baseline` (AETOS baseline and
grid seeds), `stage_run1` (all countries), `stage_demand`, `stage_aetos` (the 12 AETOS runs), `stage_run2`
(`countries:` in the config), and the optional `stage_plots` / `stage_maps` (figures and maps, not part of `all`).

Subsets: `--config countries=[ZMB] cts=[1] dems=[low] taxes=[0]`. By default (`countries: all`) run 2 covers every country with a cluster file; list ISO3 codes under
`countries:`; run 1 and the AETOS runs already cover all countries with a cluster file.

## Outputs (`runs/`)
| Path | Content |
|---|---|
| `runs/run1/`, `runs/run2/` | OnSSET results per country and scenario |
| `runs/<dem>_t<tax>_ct<ct>/` | AETOS scenario data, results and metrics (generation mix, LCOE, emission factor, renewable shares) |
| `runs/figures/`, `runs/maps/` | capacity / generation bar charts and technology maps |

## Method in brief
* **Run 1** (grid-only seeds from the AETOS baseline) gives the settlements that connect to the grid; their incremental
  electricity demand is cumulated over the steps 2030/35/40, interpolated linearly by year and added to the AETOS demand.
  `--config demand_component=extension` keeps only settlements newly connected in each step (no growth in already connected
  settlements), which limits overlap with the AETOS demand; the default `all` is the full increment.
* **AETOS runs** (demand level x carbon price x cost trajectory) are solved; `scripts/aetos_metrics.py` derives, per
  country, the grid generation cost (including imports), emission factor, capacity investment cost and renewable share
  (generation based; the capacity-based share is reported too), smoothed over a ±2-year window per step.
* **Run 2** reruns OnSSET with those seeds, so grid-extension decisions respond to the power-system results.
* All scripts carry a header docstring with inputs, outputs and an example call.

## Citation and licence
To cite this workflow:

> Martínez-Rodríguez, L., Salas Salazar, M. E., Ribó-Pérez, D., Gómez-Navarro, T., Ramirez Gomez, C., & Fuso Nerini, F. (n.d.). *OnSSET x AETOS soft-link workflow* (Version 1.0.0) [Computer software]. GitHub. https://github.com/KTH-dESA/aetos-onsset-workflow

See `CITATION.cff` for the machine-readable citation and `LICENSE` (MIT). `data/aetos_africa_pn` is derived from AETOS-Africa (MIT, Elias Kousoulos; notice in `data/aetos_africa_pn/LICENSE_AETOS`). AETOS and OnSSET are separate projects with their own licences; cite them too.

## Acknowledgements
The definitions used to post-process the AETOS results (grid LCOE incl. imports, emission factor, capacity investment cost,
technology categories) and the colours of the generation-mix plots are inherited from the TEMBA-GEP calculations
(`scripts/aetos_metrics.py`, `scripts/gurobi_sol_to_results.py`, `scripts/plot_mix.py`). See the ElectrifyNow project
(https://electrifynow.energydata.info/about). No TEMBA-GEP code or data is needed to run the workflow.
