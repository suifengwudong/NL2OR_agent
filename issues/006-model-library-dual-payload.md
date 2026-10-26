# 006 — 模型库查询输出双份数学文本，blocks 文件仍绕过缓存直读

**Labels:** `duplication`, `model-library`, `prompt`  
**Priority:** 🟡 Medium  
**Status:** ✅ Fixed

## 问题描述

1. **同一数学内容双份下发**。`_compact_model` 把 v1 字段 `objective`、`constraints`、`solver_hint` 原样转发，同时 `block_details` 又携带 `constraint_blocks.json` 的 `math`。一次 `query_model_library(keywords="p-median")` 输出 11324 字符，其中约束公式出现两遍：`constraints` 列表（`"sum_{j in J} x_ij = 1, for all i in I"`）与 `block_details[].math`（`\sum_{j \in J} x_{ij} = 1, ...`）。这些 v1 字段的消费方只有 `_compact_model` 本身，校验与文档渲染全部走块级语义，两份公式之间没有漂移测试。
2. **blocks 文件直读未复用 core**。`QueryModelLibraryTool.forward` 对 `constraint_blocks.json` 仍用 `open() + json.load()` 直读，绕过 `load_block_catalog()` 的按文件状态缓存与 schema_version 校验。归档 issue 010 的修复只覆盖了 bank 一侧（改走 `load_model_bank`），blocks 一侧漏掉了。
3. **`by_id` 在循环内重建**。`_compact_model` 每匹配一个模板就重建一遍 `{b["id"]: b for b in blocks_bank["blocks"]}`，该索引应与 blocks 加载同处取得一次。

## 建议修复

- `data/model_bank/models.json` 删除 `objective`、`constraints`、`solver_hint` 三个 v1 字段，`_compact_model` 停止转发；LLM 需要的公式由 `block_details[].math` 单份提供。`variables`/`decision_variables` 保留（`model_document._render_variables` 消费声明版本）。
- `forward` 改用 `load_block_catalog(self._blocks_path)`，`by_id` 索引随目录一次取得。
- `tests/test_tools.py` 中锁定 legacy 转发的夹具与断言跟随更新。

## 影响范围

- `data/model_bank/models.json` — 16 个具体模型条目
- `tools/model_library_tool.py` — `_compact_model`、`forward`
- `tests/test_tools.py`

## 验收

- `query_model_library` 输出中同一约束公式只出现一次。
- `constraint_blocks.json` 的读取路径只剩 `core/ir_catalog.py` 一处。
- 全部测试通过。
