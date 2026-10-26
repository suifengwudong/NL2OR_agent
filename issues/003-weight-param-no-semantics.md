# 003 — `weight` 参数声明与可执行语义脱节，只给 `weight` 的 IR 静默按 demand=1 求解

**Labels:** `bug`, `ir`, `model-bank`  
**Priority:** 🔴 High  
**Status:** ✅ Fixed

## 问题描述

模型库两处声明 `weight` 是需求权重的兼容字段，但可执行语义从未读取它：

- `data/model_bank/constraint_blocks.json` 的 `weighted_service_distance_objective` 声明可选参数 `weight`；
- `data/model_bank/models.json` 的 `p_median.parameters` 声明 `weight` 为「兼容旧字段：需求权重，可与 demand 等价」；
- 可执行语义的唯一实现 `core/block_model.py` 只读 `demand`：`READ_BLOCK_KEYS["weighted_service_distance_objective"] = ("distance", "demand")`，`_objective_weighted_service_distance` 调 `ctx.list_value("demand", ...)`，缺失时回退全 1.0，没有任何 weight→demand 的等价替换。

## 复现证据

IR 只给 `weight`（不给 `demand`），同一份数据改名为 `demand` 各求解一次：

| 参数键 | 校验结果 | solve_ir 目标值 |
|--------|----------|-----------------|
| `demand: [10, 20, 30]` | valid=True | 200 |
| `weight: [10, 20, 30]` | valid=True，无错误无提示 | 8（三个需求点全部按权重 1 求解） |

库宣称「可与 demand 等价」，实际等价关系不存在，且校验放行、求解不报错，最终答复会给出一个静默错误的目标值。

## 建议修复

1. 删除死声明：`constraint_blocks.json` 中 `weighted_service_distance_objective` 的 `weight` 参数，`models.json` 中 `p_median.parameters` 的 `weight` 条目。`weight` 继续保留给背包块（`knapsack_capacity` 语义真实读取它）。
2. 防复发：`validate_problem_ir` 对「已声明但没有任何活动块读取的参数键」给出提示，判据直接复用 `block_model.readable_keys(ir)`，不新增机制。

## 影响范围

- `data/model_bank/constraint_blocks.json` — `weighted_service_distance_objective`
- `data/model_bank/models.json` — `p_median.parameters`
- `core/ir_validate.py` — 若实施第 2 条
- `tests/` — 补一条 weight-only IR 的回归用例

## 验收

- 只给 `weight` 的 location IR 不再静默通过；按第 1 条修法时库中不再声明未被语义读取的参数。
- 背包用例不受影响，335 项测试保持通过。
