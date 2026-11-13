# Issues

## 说明

只保留仍在跟踪的问题。已完成的问题按主题归档在下方，详细过程见 git 历史。

## Issue 列表

当前没有未完成条目。

## 已完成归档

| 主题 | 内容 | 结果 |
|------|------|------|
| 奥卡姆剃刀 | 工具 7→4（删 `query_model_library`、`list_block_catalog`、`ir_to_script`）；IR 删 `report` 规格面与 4 个死字段；`schema/` 并入 `ir_normalize`；删 `solve_references.py`、`examples/`、`keywords`；`Session.save_model` 移除 | 已完成 |
| 模型库 v2 与 location 扩展 | `class`/`inherits` 分离；新增 p-median 距离上限、禁配、有容量 p-center、预算最大覆盖、有容量最大覆盖、p-dispersion、预算设施选址；新增距离、禁配、预算、容量覆盖与设施分散块 | 已完成 |
| 数学模型与报表 | `model_document`、`model_math`、报表 profile 与表渲染、`solve_ir` 结果报表 | 已完成 |
| reviewer 清理 | `weight` 死声明、`solve_ir` 重复输出、校验载荷三处双写、模型库查询重复公式、文档漂移、零散赘余 | 已完成 |
| 会话工作区保留策略 | CLI 对话落盘、CLI 启动清理、递归 `mtime` 判定活跃度 | 已完成 |
| 模型库参数一致性 | 背包 `weight` 必填；删除无实现的 `coverage_distance` 声明 | 已完成 |
| 求解与校验链路 | `solve_ir` 快路径、块语义统一、what-if 参数情景、顶层参数校验、OR-Library 用例 | 已完成 |
| Web 与会话 | 会话隔离、文件面板、模型视图、代码重跑 | 已完成 |
| 重构与清理 | `ir_processor` 拆分、TypedDict 与常量分离、模型库查询复用、`_compact_model` 加载路径 | 已完成 |
