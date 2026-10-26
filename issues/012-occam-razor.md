# 012 — 奥卡姆剃刀组分削减

**Labels:** `refactor`, `cleanup`, `design`  
**Priority:** 🟡 Medium  
**Status:** ✅ Fixed

## 目标

按工作流梳理必要的组分：只保留承载不可替代环节的模块与工具，删除无消费者或与既有回路重复的部分。删除后全链路（提示词、数据、测试、文档）保持自洽。

## 必要的组分

| 环节 | 承载者 |
|------|--------|
| 解析与建模 | CodeAgent + `prompts/`（附录自带全量块目录与 IR 规范） |
| 规范源 | `constraint_blocks.json`（块语义）+ `models.json`（骨架要求） |
| 校验 | `validate_problem_ir`（归一 + 骨架 + 维度；反馈即查库） |
| 求解 | `solve_ir`（块语义唯一实现）+ `run_solver`（库外块兜底） |
| 文档与报表 | `core/model_document.py` + `core/report.py`（按块派生） |
| 会话与前端 | `utils/session.py` + `web/` |
| 回归 | `benchmarks/` 五层 |

## 删除的不必要组分

| 组分 | 删除依据 |
|------|----------|
| `query_model_library` 工具（`tools/model_library_tool.py`） | 校验回路已覆盖其检索职能（声明的族与块由骨架校验逐项核对）；automatic 模式早已把它降为可选，附录目录 + IR 规范已含建库所需词汇 |
| `list_block_catalog` 工具 | 系统提示词附录的 canonical block 表（`catalog_markdown`）每次都在上下文中，工具只是让模型花一次调用重读同一张表 |
| `ir_to_script` 工具（`tools/ir_script_tool.py`） | `solve_ir` 落盘同一份渲染脚本，「代码」页可查看、编辑与重跑；工具只是把脚本文本再塞一遍对话 |
| IR 的 `report` 规格字段（`profile` / `tables` / `audience`） | 实测零自由度：`tables` 只能等于派生表，`audience` 校验后没有任何渲染器读取；报表类型本应由块结构唯一决定 |
| IR 死字段 `is_hybrid` / `hybrid_notes` / `decision_variables` / family 的 `confidence` | 全项目零消费（`is_hybrid` 仅一条测试断言） |
| `schema/` 包 | 36 行、4 个常量、唯一消费者是 `ir_normalize`；并入该模块 |
| `benchmarks/references/solve_references.py` | 与 T2 层重复：T2 每轮把同一批参考脚本经 `RunSolverTool` 重放并与 `solver_objective` 比对 |
| `examples/` | 单个文件、无任何引用 |
| 两份库文件中的 `keywords` 数组 | 唯一消费者是被删的检索工具 |
| `Session.save_model` | 生产路径直接走 `write_model_of_record`，方法仅测试使用 |

## 实现

- 工具：`tools/` 由 7 个减为 4 个（`validate_problem_ir`、`model_math`、`solve_ir`、`run_solver`）；`agents/nl2or_agent.py` 注册同步。
- 提示词：system 工具清单与校验步骤删去目录/检索/脚本工具；interactive 工作流删除 MODEL LOOKUP 轮次（解析 → 确认 → 求解）；automatic 的 Step 2 改为 SOLVING；`problem_ir_format` 删除 `report` 节与三个死字段，`problem_families` 记为 `{id}`。
- IR：`normalize_with_context` 不再回填 `is_hybrid`、`hybrid_notes`、`decision_variables`、`report`；`_normalize_family` 只保留 `{id}` 并删除置信度归一化；别名映射与 `FORBIDDEN_AS_BLOCK`、`VALID_STATUS` 移入 `ir_normalize.py`。
- 报表：删除 `validate_report_spec` 与 `AUDIENCES`；`render_report` 直接用 `default_report_spec` 派生；`solve_ir` 不再有「报表类型不一致」的失败分支；Web 模型视图的「报表规格」段删除。
- 数据：`models.json` 与 `constraint_blocks.json` 删除全部 `keywords`；`models.json` 的 `decision_variables` 字段统一为 `variables`；`import_orlib.py` 不再写入 `confidence`。
- 存储：删除 `Session.save_model`，测试直接调用 `write_model_of_record`。
- 修复 011 的三处残留：不可行情景只由 `format_solution` 陈述一次；README 的 schema 标签与 ASCII 工作流图同步为现状（solve_ir 主路径）。

## 验收

- `uv run ruff check .` 通过；`uv run pytest tests/` 293 项全部通过（删除的 44 项测试随被删组件一并移除）。
- `query_model_library`、`list_block_catalog`、`ir_to_script`、`validate_report_spec`、`keywords`、`is_hybrid` 在全仓无代码引用（历史更新日志与已生成的参考脚本除外）。
