import sys
import json
from typing import Any, Dict, Tuple
import subprocess
from pathlib import Path

from ortools.sat.python import cp_model

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


def is_placement(obj):
    """Example: `{'filled': False, 'id': '5fc3660b-54ff-47c4-bff2-0e50db5d60b5', 'description': 'Equivalent Placement or Credit'}`"""
    return isinstance(obj, dict) and "id" in obj and "filled" in obj and "description" in obj


def placement_key(p): 
    return f"PLACEMENT:{p['id']}"


def is_place_key(k: str) -> bool:
    return k.startswith("PLACEMENT:")


# ---------- CP-SAT model ----------

def solve_no_double_count(matching_eval, include_query: bool = False):
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
    
    # ---------- Collect all offerings ----------
    offerings: dict[str, dict] = {}    # course_id -> course dict
    placements: dict[str, dict] = {}   # placement_key -> placement dict

    x: dict[str, cp_model.IntVar] = {}       # course offer selection vars
    x_place: dict[str, cp_model.IntVar] = {} # placement selection vars
    
    # for item in matching_eval.get("allSelectedCourses", []):
    for item in [c for group in matching_eval.get("allSelectedCourses", []) for c in (group if isinstance(group, list) else [group])]:
        if is_placement(item):
            pk = placement_key(item)
            if pk not in x_place:
                placements[pk] = item
                x_place[pk] = model.new_bool_var(f"x_{pk.replace(':','_')}")
        else:
            cid = course_id(item)
            if cid not in x:
                offerings[cid] = item
                x[cid] = model.new_bool_var(f"x_{cid.replace(' ','_').replace('@','_')}")

    # Assignment vars: y[r,key] where key is course-id OR placement-key
    y: dict[tuple[int, str], cp_model.IntVar] = {}
    req_cands: list[list[str]] = []
    sat: list[cp_model.IntVar] = []

    for r, qr in enumerate(results):
        req = qr["requirement"]
        qmin, qmax = q_bounds(req["query"]["quantity"])

        cand_keys: list[str] = []
        groups: list[dict] = []  # {"limit": int, "keys": [...]}

        # Build candidate keys (courses + placements)
        # selectedCourses is a list of groups (each group is a list of courses/placements)
        # each group corresponds to one inner SELECT node in the query selector
        for group_idx, group_items in enumerate(qr["selectedCourses"]):
            # normalize: a bare course/placement dict means a singleton group
            if not isinstance(group_items, list):
                group_items = [group_items]

            # get the limit for this group from the query selector
            selector = req["query"].get("selector", [])
            if group_idx < len(selector):
                inner_query = selector[group_idx].get("Query", {})
                _, glimit = q_bounds(inner_query.get("quantity", {"Single": len(group_items)}))
            else:
                glimit = len(group_items)  # uncapped fallback

            group_keys: list[str] = []
            for item in group_items:
                if is_placement(item):
                    pk = placement_key(item)
                    cand_keys.append(pk)
                    group_keys.append(pk)
                    if pk not in x_place:
                        placements[pk] = item
                        x_place[pk] = model.new_bool_var(f"x_{pk.replace(':','_')}")
                else:
                    cid = course_id(item)
                    cand_keys.append(cid)
                    group_keys.append(cid)
                    if cid not in x:
                        offerings[cid] = item
                        x[cid] = model.new_bool_var(f"x_{cid.replace(' ','_').replace('@','_')}")

            if group_keys:
                groups.append({"limit": glimit, "keys": group_keys})

        req_cands.append(cand_keys)

        # Create y vars and link to selection vars
        for key in cand_keys:
            y[(r, key)] = model.new_bool_var(
                f"y_r{r}_{key.replace(' ','_').replace('@','_').replace(':','_')}"
            )
            if is_place_key(key):
                model.add(y[(r, key)] <= x_place[key])
            else:
                model.add(y[(r, key)] <= x[key])

        sum_assigned = sum(y[(r, key)] for key in cand_keys)

        s = model.new_bool_var(f"sat_{r}")
        sat.append(s)

        # Allow partial fills when unsatisfied:
        model.add(sum_assigned <= qmax)  # unconditional cap
        model.add(sum_assigned >= qmin).only_enforce_if(s)
        if qmin > 0:
            model.add(sum_assigned <= qmin - 1).only_enforce_if(s.negated())
        else:
            model.add(sum_assigned == 0).only_enforce_if(s.negated())
            
        for group in groups:
            gkeys = [k for k in group["keys"] if (r, k) in y]
            if gkeys:
                model.add(sum(y[(r, k)] for k in gkeys) <= group["limit"])

    # ---------- NO DOUBLE COUNTING (offering-level + placement-level) ----------
    # each course offering can satisfy at most one requirement
    for c in list(x.keys()):
        used_by = [y[(r, c)] for r in range(len(results)) if (r, c) in y]
        if used_by:
            model.add(sum(used_by) <= 1)

    # each placement checkbox can satisfy at most one requirement
    for pk in list(x_place.keys()):
        used_by = [y[(r, pk)] for r in range(len(results)) if (r, pk) in y]
        if used_by:
            model.add(sum(used_by) <= 1)

    # ---------- Base-course uniqueness (skip placements) ----------
    base_to_y: dict[str, list[cp_model.IntVar]] = {}

    for (r, key), var in y.items():
        if is_place_key(key):
            continue
        course = offerings[key]
        b = base_key(course)
        base_to_y.setdefault(b, []).append(var)

    for b, vars_ in base_to_y.items():
        model.add(sum(vars_) <= 1)

    # ---------- Objective (priority-lexicographic + best-effort fills) ----------
    total_satisfied = sum(sat)
    total_courses = sum(x.values())  # NOTE: this is only courses, not placements

    R = len(results)
    req_priority = [results[r]["requirement"]["priority"] for r in range(R)]
    priorities = sorted(set(req_priority), reverse=True)

    BASE = R + 1
    expr = 0
    for i, p in enumerate(priorities):
        tier_sat = sum(sat[r] for r in range(R) if req_priority[r] == p)
        expr += tier_sat * (BASE ** (len(priorities) - 1 - i))

    M = 10_000

    # Tie-breaker: maximize assigned items (courses + placements).
    # Optional: discourage placements slightly so the solver prefers real courses when possible.
    PLACEMENT_PENALTY = 1
    model.maximize(expr * M + sum(y.values()) - PLACEMENT_PENALTY * sum(x_place.values()))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 2.0
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {"status": "no_solution", "status_cpsat": str(status)}

    selected_courses = [c for c, var in x.items() if solver.value(var) == 1]
    selected_placements = [pk for pk, var in x_place.items() if solver.value(var) == 1]

    per_req = []
    for r, qr in enumerate(results):
        chosen = [k for k in req_cands[r] if solver.value(y[(r, k)]) == 1]

        per_req_item = {
            "description": qr["requirement"]["description"],
            "priority": qr["requirement"]["priority"],
            "satisfied": solver.value(sat[r]) == 1,
            "selected": chosen,  # contains course ids and "PLACEMENT:<id>" keys
        }
        
        if include_query:
            per_req_item["query"] = qr["requirement"]["query"]
        
        per_req.append(per_req_item)

    

    return {
        "status": "ok",
        "status_cpsat": str(status),
        "total_satisfied": solver.value(total_satisfied),
        "total_courses": solver.value(total_courses),
        "selected_courses": selected_courses,
        "selected_placements": selected_placements,
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
        # print(json.dumps(object, indent=2))
        sol = solve_no_double_count(object)
        print(json.dumps(sol, indent=2))