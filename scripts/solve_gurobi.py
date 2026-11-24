"""Solve an OSeMOSYS LP file (written by glpsol --wlp) with Gurobi and write the solution.

Replaces the CPLEX step of AETOS_Runner/commands_AETOS.txt. Run in the gep_workflow env.

    python solve_gurobi.py model.lp out.sol [--status status.json] [--log gurobi.log]
                           [--threads N] [--method 2] [--crossover 0] [--keep-lp]

Defaults: barrier (Method=2) without crossover, which is the fast route for LPs of this size and is enough for
reading activity, capacity and cost results. Use --crossover 1 if a basic (vertex) solution is needed.
The LP file is deleted after a successful solve unless --keep-lp is given (it is regenerated from the datafile).
Exit code: 0 optimal, 2 infeasible/unbounded, 3 any other non-optimal status.
"""
import argparse
import json
import os
import sys
import time

import gurobipy as gp
from gurobipy import GRB


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lp")
    ap.add_argument("sol")
    ap.add_argument("--status", default=None)
    ap.add_argument("--log", default=None)
    ap.add_argument("--threads", type=int, default=0, help="0 = Gurobi decides")
    ap.add_argument("--method", type=int, default=2, help="2 = barrier")
    ap.add_argument("--crossover", type=int, default=0)
    ap.add_argument("--keep-lp", action="store_true")
    ap.add_argument("--memlimit", type=float, default=0, help="GB; Gurobi stops cleanly instead of swapping (0 = none)")
    ap.add_argument("--timelimit", type=float, default=0, help="seconds (0 = none)")
    a = ap.parse_args()

    os.makedirs(os.path.dirname(os.path.abspath(a.sol)), exist_ok=True)
    status_path = a.status or os.path.splitext(a.sol)[0] + "_status.json"
    log_path = a.log or os.path.splitext(a.sol)[0] + "_gurobi.log"

    t0 = time.time()
    env = gp.Env(empty=True)
    env.setParam("LogFile", log_path)
    env.start()
    m = gp.read(a.lp, env=env)
    t_read = time.time() - t0
    m.setParam("Method", a.method)
    m.setParam("Crossover", a.crossover)
    if a.threads:
        m.setParam("Threads", a.threads)
    if a.memlimit:
        m.setParam("MemLimit", a.memlimit)
    if a.timelimit:
        m.setParam("TimeLimit", a.timelimit)
    m.optimize()

    info = {"lp": a.lp, "status_code": m.Status, "read_seconds": round(t_read),
            "total_seconds": round(time.time() - t0), "rows": m.NumConstrs, "columns": m.NumVars,
            "nonzeros": m.NumNZs}
    if m.SolCount > 0:
        info["objective"] = m.ObjVal
        m.write(a.sol)
        info["solution_file"] = a.sol
    info["status"] = {GRB.OPTIMAL: "optimal", GRB.INFEASIBLE: "infeasible", GRB.UNBOUNDED: "unbounded",
                      GRB.INF_OR_UNBD: "infeasible_or_unbounded"}.get(m.Status, f"status_{m.Status}")
    with open(status_path, "w") as fh:
        json.dump(info, fh, indent=2)
    print(json.dumps(info, indent=2))

    if m.Status == GRB.OPTIMAL:
        if not a.keep_lp:
            os.remove(a.lp)
            print("deleted", a.lp)
        return 0
    return 2 if m.Status in (GRB.INFEASIBLE, GRB.UNBOUNDED, GRB.INF_OR_UNBD) else 3


if __name__ == "__main__":
    sys.exit(main())
