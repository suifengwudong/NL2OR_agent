# 007 — 文档漂移：结构树缺新模块、评测表丢 T5、旧路径与已废弃方案残留

**Labels:** `docs`, `drift`  
**Priority:** 🟡 Medium  
**Status:** ✅ Fixed

## 问题描述

1. **`nl2or_agent/README.md` 项目结构树落后于现状**：`core/` 树缺 `model_document.py` 与 `report.py` 两个本轮新增模块；`tools/` 树的 `ir_tools.py` 注释漏掉 `ModelMathTool`；工具清单整体缺 `solve_ir` 与 `ir_to_script` 的说明。
2. **架构 mermaid 图只有 4 个工具**：图中 tools 层只画 `ListBlockCatalogTool / ValidateProblemIrTool / QueryModelLibraryTool / RunSolverTool`，缺 `SolveIrTool`、`ModelMathTool`、`IrScriptTool`，而求解现在默认走 `solve_ir`，`run_solver` 已是退路，图与实际工作流相反。
3. **评测表双份维护已漂移**：主 README 的 Benchmark 一节写「提供五层评测，T1、T2、T4、T5 不依赖 LLM」，但表里只有 T1–T4 四行，T5（情景对比，`--mode what_if`）整行缺失；`benchmarks/README.md` 的五层表是完整的。同一张表两处维护，主 README 这份已经少一行。
4. **`benchmarks/README.md` 引用已迁移的路径**：「可执行语义」一节写 `references/block_model.py` 是块的可执行语义，该模块 2026-10-15 已迁至 `core/block_model.py`，`benchmarks/references/` 下已无此文件。
5. **「二、主循环简易开发文档」整节描述被取代的方案**：Pydantic 强制 schema（依赖已移除）、StructuredFinalAnswer（已删除）、FastAPI `/chat` 与 `/upload`（不存在），且与 `docs/` 下的历史设计文档内容重叠，读者无从分辨哪份是现状。

## 建议修复

- 评测表以 `benchmarks/README.md` 为唯一维护点，主 README 的 Benchmark 一节只留链接与一句概述。
- 结构树与 mermaid 图补齐 7 个工具与 `core/report.py`、`core/model_document.py`，求解主路径标为 `solve_ir`。
- `benchmarks/README.md` 的路径改为 `core/block_model.py`。
- 删除「二、主循环简易开发文档」整节；历史方案归 `docs/`，现状以「架构说明」一节为准。

## 影响范围

- `nl2or_agent/README.md`
- `nl2or_agent/benchmarks/README.md`

## 验收

- 结构树、mermaid 图、评测表与代码逐项核对一致；评测表只在 `benchmarks/README.md` 出现一次。
- 全文检索 `references/block_model.py`、`Pydantic`、`StructuredFinalAnswer` 无现状性残留描述。
