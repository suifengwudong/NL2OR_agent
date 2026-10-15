"""Executable semantics of the block catalog: Problem IR -> PuLP model.

Single interface shared by the reference solvers, the OR-Library importer, the
tightness analysis and the T2 negative controls:

    solve_ir(ir)                     -> SolveResult(objective, status, variables)
    solve_ir(ir, drop=[block_id])    -> the same model without one constraint block
    render_script(ir, drop=[...])    -> a standalone solver script printing `Objective: <value>`
    analyze_tightness(ir)            -> which blocks change the optimum when removed

Everything is driven by the normalized IR (``constraint_blocks`` + ``objective`` +
``parameters`` + ``entities``), so the block set is the only thing that decides the
model. No code style is involved.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import pulp

from core.ir_normalizer import collect_parameters

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Which variables each block needs
# ---------------------------------------------------------------------------

_X2_BLOCKS = {
    "assign_each_demand_once",
    "link_assignment_to_open",
    "facility_capacity",
    "max_service_distance_bound",
    "weighted_service_distance_objective",
    "fixed_plus_service_cost_objective",
}
_Y_BLOCKS = {
    "link_assignment_to_open",
    "cardinality_open_p_facilities",
    "cardinality_open_at_most_p_facilities",
    "force_facility_open",
    "force_facility_closed",
    "cover_each_demand_at_least_once",
    "demand_coverage_activation",
    "facility_capacity",
    "facility_opening_cost_objective",
    "fixed_plus_service_cost_objective",
}
_Z_BLOCKS = {"demand_coverage_activation", "covered_demand_objective"}
_W_BLOCKS = {"max_service_distance_bound", "minimize_max_distance_objective"}
_X1_BLOCKS = {"knapsack_capacity", "total_value_objective"}


@dataclass
class ModelContext:
    """Everything a block builder may need."""

    ir: dict[str, Any]
    prob: pulp.LpProblem
    data: dict[str, Any]
    n_i: int
    n_j: int
    var: dict[str, Any] = field(default_factory=dict)

    # -- data access -------------------------------------------------------
    def list_value(self, key: str, length: int, default: float = 1.0) -> list[float]:
        raw = self.data.get(key)
        if isinstance(raw, (int, float)):
            return [float(raw)] * length
        if isinstance(raw, list) and len(raw) == length:
            return [float(v) for v in raw]
        return [default] * length

    def matrix(self, key: str) -> list[list[float]]:
        raw = self.data.get(key)
        if (
            isinstance(raw, list)
            and len(raw) == self.n_i
            and all(isinstance(row, list) and len(row) == self.n_j for row in raw)
        ):
            return [[float(v) for v in row] for row in raw]
        raise ValueError(f"参数 {key!r} 缺失或维度不是 {self.n_i}x{self.n_j}")

    def indices(self, key: str) -> list[int]:
        raw = self.data.get(key) or []
        ids = (self.ir.get("entities") or {}).get("J", {}).get("ids")
        out: list[int] = []
        for item in raw:
            if isinstance(item, int):
                out.append(item)
            elif ids and str(item) in [str(x) for x in ids]:
                out.append([str(x) for x in ids].index(str(item)))
            else:
                raise ValueError(f"参数 {key!r} 中的 {item!r} 无法解析为设施下标")
        return out


ConstraintBuilder = Callable[[ModelContext], None]


def _assign(ctx: ModelContext) -> None:
    x = ctx.var["x2"]
    for i in range(ctx.n_i):
        ctx.prob += pulp.lpSum(x[i][j] for j in range(ctx.n_j)) == 1


def _linking(ctx: ModelContext) -> None:
    x, y = ctx.var["x2"], ctx.var["y"]
    for i in range(ctx.n_i):
        for j in range(ctx.n_j):
            ctx.prob += x[i][j] <= y[j]


def _cardinality_exactly_p(ctx: ModelContext) -> None:
    y = ctx.var["y"]
    ctx.prob += pulp.lpSum(y[j] for j in range(ctx.n_j)) == int(ctx.data.get("p", 0))


def _cardinality_at_most_p(ctx: ModelContext) -> None:
    y = ctx.var["y"]
    ctx.prob += pulp.lpSum(y[j] for j in range(ctx.n_j)) <= int(ctx.data.get("p", 0))


def _force_open(ctx: ModelContext) -> None:
    y = ctx.var["y"]
    for j in ctx.indices("forced_open"):
        ctx.prob += y[j] == 1


def _force_closed(ctx: ModelContext) -> None:
    y = ctx.var["y"]
    for j in ctx.indices("forced_closed"):
        ctx.prob += y[j] == 0


def _facility_capacity(ctx: ModelContext) -> None:
    x, y = ctx.var["x2"], ctx.var["y"]
    demand = ctx.list_value("demand", ctx.n_i)
    capacity = ctx.list_value("facility_capacity", ctx.n_j)
    for j in range(ctx.n_j):
        ctx.prob += pulp.lpSum(demand[i] * x[i][j] for i in range(ctx.n_i)) <= capacity[j] * y[j]


def _knapsack_capacity(ctx: ModelContext) -> None:
    x1 = ctx.var["x1"]
    weight = ctx.list_value("weight", ctx.n_i)
    capacity = float(ctx.data.get("capacity", 0))
    ctx.prob += pulp.lpSum(weight[i] * x1[i] for i in range(ctx.n_i)) <= capacity


def _cover_each_demand(ctx: ModelContext) -> None:
    y, a = ctx.var["y"], ctx.matrix("coverage_matrix")
    for i in range(ctx.n_i):
        ctx.prob += pulp.lpSum(a[i][j] * y[j] for j in range(ctx.n_j)) >= 1


def _coverage_activation(ctx: ModelContext) -> None:
    y, z, a = ctx.var["y"], ctx.var["z"], ctx.matrix("coverage_matrix")
    for i in range(ctx.n_i):
        ctx.prob += z[i] <= pulp.lpSum(a[i][j] * y[j] for j in range(ctx.n_j))


def _max_service_distance_bound(ctx: ModelContext) -> None:
    x, w, d = ctx.var["x2"], ctx.var["w"], ctx.matrix("distance")
    for i in range(ctx.n_i):
        for j in range(ctx.n_j):
            ctx.prob += d[i][j] * x[i][j] <= w


def _objective_weighted_service_distance(ctx: ModelContext) -> None:
    x, d = ctx.var["x2"], ctx.matrix("distance")
    demand = ctx.list_value("demand", ctx.n_i)
    ctx.prob += pulp.lpSum(
        demand[i] * d[i][j] * x[i][j] for i in range(ctx.n_i) for j in range(ctx.n_j)
    )


def _objective_total_service_distance(ctx: ModelContext) -> None:
    x, d = ctx.var["x2"], ctx.matrix("distance")
    ctx.prob += pulp.lpSum(d[i][j] * x[i][j] for i in range(ctx.n_i) for j in range(ctx.n_j))


def _objective_facility_opening_cost(ctx: ModelContext) -> None:
    y = ctx.var["y"]
    fixed = ctx.list_value("fixed_cost", ctx.n_j)
    ctx.prob += pulp.lpSum(fixed[j] * y[j] for j in range(ctx.n_j))


def _objective_fixed_plus_service_cost(ctx: ModelContext) -> None:
    y, x = ctx.var["y"], ctx.var["x2"]
    fixed = ctx.list_value("fixed_cost", ctx.n_j)
    service = ctx.matrix("service_cost")
    ctx.prob += pulp.lpSum(fixed[j] * y[j] for j in range(ctx.n_j)) + pulp.lpSum(
        service[i][j] * x[i][j] for i in range(ctx.n_i) for j in range(ctx.n_j)
    )


def _objective_covered_demand(ctx: ModelContext) -> None:
    z = ctx.var["z"]
    demand = ctx.list_value("demand", ctx.n_i)
    ctx.prob += pulp.lpSum(demand[i] * z[i] for i in range(ctx.n_i))


def _objective_minimize_max_distance(ctx: ModelContext) -> None:
    ctx.prob += ctx.var["w"]


def _objective_total_value(ctx: ModelContext) -> None:
    x1 = ctx.var["x1"]
    value = ctx.list_value("value", ctx.n_i)
    ctx.prob += pulp.lpSum(value[i] * x1[i] for i in range(ctx.n_i))


CONSTRAINT_BUILDERS: dict[str, ConstraintBuilder] = {
    "assign_each_demand_once": _assign,
    "link_assignment_to_open": _linking,
    "cardinality_open_p_facilities": _cardinality_exactly_p,
    "cardinality_open_at_most_p_facilities": _cardinality_at_most_p,
    "force_facility_open": _force_open,
    "force_facility_closed": _force_closed,
    "facility_capacity": _facility_capacity,
    "knapsack_capacity": _knapsack_capacity,
    "cover_each_demand_at_least_once": _cover_each_demand,
    "demand_coverage_activation": _coverage_activation,
    "max_service_distance_bound": _max_service_distance_bound,
}

OBJECTIVE_BUILDERS: dict[str, ConstraintBuilder] = {
    "weighted_service_distance_objective": _objective_weighted_service_distance,
    "total_service_distance_objective": _objective_total_service_distance,
    "facility_opening_cost_objective": _objective_facility_opening_cost,
    "fixed_plus_service_cost_objective": _objective_fixed_plus_service_cost,
    "covered_demand_objective": _objective_covered_demand,
    "minimize_max_distance_objective": _objective_minimize_max_distance,
    "total_value_objective": _objective_total_value,
}


# ---------------------------------------------------------------------------
# IR -> model
# ---------------------------------------------------------------------------


@dataclass
class SolveResult:
    objective: float | None
    status: str
    variables: dict[str, float] = field(default_factory=dict)


def constraint_block_ids(ir: dict[str, Any]) -> list[str]:
    return [str(b["block_id"]) for b in ir.get("constraint_blocks") or []]


def objective_block_id(ir: dict[str, Any]) -> str:
    return str((ir.get("objective") or {}).get("block_id") or "")


def _sizes(ir: dict[str, Any]) -> tuple[int, int]:
    data = ir.get("parameters") or {}
    entities = ir.get("entities") or {}

    def size_of(key: str, fallback: int = 1) -> int:
        value = (entities.get(key) or {}).get("size")
        return int(value) if value else fallback

    n_i = size_of("I")
    n_j = size_of("J")
    if not n_j:
        n_j = n_i
    for key in ("demand", "value", "weight"):
        value = data.get(key)
        if isinstance(value, list) and value:
            n_i = len(value)
            break
    for key in ("fixed_cost", "facility_capacity"):
        value = data.get(key)
        if isinstance(value, list) and value:
            n_j = len(value)
            break
    for key in ("distance", "service_cost", "coverage_matrix"):
        value = data.get(key)
        if isinstance(value, list) and value and isinstance(value[0], list):
            n_i, n_j = len(value), len(value[0])
            break
    return n_i, n_j


def build_model(
    ir: dict[str, Any], *, drop: tuple[str, ...] = ()
) -> tuple[pulp.LpProblem, ModelContext]:
    """Build the PuLP model described by *ir*, ignoring the blocks in *drop*."""
    blocks = [b for b in constraint_block_ids(ir) if b not in drop]
    objective = objective_block_id(ir)
    active = set(blocks) | {objective}

    unknown = sorted((active - set(OBJECTIVE_BUILDERS)) - set(CONSTRAINT_BUILDERS))
    if unknown:
        raise ValueError(f"没有可执行语义的块: {', '.join(unknown)}")
    if objective not in OBJECTIVE_BUILDERS:
        raise ValueError(f"目标块 {objective!r} 没有可执行语义")

    sense = str((ir.get("objective") or {}).get("sense") or "minimize")
    n_i, n_j = _sizes(ir)
    prob = pulp.LpProblem("nl2or", pulp.LpMinimize if sense == "minimize" else pulp.LpMaximize)
    ctx = ModelContext(ir=ir, prob=prob, data=collect_parameters(ir), n_i=n_i, n_j=n_j)

    if active & _X2_BLOCKS:
        ctx.var["x2"] = pulp.LpVariable.dicts("x", (range(n_i), range(n_j)), cat=pulp.LpBinary)
    if active & _Y_BLOCKS:
        ctx.var["y"] = pulp.LpVariable.dicts("y", range(n_j), cat=pulp.LpBinary)
    if active & _Z_BLOCKS:
        ctx.var["z"] = pulp.LpVariable.dicts("z", range(n_i), cat=pulp.LpBinary)
    if active & _W_BLOCKS:
        ctx.var["w"] = pulp.LpVariable("w", lowBound=0)
    if active & _X1_BLOCKS:
        ctx.var["x1"] = pulp.LpVariable.dicts("x", range(n_i), cat=pulp.LpBinary)

    for block in blocks:
        CONSTRAINT_BUILDERS[block](ctx)
    OBJECTIVE_BUILDERS[objective](ctx)
    return prob, ctx


def solve_ir(
    ir: dict[str, Any],
    *,
    drop: tuple[str, ...] = (),
    time_limit: int | None = None,
) -> SolveResult:
    """Solve the model described by *ir*; *drop* removes constraint blocks."""
    prob, ctx = build_model(ir, drop=drop)
    solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=time_limit)
    prob.solve(solver)
    status = pulp.LpStatus[prob.status]
    value = pulp.value(prob.objective)
    objective = float(value) if isinstance(value, (int, float)) else None

    variables: dict[str, float] = {}
    for name, var in ctx.var.items():
        if not isinstance(var, dict):
            if var.varValue:
                variables[name] = float(var.varValue)
            continue
        for key, item in var.items():
            if isinstance(item, dict):
                for sub_key, sub_item in item.items():
                    if sub_item.varValue:
                        variables[f"{name}[{key},{sub_key}]"] = float(sub_item.varValue)
            elif item.varValue:
                variables[f"{name}[{key}]"] = float(item.varValue)
    return SolveResult(objective=objective, status=status, variables=variables)


def analyze_tightness(ir: dict[str, Any], *, time_limit: int | None = None) -> dict[str, Any]:
    """Which constraint blocks change the optimum when removed."""
    base = solve_ir(ir, time_limit=time_limit)
    tight: list[str] = []
    nonbinding: list[str] = []
    failed: list[str] = []
    for block in constraint_block_ids(ir):
        variant = solve_ir(ir, drop=(block,), time_limit=time_limit)
        if variant.objective is None:
            failed.append(block)
        elif base.objective is not None and abs(variant.objective - base.objective) > 1e-6 * max(
            1.0, abs(base.objective)
        ):
            tight.append(block)
        else:
            nonbinding.append(block)
    return {
        "baseline_objective": base.objective,
        "status": base.status,
        "tight_blocks": tight,
        "nonbinding_blocks": nonbinding,
        "unsolved_blocks": failed,
    }


def render_script(ir: dict[str, Any], *, drop: tuple[str, ...] = ()) -> str:
    """Render a solver script that prints ``Objective: <value>``.

    The script resolves the project root from its own location, so a committed
    reference script stays portable inside the repository.
    """
    payload = json.dumps(ir, ensure_ascii=False)
    # 拆成多段相邻字符串字面量，避免生成超长行（切片按码点，不会截断转义或多字节字符）
    pieces = [payload[i : i + 70] for i in range(0, len(payload), 70)]
    literal = "\n".join(f"    {piece!r}" for piece in pieces)
    return (
        '"""Reference solver: model built from the case IR by block_model.py."""\n\n'
        "import json\n"
        "import sys\n"
        "from pathlib import Path\n\n"
        "# <repo>/benchmarks/references/solvers/<case>.py -> <repo>\n"
        "_ROOT = Path(__file__).resolve().parents[3]\n"
        "if (_ROOT / 'benchmarks').is_dir():\n"
        "    sys.path.insert(0, str(_ROOT))\n"
        "else:\n"
        f"    sys.path.insert(0, {str(_PROJECT_ROOT)!r})\n\n"
        "from benchmarks.references.block_model import solve_ir  # noqa: E402\n\n"
        "IR = json.loads(\n"
        f"{literal}\n"
        ")\n"
        f"DROP = {list(drop)!r}\n\n"
        "result = solve_ir(IR, drop=tuple(DROP))\n"
        "print('Objective:', result.objective)\n"
        "for name, value in sorted(result.variables.items()):\n"
        "    print(f'{name}: {value}')\n"
    )
