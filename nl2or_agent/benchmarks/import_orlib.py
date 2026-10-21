"""Import real location instances from OR-Library (Beasley) into benchmark cases.

One interface for every family; each emitted case follows the benchmark schema and
carries executable data in its IR, a reference script rendered from that IR, and the
published optimum as ``solver_objective`` (cross-checked with our own solve).

  pmed    p-median, uncapacitated            pmed1..pmed40         pmedopt.txt
  uflp    uncapacitated warehouse location   cap71..cap134         uncapopt.txt
  cflp    capacitated warehouse location     cap41..cap134         capopt.txt
  cappmed capacitated p-median               pmedcap1 (20 problems) value in file

Usage:
  uv run python benchmarks/import_orlib.py                          # 默认小规模子集
  uv run python benchmarks/import_orlib.py --family uflp --ids 71 101
  uv run python benchmarks/import_orlib.py --family cflp --ids 41 61
  uv run python benchmarks/import_orlib.py --family cappmed --ids 1 2 3
  uv run python benchmarks/import_orlib.py --family pmed --ids 1 5 6 10
"""

from __future__ import annotations

import argparse
import json
import math
import urllib.request
from pathlib import Path

import numpy as np
from scipy.sparse.csgraph import shortest_path

from core.block_model import render_script, solve_ir

OUT_DIR = Path(__file__).parent / "orlib_cases"
SOLVERS_DIR = Path(__file__).parent / "references" / "solvers"
FILES_URL = "https://people.brunel.ac.uk/~mastjjb/jeb/orlib/files/"

FAMILIES = ("pmed", "uflp", "cflp", "cappmed")
DEFAULT_IDS = {"pmed": [1], "uflp": [71], "cflp": [61], "cappmed": [1]}


# ---------------------------------------------------------------------------
# raw fetching
# ---------------------------------------------------------------------------


def _fetch(name: str) -> str:
    with urllib.request.urlopen(FILES_URL + name, timeout=60) as resp:
        return resp.read().decode()


def _optima(file_name: str) -> dict[str, float]:
    """Parse a published optimum table (`capopt.txt` / `uncapopt.txt` / `pmedopt.txt`)."""
    table: dict[str, float] = {}
    for line in _fetch(file_name).splitlines():
        parts = line.split()
        if len(parts) == 2:
            try:
                table[parts[0]] = float(parts[1])
            except ValueError:
                continue
    return table


# ---------------------------------------------------------------------------
# family loaders -> (input_ir, expected, reference script, scale)
# ---------------------------------------------------------------------------


def _pmed_case(instance_id: int, optima: dict[str, float]) -> dict:
    """p-median instance: the graph is too large for the IR, so the script carries it."""
    tokens = _fetch(f"pmed{instance_id}.txt").split()
    n, m, p = int(tokens[0]), int(tokens[1]), int(tokens[2])
    vals = list(map(int, tokens[3 : 3 + 3 * m]))
    edges = [(vals[3 * i] - 1, vals[3 * i + 1] - 1, vals[3 * i + 2]) for i in range(m)]

    published = optima.get(f"pmed{instance_id}")
    if published is None:
        raise ValueError(f"pmedopt.txt 中没有 pmed{instance_id} 的最优值")
    # n>100 的实例用 CBC 复算会超过可用时限，此时以已发表最优值为准
    if n <= 100:
        computed = _solve_pmed(n, p, edges)
        if computed != published:
            raise ValueError(f"pmed{instance_id}: 自算 {computed} 与已发表 {published} 不一致")

    case_id = f"pmed_{instance_id}"
    script = _render_pmed_script(n, p, edges)
    return {
        "id": case_id,
        "name": f"OR-Library p-median pmed{instance_id}",
        "family": "p_median",
        "scale": "m" if n <= 200 else "l",
        "tiers": ["ir", "solver", "online"] if n <= 100 else ["ir"],
        "source": f"OR-Library p-median pmed{instance_id}（已发表最优 {published}）",
        "problem": _pmed_problem(n, p, edges),
        "input_ir": {
            "problem_families": [{"id": "p_median", "confidence": 0.95}],
            "entities": {"I": {"size": n}, "J": {"size": n}},
            "parameters": {"p": p},
            "constraint_blocks": [
                {"block_id": "assignment", "parameters": {}, "status": "required"},
                {"block_id": "linking", "parameters": {}, "status": "required"},
                {"block_id": "cardinality", "parameters": {"p": p}, "status": "required"},
            ],
            "objective": "minimize_total_weighted_distance",
        },
        "expected": {
            "valid": True,
            "families": ["p_median"],
            "block_ids": [
                "assign_each_demand_once",
                "link_assignment_to_open",
                "cardinality_open_p_facilities",
            ],
            "objective_block": "weighted_service_distance_objective",
        },
        "solver_objective": float(published),
        "_script": script,
        "_instance": {"n": n, "p": p, "edges": len(edges)},
    }


def _warehouse_case(kind: str, instance_id: int, data: str, optima: dict[str, float]) -> dict:
    """UFLP (`uflp`) or capacitated warehouse location (`cflp`) from the same cap files."""
    tokens = data.split()
    m, n = int(tokens[0]), int(tokens[1])
    cursor = 2
    capacity, fixed_cost = [], []
    for _ in range(m):
        capacity.append(float(tokens[cursor]))
        fixed_cost.append(float(tokens[cursor + 1]))
        cursor += 2
    demand, service_cost = [], []
    for _ in range(n):
        demand.append(float(tokens[cursor]))
        service_cost.append([float(x) for x in tokens[cursor + 1 : cursor + 1 + m]])
        cursor += 1 + m

    name = f"cap{instance_id}"
    published = optima.get(name)
    if published is None:
        raise ValueError(f"最优值表中没有 {name}")

    capacity_blocks = (
        [
            {
                "block_id": "facility_capacity",
                "parameters": {"facility_capacity": capacity, "demand": demand},
                "status": "required",
            }
        ]
        if kind == "cflp"
        else []
    )
    model_id = "capacitated_facility_location" if kind == "cflp" else "facility_location"
    objective_block = "fixed_plus_service_cost_objective"
    input_ir = {
        "problem_families": [{"id": model_id, "confidence": 0.95}],
        "entities": {"I": {"size": n}, "J": {"size": m}},
        "parameters": {
            "fixed_cost": fixed_cost,
            "service_cost": service_cost,
            "demand": demand,
            "facility_capacity": capacity,
        },
        "constraint_blocks": [
            {"block_id": "assignment", "parameters": {}, "status": "required"},
            {"block_id": "linking", "parameters": {}, "status": "required"},
        ]
        + capacity_blocks,
        "objective": {"block_id": objective_block, "sense": "minimize"},
    }
    block_ids = ["assign_each_demand_once", "link_assignment_to_open"] + (
        ["facility_capacity"] if kind == "cflp" else []
    )
    check = solve_ir(_normalize(input_ir))
    if check.status != "Optimal":
        raise ValueError(
            f"{name}: 单源分配模型下不可行（状态 {check.status}）。"
            "Beasley 的 cap 系列允许需求拆分，单个需求超过单仓容量的实例无法用当前块语义表达。"
        )
    if abs((check.objective or 0.0) - published) > 1e-3 * max(1.0, published):
        raise ValueError(f"{name}: 自算 {check.objective} 与已发表 {published} 不一致")

    return {
        "id": f"{kind}_{name}",
        "name": f"OR-Library {name}（{'有容量仓库选址' if kind == 'cflp' else '无容量仓库选址'}）",
        "family": model_id,
        "scale": "m" if n <= 200 else "l",
        "tiers": ["ir", "solver", "online", "tightness"],
        "source": f"OR-Library {name}（已发表最优 {published}）",
        "problem": _warehouse_problem(kind, m, n, capacity, fixed_cost, demand, service_cost),
        "input_ir": input_ir,
        "expected": {
            "valid": True,
            "families": [model_id],
            "block_ids": block_ids,
            "objective_block": objective_block,
        },
        "solver_objective": float(published),
        "_instance": {"m": m, "n": n},
    }


def _cappmed_case(problem_index: int, data: str) -> dict:
    """Capacitated p-median from pmedcap1 (coordinates -> floored Euclidean distances)."""
    tokens = data.split()
    cursor = 1  # first token: number of problems
    chosen: dict | None = None
    for _ in range(int(tokens[0])):
        problem_id = int(tokens[cursor])
        best = float(tokens[cursor + 1])
        n, p, capacity = int(tokens[cursor + 2]), int(tokens[cursor + 3]), float(tokens[cursor + 4])
        cursor += 5
        customers = []
        for _ in range(n):
            customers.append(
                (
                    int(tokens[cursor]),
                    float(tokens[cursor + 1]),
                    float(tokens[cursor + 2]),
                    float(tokens[cursor + 3]),
                )
            )
            cursor += 4
        if problem_id == problem_index:
            chosen = {
                "id": problem_id,
                "best": best,
                "n": n,
                "p": p,
                "capacity": capacity,
                "customers": customers,
            }
            break
    if chosen is None:
        raise ValueError(f"pmedcap1 中没有题号 {problem_index}")

    n, p, capacity = chosen["n"], chosen["p"], chosen["capacity"]
    customers = chosen["customers"]
    demand = [c[3] for c in customers]
    distance = [
        [float(math.floor(math.hypot(a[1] - b[1], a[2] - b[2]))) for b in customers]
        for a in customers
    ]
    input_ir = {
        "problem_families": [{"id": "capacitated_p_median", "confidence": 0.95}],
        "entities": {"I": {"size": n}, "J": {"size": n}},
        "parameters": {
            "p": p,
            "distance": distance,
            "demand": demand,
            "facility_capacity": [capacity] * n,
        },
        "constraint_blocks": [
            {"block_id": "assignment", "parameters": {}, "status": "required"},
            {"block_id": "linking", "parameters": {}, "status": "required"},
            {"block_id": "cardinality", "parameters": {"p": p}, "status": "required"},
            {
                "block_id": "facility_capacity",
                "parameters": {"facility_capacity": [capacity] * n, "demand": demand},
                "status": "required",
            },
        ],
        "objective": {"block_id": "total_service_distance_objective", "sense": "minimize"},
    }
    check = solve_ir(_normalize(input_ir))
    if check.objective is None or abs(check.objective - chosen["best"]) > 1e-3 * chosen["best"]:
        raise ValueError(
            f"pmedcap 第 {problem_index} 题: 自算 {check.objective} 与已发表 {chosen['best']} 不一致"
        )

    return {
        "id": f"cappmed_{problem_index}",
        "name": f"OR-Library 有容量 p-median 第 {problem_index} 题",
        "family": "capacitated_p_median",
        "scale": "m",
        "tiers": ["ir", "solver", "online", "tightness"],
        "source": f"OR-Library pmedcap1 第 {problem_index} 题（已发表最优 {chosen['best']}）",
        "problem": _cappmed_problem(problem_index, n, p, capacity, customers),
        "input_ir": input_ir,
        "expected": {
            "valid": True,
            "families": ["capacitated_p_median"],
            "block_ids": [
                "assign_each_demand_once",
                "link_assignment_to_open",
                "cardinality_open_p_facilities",
                "facility_capacity",
            ],
            "objective_block": "total_service_distance_objective",
        },
        "solver_objective": float(chosen["best"]),
        "_instance": {"n": n, "p": p, "capacity": capacity},
    }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _normalize(input_ir: dict) -> dict:
    from core.ir_validate import validate_problem_ir

    report = validate_problem_ir(dict(input_ir))
    if not report["valid"]:
        raise ValueError(f"导入的 IR 未通过校验: {report['errors']}")
    return report["normalized_ir"]


def _solve_pmed(n: int, p: int, edges: list[tuple[int, int, int]]) -> int:
    """Independent check: all-pairs shortest paths + p-median MIP via PuLP/CBC."""
    import pulp

    inf = 10**9
    dist = np.full((n, n), inf, dtype=float)
    for i, j, w in edges:
        dist[i, j] = dist[j, i] = w
    sp = shortest_path(dist, method="D")

    prob = pulp.LpProblem("p_median", pulp.LpMinimize)
    y = pulp.LpVariable.dicts("y", range(n), cat=pulp.LpBinary)
    x = pulp.LpVariable.dicts("x", (range(n), range(n)), cat=pulp.LpBinary)
    prob += pulp.lpSum(sp[i][j] * x[i][j] for i in range(n) for j in range(n))
    for i in range(n):
        prob += pulp.lpSum(x[i][j] for j in range(n)) == 1
        for j in range(n):
            prob += x[i][j] <= y[j]
    prob += pulp.lpSum(y[j] for j in range(n)) == p
    prob.solve(pulp.PULP_CBC_CMD(msg=False))
    value = pulp.value(prob.objective)
    return round(value) if isinstance(value, (int, float)) else 0


def _render_pmed_script(n: int, p: int, edges: list[tuple[int, int, int]]) -> str:
    edge_literal = ",\n    ".join(f"({i}, {j}, {w})" for i, j, w in edges)
    return f'''"""Reference solver: OR-Library pmed instance (n={n}, p={p}). Generated by import_orlib.py."""

import numpy as np
import pulp
from scipy.sparse.csgraph import shortest_path

N, P = {n}, {p}
EDGES = [
    {edge_literal},
]

INF = 10**9
D = np.full((N, N), INF, dtype=float)
for i, j, w in EDGES:
    D[i, j] = D[j, i] = w
SP = shortest_path(D, method="D")

prob = pulp.LpProblem("p_median", pulp.LpMinimize)
y = pulp.LpVariable.dicts("y", range(N), cat=pulp.LpBinary)
x = pulp.LpVariable.dicts("x", (range(N), range(N)), cat=pulp.LpBinary)
prob += pulp.lpSum(SP[i][j] * x[i][j] for i in range(N) for j in range(N))
for i in range(N):
    prob += pulp.lpSum(x[i][j] for j in range(N)) == 1
    for j in range(N):
        prob += x[i][j] <= y[j]
prob += pulp.lpSum(y[j] for j in range(N)) == P
prob.solve(pulp.PULP_CBC_CMD(msg=False))
value = pulp.value(prob.objective)
print("Objective:", round(value) if isinstance(value, (int, float)) else 0)
'''


def _pmed_problem(n: int, p: int, edges: list[tuple[int, int, int]]) -> str:
    lines = [
        f"在一个无向有权图中，有 {n} 个节点（编号 1~{n}）。",
        f"现需选择 {p} 个节点作为中位节点，使所有节点到其最近中位节点的最短路径距离之和最小。",
        "图中每条边为 (节点i, 节点j, 权重w)，边列表如下：",
    ]
    lines.append(", ".join(f"{i + 1} {j + 1} {w}" for i, j, w in edges))
    return "\n".join(lines)


def _warehouse_problem(
    kind: str,
    m: int,
    n: int,
    capacity: list[float],
    fixed: list[float],
    demand: list[float],
    service: list[list[float]],
) -> str:
    capacity_note = (
        "每个仓库有容量上限，分配给某仓库的客户需求之和不得超过该容量；"
        if kind == "cflp"
        else "仓库容量在本问题中不构成约束；"
    )
    lines = [
        f"有 {m} 个候选仓库与 {n} 个客户。",
        f"仓库固定开设成本为 {fixed}。",
        capacity_note + f"仓库容量为 {capacity}。",
        f"各客户需求量分别为 {demand}。",
        "客户 j 由仓库 i 服务时，全部需求的服务成本（矩阵第 j 行第 i 列）为：",
    ]
    for j, row in enumerate(service):
        lines.append(f"客户{j + 1}: {row}")
    lines.append("每个客户必须恰好分配到一个已开设仓库，只有开设的仓库才能接收分配。")
    lines.append("目标是最小化固定开设成本与服务成本之和。")
    return "\n".join(lines)


def _cappmed_problem(problem_index: int, n: int, p: int, capacity: float, customers: list) -> str:
    lines = [
        f"有 {n} 个客户（编号、x 坐标、y 坐标、需求量如下），需要选出 {p} 个客户作为聚类中心。",
        f"每个中心的容量上限均为 {capacity}，分配到该中心的需求之和不得超过容量。",
        "客户间距离取欧氏距离向下取整。每个客户必须恰好分配到一个已选中心。",
        "目标是最小化所有客户到其中心距离之和。",
    ]
    for cid, x, y, d in customers:
        lines.append(f"{cid} {x} {y} {d}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def build_case(family: str, instance_id: int) -> dict:
    if family == "pmed":
        return _pmed_case(instance_id, _optima("pmedopt.txt"))
    if family == "uflp":
        return _warehouse_case(
            "uflp", instance_id, _fetch(f"cap{instance_id}.txt"), _optima("uncapopt.txt")
        )
    if family == "cflp":
        return _warehouse_case(
            "cflp", instance_id, _fetch(f"cap{instance_id}.txt"), _optima("capopt.txt")
        )
    if family == "cappmed":
        return _cappmed_case(instance_id, _fetch("pmedcap1.txt"))
    raise ValueError(f"未知数据集 {family}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Import OR-Library location cases")
    parser.add_argument("--family", choices=list(FAMILIES), default=None)
    parser.add_argument("--ids", nargs="+", type=int, help="instance ids, e.g. 71 101")
    parser.add_argument("--all", action="store_true", help="所有 family 的默认小规模子集")
    args = parser.parse_args()

    jobs: list[tuple[str, int]] = []
    if args.all or args.family is None:
        for family in FAMILIES:
            jobs += [(family, i) for i in DEFAULT_IDS[family]]
    else:
        jobs = [(args.family, i) for i in (args.ids or DEFAULT_IDS[args.family])]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SOLVERS_DIR.mkdir(parents=True, exist_ok=True)
    for family, instance_id in jobs:
        case = build_case(family, instance_id)
        script = case.pop("_script", None)
        case.pop("_instance", None)
        case["tight_blocks"] = []
        case["nonbinding_blocks"] = []

        path = OUT_DIR / f"{case['id']}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(case, f, ensure_ascii=False, indent=2)
            f.write("\n")

        if script is None:
            script = render_script(_normalize(case["input_ir"]))
        solver_path = SOLVERS_DIR / f"{case['id']}.py"
        solver_path.write_text(script, encoding="utf-8")

        print(f"imported {case['id']}: objective={case['solver_objective']} tiers={case['tiers']}")

    print(f"\nDone: {len(jobs)} cases written to {OUT_DIR}")


if __name__ == "__main__":
    main()
