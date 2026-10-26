# 011 — 第二轮复核残留：不可行情景双重提示、README schema 标签与工作流图未随修复更新

**Labels:** `cleanup`, `duplication`, `docs`  
**Priority:** 🟢 Low  
**Status:** ✅ Fixed

## 问题清单

003–008 修复后逐项复核发现的残留，均为小改动，已在 012 的组分削减中一并处理：

1. **不可行情景的双重提示**（004 修复留下的相邻重复）。同一份 `solve_ir` 输出中，`format_solution` 打印 `[NOTE] 该情景没有最优解（不可行），不要为它编造目标值。`，`render_report` 又打印 `该情景没有最优解，以下只保留目标项。`——同一事实两次陈述。已改为只由 `format_solution` 陈述，报表侧只保留「以下只保留目标项」。
2. **README 中 schema 的标签仍写 TypedDict**。`nl2or_agent/README.md` 架构 mermaid 图与模块职责表已随 `schema/` 包的删除更新为现状。
3. **README 的 ASCII 工作流图未反映 solve_ir 主路径**。已改为 解析 → 确认 → 求解（`solve_ir` 主路径，库外块退 `run_solver`）。

## 影响范围

- `core/block_model.py`、`core/report.py` — 第 1 条
- `nl2or_agent/README.md` — 第 2、3 条
- `tests/test_report.py` — 第 1 条断言跟随

## 验收

- 不可行情景的 `solve_ir` 输出中「没有最优解」只出现一次。
- 全文检索 `TypedDict` 在 README 中无现状性残留描述；工作流图与现行主路径一致（或明确标注为历史设计）。
- 现有 337 项测试保持通过。
