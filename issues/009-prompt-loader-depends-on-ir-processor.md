# 009 — `prompt_loader.py` 直接依赖 `ir_processor`

**Labels:** `refactor`, `medium-priority`
**Priority:** 🟡 Medium
**Status:** ✅ Fixed — 2026-05-27

## 问题描述

`core/prompt_loader.py` 的 `load_system_prompt()` 直接从 `ir_processor` 导入 `catalog_markdown`：

```python
from .ir_processor import catalog_markdown
```

Prompt 组装是"表现层"关注点，直接依赖 IR 处理引擎造成了职责倒置。当 `ir_processor` 被拆分后，此导入也应更新。

## 修复方案

```python
from .ir_catalog import catalog_markdown
```

`catalog_markdown` 本质上是数据格式化函数，属于 catalog 层，不涉及归一化逻辑。

## 影响范围

- `nl2or_agent/core/prompt_loader.py`
