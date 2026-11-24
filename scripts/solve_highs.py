"""Solve an OSeMOSYS LP file (written by glpsol --wlp) with HiGHS (open source) and write the solution.

Free alternative to solve_gurobi.py: no licence needed. Writes the same plain "name value" solution file, so the next step
(gurobi_sol_to_results.py) is unchanged. Run in the gep_workflow env (pip install highspy).

    python solve_highs.py model.lp out.sol [--status status.json] [--log highs.log] [--threads N] [--solver ipm]
                          [--keep-lp] [--timelimit SECONDS]

Defaults: interior-point method without crossover (same idea as the Gurobi barrier route). The --memlimit option of the
other solve_* scripts is accepted and ignored (HiGHS has no memory limit). Exit code: 0 optimal, 2 infeasible/unbounded,
3 any other status. NOTE: not used for the study results (Gurobi was) and not tested on the full-size LPs; expect longer
run times and higher memory use.
"""
import argparse
import json
import os
import sys
import time

import highspy


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lp")
    ap.add_argument("sol")
    ap.add_argument("--status", default=None)
    ap.add_argument("--log", default=None)
    ap.add_argument("--threads", type=int, default=0, help="0 = HiGHS decides")
    ap.add_argument("--solver", default="ipm", choices=["ipm", "simplex", "choose"])
    ap.add_argument("--keep-lp", action="store_true")
    ap.add_argument("--memlimit", type=float, default=0, help="ignored (kept for a common command line)")
    ap.add_argument("--timelimit", type=float, default=0, help="seconds (0 = none)")
    a = ap.parse_args()

    os.makedirs(os.path.dirname(os.path.abspath(a.sol)), exist_ok=True)
    status_path = a.status or os.path.splitext(a.sol)[0] + "_status.json"
    log_path = a.log or os.path.splitext(a.sol)[0] + "_highs.log"

    t0 = time.time()
    h = highspy.Highs()
    h.setOptionValue("log_file", log_path)
    h.setOptionValue("solver", a.solver)
    h.setOptionValue("run_crossover", "off")
    if a.threads:
        h.setOptionValue("threads", a.threads)
    if a.timelimit:
        h.setOptionValue("time_limit", a.timelimit)
    h.readModel(a.lp)
    t_read = time.time() - t0
    h.run()
    status = h.modelStatusToString(h.getModelStatus()).lower()
    lp = h.getLp()
    info = {"lp": a.lp, "status": status, "read_seconds": round(t_read), "total_seconds": round(time.time() - t0),
            "rows": lp.num_row_, "columns": lp.num_col_}
    ok = status == "optimal"
    if ok:
        info["objective"] = h.getInfo().objective_function_value
        values = h.getSolution().col_value
        with open(a.sol, "w") as fh:                       # "name value", as Gurobi writes it
            for i in range(lp.num_col_):
                fh.write(f"{h.getColName(i)[1]} {values[i]:.12g}\n")
        info["solution_file"] = a.sol
    with open(status_path, "w") as fh:
        json.dump(info, fh, indent=2)
    print(json.dumps(info, indent=2))
    if ok:
        if not a.keep_lp:
            os.remove(a.lp)
            print("deleted", a.lp)
        return 0
    return 2 if "infeasible" in status or "unbounded" in status else 3


if __name__ == "__main__":
    sys.exit(main())
