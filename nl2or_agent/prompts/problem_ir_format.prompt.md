# Problem IR 规范（与 constraint_blocks.json 对齐）

## 顶层字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `problem_families` | list | `{id}`；`id` 用 `search_model_library` / `describe_model` 返回的模型 id |
| `entities` | object | 索引集合：`{"I": {"size": 6}, "J": {"size": 5, "ids": ["A","B","C","D","E"]}}`；`ids` 按题面写法抄录，可省略 |
| `parameters` | object | 数值数据：只放被启用块读取的键，键名来自 `describe_model` 与块的参数定义 |
| `objective` | object | 必须含 `block_id`（库中目标块）与 `sense`，见下 |
| `constraint_blocks` | list | 仅含库中**约束**块，每项见下 |
| `custom_constraints` | list[str] | **仅**题面额外给出、库无法表达的限制；说明某个块不适用的句子不写进 IR |
| `missing_data` | list[str] | 缺失数据说明 |

`entities` 用来核对数据是否与索引集合一致：参数长度与维度、`p <= |J|`、`forced_open`/`forced_closed` 落在 `J` 内等检查由校验器执行，核对哪些键、什么形状以 `core/ir_validate.py::_check_entities` 为准；每个参数的名称、类型与必填性来自 `describe_model` 与检索结果。数据可以放在顶层 `parameters`，也可以放在对应块的 `parameters` 里；字符串视为占位说明，不参与校验。

## constraint_blocks 每一项

```json
{
  "block_id": "cardinality_open_p_facilities",
  "parameters": {"p": 2},
  "status": "required",
  "natural_language": "恰好开设2个设施"
}
```

- `block_id`：必须是 `describe_model` / `search_model_library` 返回的标准 id（未知 id 会被校验拒绝）。
- `parameters`：该块 `required_parameters` 列出的参数必须出现（可用说明文字作为占位值）。
- `status`：`required` | `optional` | `user_specified`
- `natural_language`：可选；省略时由目录描述补齐，用于追溯约束来源。

## objective 对象

```json
{
  "sense": "minimize",
  "block_id": "weighted_service_distance_objective",
  "expression": "sum_i sum_j w_i d_ij x_ij",
  "natural_language": "最小化加权总距离"
}
```

- `block_id`：取自 `describe_model` 返回的目标块；`sense` 与该块的 `sense` 一致（maximize 的目标块以 `describe_model` 标注为准）。
- `natural_language`：可选；省略时由目录描述补齐。
- 目标块的 `required_parameters` 需在 `objective.parameters` 或顶层 `parameters` 中出现。
- 库中没有对应目标块时，保留原有 `expression` 与 `sense` 并允许它留在 `block_id` 之外；校验会把该目标标为库外目标并给出提示，不会替换成别的目标。

