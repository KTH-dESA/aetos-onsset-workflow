"""Pull end-year population and urban-ratio projections from the World Bank API (source 40, "Population estimates
and projections", series SP.POP.TOTL and SP.URB.TOTL.IN.ZS, which run to 2050) and write the lookup that
refresh_specs.py reads.

To stay consistent with the 2025 values of the onstove table (the calibration base), the projection is used as a GROWTH:
    PopEndYear         = onstove Population_start_year * WB_pop(end) / WB_pop(start)
    UrbanRatioEndYear  = onstove Urban_start + (WB_urban(end) - WB_urban(start)) / 100
Raw World Bank values are kept in the output for checking.

    python pull_projections.py [--end-year 2040] [--start-year 2025] [--out onsset/projections_2040.csv]
"""
import argparse
import json
import os
import urllib.request

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def fetch(iso3s, indicator, years):
    out = {}
    for i in range(0, len(iso3s), 40):
        chunk = ";".join(iso3s[i:i + 40])
        url = (f"https://api.worldbank.org/v2/country/{chunk}/indicator/{indicator}"
               f"?source=40&date={years[0]}:{years[1]}&format=json&per_page=20000")
        with urllib.request.urlopen(url, timeout=60) as r:
            meta, rows = json.load(r)
        for x in rows or []:
            if x["value"] is not None:
                out[(x["countryiso3code"], int(x["date"]))] = float(x["value"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--onstove", default=os.path.join(ROOT, "onsset", "onstove_country_inputs_SSA.csv"))
    ap.add_argument("--start-year", type=int, default=2025)
    ap.add_argument("--end-year", type=int, default=2040)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    out = a.out or os.path.join(ROOT, "onsset", f"projections_{a.end_year}.csv")

    ons = pd.read_csv(a.onstove, keep_default_na=False).set_index("Country_code")
    iso3s = list(ons.index)
    yrs = (a.start_year, a.end_year)
    pop = fetch(iso3s, "SP.POP.TOTL", yrs)
    urb = fetch(iso3s, "SP.URB.TOTL.IN.ZS", yrs)

    rows, missing = [], []
    for c in iso3s:
        try:
            p0, p1 = pop[(c, a.start_year)], pop[(c, a.end_year)]
            u0, u1 = urb[(c, a.start_year)], urb[(c, a.end_year)]
        except KeyError:
            missing.append(c)
            continue
        rows.append(dict(Country_code=c, WB_pop_start=p0, WB_pop_end=p1, WB_urban_start=u0, WB_urban_end=u1,
                         PopEndYear=round(float(ons.loc[c, "Population_start_year"]) * p1 / p0),
                         UrbanRatioEndYear=round(float(ons.loc[c, "Urban_start"]) + (u1 - u0) / 100, 4)))
    df = pd.DataFrame(rows)
    df.to_csv(out, index=False)
    print(f"{len(df)} countries written to {out}; missing: {missing or 'none'}")
    df["pop_growth"] = df.WB_pop_end / df.WB_pop_start
    df["urban_gain_pts"] = df.WB_urban_end - df.WB_urban_start
    print(df[df.Country_code.isin(["ZMB", "NGA"])].round(3).T.to_string())
    print("pop growth range", df.pop_growth.min().round(2), df.pop_growth.max().round(2),
          "| urban gain range (pts)", df.urban_gain_pts.min().round(1), df.urban_gain_pts.max().round(1))


if __name__ == "__main__":
    main()
