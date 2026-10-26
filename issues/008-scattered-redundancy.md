# 008 — 零散赘余清单：死分支、重复契约正则、借道存盘与手写 LRU

**Labels:** `cleanup`, `redundancy`  
**Priority:** 🟢 Low  
**Status:** ✅ Fixed

## 问题清单

逐条可独立处理，均为小改动：

1. **`search_by_keywords` 的 `ast.literal_eval` 扁平化分支生产不可达**（`utils/search.py:77-91`）。两个生产调用点（`tools/model_library_tool.py:23,35`）都传 `search_fields`，走的是不展平的分支；`search_fields=None` 的扁平化分支只有测试自己调用。且 `search_fields` 路径对列表字段用 Python repr 字符串做子串匹配（`"['p-median', ...]"`），扁平化逻辑当初正是为这类字段写的，却没有接到这条路径上。修法：在 `search_fields` 分支内对列表值展平，删除 `literal_eval` 分支。
2. **「Objective: <值>」契约正则三份拷贝**：`tools/solver_tool.py:19`、`benchmarks/run_benchmark.py:51`、`benchmarks/references/solve_references.py:19`。契约只有一处定义，三处引用；`solve_references.py` 的子进程执行逻辑也与 `RunSolverTool._execute` 重复，可改调 `RunSolverTool`。
3. **代码存盘两条写法与借道实例**：`RunSolverTool.save_code`（`tools/solver_tool.py:84`）与 `Session.save_code`（`utils/session.py:93`）各自实现一份 `filename or f"solver_{uuid...}.py"` 默认逻辑；`SolveIrTool._save_script`（`tools/solve_ir_tool.py:92-94`）与 `IrScriptTool.forward`（`tools/ir_script_tool.py:51`）为了调 `save_code` 各自构造一个 `RunSolverTool` 实例。修法：存盘函数归 `utils/session` 一个模块级函数（与 `write_model_of_record` 同型），三个工具直接调用。
4. **纯别名常量**：`tools/model_library_tool.py:15-16` 的 `_DEFAULT_BANK_PATH = MODEL_BANK_PATH`、`_DEFAULT_BLOCKS_PATH = BLOCKS_CATALOG_PATH`，直接使用 `core._defaults` 常量即可。
5. **一行包装**：`web/app.py:59-61` 的 `_display_answer` 只转发 `format_agent_output`，调用点仅一处。
6. **手写 LRU 的裁剪使淘汰失真**（`web/app.py:71-84`）：`_agent_access_order` 超过 `_MAX_AGENTS * 2` 时裁到尾部 100 个，此后部分已缓存会话不在序表里，淘汰 `pop(0)` 弹出的可能是最近使用的会话，真正的最久未用项反而常驻。用 `collections.OrderedDict` + `move_to_end` 三行可替代并消除该缺陷。
7. **schema 的 7 个 TypedDict 全项目零引用**：`ProblemIRDict`、`ProblemFamily`、`ConstraintBlock`、`ObjectiveBlock`、`EntitySet`、`ValidationReport`、`BlockCatalog` 只在 `schema/__init__.py` 转出口，无任何注解使用；且 `BlockCatalog` 与真实目录已漂移（缺 `objective_sense` 键）。修法：删除，或落到 `normalize_with_context` 等函数的真实标注上。
8. **`_score_solver_case` 对同一用例重复全量校验**（`benchmarks/run_benchmark.py:271,283`）：参考脚本缺失时 `_normalized_ir(case)` 被调两次，每次都跑完整校验并渲染数学文档。归一化结果取一次复用即可。

## 验收

逐条修完后 `uv run ruff check .` 与全部测试通过；第 1、6、7 条各配一条行为断言（search_fields 展平匹配、LRU 淘汰命中最久未用项、删除后无 import 残留）。
