"""Build onsset-1 specs files from the staged GEP specs + onstove 2025 scalars.

One output workbook per country (`<cc>-1-specs.xlsx`) with the three sheets onsset-1's `runner` reads:
  ScenarioInfo        only the requested scenarios, numbered 0..n-1 (the runner uses `iloc[Scenario]`), plus a `Code` column
  ScenarioParameters  GEP rows (incl. the AETOS grid seeds) + RuralTargetTierLarge/Small, RuralCutoffSize,
                      MaxIntensificationCost, NewGridGenerationCapacityAnnualLimitMW
  SpecsData           one row per model year; FIRST COLUMN = `Year` (the runner reads it with index_col=0);
                      row 0 also carries the start-year calibration inputs (population, urban ratio, access)

Values: start year (2025) population, urban ratio, access rates and household sizes come from the onstove table;
grid losses, base-to-peak, max extension distance, grid generation limits stay as in the GEP specs.
End-year population / urban ratio: from the World Bank projections lookup (scripts/pull_projections.py) when present,
otherwise a PLACEHOLDER extrapolation of the GEP specs' own 2020-2030 trend (flagged in the log).
Access target per year: linear from today's access to 100 % in --universal-year.

    python refresh_specs.py [--countries ZMB NGA | all] [--years 2030 2035 2040] [--scenarios 1_1_0_0_1_0 ...]
                            [--rural-tiers split|gep] [--projections file.csv] [--out-dir onsset/specs_onsset1]
"""
import argparse
import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SCEN = ["1_1_0_0_1_0", "1_1_1_0_1_0", "2_0_0_0_1_0", "2_0_1_0_1_0"]
# order of the scenario code -> ScenarioInfo columns
CODE_COLS = ["Target_electricity_consumption_level", "Productive_uses_demand", "Grid_electricity_generation_cost",
             "PV_cost_adjust", "Grid_connection_cap", "Prioritization_algorithm"]
NORTH_AFRICA = {"DZ", "EG", "LY", "MA", "TN"}  # assumed fully electrified: no OnSSET run, AETOS demand kept


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--countries", nargs="+", default=["all"],
                    help="ISO3 codes, or 'all' = every country with GEP specs + onstove row, minus North Africa")
    ap.add_argument("--gep-specs-dir", default=os.path.join(ROOT, "onsset", "specs"))
    ap.add_argument("--onstove", default=os.path.join(ROOT, "onsset", "onstove_country_inputs_SSA.csv"))
    ap.add_argument("--iso-codes", default=os.path.join(ROOT, "onsset", "iso_codes.csv"))
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "onsset", "specs_onsset1"))
    ap.add_argument("--carbon-price-file", default=os.path.join(ROOT, "data", "carbon_price_wb_high_2021usd.csv"),
                    help="YEAR,VALUE (USD2021/t CO2) from make_carbon_price.py; AETOS (make_gep_scenario) uses the same file")
    ap.add_argument("--start-year", type=int, default=2025)
    ap.add_argument("--years", nargs="+", type=int, default=[2030, 2035, 2040])
    ap.add_argument("--universal-year", type=int, default=2040)
    ap.add_argument("--scenarios", nargs="+", default=DEFAULT_SCEN)
    ap.add_argument("--rural-tiers", choices=["split", "gep"], default="split")
    ap.add_argument("--rural-cutoff", type=float, default=100, help="households; larger rural settlements are 'large'")
    ap.add_argument("--max-intensification-cost", type=float, default=1500)
    ap.add_argument("--grid-conn-share", type=float, default=-1,
                    help="annual cap on NEW GRID CONNECTIONS as a share of the country's start-year households, e.g. 0.015 "
                         "(GridConnectionsLimitThousands rows 1 and 2). DEFAULT -1 = no cap (9999 thousand/yr, like row 0). "
                         "0 = keep the GEP specs' value")
    ap.add_argument("--grid-capacity-mw", type=float, default=1e6,
                    help="NewGridGenerationCapacityAnnualLimitMW; 1e6 = effectively no capacity cap. <0 = keep the GEP specs' value")
    ap.add_argument("--projections", default=None,
                    help="CSV from pull_projections.py; default onsset/projections_<last year>.csv if it exists")
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)

    iso = pd.read_csv(a.iso_codes, keep_default_na=False).set_index("Alpha-3")["Alpha-2"]
    ons = pd.read_csv(a.onstove, keep_default_na=False).set_index("Country_code")
    pfile = a.projections or os.path.join(ROOT, "onsset", f"projections_{a.years[-1]}.csv")
    proj = pd.read_csv(pfile).set_index("Country_code") if os.path.exists(pfile) else None
    print("projections:", pfile if proj is not None else "none found -> GEP-trend placeholder")
    if a.countries == ["all"]:
        have = {f.split("-")[0] for f in os.listdir(a.gep_specs_dir) if f.endswith("-3-specs.xlsx")}
        a.countries = [c for c in ons.index if iso.get(c, "").lower() in have
                       and iso[c] not in NORTH_AFRICA]
    log = []

    for iso3 in a.countries:
        cc = iso[iso3].lower()
        src = os.path.join(a.gep_specs_dir, f"{cc}-3-specs.xlsx")
        if iso3 not in ons.index or not os.path.exists(src):
            print(f"{iso3}: skipped (no onstove row or no GEP specs)")
            continue
        o = ons.loc[iso3]
        x = pd.ExcelFile(src)
        info, par, sd = x.parse("ScenarioInfo"), x.parse("ScenarioParameters"), x.parse("SpecsData")
        t = sd.iloc[0].to_dict()

        # --- ScenarioInfo: built from the codes (country sheets differ in size, e.g. Somalia has 24 rows) -----------
        rows = []
        for n, code in enumerate(a.scenarios):
            v = [int(q) for q in code.split("_")]
            r = dict(zip(CODE_COLS, v))
            rows.append({"Scenario": n, "Productive_uses_demand": r["Productive_uses_demand"],
                         "Target_electricity_consumption_level": r["Target_electricity_consumption_level"],
                         "Grid_connection_cap": r["Grid_connection_cap"],
                         "Grid_electricity_generation_cost": r["Grid_electricity_generation_cost"],
                         "PV_cost_adjust": r["PV_cost_adjust"], "Prioritization_algorithm": r["Prioritization_algorithm"],
                         "Code": code})
        info1 = pd.DataFrame(rows)

        # --- ScenarioParameters: study definitions override the country sheet's lever rows ----------------------------
        # (row 0 = custom/none, row 1 = low demand / productive OFF / carbon tax ON, row 2 = high demand)
        par = par.iloc[:3].copy().reset_index(drop=True)
        par["UrbanTargetTier"] = [6, 4, 5]
        if a.rural_tiers == "split":
            par["RuralTargetTier"] = [6, 1, 3]                  # kept for reference
            par["RuralTargetTierLarge"] = [6, 2, 3]
            par["RuralTargetTierSmall"] = [6, 1, 2]
        else:
            par["RuralTargetTier"] = [6, 1, 3]
            par["RuralTargetTierLarge"] = [6, 1, 3]
            par["RuralTargetTierSmall"] = [6, 1, 3]
        par["ProductiveDemand"] = [1, 0, np.nan]                # ProductiveDemand[index]: row 0 = ON, row 1 = OFF
        par["CarbonTax"] = [0, 106, np.nan]                      # fallback if no per-year column
        # per-year carbon price, the same series AETOS gets (make_gep_scenario --carbon-tax): row 0 = none, row 1 = tax
        pen = pd.read_csv(a.carbon_price_file).set_index("YEAR")["VALUE"]
        for y in a.years:
            par[f"CarbonTax{y}"] = [0, float(pen.loc[y]), np.nan]
        par["RuralCutoffSize"] = a.rural_cutoff
        par["MaxIntensificationCost"] = a.max_intensification_cost
        par["NewGridGenerationCapacityAnnualLimitMW"] = (float(t["NewGridGenerationCapacityAnnualLimitMW"])
                                                         if a.grid_capacity_mw < 0 else a.grid_capacity_mw)

        # --- SpecsData -------------------------------------------------------------------------------
        pop0, u0, e0 = float(o["Population_start_year"]), float(o["Urban_start"]), float(o["Elec_rate"])
        # grid connection cap: share of the start-year households per year (thousands of households), same for both demand levels
        hh0 = pop0 * (u0 / float(o["Urban_HHsize"]) + (1 - u0) / float(o["Rural_HHsize"]))
        if a.grid_conn_share != 0:
            cap_k = 9999.0 if a.grid_conn_share < 0 else a.grid_conn_share * hh0 / 1000
            par["GridConnectionsLimitThousands"] = [9999.0, cap_k, cap_k]
        flag = "projections file"
        if proj is not None and iso3 in proj.index:
            pop1, u1 = float(proj.loc[iso3, "PopEndYear"]), float(proj.loc[iso3, "UrbanRatioEndYear"])
        else:  # placeholder: continue the GEP specs' own trend
            n = float(t["EndYEar"]) - float(t["StartYear"])
            g = (float(t["PopEndYear"]) / float(t["PopStartYear"])) ** (1 / n)
            pop1 = pop0 * g ** (a.years[-1] - a.start_year)
            du = (float(t["UrbanRatioEndYear"]) - float(t["UrbanRatioStartYear"])) / n
            u1 = min(0.95, u0 + du * (a.years[-1] - a.start_year))
            flag = "PLACEHOLDER (GEP trend extrapolated)"
        t.update(StartYear=a.start_year, EndYEar=a.years[-1], PopStartYear=pop0, UrbanRatioStartYear=u0,
                 PopEndYear=pop1, UrbanRatioEndYear=u1, NumPeoplePerHHRural=float(o["Rural_HHsize"]),
                 NumPeoplePerHHUrban=float(o["Urban_HHsize"]), ElecActual=e0,
                 Rural_elec_ratio=float(o["rural_elec_rate"]), Urban_elec_ratio=float(o["urban_elec_rate"]),
                 UrbanCutOff=np.nan, UrbanRatioModelled=np.nan, ElecModelled=np.nan,
                 urban_elec_ratio_modelled=np.nan, rural_elec_ratio_modelled=np.nan)
        recs = []
        for y in a.years:
            r = dict(t)
            r["ElecTarget"] = min(1.0, e0 + (1 - e0) * (y - a.start_year) / (a.universal_year - a.start_year))
            recs.append({"Year": y, **r})
        specs1 = pd.DataFrame(recs)

        out = os.path.join(a.out_dir, f"{cc}-1-specs.xlsx")
        with pd.ExcelWriter(out, engine="openpyxl") as w:
            info1.to_excel(w, sheet_name="ScenarioInfo", index=False)
            par.to_excel(w, sheet_name="ScenarioParameters", index=False)
            specs1.to_excel(w, sheet_name="SpecsData", index=False)
        log.append(dict(iso3=iso3, file=out, pop_start=pop0, pop_end=pop1, urban_start=u0, urban_end=u1,
                        elec=e0, end_year_source=flag, years=" ".join(map(str, a.years)),
                        targets=" ".join(f"{v:.3f}" for v in specs1["ElecTarget"]),
                        conn_limit_k_per_yr=" ".join(str(v) for v in par["GridConnectionsLimitThousands"].tolist())))
        print(f"{iso3}: wrote {out} | pop {pop0:,.0f} -> {pop1:,.0f}, urban {u0:.3f} -> {u1:.3f} [{flag}] | "
              f"targets {', '.join(f'{v:.2f}' for v in specs1['ElecTarget'])}")
    pd.DataFrame(log).to_csv(os.path.join(a.out_dir, "refresh_log.csv"), index=False)


if __name__ == "__main__":
    main()
