"""Turn the extracted AETOS-Africa dataset (UNNZ test scenario) into a GEP scenario.

What it changes (everything else stays as AETOS has it):
 1. Emission caps off:   AnnualEmissionLimit = 9999 everywhere, ModelPeriodEmissionLimit empty,
                         AnnualExogenousEmission = 0 (the exogenous values are only used against the caps).
 2. Carbon price:        --carbon-tax adds TEMBA-GEP's EmissionsPenalty (USD/t CO2, same for every country,
                         from the `*_CT_high.xlsx` scenario files) to every <CC>CO2 emission. Years after TEMBA's
                         last year (2040) repeat the 2040 value.
 3. Demand (SpecifiedAnnualDemand) for the study countries: replaced by TEMBA's existing-user demand
                         (<ISO3>EL3E, PJ) for the model years; years beyond TEMBA's 2040 continue with the average
                         yearly change of 2036-2040. Optionally `--new-demand file.csv` (columns CC,YEAR,VALUE in PJ)
                         is added on top: that is the OnSSET grid demand of newly connected people.
                         Other countries keep AETOS's demand. The hourly profile (SpecifiedDemandProfile) is kept.

    python make_gep_scenario.py <extracted dir> <out dir> [--carbon-tax] [--new-demand file.csv] [--carbon-price-csv file.csv]
                                [--baseline aetos]   (the legacy --baseline temba also needs --temba <TEMBA-GEP repo>)
"""
import argparse
import os
import shutil

import pandas as pd


def main(src, out, temba, carbon_tax, countries, new_demand, carbon_price_csv=None, baseline="aetos"):
    if os.path.exists(out):
        shutil.rmtree(out)
    shutil.copytree(src, out)
    p = lambda f: os.path.join(out, f + ".csv")
    log = []

    # 1. caps off ------------------------------------------------------------------------------
    lim = pd.read_csv(p("AnnualEmissionLimit"))
    log.append(f"AnnualEmissionLimit: {int((lim.VALUE < 9999).sum())} binding rows set to 9999")
    lim["VALUE"] = 9999.0
    lim.to_csv(p("AnnualEmissionLimit"), index=False)
    exo = pd.read_csv(p("AnnualExogenousEmission"))
    log.append(f"AnnualExogenousEmission: {int((exo.VALUE != 0).sum())} non-zero rows set to 0")
    exo["VALUE"] = 0.0
    exo.to_csv(p("AnnualExogenousEmission"), index=False)

    years = sorted(pd.read_csv(p("YEAR"))["VALUE"].astype(int))
    scen = os.path.join(temba, "input_data", "Scenarios") if temba else None

    # 2. carbon price --------------------------------------------------------------------------
    pen = pd.read_csv(p("EmissionsPenalty"))
    if carbon_tax:
        ref = pd.read_csv(carbon_price_csv).set_index("YEAR")["VALUE"]      # make_carbon_price.py, USD2021/t
        price = {y: float(ref[y] if y in ref.index else ref[ref.index.max()]) for y in years}
        em = pd.read_csv(p("EMISSION"))["VALUE"]
        em = [e for e in em if len(e) == 5 and e.endswith("CO2")]
        pen = pd.DataFrame([("REGION1", e, y, price[y]) for e in em for y in years],
                           columns=["REGION", "EMISSION", "YEAR", "VALUE"])
        log.append(f"EmissionsPenalty: {len(em)} CO2 emissions, {price[years[0]]:.1f} -> {price[years[-1]]:.1f} USD/t")
    else:
        pen = pen.iloc[0:0]
        log.append("EmissionsPenalty: none (no carbon tax)")
    pen.to_csv(p("EmissionsPenalty"), index=False)

    # 3. demand --------------------------------------------------------------------------------
    d = pd.read_csv(p("SpecifiedAnnualDemand"))
    base = None
    if baseline == "temba":                               # legacy design only: needs a TEMBA-GEP checkout (--temba)
        base = pd.read_excel(os.path.join(scen, "Low.xlsx"), sheet_name="SpecifiedAnnualDemand").set_index("FUEL")
    new = pd.read_csv(new_demand, keep_default_na=False) if new_demand else None   # keep_default_na: ISO2 "NA" = Namibia
    if baseline == "aetos":
        # option C: AETOS's own demand is the baseline of every country; the OnSSET new-user demand (PJ, stock) is added
        if new is None:
            log.append("SpecifiedAnnualDemand: AETOS baseline, no OnSSET demand added")
        else:
            for c2 in sorted(new.CC.unique()):
                mask = d.FUEL == c2 + "E3"
                if not mask.any():
                    log.append(f"SpecifiedAnnualDemand {c2}E3: not in AETOS, OnSSET demand NOT added")
                    continue
                n = new[new.CC == c2].set_index("YEAR")["VALUE"]
                d.loc[mask, "VALUE"] = d.loc[mask, "VALUE"].to_numpy() + d.loc[mask, "YEAR"].map(n).fillna(0.0).to_numpy()
            tot = d[d.FUEL.str.endswith("E3")].groupby("YEAR").VALUE.sum() / 3.6
            log.append(f"SpecifiedAnnualDemand: AETOS + OnSSET new users, all countries {tot.get(2025, 0):.0f} (2025), "
                       f"{tot.get(2030, 0):.0f} (2030), {tot.get(2040, 0):.0f} (2040) TWh")
        countries = []
    for c2, c3 in countries:
        s = base.loc[c3 + "EL3E"]
        tail = s[[2036, 2037, 2038, 2039, 2040]]
        slope = (tail.iloc[-1] - tail.iloc[0]) / 4
        vals = {y: float(s[y]) if y in s.index else float(s[2040] + slope * (y - 2040)) for y in years}
        if new is not None:
            n = new[new.CC == c2].set_index("YEAR")["VALUE"]
            vals = {y: vals[y] + float(n.get(y, 0.0)) for y in years}
        d = d[d.FUEL != c2 + "E3"]
        d = pd.concat([d, pd.DataFrame([("REGION1", c2 + "E3", y, vals[y]) for y in years], columns=d.columns)])
        log.append(f"SpecifiedAnnualDemand {c2}E3 <- TEMBA {c3}EL3E{' + OnSSET new demand' if new is not None else ''}: "
                   f"{vals[years[0]]:.1f} PJ ({years[0]}) .. {vals[2040]:.1f} (2040) .. {vals[years[-1]]:.1f} ({years[-1]})")
    d.to_csv(p("SpecifiedAnnualDemand"), index=False)

    with open(os.path.join(out, "_scenario_log.txt"), "w") as fh:
        fh.write("\n".join(log) + "\n")
    print("\n".join(log))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--temba", default=None, help="TEMBA-GEP repo; only for the legacy --baseline temba")
    ap.add_argument("--carbon-tax", action="store_true")
    ap.add_argument("--carbon-price-csv", default="data/carbon_price_wb_high_2021usd.csv")
    ap.add_argument("--countries", nargs="*", default=["NG:NGA", "ZM:ZMB"])
    ap.add_argument("--new-demand", default=None)
    ap.add_argument("--baseline", choices=["aetos", "temba"], default="aetos",
                    help="aetos (default, option C) = keep AETOS's demand of every country and add --new-demand; "
                         "temba = replace the --countries' demand by TEMBA's EL3E (earlier design)")
    a = ap.parse_args()
    main(a.src, a.out, a.temba, a.carbon_tax, [c.split(":") for c in a.countries], a.new_demand, a.carbon_price_csv, a.baseline)
