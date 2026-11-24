"""Extract the African block of AETOS from its otoole CSV folder.

AETOS is a single-region OSeMOSYS model ("REGION1") in which the country is the 2-letter ISO
prefix of every technology / fuel / emission / storage code (e.g. ZMHYDMSH1, ZME3, ZMCO2).
Cross-border links (interconnectors, pipelines) are ordinary technologies that take in and put out
the fuels of BOTH countries (ESELMAPH1: ESE1 <-> MAE1).

Rule: keep a technology iff its own prefix AND the prefix of every fuel it consumes/produces is
African. Everything that touches a European (or other non-African) code is cut. Fuels, emissions
and storages are kept iff their prefix is African. Every other CSV is filtered row-wise on the
TECHNOLOGY / FUEL / EMISSION / STORAGE columns it carries.

The model file declares a copy of YearlyPeak<XX> and <XX>ReserveMarginTagTechnology for every
country, so those files are KEPT for European countries but emptied (header only). The model file
and otoole config can then be used unchanged.

Usage:
    python extract_africa.py <aetos CSVFiles dir> <out dir> [--report <dir>]
"""
import argparse
import os
import sys

import pandas as pd

AFRICA = set("""AO BF BI BJ BW CD CF CG CI CM DJ DZ EG ER ET GA GH GM GN GQ GW KE LR LS LY MA ML MR MW
MZ NA NE NG RW SD SL SN SO SS SZ TD TG TN TZ UG ZA ZM ZW""".split())
SET_FILES = {"TECHNOLOGY": "TECHNOLOGY", "FUEL": "FUEL", "EMISSION": "EMISSION", "STORAGE": "STORAGE"}
ACTIVITY_FILES = ("InputActivityRatio.csv", "OutputActivityRatio.csv")


def read(path):
    # strings only, so numbers are written back exactly as they were read
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def main(src, out, report, last_year=None):
    os.makedirs(out, exist_ok=True)
    os.makedirs(report, exist_ok=True)
    files = sorted(f for f in os.listdir(src) if f.endswith(".csv"))

    sets = {k: read(os.path.join(src, k + ".csv"))["VALUE"] for k in SET_FILES
            if os.path.exists(os.path.join(src, k + ".csv"))}
    pref = lambda s: s[:2]

    # --- which fuels does each technology touch ---------------------------------------------
    touched = {}
    for f in ACTIVITY_FILES:
        df = read(os.path.join(src, f))
        for t, fuel in zip(df["TECHNOLOGY"], df["FUEL"]):
            touched.setdefault(t, set()).add(fuel)

    keep = {}
    rows = []
    for name, values in sets.items():
        keep[name] = set()
        for v in values:
            ok = pref(v) in AFRICA
            reason = "" if ok else "non-African prefix"
            if ok and name == "TECHNOLOGY":
                bad = sorted(x for x in touched.get(v, ()) if pref(x) not in AFRICA)
                if bad:
                    ok, reason = False, "touches non-African fuel(s): " + " ".join(bad)
            if ok:
                keep[name].add(v)
            else:
                rows.append((name, v, reason))
    dropped = pd.DataFrame(rows, columns=["set", "element", "reason"])
    dropped.to_csv(os.path.join(report, "dropped_elements.csv"), index=False)

    # cross-continent links: African-prefixed technologies that touch a non-African fuel, plus
    # non-African-prefixed ones that touch an African fuel
    links = []
    for t, fuels in touched.items():
        pr = {pref(x) for x in fuels} | {pref(t)}
        if pr & AFRICA and pr - AFRICA:
            links.append((t, " ".join(sorted(fuels))))
    pd.DataFrame(links, columns=["technology", "fuels"]).to_csv(
        os.path.join(report, "cut_links.csv"), index=False)

    # --- filter every file -------------------------------------------------------------------
    summary = []
    for f in files:
        df = read(os.path.join(src, f))
        n0 = len(df)
        stem = f[:-4]
        if last_year and stem == "YEAR":
            df = df[df["VALUE"].astype(int) <= last_year]
        elif last_year and "YEAR" in df.columns:
            df = df[df["YEAR"].astype(int) <= last_year]
        if stem in SET_FILES:
            df = df[df["VALUE"].isin(keep[stem])]
        elif stem.startswith("YearlyPeak") and stem[-2:] not in AFRICA:
            df = df.iloc[0:0]
        else:
            for col in SET_FILES:
                if col in df.columns:
                    df = df[df[col].isin(keep[col])]
        df.to_csv(os.path.join(out, f), index=False)
        summary.append((f, n0, len(df)))
    pd.DataFrame(summary, columns=["file", "rows_in", "rows_out"]).to_csv(
        os.path.join(report, "file_summary.csv"), index=False)

    # --- sanity checks -----------------------------------------------------------------------
    warn = []
    for f in ACTIVITY_FILES:
        df = read(os.path.join(out, f))
        for col in ("TECHNOLOGY", "FUEL"):
            miss = set(df[col]) - keep[col]
            if miss:
                warn.append(f"{f}: {col} not in kept set: {sorted(miss)[:5]}")
    prod = set(read(os.path.join(out, "OutputActivityRatio.csv"))["FUEL"])
    use = set(read(os.path.join(out, "InputActivityRatio.csv"))["FUEL"])
    demand = set(read(os.path.join(out, "SpecifiedAnnualDemand.csv"))["FUEL"]) if os.path.exists(
        os.path.join(out, "SpecifiedAnnualDemand.csv")) else set()
    orphan = sorted(f for f in keep["FUEL"] if f not in prod and (f in use or f in demand))
    if orphan:
        warn.append("fuels used/demanded but never produced after the cut: " + " ".join(orphan))
    unused = sorted(f for f in keep["FUEL"] if f in prod and f not in use and f not in demand)
    with open(os.path.join(report, "summary.txt"), "w") as fh:
        fh.write(f"kept: " + ", ".join(f"{k}={len(v)}" for k, v in keep.items()) + "\n")
        fh.write("dropped: " + ", ".join(
            f"{k}={(dropped['set'] == k).sum()}" for k in keep) + "\n")
        fh.write(f"cut links: {len(links)}\n")
        fh.write("WARNINGS:\n" + "\n".join(warn) + "\n")
        fh.write("fuels produced but with no consumer after the cut (check these): "
                 + " ".join(unused) + "\n")
    print(open(os.path.join(report, "summary.txt")).read())
    return 1 if warn else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--report", default=None)
    ap.add_argument("--last-year", type=int, default=None,
                    help="drop all years after this one (horizon cut; keep a margin beyond the reporting year)")
    a = ap.parse_args()
    sys.exit(main(a.src, a.out, a.report or os.path.join(a.out, "_extraction_report"), a.last_year))
