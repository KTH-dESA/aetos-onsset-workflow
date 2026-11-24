"""Solve an OSeMOSYS LP file (written by glpsol --wlp) with IBM CPLEX and write the solution.

Scripted version of the interactive `cplex` session in AETOS_Runner/commands_AETOS.txt (read / optimize / write). Needs a CPLEX
licence: the free Community Edition is limited to 1000 variables/constraints, far below the size of an AETOS LP. Writes the same
plain "name value" solution file as the other solve_* scripts, so the next step (gurobi_sol_to_results.py) is unchanged.
Run in an environment with the `cplex` python package (pip install cplex).

    python solve_cplex.py model.lp out.sol [--status status.json] [--log cplex.log] [--threads N] [--keep-lp]

Barrier without crossover. --memlimit (GB) is passed as CPLEX's working-memory limit. Exit code: 0 optimal,
2 infeasible/unbounded, 3 any other status. NOTE: not used for the study results (Gurobi was) and not tested here.
"""
import argparse
import json
import os
import sys
import time

import cplex


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lp")
    ap.add_argument("sol")
    ap.add_argument("--status", default=None)
    ap.add_argument("--log", default=None)
    ap.add_argument("--threads", type=int, default=0, help="0 = CPLEX decides")
    ap.add_argument("--keep-lp", action="store_true")
    ap.add_argument("--memlimit", type=float, default=0, help="GB, working memory (0 = none)")
    ap.add_argument("--timelimit", type=float, default=0, help="seconds (0 = none)")
    a = ap.parse_args()

    os.makedirs(os.path.dirname(os.path.abspath(a.sol)), exist_ok=True)
    status_path = a.status or os.path.splitext(a.sol)[0] + "_status.json"
    log_path = a.log or os.path.splitext(a.sol)[0] + "_cplex.log"

    t0 = time.time()
    c = cplex.Cplex()
    log = open(log_path, "w")
    for stream in (c.set_log_stream, c.set_results_stream, c.set_warning_stream, c.set_error_stream):
        stream(log)
    c.read(a.lp)
    t_read = time.time() - t0
    c.parameters.lpmethod.set(c.parameters.lpmethod.values.barrier)
    c.parameters.solutiontype.set(c.parameters.solutiontype.values.nonbasic)      # barrier without crossover
    if a.threads:
        c.parameters.threads.set(a.threads)
    if a.memlimit:
        c.parameters.workmem.set(a.memlimit * 1024)
    if a.timelimit:
        c.parameters.timelimit.set(a.timelimit)
    c.solve()
    status = c.solution.get_status_string()
    info = {"lp": a.lp, "status": status, "read_seconds": round(t_read), "total_seconds": round(time.time() - t0),
            "rows": c.linear_constraints.get_num(), "columns": c.variables.get_num()}
    ok = "optimal" in status.lower()
    if ok:
        info["objective"] = c.solution.get_objective_value()
        with open(a.sol, "w") as fh:                       # "name value", as Gurobi writes it
            for name, v in zip(c.variables.get_names(), c.solution.get_values()):
                fh.write(f"{name} {v:.12g}\n")
        info["solution_file"] = a.sol
    with open(status_path, "w") as fh:
        json.dump(info, fh, indent=2)
    print(json.dumps(info, indent=2))
    if ok:
        if not a.keep_lp:
            os.remove(a.lp)
            print("deleted", a.lp)
        return 0
    return 2 if "infeasible" in status.lower() or "unbounded" in status.lower() else 3


if __name__ == "__main__":
    sys.exit(main())
