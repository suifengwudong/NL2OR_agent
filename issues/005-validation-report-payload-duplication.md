# 005 — 校验报告载荷重复：normalized_ir 双写、报表规格双写、model_document 双路

**Labels:** `duplication`, `ir`, `session`  
**Priority:** 🟡 Medium  
**Status:** ✅ Fixed

## 问题描述

`validate_problem_ir` 的返回值无差别打包全部产物（normalized IR、校验报告、报表规格、数学模型文档），每个消费方又各自再嵌一层，同一内容落多份：

1. **model.json 里归一化 IR 存两份**。`write_model_of_record(path, report["normalized_ir"], report)` 写出 `{saved_at, ir, report}`，而 `report` 内含 `normalized_ir`，与顶层 `ir` 是同一对象。实测键比对 `record["ir"] == record["report"]["normalized_ir"]` 为 True；现有会话中最大的 `model.json` 有 917 行，重复部分约占一半。
2. **报表规格存两份**。规格同时写入 `normalized_ir["report"]`（`validate_problem_ir` 第 52 行）与报告顶层 `report` 键（第 63 行），实测两者相等。报告顶层这份在全项目中只有 `tests/test_report.py:77` 一处读取，Web 视图读的是 `ir.get("report")`。
3. **数学模型文档两条产出路径**。`validate_problem_ir` 每次调用都渲染 `model_document` 并塞进返回 JSON，而提示词要求 agent 用 `model_math(json.dumps(ir))` 取同一份文档——后者内部再跑一遍完整校验（归一化、骨架、维度、报表规格）只为重新渲染同一个文档。agent 的工作流（提示词只读 `errors` 与 `skeleton`）不消费 validate 返回里的 `model_document`，这份内嵌副本是纯上下文膨胀；`run_benchmark._normalized_ir` 与 `import_orlib._normalize` 只要 `normalized_ir`，文档渲染的代价也照付。

## 建议修复

- `model.json` 只存报告一份：`write_model_of_record(path, report)`，归一化 IR 由 `report["normalized_ir"]` 提供；`web/views.py` 的取值点从 `payload["ir"]` 改为 `payload["report"]["normalized_ir"]`。
- 删除 `ValidationReport` 顶层 `report` 键，`tests/test_report.py:77` 改读 `normalized_ir["report"]`。
- `validate_problem_ir` 返回的 `model_document` 从工具回传 JSON 中裁掉（model.json 与 Web 视图仍保留），`ModelMathTool` 改为对归一化 IR 直接调 `render_model_document`，不再重复整条校验管线。

## 影响范围

- `core/ir_validate.py` — 返回值与规格写入位置
- `utils/session.py` — `write_model_of_record` 签名
- `tools/ir_tools.py` — `ModelMathTool.forward`、`ValidateProblemIrTool` 返回载荷
- `web/views.py` — 取值点一处
- `benchmarks/run_benchmark.py`、`benchmarks/import_orlib.py` — 取 `normalized_ir` 的调用点核对
- `tests/test_report.py`、`tests/test_main.py`、`tests/test_utils.py` — 断言与签名跟随

## 验收

- `model.json` 中归一化 IR 与报表规格各只出现一次，体积约为现在的 60%。
- agent 一次会话轮次内同一文档只生成一份（`model_math` 输出）。
- 全部测试通过。
