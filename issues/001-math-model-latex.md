# 001 — 数学模型输出与 LaTeX 渲染

**Labels:** `feature`, `ir`, `prompt`  
**Priority:** 🔴 High  
**Status:** ✅ Fixed

## 目标

由 Problem IR 生成完整的数学模型文档，供最终答复、Web 模型视图与教学说明使用。模型文档包含索引集合、参数、决策变量、目标函数与逐条约束，公式使用 LaTeX 语法。

## 现状

- `constraint_blocks.json` 的每个块已有 `math` 字段，目标块也有 `math` 与 `sense`。
- 模型条目的 `variables` 与 `parameters` 提供变量和参数的自然语言含义。
- IR 只有结构化的 `constraint_blocks` 与 `objective`，没有组装成一份可读的模型文档。

## 范围

- 新增 `core/model_document.py`，提供 `render_model_document(ir)`，返回 Markdown + LaTeX。
- `validate_problem_ir` 的报告增加 `model_document` 字段。
- 新增 `model_math` 工具，输入 IR，返回同一份文档。
- 提示词要求最终答复包含“数学模型”段落，公式使用 `$$...$$`。
- Web 模型视图展示模型文档，Gradio 的 Markdown 组件按 LaTeX 渲染。
- 库外目标没有 `math` 时回退到 `expression` 或 `natural_language`。

## 实现

- `core/model_document.py`：组装索引集合、参数、变量、目标与约束；变量优先取模型条目，缺失时由启用块派生。
- `model_math` 工具：输入 IR，返回 Markdown + LaTeX；`validate_problem_ir` 报告增加 `model_document`。
- 提示词：最终答复包含数学模型段落，公式使用 `$$...$$`；交互模式的教学步骤调用 `model_math`。
- Web 模型视图：展示模型文档。

## 验收

- p-median、p-dispersion、背包、有容量最大覆盖各渲染一次，文档包含全部变量、目标与约束。
- 每个在库目标块的 `math` 都能出现在文档中。
- 库外目标保留原表达式并给出提示。
- 测试覆盖文档结构与 LaTeX 定界符。
