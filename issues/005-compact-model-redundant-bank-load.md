# 005 — `_compact_model` 在循环内重复加载模型库（性能问题）

**Labels:** `performance`, `low-priority`  
**Priority:** 🟢 Low  
**Status:** 📝 Open

## 问题描述

`tools/model_library_tool.py` 中的 `_compact_model()` 辅助函数，在处理"有 family 字段的模型"时，会在函数内部调用 `load_model_bank()` 读取并解析 `models.json`：

```python
def _compact_model(m: dict[str, Any], blocks_bank: dict[str, Any]) -> dict[str, Any]:
    ...
    if family_name := m.get("family"):
        from core.ir_processor import load_model_bank
        mb = load_model_bank()          # ← 每次都从磁盘重新读取 JSON
        family = mb["by_id"].get(family_name)
        ...
```

`_compact_model` 由 `QueryModelLibraryTool.forward()` 对每个匹配结果调用（最多 3 条），而 `forward()` 本身已经读取了 `models.json`：

```python
with open(self._bank_path, encoding="utf-8") as f:
    bank = json.load(f)         # ← 已加载
...
payload["templates"] = [_compact_model(m, blocks_bank) for m in models]
```

因此，当搜索结果包含多个 family 模型时，`models.json` 会被**重复读取和解析**，造成不必要的 I/O 开销。

## 建议修复

在 `forward()` 中将已加载的 `bank` 传入 `_compact_model`，避免重复读取：

```python
def _compact_model(m: dict[str, Any], blocks_bank: dict[str, Any], bank: dict[str, Any] | None = None) -> dict[str, Any]:
    ...
    if family_name := m.get("family"):
        by_model_id = {mo["id"]: mo for mo in (bank or {}).get("models", [])} if bank else {}
        family = by_model_id.get(family_name)
        ...
```

或者将 `_compact_model` 重构为一个类方法，持有预加载的 bank 引用。

## 影响范围

- `nl2or_agent/tools/model_library_tool.py` — `_compact_model()`
- `nl2or_agent/tools/model_library_tool.py` — `QueryModelLibraryTool.forward()`

## 注意

当前模型库较小（数十条记录），实际性能影响有限。但在模型库增长或高并发场景下，此问题会被放大。
