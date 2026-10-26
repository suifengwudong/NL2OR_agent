# 004 — `solve_ir` 单次输出重复陈述状态与目标值

**Labels:** `duplication`, `report`, `solve`  
**Priority:** 🟡 Medium  
**Status:** ✅ Fixed

## 问题描述

`SolveIrTool.forward` 把 `describe_model`、`format_solution`、`render_report` 三段拼接返回。`format_solution` 与 `render_report` 各自渲染一遍状态，目标值出现三次，且同一状态有两种写法。实测一次 p-median 求解的输出：

```
状态：最优                      ← format_solution
应用的覆盖：无（基准）
[RESULT] Objective: 200        ← 目标值第 1 次
决策：分配 3 条；开设 [0]

## 结果报表

**状态**：Optimal              ← 状态第 2 次，同一事实换成英文
**目标值**：200                ← 目标值第 2 次

**目标项**
| 加权服务距离目标（`weighted_service_distance_objective`） | 最小化 | 200 |   ← 目标值第 3 次
```

每次求解调用都把同样的两三个事实重复发给模型上下文，情景对比时逐情景放大。

## 建议修复

- `render_report` 去掉 `**状态**` 与 `**目标值**` 两个头部行：状态由 `format_solution` 承载，目标值由 `[RESULT]` 行（机器契约）与目标项表（人工报表）承载。不可行情景的「该情景没有最优解」提示保留。
- 状态文本统一为一种语言（建议沿用 `_STATUS_TEXT` 的中文写法，目标项表方向列已是中文）。

## 影响范围

- `core/report.py` — `render_report` 头部两行
- `core/block_model.py` — 若统一状态语言需调整 `_STATUS_TEXT` 的使用位置
- `tests/test_report.py` — 不可行情景的两条断言改为不再检查 `**目标值**` 头部

## 验收

- 一次 `solve_ir` 输出中状态只出现一次、目标值至多两次（`[RESULT]` 行与目标项表）。
- `tests/test_report.py` 全部通过。
