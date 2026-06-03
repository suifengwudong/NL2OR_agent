# 012 — `_compact_model` 无保护的 fallback 加载

**Labels:** `refactor`, `low-priority`
**Priority:** 🟢 Low
**Status:** ✅ Fixed — 2026-05-27

## 问题描述

`tools/model_library_tool.py` 的 `_compact_model()` 在 `mb=None` 时会 fallback 到调用 `load_model_bank()`，重新读取磁盘文件。

虽然 `forward()` 现在传入了 `mb=bank`，但 fallback 路径仍然存在，且导入的是旧的 `core.ir_processor` 路径。

## 修复方案

- 更新 fallback 导入为 `core.ir_catalog.load_model_bank`
- 保留 fallback（防御性编程），但标记为 `# pragma: no cover`

## 影响范围

- `nl2or_agent/tools/model_library_tool.py`
