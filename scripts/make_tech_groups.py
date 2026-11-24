"""Classify every technology of the extracted AETOS-Africa data into cost-trajectory (CT) groups.

AETOS technology code = 2-letter country + 3-letter family + rest (e.g. ZM HYD MSH1). Fuels E1/E2/E3 are
generation bus / transmission / distribution. This script only labels; scripts that apply the CT multipliers
read its CSV, so the mapping can be reviewed and edited in one place.

Usage: python make_tech_groups.py <extracted csv dir> <out csv>
"""
import sys
import pandas as pd

# family (chars 3-5 of the code) -> (group, comment)
FAMILY = {
    # renewable generation -> 'Renewable CAPEX'
    "HYD": ("renewable", "hydro (MS = run-of-river/reservoir, SP = pumped storage)"),
    "SOC": ("renewable", "concentrated solar"),
    "SOU": ("renewable", "utility solar PV"),
    "WIN": ("renewable", "wind"),
    "GOC": ("renewable", "geothermal"),
    "BMC": ("renewable", "biomass (REVIEW: renewable or not)"),
    "BAT": ("renewable", "battery storage (REVIEW: renewable or not)"),
    # conventional grid generation -> 'Grid CAPEX' (generation part)
    "COC": ("grid_thermal", "coal with CCS"),
    "COS": ("grid_thermal", "coal"),
    "NGC": ("grid_thermal", "gas combined cycle (incl. CCS)"),
    "NGG": ("grid_thermal", "gas turbine"),
    "NUL": ("grid_thermal", "nuclear"),
    "HFG": ("grid_thermal", "heavy fuel oil (REVIEW: grid thermal or diesel)"),
    # diesel / light fuel oil generation -> 'Diesel CAPEX' / 'Diesel OPEX'
    "LFR": ("diesel", "light fuel oil / diesel generation"),
}
# technologies identified by full suffix after the country prefix
SUFFIX = {
    "LF00I00": ("diesel_fuel", "diesel/light fuel import; VariableCost = fuel price -> 'Diesel OPEX'"),
    "EL00T00": ("transmission", "E1->E2, carries no cost in AETOS"),
    "EL00D00": ("distribution", "E2->E3, carries no cost in AETOS"),
    "BACKSTOP": ("none", "backstop"),
    "CO2BACKSTOP": ("none", "backstop"),
    "NGBACKSTOP": ("none", "backstop"),
}


def classify(tech):
    s = tech[2:]
    if s in SUFFIX:
        return SUFFIX[s]
    fam = s[:3]
    if fam in FAMILY:
        return FAMILY[fam]
    # electricity interconnectors: ELxx PH1 (E1 -> E1 between two countries)
    if fam.startswith("EL") and s.endswith("PH1"):
        return ("interconnector", "cross-border power line (REVIEW: scaled with 'Grid CAPEX'?)")
    if fam.startswith("NG") and s.endswith("PI0"):
        return ("none", "gas pipeline")
    return ("none", "fuel import/extraction or other, not scaled")


def main(src, out):
    techs = pd.read_csv(f"{src}/TECHNOLOGY.csv")["VALUE"]
    cap = pd.read_csv(f"{src}/CapitalCost.csv")
    fix = pd.read_csv(f"{src}/FixedCost.csv")
    var = pd.read_csv(f"{src}/VariableCost.csv")
    rows = []
    for t in techs:
        g, c = classify(t)
        rows.append(dict(technology=t, country=t[:2], family=t[2:5], group=g,
                         has_capital_cost=t in set(cap.TECHNOLOGY),
                         has_fixed_cost=t in set(fix.TECHNOLOGY),
                         has_variable_cost=t in set(var.TECHNOLOGY), comment=c))
    df = pd.DataFrame(rows)
    df.to_csv(out, index=False)
    print(df.groupby(["group", "family"]).agg(
        n=("technology", "size"), countries=("country", "nunique"),
        capex=("has_capital_cost", "sum"), fixed=("has_fixed_cost", "sum"),
        variable=("has_variable_cost", "sum")).to_string())


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
