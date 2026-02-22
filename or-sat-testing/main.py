from __future__ import annotations

import sys
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple
import subprocess
from pathlib import Path

from ortools.sat.python import cp_model


# ---------- Helpers for your schema ----------

def quantity_bounds(q: Dict[str, Any]) -> Tuple[int, int]:
    """
    q is like {"Single": 1} or {"Many": {"from": 2, "to": 4}}
    Returns (min, max)
    """
    if "Single" in q:
        n = int(q["Single"])
        return n, n
    many = q["Many"]
    return int(many["from"]), int(many["to"])


def course_id(course: dict) -> str:
    code = course["codes"][0]
    season = course["season_codes"][0] if course.get("season_codes") else "NA"
    return f"{code}@{season}"

def base_key(course: dict) -> str:
    # e.g. "MATH 2250"
    return course["codes"][0]


# ---------- CP-SAT model ----------

def solve_no_double_count(matching_eval):
    """
    The model creates boolean decision variables for each course offering (x) 
    and for each course-requirement assignment (y), where a course can only be 
    assigned to a requirement if it's selected. Each requirement has a satisfaction 
    variable (sat) that enforces the quantity constraints (min/max courses needed) 
    and is set to false if no courses are assigned to it. Double-counting is prevented 
    by constraining each course to satisfy at most one requirement, with an additional 
    constraint grouping course variants by a base key so cross-listed or repeated courses 
    also can't fulfill multiple requirements. The solver maximizes a weighted objective 
    that heavily prioritizes satisfying more requirements (weight 10,000) and secondarily 
    minimizes total courses selected, with a 2-second time limit.
    """
    
    model = cp_model.CpModel()
    results = matching_eval["results"]

    def q_bounds(q):
        if "Single" in q:
            n = int(q["Single"])
            return n, n
        return int(q["Many"]["from"]), int(q["Many"]["to"])

    def cid(course):
        code = course["codes"][0]
        season = course["season_codes"][0] if course.get("season_codes") else "NA"
        return f"{code}@{season}"

    # Collect all offerings
    offerings = {}
    for c in matching_eval.get("allSelectedCourses", []):
        offerings[cid(c)] = c

    # Decision var: offering selected
    x = {c: model.NewBoolVar(f"x_{c.replace(' ','_').replace('@','_')}")
         for c in offerings.keys()}

    # Assignment vars: y[r,c] = counts toward requirement r
    y = {}  # (r,c) -> BoolVar
    req_cands = []
    sat = []

    for r, qr in enumerate(results):
        req = qr["requirement"]
        qmin, qmax = q_bounds(req["query"]["quantity"])

        cands = [cid(c) for c in qr["selectedCourses"]]
        req_cands.append(cands)

        # ensure any missing offerings get vars
        for c in qr["selectedCourses"]:
            k = cid(c)
            if k not in x:
                offerings[k] = c
                x[k] = model.NewBoolVar(f"x_{k.replace(' ','_').replace('@','_')}")

        # create y vars for this requirement's candidates
        for c in cands:
            y[(r, c)] = model.NewBoolVar(f"y_r{r}_{c.replace(' ','_').replace('@','_')}")
            model.Add(y[(r, c)] <= x[c])  # can only assign if selected

        sum_assigned = sum(y[(r, c)] for c in cands)

        s = model.NewBoolVar(f"sat_{r}")
        sat.append(s)

        # sat=1 => qmin <= assigned <= qmax
        model.Add(sum_assigned >= qmin).OnlyEnforceIf(s)
        model.Add(sum_assigned <= qmax).OnlyEnforceIf(s)

        # sat=0 => assigned == 0
        model.Add(sum_assigned == 0).OnlyEnforceIf(s.Not())

    # NO DOUBLE COUNTING:
    # each offering can satisfy at most one requirement
    for c in x.keys():
        used_by = [y[(r, c)] for r in range(len(results)) if (r, c) in y]
        if used_by:
            model.Add(sum(used_by) <= 1)

    base_to_y: dict[str, list[cp_model.IntVar]] = {}

    for (r, cid), var in y.items():
        course = offerings[cid]
        b = base_key(course)
        base_to_y.setdefault(b, []).append(var)

    for b, vars_ in base_to_y.items():
        model.Add(sum(vars_) <= 1)

    total_satisfied = sum(sat)
    total_courses = sum(x.values())

    M = 10_000
    model.Maximize(total_satisfied * M + total_courses)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 2.0
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {"status": "no_solution"}

    selected = [c for c, var in x.items() if solver.Value(var) == 1]

    per_req = []
    for r, qr in enumerate(results):
        chosen = [c for c in req_cands[r] if solver.Value(y[(r, c)]) == 1]
        per_req.append({
            "description": qr["requirement"]["description"],
            "priority": qr["requirement"]["priority"],
            "satisfied": solver.Value(sat[r]) == 1,
            "selected": chosen,
        })

    return {
        "status": "ok",
        "total_satisfied": solver.Value(total_satisfied),
        "total_courses": solver.Value(total_courses),
        "selected_courses": selected,
        "per_requirement": per_req,
    }
    

SCRIPT_LOCATION = Path(__file__).resolve()
INPUT_LOCATION = SCRIPT_LOCATION.parent.parent /"inputs" / "test"

if __name__ == "__main__":
    try:
        compiled_mql = subprocess.run(
            ["mql", f"{INPUT_LOCATION / "test.mql" }"],
            capture_output=True,
            check=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"Compilation failed with exit code {e.returncode}", file=sys.stderr)
        print(f"Error output (stderr): {e.stderr}", file=sys.stderr)
        exit(1)
    
    print("Compiled MQL")
    
    try:
        result = subprocess.run(
            ["npm", "run", "dev", "--silent"],
            check=True,
            input=compiled_mql.stdout,
            text=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"Matching failed with exit code {e.returncode}", file=sys.stderr)
        print(f"Error output (stderr): {e.stderr}", file=sys.stderr)
        exit(2)

    print("Found required courses")
    
    for object in json.loads(result.stdout):
        print(json.dumps(object, indent=2))

        sol = solve_no_double_count(object)
        print(json.dumps(sol, indent=2))