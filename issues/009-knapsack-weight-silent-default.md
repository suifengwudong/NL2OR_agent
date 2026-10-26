# 009 — 背包 `weight` 语义读取但块目录未声明，缺失时静默按 1.0 求解

**Labels:** `bug`, `ir`, `model-bank`  
**Priority:** 🟡 Medium  
**Status:** Open

## 问题描述

003 修复后的镜像问题：这次是「语义读取、目录未声明」，声明了必填却没有任何机制执行。

- `READ_BLOCK_KEYS["knapsack_capacity"] = ("capacity", "weight")` — 可执行语义读取 `weight`；
- `constraint_blocks.json` 的 `knapsack_capacity` 块只声明 `capacity` 必填，`weight` 不在其参数列表中，因此现有的必填参数检查（`validate_problem_ir` 遍历块目录）从不要求 `weight`；
- `models.json` 的 `knapsack` 条目声明 `weight` 为 `required: true`，但模型级的 `required` 在全项目中没有任何校验读取它；
- `_knapsack_capacity` 用 `ctx.list_value("weight", ctx.n_i)` 取值，缺失时回退全 1.0，静默。

003 修复加的「参数未被任何已启用块读取」提示只覆盖「声明了但没人读」的方向；「语义要读但 IR 没给」的方向没有对应检查。

## 复现证据

背包 IR 给 `capacity: 50` 与 `value: [60, 100, 120]`，不给 `weight`：

- `validate_problem_ir`：valid=True，errors 与 warnings 均为空；
- `solve_ir`：`[RESULT] Objective: 280`（60+100+120），物品重量全部按 1.0 参与容量约束。

正确的答案取决于真实重量；无论结果数值如何，这里是一条静默的错解路径，而库条目明确宣称 `weight` 必填。

## 建议修复

在 `constraint_blocks.json` 的 `knapsack_capacity` 块参数中声明 `weight` 为必填（与 `facility_capacity` 块同时声明 `facility_capacity` 与 `demand` 的写法一致）。现有必填参数检查立即生效，不新增机制；OR-Library 与手工背包用例的 `weight` 都声明在顶层参数中，不受影响。

## 影响范围

- `data/model_bank/constraint_blocks.json` — `knapsack_capacity`
- `tests/` — 补一条背包缺 `weight` 的负例或提示类断言

## 验收

- 背包 IR 缺 `weight` 时校验报错（或按项目约定给出明确提示），不再静默以 1.0 求解。
- 现有 337 项测试保持通过。
