import sys
import json
from typing import Any, Dict, Tuple
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


def course_id(course: dict, use_seasons: bool = False) -> str:
    code = course["codes"][0]
    if use_seasons:
        season = course["season_codes"][0] if course.get("season_codes") else "NA"
        return f"{code}@{season}"
    else:
        return code


def base_key(course: dict) -> str:
    return course["codes"][0]


def q_bounds(q):
        if "Single" in q:
            n = int(q["Single"])
            return n, n
        return int(q["Many"]["from"]), int(q["Many"]["to"])


# ---------- CP-SAT model ----------

def solve_no_double_count(matching_eval):
    """
    ## Classes are not double counted
    
    Classes are consumed by each constraint.
    
    ## Fills the most important priorities first (non-negotiable)
    
    Eg.
    ```mql
    @1 -- SELECT 2 FROM [SELECT 1 FROM CLASS(MATH 2250), SELECT 1 FROM CLASS(MATH 2260)] : "must take a linear algebra" : 1;
    @2 -- SELECT 1 FROM CLASS(MATH 2260) : "must take a hard linear algebra" : 2;
    ```
    
    will partially fill MATH 2250 for @1 (failing) and MATH 2260 for @2 (passing).
    
    ## 
    """
    
    model = cp_model.CpModel()
    results = matching_eval["results"]

    # Collect all offerings
    offerings = {}
    for c in matching_eval.get("allSelectedCourses", []):
        offerings[course_id(c)] = c

    # Decision var: offering selected
    x = {c: model.new_bool_var(f"x_{c.replace(' ','_').replace('@','_')}")
         for c in offerings.keys()}

    # Assignment vars: y[r,c] = counts toward requirement r
    y = {}  # (r,c) -> BoolVar
    req_cands = []
    sat = []

    for r, qr in enumerate(results):
        req = qr["requirement"]
        qmin, qmax = q_bounds(req["query"]["quantity"])

        cands = [course_id(c) for c in qr["selectedCourses"]]
        req_cands.append(cands)

        # ensure any missing offerings get vars
        for c in qr["selectedCourses"]:
            k = course_id(c)
            if k not in x:
                offerings[k] = c
                x[k] = model.new_bool_var(f"x_{k.replace(' ','_').replace('@','_')}")

        # create y vars for this requirement's candidates
        for c in cands:
            y[(r, c)] = model.new_bool_var(f"y_r{r}_{c.replace(' ','_').replace('@','_')}")
            model.add(y[(r, c)] <= x[c])  # can only assign if selected

        sum_assigned = sum(y[(r, c)] for c in cands)

        s = model.new_bool_var(f"sat_{r}")
        sat.append(s)

        model.add(sum_assigned <= qmax)  # unconditional
        model.add(sum_assigned >= qmin).only_enforce_if(s)
        model.add(sum_assigned <= qmin - 1).only_enforce_if(s.negated())


    # NO DOUBLE COUNTING:
    # each offering can satisfy at most one requirement
    for c in x.keys():
        used_by = [y[(r, c)] for r in range(len(results)) if (r, c) in y]
        if used_by:
            model.add(sum(used_by) <= 1)

    base_to_y: dict[str, list[cp_model.IntVar]] = {}

    for (r, cid), var in y.items():
        course = offerings[cid]
        b = base_key(course)
        base_to_y.setdefault(b, []).append(var)

    for b, vars_ in base_to_y.items():
        model.add(sum(vars_) <= 1)

    total_satisfied = sum(sat)
    total_courses = sum(x.values())
    
    req_priority = []
    for r, qr in enumerate(results):
        req = qr["requirement"]
        req_priority.append(req["priority"])
        
    R = len(results)

    req_priority = [results[r]["requirement"]["priority"] for r in range(R)]

    priorities = sorted(set(req_priority), reverse=True)

    MAX_REQS = R
    BASE = MAX_REQS + 1

    expr = 0
    for i, p in enumerate(priorities):
        tier_sat = sum(
            sat[r] for r in range(R)
            if req_priority[r] == p
        )
        expr += tier_sat * (BASE ** (len(priorities) - 1 - i))

    M = 10_000

    # Tie-breaker: maximize actual assigned courses
    model.maximize(expr * M + sum(y.values()))

    # model.Maximize(total_satisfied * M + total_courses)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 2.0
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {"status": "no_solution", "status_cpsat": str(status) }

    selected = [c for c, var in x.items() if solver.value(var) == 1]

    per_req = []
    for r, qr in enumerate(results):
        chosen = [c for c in req_cands[r] if solver.value(y[(r, c)]) == 1]
        per_req.append({
            "description": qr["requirement"]["description"],
            "priority": qr["requirement"]["priority"],
            "satisfied": solver.Value(sat[r]) == 1,
            "selected": chosen,
            "query": qr["requirement"]["query"]
        })

    return {
        "status": "ok",
        "status_cpsat": str(status),
        "total_satisfied": solver.value(total_satisfied),
        "total_courses": solver.value(total_courses),
        "selected_courses": selected,
        "per_requirement": per_req,
    }
    

SCRIPT_LOCATION = Path(__file__).resolve()
INPUT_LOCATION = SCRIPT_LOCATION.parent.parent / "inputs" / "test"


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
        print(e.stdout)
        print(f"Matching failed with exit code {e.returncode}", file=sys.stderr)
        print(f"Error output (stderr): {e.stderr}", file=sys.stderr)
        exit(2)

    print("Found required courses")
    
    for object in json.loads(result.stdout):
        sol = solve_no_double_count(object)
        print(json.dumps(sol, indent=2))
        