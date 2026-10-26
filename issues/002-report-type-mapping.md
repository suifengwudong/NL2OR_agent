# 002 — 报表类型严格映射

**Labels:** `feature`, `report`, `validation`  
**Priority:** 🔴 High  
**Status:** ✅ Fixed

## 目标

按模型类型选择固定的报表集合，避免不同问题都输出同一段决策摘要。报表由 IR 的块与变量角色派生，渲染结果进入 `solve_ir` 输出与最终答复。

## 现状

- `format_solution` 只输出状态、覆盖、目标值与决策摘要。
- `web/views.py` 只渲染 IR 对照，没有解报表。
- IR 没有报表规格字段，模型类型与报表集合之间没有约束。

## 范围

- 新增 `core/report.py`：`resolve_report_profile(ir)`、`validate_report_spec(ir, spec)`、`render_report(ir, result)`。
- IR 增加可选顶层 `report`：`profile`、`tables`、`audience`。
- 报表类型与必需表：
  - `location`：开设设施、分配关系、目标项
  - `covering`：开设设施、覆盖状态、目标项
  - `knapsack`：选中物品、目标项
  - `dispersion`：开设设施、最小设施间距、目标项
  - `capacity`：开设设施、分配关系、设施负荷、目标项
  - `covering_capacity`：开设设施、覆盖状态、设施负荷、目标项
  - `general`：目标项
- `profile` 与模型结构不一致时报错；请求的表名不在允许集合内时报错；必需表自动补齐。
- `solve_ir` 工具在 `[RESULT]` 之后追加报表；Web 模型视图可展示报表规格。

## 实现

- `core/report.py`：`resolve_report_profile`、`validate_report_spec`、`render_report` 与七类表渲染器。
- IR 顶层 `report`：`profile`、`tables`、`audience`；`validate_problem_ir` 默认补齐必需表并拒绝错误 profile 与非法表名。
- `solve_ir` 在 `[RESULT]` 与决策摘要后追加 `## 结果报表`；不可行情景只保留目标项。
- Web 模型视图展示报表规格。

## 验收

- p-median、集合覆盖、背包、p-dispersion、有容量 p-center、有容量最大覆盖各渲染对应报表。
- 错误 profile 与非法表名被 `validate_problem_ir` 拒绝。
- 报表列使用实体 id，不使用裸下标。
- 测试覆盖 profile 派生、必需表补齐、非法表名与渲染内容。
