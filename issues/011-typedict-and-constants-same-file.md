# 011 — TypedDict 与常量同文件（`schema/problem_ir.py`）

**Labels:** `refactor`, `low-priority`
**Priority:** 🟢 Low
**Status:** ✅ Fixed — 2026-05-27

## 问题描述

`schema/problem_ir.py` 同时包含：

- 6 个 TypedDict 类定义（`ProblemFamily`, `ConstraintBlock`, `ObjectiveBlock`, `ProblemIR`, `ValidationReport`, `BlockCatalog`）
- 4 组 alias 映射 + 2 个 frozenset 常量
- 业务逻辑函数（`load_block_catalog`, `normalize_problem_ir`, 等 — 已在 #007 中移出）

## 修复方案

- 新建 `schema/ir_types.py`：纯 TypedDict 定义
- `schema/problem_ir.py`：仅保留 alias 常量 + 从 `ir_types` 重新导出 TypedDict（向后兼容）

## 影响范围

- `nl2or_agent/schema/ir_types.py` → 新增
- `nl2or_agent/schema/problem_ir.py` → 精简
