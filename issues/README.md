# Issues

## 说明

只保留仍在跟踪的问题。已完成的问题按主题归档在下方，详细过程见 git 历史。

## Issue 列表

| 编号 | 标题 | 标签 | 优先级 | 状态 |
|------|------|------|--------|------|
| 001 | 数学模型输出与 LaTeX 渲染 | feature, ir, prompt | 🔴 High | ✅ Fixed |
| 002 | 报表类型严格映射 | feature, report, validation | 🔴 High | ✅ Fixed |
| 003 | `weight` 参数声明与可执行语义脱节 | bug, ir, model-bank | 🔴 High | ✅ Fixed |
| 004 | `solve_ir` 单次输出重复状态与目标值 | duplication, report, solve | 🟡 Medium | ✅ Fixed |
| 005 | 校验报告载荷重复 | duplication, ir, session | 🟡 Medium | ✅ Fixed |
| 006 | 模型库查询双份数学文本 | duplication, model-library, prompt | 🟡 Medium | ✅ Fixed |
| 007 | 文档漂移 | docs, drift | 🟡 Medium | ✅ Fixed |
| 008 | 零散赘余清单 | cleanup, redundancy | 🟢 Low | ✅ Fixed |
| 009 | 背包 `weight` 缺失时静默按 1.0 求解 | bug, ir, model-bank | 🟡 Medium | Open |
| 010 | `coverage_distance` 宣传的生成能力在代码中不存在 | bug, model-bank, ir | 🟡 Medium | Open |
| 011 | 复核残留：不可行情景双重提示、README 标签未随修复更新 | cleanup, duplication, docs | 🟢 Low | ✅ Fixed |
| 012 | 奥卡姆剃刀组分削减 | refactor, cleanup, design | 🟡 Medium | ✅ Fixed |

## 已完成归档

| 主题 | 内容 | 结果 |
|------|------|------|
| 奥卡姆剃刀 | 工具 7→4（删 `query_model_library`、`list_block_catalog`、`ir_to_script`）；IR 删 `report` 规格面与 4 个死字段；`schema/` 并入 `ir_normalize`；删 `solve_references.py`、`examples/`、`keywords`；`Session.save_model` 移除；全链路提示词、测试、README 同步 | 已完成，见 012 |
| 模型库 v2 与 location 扩展 | `class`/`inherits` 分离；新增 p-median 距离上限、禁配、有容量 p-center、预算最大覆盖、有容量最大覆盖、p-dispersion、预算设施选址；新增距离、禁配、预算、容量覆盖与设施分散块 | 已完成，334 项测试通过 |
| 数学模型与报表 | `model_document`、`model_math`、报表 profile 与表渲染、`solve_ir` 结果报表 | 已完成，337 项测试通过 |
| reviewer 清理 | `weight` 死声明、`solve_ir` 重复输出、校验载荷三处双写、模型库查询重复公式、文档漂移、零散赘余 | 已完成，337 项测试通过 |
| 求解与校验链路 | `solve_ir` 快路径、块语义统一、what-if 参数情景、顶层参数校验、OR-Library 用例 | 已完成 |
| Web 与会话 | 会话隔离、文件面板、模型视图、代码重跑 | 已完成 |
| 重构与清理 | `ir_processor` 拆分、TypedDict 与常量分离、模型库查询复用、`_compact_model` 加载路径 | 已完成 |
