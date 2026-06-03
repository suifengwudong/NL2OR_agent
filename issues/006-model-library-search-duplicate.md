# 006 — `model_library_tool.py` 与 `utils/search.py` 功能重复

**Labels:** `refactor`, `DRY`, `high-priority`
**Priority:** 🔴 High
**Status:** ✅ Fixed — 2026-05-27

## 问题描述

`tools/model_library_tool.py` 中定义了与 `utils/search.py` 功能完全相同的低层函数：

| model_library_tool.py | utils/search.py |
|---|---|
| `_keyword_list()` | `parse_keywords()` |
| `_score_keywords()` | `score_keywords()` |
| `_search_models()` (内联打分+排序) | `search_by_keywords()` |
| `_search_blocks()` (内联打分+排序) | `search_by_keywords()` |

严重违反 DRY 原则，维护时需要同时修改两处。

## 修复方案

- 删除 `model_library_tool.py` 中的 `_keyword_list`、`_score_keywords`
- `_search_models()` 和 `_search_blocks()` 改为调用 `search_by_keywords()`
- `forward()` 中 `_keyword_list` → `parse_keywords`

## 影响范围

- `nl2or_agent/tools/model_library_tool.py`
