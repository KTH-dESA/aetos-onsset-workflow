"""World Bank shadow price of carbon -> one yearly series in constant 2021 USD, used by AETOS and OnSSET alike.

Source: World Bank (2024), Guidance Note on the Shadow Price of Carbon in Economic Analysis; table in constant 2017 USD
per t CO2e, 2017-2050, low and high trajectories (pasted below). The study uses the HIGH trajectory.
Conversion to 2021 USD (AETOS costs are constant 2021 USD): multiply by the US CPI-U ratio 2021/2017
(annual averages 270.970 / 245.120 = 1.1055, BLS). Change with --usd-factor if you prefer another deflator.
Years after 2050 are not needed (the models end in 2045).

    python scripts/make_carbon_price.py [--case high|low] [--usd-factor 1.1055] [--out data/carbon_price_wb_high_2021usd.csv]
Output columns: YEAR, VALUE (USD2021/t CO2), VALUE_2017USD.
"""
import argparse
import pandas as pd

YEARS = list(range(2017, 2051))
LOW = [37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 55, 56, 57, 58, 60, 61, 63, 64, 65, 67, 68, 70, 71, 73, 75, 76, 78]
HIGH = [75, 77, 78, 80, 82, 84, 86, 87, 89, 91, 94, 96, 98, 100, 102, 105, 107, 109, 112, 114, 117, 120, 122, 125, 128, 131, 134, 137, 140, 143, 146, 149, 153, 156]

ap = argparse.ArgumentParser()
ap.add_argument("--case", choices=["high", "low"], default="high")
ap.add_argument("--usd-factor", type=float, default=270.970 / 245.120)
ap.add_argument("--out", default=None)
a = ap.parse_args()
v = HIGH if a.case == "high" else LOW
assert len(v) == len(YEARS)
df = pd.DataFrame({"YEAR": YEARS, "VALUE_2017USD": v})
df["VALUE"] = (df.VALUE_2017USD * a.usd_factor).round(3)
out = a.out or f"data/carbon_price_wb_{a.case}_2021usd.csv"
df[["YEAR", "VALUE", "VALUE_2017USD"]].to_csv(out, index=False)
print(f"wrote {out}  (factor {a.usd_factor:.4f})")
print(df[df.YEAR.isin([2025, 2030, 2035, 2040, 2045])].to_string(index=False))
