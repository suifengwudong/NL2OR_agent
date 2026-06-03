# 010 — `model_library_tool.py` 直读 JSON，不复用 `core` 的加载函数

**Labels:** `refactor`, `medium-priority`
**Priority:** 🟡 Medium
**Status:** ✅ Fixed — 2026-05-27 (forward 直接 json.load 读取 bank 暂保留)

## 问题描述

`QueryModelLibraryTool.forward()` 直接用 `json.load()` 读取 `models.json`：

```python
with open(self._bank_path, encoding="utf-8") as f:
    bank = json.load(f)
```

而 `core/ir_processor.py`（现 `core/ir_catalog.py`）已有 `load_model_bank()` 做同样的事情，且额外构建 `by_id` 和 `effective_blocks` 索引。

`_compact_model` 在 fallback 路径中也会重复加载。

## 修复方案

- `forward()` 继续使用直接 `json.load()`（因为 `QueryModelLibraryTool` 可接受自定义路径，需要灵活性）
- `_compact_model` 的 fallback 改为从 `core.ir_catalog.load_model_bank` 导入
- 接受 `mb` 参数传递已加载的 bank，避免重复 I/O

## 影响范围

- `nl2or_agent/tools/model_library_tool.py`
