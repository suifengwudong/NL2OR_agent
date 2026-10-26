# 010 — `coverage_distance` 宣传的覆盖矩阵生成能力在代码中不存在

**Labels:** `bug`, `model-bank`, `ir`  
**Priority:** 🟡 Medium  
**Status:** Open

## 问题描述

与 003 同类：库条目声明的参数（及其承诺的能力）没有对应的任何实现。

- `models.json` 的 `set_covering.parameters` 与 `maximum_covering.parameters` 声明 `coverage_distance`：
  「C，覆盖距离阈值；若给定 distance，可由 d_ij <= C 生成 a_ij」；
- 全项目代码中 `coverage_distance` 无一处出现（`core/`、`tools/`、`tests/`、`benchmarks/` 均无）；核心语义只认块必填的 `coverage_matrix`；
- 即没有任何代码按 `distance <= C` 生成覆盖矩阵，`coverage_distance` 也不在任何可读取键词汇表中（`READABLE_DATA_KEYS`、`READ_BLOCK_KEYS`、块目录参数均无）。

003 修复加的「参数未被任何已启用块读取」提示会在 agent 真把 `coverage_distance` 写进 IR 时给出提示，但 `query_model_library` 的返回仍把该参数连同生成承诺下发给 agent——agent 按库的指导建模，随后必然撞上「缺少 coverage_matrix」的报错与「coverage_distance 未被读取」的提示，两处指导互相矛盾。

## 建议修复

二选一，按块语义唯一实现的项目方向推荐前者：

- 删除 `set_covering` 与 `maximum_covering` 参数列表中的 `coverage_distance` 条目（其描述里承诺的生成路径一并删除）；
- 或实现该生成能力：归一化阶段当 `coverage_matrix` 缺失且 `distance` 与阈值齐备时生成矩阵，配漂移测试。

## 影响范围

- `data/model_bank/models.json` — `set_covering`、`maximum_covering`

## 验收

- `query_model_library` 返回的参数列表中不再出现代码不认识的参数名。
- 现有 337 项测试保持通过。
