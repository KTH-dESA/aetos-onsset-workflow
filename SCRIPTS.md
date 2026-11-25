# Scripts in the order they are used

The Snakefile calls every script below; you normally never run them by hand. The order follows the stages of the
workflow (`stage_*` targets). Each script has a docstring with its options (`python scripts/<name>.py --help`).

Environments: scripts marked **[onsset]** run with the OnSSET environment (`envs/onsset.yaml`, python path in `config.yaml`);
**[workflow]** scripts run in the Snakemake environment (`envs/workflow.yaml`).

```
data preparation (once)                 run 1 (OnSSET, tax-free)                 AETOS (12 runs)                    run 2 (OnSSET, seeded)
stage_onsset_inputs ─ refresh_specs ─ calibrate_all ─ baseline AETOS ─ write_grid_seeds ─ run_onsset1 ─ make_demand ─ make_gep_scenario ─ solve ─ aetos_metrics ─ write_grid_seeds ─ run_onsset1
```

## 0. Shipped data and one-off preparation (already done; outputs are in `data/`)
| Script | What it does | Output |
|---|---|---|
| `extract_africa.py` | Cuts the African block out of the AETOS otoole dataset (a technology is kept if its country prefix and the prefix of every fuel it uses are African). | `data/aetos_africa_pn/` |
| `make_tech_groups.py` | Labels every AETOS technology with a cost-trajectory group (grid thermal, renewable, ...). | `data/ct_technology_groups.csv` |
| `make_carbon_price.py` | World Bank shadow price of carbon (high trajectory), converted to constant 2021 USD, one series for AETOS and OnSSET. | `data/carbon_price_wb_high_2021usd.csv` |
| `pull_projections.py` | World Bank population and urban-share projections to 2040, used as growth on the 2025 onstove values. Optional: `refresh_specs.py` reads its output when present. | `onsset/projections_2040.csv` |

## 1. Inputs and specs (`stage_specs`)
1. **`stage_onsset_inputs.py`** (run by hand once): copies the cluster files, GEP specs, onstove scalars and the country-code table named in `config.yaml` into `onsset/`.
2. **`refresh_specs.py`** [onsset]: builds one onsset-1 specs workbook per country (`runs/specs/<cc>-1-specs.xlsx`) from the GEP specs and the onstove 2025 scalars. It also sets the carbon price per year, the end-year population and urban share, and lifts the grid connection and capacity limits (`GridConnectionsLimitThousands` = 9999, `NewGridGenerationCapacityAnnualLimitMW` = 1e6).

## 2. Calibration (`stage_calibrate`)
3. **`calibrate_all.py`** [onsset]: one job per country. Calibrates population, urban share and the 2025 electrification to the onstove values (rank method) and writes the calibrated settlement file and specs ratios.

## 3. AETOS baseline and grid seeds (`stage_baseline`)
4. **AETOS baseline solve.** The raw AETOS-Africa data (`data/aetos_africa_pn`) is solved once with the same four steps as every AETOS run below (LP build, solve, results, metrics). The result gives grid seeds for run 1.
5. **`write_grid_seeds.py`** [onsset]: writes the AETOS-derived grid parameters (generation cost incl. imports, emission factor, capacity cost, renewable share, per step 2030/35/40) into each country's `ScenarioParameters` sheet. Output: `runs/specs_seeded.flag` and `runs/seeds_baseline.csv`.

## 4. OnSSET run 1 (`stage_run1`)
6. **`run_onsset1.py`** [onsset]: one job per country, demand level (low, high) and cost trajectory (CT1–CT3). Runs onsset-1 with the baseline seeds, no carbon price. Result: settlements, technologies and `EnergyPerSettlement` per step.

## 5. New grid demand (`stage_demand`)
7. **`make_demand.py`** [onsset]: adds up the grid demand of the newly connected people per country and step (2030/35/40), accumulates it over the steps, and interpolates it linearly by year from zero in 2025 (flat after 2040).
   - `--component all` (default, the paper): every settlement on grid (code 1 or 2).
   - `--component extension`: only settlements that were not on grid in the previous step. Set in the Snakefile with `--config demand_component=extension`.
   - Output: `runs/run1/demand_<level>_ct<n>.csv` (PJ; columns CC, YEAR, VALUE).

## 6. The 12 AETOS runs (`stage_aetos`): demand level x carbon price x cost trajectory
8. **`make_gep_scenario.py`** [workflow]: takes the AETOS dataset, switches off emission caps, adds the OnSSET demand of step 7 on top of AETOS's own demand, and, if `tax=1`, adds the carbon price as `EmissionsPenalty`.
9. **`apply_ct_multipliers.py`** [workflow]: applies the cost-trajectory multipliers to the scenario data, using `data/ct_technology_groups.csv`.
10. **LP build** (rule `aetos_lp`): `otoole convert` and `glpsol` write the LP. Needs about 26 GB RAM.
11. **`solve_gurobi.py`** (or `solve_highs.py`, `solve_cplex.py`, chosen by `solver:` in `config.yaml`) [workflow]: solves the LP with barrier and no crossover. Gurobi was used for the study; HiGHS and CPLEX are untested alternatives.
12. **`gurobi_sol_to_results.py`** [workflow]: turns the solver output into one CSV per OSeMOSYS variable.
13. **`aetos_metrics.py`** [workflow]: per country computes grid LCOE incl. imports, emission factor incl. imports, capacity investment cost, renewable share and the generation mix, for 2025–2040 and for the three step windows (2025–30, 2025–35, 2025–40).

## 7. OnSSET run 2 (`stage_run2`, and `all`)
14. **`write_grid_seeds.py`** [onsset] again (rule `specs_final`): per demand level and CT, takes the grid seeds from the matching AETOS runs, the tax-free one for the no-tax scenarios and the priced one for the carbon-price scenarios.
15. **`run_onsset1.py`** [onsset] again (rule `run2`): one job per country, demand level, tax and CT. Reuses the calibration of run 1. Run 2 covers every country with a cluster file by default (`countries: all`).

## 8. Figures and checks (optional, not part of `all`)
| Script | Use |
|---|---|
| `plot_mix.py` [onsset] | Capacity and generation bar charts per AETOS run (`stage_plots`). |
| `plot_map.py` [onsset] | Electrification-technology map per run-2 scenario and a slim settlement CSV for QGIS (`stage_maps`). |
| `overview_aetos.py` [workflow] | Health check of the 12 AETOS runs: solve status, unmet demand (backstop), demand against the CMP ceilings. |
| `report_seeds.py` [onsset] | One table of every grid and carbon seed in the specs workbooks. |

## Run order at a glance
```
snakemake -c 6 stage_specs stage_calibrate stage_baseline stage_run1 stage_demand stage_aetos stage_run2 \
          --retries 2 --keep-going --rerun-triggers mtime --resources mem_gb=60
```
`snakemake -c 6 --rerun-triggers mtime --resources mem_gb=60` does the same through `all`. Add `stage_plots stage_maps` for the figures.
