# 007 — `core/ir_processor.py` 单一文件过重

**Labels:** `refactor`, `high-priority`
**Priority:** 🔴 High
**Status:** ✅ Fixed — 2026-05-27

## 问题描述

`core/ir_processor.py` 包含了 5 类不同职责：

1. 数据加载：`load_block_catalog()`, `load_model_bank()`
2. 别名解析：`_canonical_block_id_fixed()`
3. 归一化逻辑：`_normalize_*` + `normalize_problem_ir()`
4. 格式化输出：`catalog_markdown()`

单一文件超过 300 行，职责混杂，难以测试和维护。

## 修复方案

拆分为两个职责明确的模块：

- **`core/ir_catalog.py`** — 数据加载 + 目录生成（`load_block_catalog`, `load_model_bank`, `catalog_markdown`）
- **`core/ir_normalizer.py`** — 归一化逻辑（`normalize_problem_ir` + 所有 `_normalize_*` 辅助函数）
- **`core/ir_processor.py`** — 保留为向后兼容的重导出包装

## 影响范围

- `nl2or_agent/core/ir_processor.py` → 拆分
- `nl2or_agent/core/ir_catalog.py` → 新增
- `nl2or_agent/core/ir_normalizer.py` → 新增
- `nl2or_agent/core/ir_validator.py` → 更新导入路径
- `nl2or_agent/core/__init__.py` → 更新导入
- `nl2or_agent/core/prompt_loader.py` → 更新导入
- `nl2or_agent/tools/model_library_tool.py` → 更新导入
