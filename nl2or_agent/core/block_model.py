"""Executable semantics of the block catalog: Problem IR -> PuLP model.

Core module: the single interface shared by the reference solvers, the OR-Library
importer, the tightness analysis, the T2 negative controls and ``solve_ir``:

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
from typing import Any, Callable

import pulp

from ._defaults import PROJECT_ROOT
from .problem_ir import ProblemIR

# ---------------------------------------------------------------------------
# Which variables each block needs
# ---------------------------------------------------------------------------

_X2_BLOCKS = {
    "assign_each_demand_once",
    "link_assignment_to_open",
    "facility_capacity",
    "max_service_distance_bound",
    "assignment_distance_limit",
    "assignment_availability",
    "assignment_coverage_activation",
    "weighted_service_distance_objective",
    "fixed_plus_service_cost_objective",
    "service_cost_objective",
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
    "opening_budget",
    "min_pairwise_distance_bound",
    "facility_opening_cost_objective",
    "fixed_plus_service_cost_objective",
    "maximize_min_pairwise_distance_objective",
}
_Z_BLOCKS = {
    "demand_coverage_activation",
    "assignment_coverage_activation",
    "covered_demand_objective",
}
_W_BLOCKS = {"max_service_distance_bound", "minimize_max_distance_objective"}
_DMIN_BLOCKS = {"min_pairwise_distance_bound", "maximize_min_pairwise_distance_objective"}
_X1_BLOCKS = {"knapsack_capacity", "total_value_objective"}

_STATUS_TEXT = {
    "Optimal": "最优",
    "Not Solved": "未求解",
    "Infeasible": "不可行",
    "Unbounded": "无界",
    "Undefined": "未定义",
}

SOLVE_STATUSES: frozenset[str] = frozenset(_STATUS_TEXT)

_VARIABLE_LABELS = {
    "y": "开设",
    "z": "覆盖需求",
    "x2": "分配",
    "x1": "选中",
    "dmin": "最小设施间距",
}


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

    def facility_matrix(self, key: str) -> list[list[float]]:
        raw = self.data.get(key)
        if (
            isinstance(raw, list)
            and len(raw) == self.n_j
            and all(isinstance(row, list) and len(row) == self.n_j for row in raw)
        ):
            return [[float(v) for v in row] for row in raw]
        raise ValueError(f"参数 {key!r} 缺失或维度不是 {self.n_j}x{self.n_j}")

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


def _assignment_distance_limit(ctx: ModelContext) -> None:
    x, d = ctx.var["x2"], ctx.matrix("distance")
    limit = float(ctx.data.get("service_distance_limit"))
    for i in range(ctx.n_i):
        for j in range(ctx.n_j):
            if d[i][j] > limit:
                ctx.prob += x[i][j] == 0


def _assignment_availability(ctx: ModelContext) -> None:
    x, a = ctx.var["x2"], ctx.matrix("availability")
    for i in range(ctx.n_i):
        for j in range(ctx.n_j):
            ctx.prob += x[i][j] <= a[i][j]


def _opening_budget(ctx: ModelContext) -> None:
    y = ctx.var["y"]
    fixed = ctx.list_value("fixed_cost", ctx.n_j)
    budget = float(ctx.data.get("opening_budget"))
    ctx.prob += pulp.lpSum(fixed[j] * y[j] for j in range(ctx.n_j)) <= budget


def _min_pairwise_distance_bound(ctx: ModelContext) -> None:
    y, dmin = ctx.var["y"], ctx.var["dmin"]
    distance = ctx.facility_matrix("facility_distance")
    big_m = max(max(row) for row in distance) if distance else 0.0
    for j in range(ctx.n_j):
        for k in range(j + 1, ctx.n_j):
            ctx.prob += dmin <= distance[j][k] + big_m * (2 - y[j] - y[k])


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


def _assignment_coverage_activation(ctx: ModelContext) -> None:
    x, z, a = ctx.var["x2"], ctx.var["z"], ctx.matrix("coverage_matrix")
    for i in range(ctx.n_i):
        ctx.prob += z[i] <= pulp.lpSum(a[i][j] * x[i][j] for j in range(ctx.n_j))


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


def _objective_service_cost(ctx: ModelContext) -> None:
    x = ctx.var["x2"]
    service = ctx.matrix("service_cost")
    ctx.prob += pulp.lpSum(service[i][j] * x[i][j] for i in range(ctx.n_i) for j in range(ctx.n_j))


def _objective_covered_demand(ctx: ModelContext) -> None:
    z = ctx.var["z"]
    demand = ctx.list_value("demand", ctx.n_i)
    ctx.prob += pulp.lpSum(demand[i] * z[i] for i in range(ctx.n_i))


def _objective_minimize_max_distance(ctx: ModelContext) -> None:
    ctx.prob += ctx.var["w"]


def _objective_max_min_pairwise_distance(ctx: ModelContext) -> None:
    ctx.prob += ctx.var["dmin"]


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
    "assignment_distance_limit": _assignment_distance_limit,
    "assignment_availability": _assignment_availability,
    "assignment_coverage_activation": _assignment_coverage_activation,
    "opening_budget": _opening_budget,
    "min_pairwise_distance_bound": _min_pairwise_distance_bound,
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
    "service_cost_objective": _objective_service_cost,
    "covered_demand_objective": _objective_covered_demand,
    "minimize_max_distance_objective": _objective_minimize_max_distance,
    "maximize_min_pairwise_distance_objective": _objective_max_min_pairwise_distance,
    "total_value_objective": _objective_total_value,
}


# ---------------------------------------------------------------------------
# Which parameter overrides this model actually reads
# ---------------------------------------------------------------------------

# The executable keys each block reads. Derived per model from the active
# blocks, so a key that no active block reads is rejected instead of being
# applied and silently ignored.
READ_BLOCK_KEYS: dict[str, tuple[str, ...]] = {
    "assign_each_demand_once": (),
    "link_assignment_to_open": (),
    "cardinality_open_p_facilities": ("p",),
    "cardinality_open_at_most_p_facilities": ("p",),
    "force_facility_open": ("forced_open",),
    "force_facility_closed": ("forced_closed",),
    "facility_capacity": ("demand", "facility_capacity"),
    "assignment_distance_limit": ("distance", "service_distance_limit"),
    "assignment_availability": ("availability",),
    "assignment_coverage_activation": ("coverage_matrix",),
    "opening_budget": ("fixed_cost", "opening_budget"),
    "min_pairwise_distance_bound": ("facility_distance",),
    "knapsack_capacity": ("capacity", "weight"),
    "cover_each_demand_at_least_once": ("coverage_matrix",),
    "demand_coverage_activation": ("coverage_matrix",),
    "max_service_distance_bound": ("distance",),
    "weighted_service_distance_objective": ("distance", "demand"),
    "total_service_distance_objective": ("distance",),
    "facility_opening_cost_objective": ("fixed_cost",),
    "fixed_plus_service_cost_objective": ("fixed_cost", "service_cost"),
    "service_cost_objective": ("service_cost",),
    "covered_demand_objective": ("demand",),
    "minimize_max_distance_objective": (),
    "maximize_min_pairwise_distance_objective": (),
    "total_value_objective": ("value",),
}


def active_variable_names(ir: dict[str, Any]) -> list[str]:
    """Variable roles the active blocks and objective actually use."""
    active = set(constraint_block_ids(ir)) | {objective_block_id(ir)}
    names: list[str] = []
    for name, blocks in (
        ("y", _Y_BLOCKS),
        ("x2", _X2_BLOCKS),
        ("z", _Z_BLOCKS),
        ("w", _W_BLOCKS),
        ("dmin", _DMIN_BLOCKS),
        ("x1", _X1_BLOCKS),
    ):
        if active & blocks:
            names.append(name)
    return names


def readable_keys(ir: dict[str, Any]) -> frozenset[str]:
    """The parameter keys this IR's blocks read, and only those."""
    blocks = [*constraint_block_ids(ir), objective_block_id(ir)]
    keys: set[str] = set()
    for block in blocks:
        keys.update(READ_BLOCK_KEYS.get(block, ()))
    return frozenset(keys)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_override_value(key: str, value: Any, n_i: int, n_j: int) -> None:
    """Reject an override whose value cannot be read as the key's own shape."""

    def fail(expected: str) -> None:
        raise ValueError(f"覆盖 {key!r} 的值应为{expected}，收到 {value!r}")

    if key == "p":
        if not _is_number(value) or value < 0 or float(value) != int(value):
            fail("非负整数")
        return
    if key in {"capacity", "service_distance_limit", "opening_budget"}:
        if not _is_number(value) or value < 0:
            fail("非负数")
        return
    if key in {"forced_open", "forced_closed"}:
        if not isinstance(value, list):
            fail("设施下标的列表")
        return
    if key in {"demand", "value", "weight", "fixed_cost", "facility_capacity"}:
        length = n_i if key in {"demand", "value", "weight"} else n_j
        if _is_number(value):
            return
        if (
            not isinstance(value, list)
            or len(value) != length
            or not all(_is_number(v) for v in value)
        ):
            fail(f"长度 {length} 的数值列表")
        return
    if key in {"distance", "service_cost", "coverage_matrix", "availability"}:
        shaped = (
            isinstance(value, list)
            and len(value) == n_i
            and all(
                isinstance(row, list) and len(row) == n_j and all(_is_number(v) for v in row)
                for row in value
            )
        )
        if not shaped:
            fail(f" {n_i}x{n_j} 的数值矩阵")
        return
    if key == "facility_distance":
        shaped = (
            isinstance(value, list)
            and len(value) == n_j
            and all(
                isinstance(row, list) and len(row) == n_j and all(_is_number(v) for v in row)
                for row in value
            )
        )
        if not shaped:
            fail(f" {n_j}x{n_j} 的数值矩阵")
        return
    fail("块模型可读取的值")


def prepare_overrides(ir: dict[str, Any], value: Any) -> dict[str, Any]:
    """Coerce, key-check and shape-check the overrides for this model."""
    overrides = ProblemIR.parse_overrides(value, allowed=readable_keys(ir))
    n_i, n_j = _sizes(ir)
    for key, item in overrides.items():
        _check_override_value(key, item, n_i, n_j)
    return overrides


# ---------------------------------------------------------------------------
# IR -> model
# ---------------------------------------------------------------------------


@dataclass
class SolveResult:
    objective: float | None
    status: str
    variables: dict[str, float] = field(default_factory=dict)


def describe_model(ir: dict[str, Any]) -> str:
    """One-line description of the model the IR describes."""
    families = [str(f.get("id")) for f in ir.get("problem_families") or [] if f.get("id")]
    blocks = constraint_block_ids(ir)
    objective = objective_block_id(ir)
    return (
        f"模型：{'、'.join(families) or '未声明族'}；"
        f"约束块 {len(blocks)} 个；目标块 {objective or '未声明'}"
    )


def format_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def objective_close(value: float, expected: float, tol: float = 1e-6) -> bool:
    """True when two objective values count as the same solution."""
    return abs(value - expected) <= tol * max(1.0, abs(expected))


def summarize_decisions(variables: dict[str, float]) -> str:
    """Compact decision summary, grouped by variable name (no per-family branches)."""
    scalars: list[str] = []
    groups: dict[str, list[str]] = {}
    for key, value in variables.items():
        if "[" not in key:
            scalars.append(f"{key}={format_number(value)}")
            continue
        name, rest = key.split("[", 1)
        groups.setdefault(name, []).append(rest.rstrip("]"))

    parts = list(scalars)
    for name, entries in sorted(groups.items()):
        label = _VARIABLE_LABELS.get(name, name)
        points = [entry for entry in entries if "," not in entry]
        edges = [entry for entry in entries if "," in entry]
        if points:
            parts.append(f"{label} [{', '.join(points)}]")
        if edges:
            parts.append(f"{label} {len(edges)} 条")
    return "；".join(parts) if parts else "—"


def format_solution(result: SolveResult, applied: dict[str, Any] | None = None) -> str:
    """Render one solved scenario as plain text for the agent to read and tabulate."""
    status = _STATUS_TEXT.get(result.status, result.status)
    if applied:
        shown = "、".join(
            f"{key}={format_number(value) if isinstance(value, (int, float)) else value}"
            for key, value in applied.items()
        )
    else:
        shown = "无（基准）"

    lines = [f"状态：{status}", f"应用的覆盖：{shown}"]
    if result.status == "Optimal" and result.objective is not None:
        # 与 run_solver 用同一行格式，最终答复里的目标值都取自它
        lines.append(f"[RESULT] Objective: {format_number(result.objective)}")
        lines.append(f"决策：{summarize_decisions(result.variables)}")
    else:
        lines.append(f"[NOTE] 该情景没有最优解（{status}），不要为它编造目标值。")
    return "\n".join(lines)


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
    for key in ("distance", "service_cost", "coverage_matrix", "availability"):
        value = data.get(key)
        if isinstance(value, list) and value and isinstance(value[0], list):
            n_i, n_j = len(value), len(value[0])
            break
    value = data.get("facility_distance")
    if isinstance(value, list) and value and isinstance(value[0], list):
        n_j = len(value)
    return n_i, n_j


def model_sizes(ir: dict[str, Any]) -> tuple[int, int]:
    """Public size view used by the report renderer."""
    return _sizes(ir)


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
    ctx = ModelContext(ir=ir, prob=prob, data=ProblemIR(ir).parameters, n_i=n_i, n_j=n_j)

    if active & _X2_BLOCKS:
        ctx.var["x2"] = pulp.LpVariable.dicts("x", (range(n_i), range(n_j)), cat=pulp.LpBinary)
    if active & _Y_BLOCKS:
        ctx.var["y"] = pulp.LpVariable.dicts("y", range(n_j), cat=pulp.LpBinary)
    if active & _Z_BLOCKS:
        ctx.var["z"] = pulp.LpVariable.dicts("z", range(n_i), cat=pulp.LpBinary)
    if active & _W_BLOCKS:
        ctx.var["w"] = pulp.LpVariable("w", lowBound=0)
    if active & _DMIN_BLOCKS:
        ctx.var["dmin"] = pulp.LpVariable("dmin", lowBound=0)
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
    if base.status != "Optimal" or base.objective is None:
        # 基准没有最优解时逐块比较没有意义；PuLP 还会残留上一次的目标值
        return {
            "baseline_objective": None,
            "status": base.status,
            "tight_blocks": [],
            "nonbinding_blocks": [],
            "unsolved_blocks": constraint_block_ids(ir),
        }
    tight: list[str] = []
    nonbinding: list[str] = []
    failed: list[str] = []
    for block in constraint_block_ids(ir):
        variant = solve_ir(ir, drop=(block,), time_limit=time_limit)
        if variant.objective is None or variant.status != "Optimal":
            failed.append(block)
        elif not objective_close(variant.objective, base.objective):
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

    The script locates the repo by its ``core`` package instead of counting path
    levels, so a committed reference script keeps working from any location inside
    the repository; the baked absolute path only covers being copied outside it.
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
        "_REPO_MARKER = Path('core') / 'block_model.py'\n\n\n"
        "def _repo_root() -> Path:\n"
        "    for base in Path(__file__).resolve().parents:\n"
        "        if (base / _REPO_MARKER).is_file():\n"
        "            return base\n"
        f"    return Path({str(PROJECT_ROOT)!r})\n\n"
        "sys.path.insert(0, str(_repo_root()))\n\n"
        "from core.block_model import solve_ir  # noqa: E402\n\n"
        "IR = json.loads(\n"
        f"{literal}\n"
        ")\n"
        f"DROP = {list(drop)!r}\n\n"
        "result = solve_ir(IR, drop=tuple(DROP))\n"
        "print('Objective:', result.objective)\n"
        "for name, value in sorted(result.variables.items()):\n"
        "    print(f'{name}: {value}')\n"
    )
