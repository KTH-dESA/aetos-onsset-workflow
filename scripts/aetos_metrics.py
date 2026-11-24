"""Grid metrics for the OnSSET soft link, computed from a solved AETOS(-Africa) run.

AETOS version of TEMBA-GEP's scripts/lcoe_and_emissions.py (same definitions, AETOS naming and accounting).
Reads the tables written by gurobi_sol_to_results.py plus the otoole CSVs the model was built from.

Per country it produces what goes into OnSSET's ScenarioParameters:
    GridGenerationCost            LCOE of grid electricity, USD/kWh   (TEMBA: final LCOE incl. imports)
    GridEmissionFactor            gCO2/kWh                            (TEMBA: incl. imports at the exporter's factor)
    GridCapacityInvestmentCost    USD/kW of new generation capacity   (capital investment / new capacity)
    GridRenShare                  CAPACITY-based renewable share (renewable / total installed generator capacity) in the
                                  window's last year, as in the paper's eq. 3 (the energy-based share incl. imports is
                                  kept as ren_share_grid_energy)
and the generation mix by TEMBA's technology categories.

Definitions
  * Generators: technologies that put electricity on the country's E1 node and fall in a generation category
    (Coal, Gas, Oil, Nuclear, Hydro, Solar PV, Solar CSP, Wind, Geothermal, Biomass). Batteries and pumped
    hydro (Storage), interconnectors (Imports), transmission/distribution and backstops are not generators.
  * LCOE (TEMBA): sum of discounted (capital investment - salvage + O&M) / sum of discounted generation over
    the window, 8 % discount rate, salvage = straight-line value of the investment left at the window end.
    O&M = plants' fixed and variable cost + fuel cost + emission penalty (if any). Imports are priced at
    import_cost_factor (TEMBA: 1.5) x the exporter's domestic LCOE.
  * Emissions: AETOS books CO2 on the fuel SUPPLY technologies (e.g. NGNG00X00), not on the plants.
    Plant emissions are therefore fuel use x the fuel's emission factor (EmissionActivityRatio / output ratio of the
    supply technologies, by fuel type) + the plants' own EmissionActivityRatio (negative for CCS).
    The country's AnnualEmissions variable (supply side, incl. exported fuel) is reported next to it.
  * Units: capacity GW, energy PJ (x277.7778 = GWh), emissions Mt, costs million USD (constant 2021).

    python aetos_metrics.py --results <dir> --data <otoole CSV dir> --out <dir> [--countries NG ZM]
                            [--window 2025 2040] [--discount 0.08] [--import-cost-factor 1.5]
"""
import argparse
import os

import numpy as np
import pandas as pd

PJ_TO_GWH = 277.777778
GEN_CATEGORIES = ["Coal", "Gas", "Oil", "Nuclear", "Hydro", "Solar PV", "Solar CSP", "Wind", "Geothermal", "Biomass"]
RENEWABLE = ["Hydro", "Solar PV", "Solar CSP", "Wind", "Geothermal", "Biomass"]   # biomass: edit here if needed
FAMILY = {"COC": "Coal", "COS": "Coal", "NGC": "Gas", "NGG": "Gas", "HFG": "Oil", "LFR": "Oil", "NUL": "Nuclear",
          "HYD": "Hydro", "SOU": "Solar PV", "SOC": "Solar CSP", "WIN": "Wind", "GOC": "Geothermal",
          "BMC": "Biomass", "BAT": "Storage"}


def categorize(t):
    """AETOS code = COUNTRY(2) + FUEL + TECH + CLASS; map to TEMBA's categories."""
    s = t[2:]
    if s == "BACKSTOP":
        return "Backstop"
    if s in ("EL00T00", "EL00D00"):
        return "T&D"
    if s.startswith("EL") and s.endswith("PH1") and len(s) == 7:
        return "Interconnector"
    if s.startswith("HYDSP"):
        return "Storage"
    if s.endswith("PI0"):       # gas pipelines to a neighbour (e.g. NGNGGHPI0): trade infrastructure, not a plant
        return "Other"
    return FAMILY.get(s[:3], "Other")


def read(res, name):
    return pd.read_csv(os.path.join(res, name + ".csv"))


def main(a):
    res, data, out = a.results, a.data, a.out
    os.makedirs(out, exist_ok=True)
    y0, y1 = a.window

    prod = read(res, "ProductionByTechnologyAnnual")
    use = read(res, "UseByTechnologyAnnual")
    capex = read(res, "CapitalInvestment")
    newcap = read(res, "NewCapacity")
    fixed = read(res, "AnnualFixedOperatingCost")
    var = read(res, "AnnualVariableOperatingCost")
    tech_em = read(res, "AnnualTechnologyEmission")
    ann_em = read(res, "AnnualEmissions")
    life = pd.read_csv(os.path.join(data, "OperationalLife.csv")).rename(columns={"TECHNOLOGY": "t", "VALUE": "life"})[["t", "life"]]
    ear = pd.read_csv(os.path.join(data, "EmissionActivityRatio.csv"))
    oar = pd.read_csv(os.path.join(data, "OutputActivityRatio.csv"))
    pen_path = os.path.join(data, "EmissionsPenalty.csv")
    pen = pd.read_csv(pen_path) if os.path.exists(pen_path) else pd.DataFrame()

    techs = pd.Series(sorted(set(prod.t) | set(capex.t) | set(use.t)), name="t").to_frame()
    techs["cat"] = techs.t.map(categorize)
    techs["country"] = techs.t.str[:2]
    techs.to_csv(os.path.join(out, "tech_categories.csv"), index=False)
    cat = techs.set_index("t")["cat"]
    gen_techs = set(techs.loc[techs.cat.isin(GEN_CATEGORIES), "t"])

    # ---- generation (E1 output of generators), imports (E1 output of interconnectors) --------------------
    e1 = prod[prod.f.str[2:] == "E1"].copy()
    e1["country"] = e1.f.str[:2]
    e1["cat"] = e1.t.map(cat)
    gen = e1[e1.cat.isin(GEN_CATEGORIES)].copy()
    gen["GWh"] = gen.ProductionByTechnologyAnnual * PJ_TO_GWH
    mix = gen.groupby(["country", "y", "cat"], as_index=False)["GWh"].sum()
    imp = e1[e1.cat == "Interconnector"].copy()
    imp["exporter"] = [t[4:6] if t[:2] == c else t[:2] for t, c in zip(imp.t, imp.country)]
    imp["GWh"] = imp.ProductionByTechnologyAnnual * PJ_TO_GWH
    imports = imp.groupby(["country", "exporter", "y"], as_index=False)["GWh"].sum()
    backstop = e1[e1.cat == "Backstop"].groupby(["country", "y"])["ProductionByTechnologyAnnual"].sum() * PJ_TO_GWH

    # installed capacity of generators (paper: RES = renewable installed capacity / total installed capacity)
    tcap = read(res, "TotalCapacityAnnual")
    tcap = tcap[tcap.t.isin(gen_techs)].copy()
    tcap["country"] = tcap.t.str[:2]
    tcap["cat"] = tcap.t.map(cat)
    cap_y = tcap.groupby(["country", "y"])["TotalCapacityAnnual"].sum().rename("cap_GW")
    rencap_y = tcap[tcap.cat.isin(RENEWABLE)].groupby(["country", "y"])["TotalCapacityAnnual"].sum().rename("ren_cap_GW")

    gen_y = gen.groupby(["country", "y"])["GWh"].sum().rename("gen_GWh")
    ren_y = gen[gen.cat.isin(RENEWABLE)].groupby(["country", "y"])["GWh"].sum().rename("ren_GWh")

    # ---- emissions of the power plants -----------------------------------------------------------------
    # fuel emission factors (Mt/PJ) from the supply technologies, by fuel type (NG, LF, HF, CO, ...)
    co2 = ear[ear.EMISSION.str.endswith("CO2")].rename(columns={"TECHNOLOGY": "t", "VALUE": "ear"})
    o = oar.rename(columns={"TECHNOLOGY": "t", "FUEL": "f", "VALUE": "oar"})
    sup = co2.merge(o, on=["t", "MODE_OF_OPERATION", "YEAR"])
    sup = sup[(sup.ear > 0) & (sup.f.str[2:].str.len() == 2)]
    sup["ef"] = sup.ear / sup.oar
    fuel_ef = sup.groupby(sup.f.str[2:])["ef"].median()
    fuel_ef.rename("MtCO2_per_PJ").to_csv(os.path.join(out, "fuel_emission_factors.csv"))

    u = use[use.t.isin(gen_techs)].copy()
    u["country"] = u.t.str[:2]
    u["fuel"] = u.f.str[2:]
    u["fuel_em"] = u.UseByTechnologyAnnual * u.fuel.map(fuel_ef).fillna(0.0)
    plant_own = tech_em[tech_em.t.isin(gen_techs)].copy()
    plant_own["country"] = plant_own.t.str[:2]
    em_fuel = u.groupby(["country", "y"])["fuel_em"].sum().rename("em_fuel")
    em_own = plant_own.groupby(["country", "y"])["AnnualTechnologyEmission"].sum().rename("em_plant_own")

    # ---- yearly table ------------------------------------------------------------------------------------
    yr = pd.concat([gen_y, ren_y, cap_y, rencap_y, em_fuel, em_own], axis=1).fillna(0.0).reset_index()
    yr["ren_share_cap"] = yr.ren_cap_GW / yr.cap_GW.replace(0, np.nan)
    yr["em_gen_Mt"] = yr.em_fuel + yr.em_plant_own
    yr["EF_gen_gCO2_kWh"] = np.where(yr.gen_GWh > 0, yr.em_gen_Mt * 1e6 / yr.gen_GWh, np.nan)
    ref = yr.set_index(["country", "y"])
    imp2 = imports.copy()
    imp2["exp_EF"] = [ref["EF_gen_gCO2_kWh"].get((x, y), np.nan) for x, y in zip(imp2.exporter, imp2.y)]
    imp2["exp_ren"] = [(ref["ren_GWh"].get((x, y), 0) / ref["gen_GWh"].get((x, y), np.nan)) for x, y in zip(imp2.exporter, imp2.y)]
    imp2["imp_em_Mt"] = imp2.GWh * imp2.exp_EF.fillna(imp2.exp_EF.mean()) / 1e6
    imp2["imp_ren_GWh"] = imp2.GWh * imp2.exp_ren.fillna(0)
    imp_y = imp2.groupby(["country", "y"]).agg(imports_GWh=("GWh", "sum"), imp_em_Mt=("imp_em_Mt", "sum"),
                                                imp_ren_GWh=("imp_ren_GWh", "sum")).reset_index()
    yr = yr.merge(imp_y, on=["country", "y"], how="left").fillna({"imports_GWh": 0, "imp_em_Mt": 0, "imp_ren_GWh": 0})
    yr["EF_grid_gCO2_kWh"] = (yr.em_gen_Mt + yr.imp_em_Mt) * 1e6 / (yr.gen_GWh + yr.imports_GWh).replace(0, np.nan)
    yr["ren_share_gen"] = yr.ren_GWh / yr.gen_GWh.replace(0, np.nan)
    yr["ren_share_grid"] = (yr.ren_GWh + yr.imp_ren_GWh) / (yr.gen_GWh + yr.imports_GWh).replace(0, np.nan)
    ae = ann_em[ann_em.e.str.endswith("CO2")].copy()
    ae["country"] = ae.e.str[:2]
    yr = yr.merge(ae.groupby(["country", "y"], as_index=False)["AnnualEmissions"].sum().rename(
        columns={"AnnualEmissions": "AETOS_AnnualEmissions_Mt"}), on=["country", "y"], how="left")
    yr["backstop_GWh"] = [backstop.get((c, y), 0.0) for c, y in zip(yr.country, yr.y)]

    # ---- costs & LCOE over the window ---------------------------------------------------------------------
    def gsum(df, col, name):
        d = df[df.t.isin(gen_techs)].copy()
        d["country"] = d.t.str[:2]
        return d.groupby(["country", "y"])[col].sum().rename(name)

    # fuel unit cost = variable cost of the techs producing the fuel / their production (per country, fuel, year)
    pv = prod.merge(var, on=["t", "y"], how="left").fillna({"AnnualVariableOperatingCost": 0})
    fuel_nodes = pv[~pv.f.str[2:].str.match(r"^E\d$|^BATF$|^PSF$|^NGE$")].copy()
    node = fuel_nodes.groupby(["f", "y"]).agg(cost=("AnnualVariableOperatingCost", "sum"), amount=("ProductionByTechnologyAnnual", "sum")).reset_index()
    node["unit_cost"] = np.where(node.amount > 0, node.cost / node.amount, 0.0)
    u2 = u.merge(node[["f", "y", "unit_cost"]], on=["f", "y"], how="left").fillna({"unit_cost": 0})
    u2["fuel_cost"] = u2.UseByTechnologyAnnual * u2.unit_cost
    fuel_cost = u2.groupby(["country", "y"])["fuel_cost"].sum().rename("fuel_cost")
    pen_cost = pd.Series(0.0, index=yr.set_index(["country", "y"]).index, name="pen_cost")
    if len(pen):
        p = pen[pen.EMISSION.str.endswith("CO2")].copy()
        p["country"] = p.EMISSION.str[:2]
        pmap = p.set_index(["country", "YEAR"])["VALUE"]
        pen_cost = pd.Series([pmap.get((c, y), 0.0) * e for c, y, e in zip(yr.country, yr.y, yr.em_gen_Mt)],
                             index=pen_cost.index, name="pen_cost")

    ci = capex[capex.t.isin(gen_techs)].merge(life, on="t", how="left")
    ci["life"] = ci["life"].fillna(30)
    ci = ci[(ci.y >= y0) & (ci.y <= y1)]
    ci["used"] = (y1 - ci.y + 1) % ci.life
    ci["salvage"] = ci.CapitalInvestment * (1 - ci.used / ci.life)
    ci["country"] = ci.t.str[:2]
    ci_y = ci.groupby(["country", "y"])[["CapitalInvestment", "salvage"]].sum()

    costs = pd.concat([ci_y, gsum(fixed, "AnnualFixedOperatingCost", "fixed"),
                       gsum(var, "AnnualVariableOperatingCost", "var_plants"), fuel_cost, pen_cost],
                      axis=1).fillna(0.0).reset_index()
    costs = costs[(costs.y >= y0) & (costs.y <= y1)]
    costs["OM"] = costs.fixed + costs.var_plants + costs.fuel_cost + costs.pen_cost
    costs = costs.merge(yr[["country", "y", "gen_GWh", "imports_GWh"]], on=["country", "y"], how="left").fillna(0)
    df = (1 + a.discount) ** -(costs.y - y0)
    costs["disc_cost"] = (costs.CapitalInvestment - costs.salvage + costs.OM) * df
    costs["disc_gen"] = costs.gen_GWh * df
    lc = costs.groupby("country")[["disc_cost", "disc_gen"]].sum()
    lc["LCOE_gen_USD_kWh"] = lc.disc_cost / lc.disc_gen.replace(0, np.nan)

    imp_w = imports[(imports.y >= y0) & (imports.y <= y1)].copy()
    imp_w["rate"] = imp_w.exporter.map(lc.LCOE_gen_USD_kWh).fillna(lc.LCOE_gen_USD_kWh.mean())
    imp_w["cost"] = imp_w.GWh * imp_w.rate * a.import_cost_factor
    imp_w["df"] = (1 + a.discount) ** -(imp_w.y - y0)
    imp_c = imp_w.assign(dc=imp_w.cost * imp_w.df, de=imp_w.GWh * imp_w.df).groupby("country")[["dc", "de"]].sum()
    lc = lc.join(imp_c).fillna(0)
    lc["LCOE_grid_USD_kWh"] = (lc.disc_cost + lc.dc) / (lc.disc_gen + lc.de).replace(0, np.nan)

    nc = newcap[newcap.t.isin(gen_techs) & (newcap.y >= y0) & (newcap.y <= y1)].copy()
    nc["country"] = nc.t.str[:2]
    cap = pd.concat([ci_y.reset_index().groupby("country")["CapitalInvestment"].sum(),
                     nc.groupby("country")["NewCapacity"].sum()], axis=1).fillna(0)
    cap["CapCost_USD_kW"] = cap.CapitalInvestment / cap.NewCapacity.replace(0, np.nan)

    w = yr[(yr.y >= y0) & (yr.y <= y1)]
    per = w.groupby("country").agg(gen_GWh=("gen_GWh", "sum"), ren_GWh=("ren_GWh", "sum"), imports_GWh=("imports_GWh", "sum"),
                                   imp_ren_GWh=("imp_ren_GWh", "sum"), em_gen_Mt=("em_gen_Mt", "sum"), imp_em_Mt=("imp_em_Mt", "sum"))
    per["EF_gen_gCO2_kWh"] = per.em_gen_Mt * 1e6 / per.gen_GWh.replace(0, np.nan)
    per["EF_grid_gCO2_kWh"] = (per.em_gen_Mt + per.imp_em_Mt) * 1e6 / (per.gen_GWh + per.imports_GWh).replace(0, np.nan)
    per["ren_share_gen"] = per.ren_GWh / per.gen_GWh.replace(0, np.nan)
    per["ren_share_grid"] = (per.ren_GWh + per.imp_ren_GWh) / (per.gen_GWh + per.imports_GWh).replace(0, np.nan)
    per["ren_share_cap"] = yr[yr.y == y1].set_index("country")["ren_share_cap"]   # capacity-based, at the window's last year
    period = per.join(lc[["LCOE_gen_USD_kWh", "LCOE_grid_USD_kWh"]]).join(cap[["CapCost_USD_kW"]])
    period = period.rename(columns={"LCOE_grid_USD_kWh": "GridGenerationCost", "EF_grid_gCO2_kWh": "GridEmissionFactor",
                                    "CapCost_USD_kW": "GridCapacityInvestmentCost", "ren_share_cap": "GridRenShare",
                                    "ren_share_grid": "ren_share_grid_energy"})
    period["window"] = f"{y0}-{y1}"

    keep = a.countries
    for name, d in (("generation_mix", mix), ("metrics_yearly", yr), ("imports", imports)):
        d = d[d.country.isin(keep)] if keep else d
        d.to_csv(os.path.join(out, name + ".csv"), index=False)
    pp = period.loc[[c for c in period.index if (not keep or c in keep)]]
    pp.round(5).to_csv(os.path.join(out, "metrics_period.csv"))
    pd.set_option("display.width", 250, "display.max_columns", 30)
    print(pp[["GridGenerationCost", "LCOE_gen_USD_kWh", "GridEmissionFactor", "EF_gen_gCO2_kWh",
              "GridCapacityInvestmentCost", "GridRenShare", "ren_share_gen"]].round(4).to_string())
    print("written to", out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--countries", nargs="*", default=["NG", "ZM"], help="empty = all")
    ap.add_argument("--window", nargs=2, type=int, default=[2025, 2040])
    ap.add_argument("--discount", type=float, default=0.08)
    ap.add_argument("--import-cost-factor", type=float, default=1.5)
    main(ap.parse_args())
