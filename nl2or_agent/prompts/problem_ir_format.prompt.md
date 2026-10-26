# Problem IR 规范（与 constraint_blocks.json 对齐）

## 顶层字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `problem_families` | list | `{id, name, confidence, notes}`；`id` 用 `p_median`、`facility_location` 等 |
| `is_hybrid` | bool | 多族组合或含自定义约束时为 true |
| `entities` | object | 索引集合：`{"I": {"size": 6}, "J": {"size": 5, "ids": ["A","B","C","D","E"]}}`；`ids` 可省略 |
| `parameters` | object | 数值数据：p、distance、demand、weight、fixed_cost、service_cost、coverage_matrix、facility_capacity、capacity、forced_open、availability、facility_distance、service_distance_limit、opening_budget 等 |
| `decision_variables` | list | `{symbol, type, meaning}` |
| `objective` | object | 必须含 `block_id`（库中目标块）与 `sense`，见下 |
| `constraint_blocks` | list | 仅含库中**约束**块，每项见下 |
| `custom_constraints` | list[str] | **仅**非库标准规则的自然语言/公式，不得作为 block_id |
| `missing_data` | list[str] | 缺失数据说明 |
| `report` | object | 可选报表规格：`profile`、`tables`、`audience`；`profile` 由块结构决定，见下 |

`entities` 用来核对数据是否与索引集合一致，写出来就能被校验：`p <= |J|`、`demand`/`value`/`weight` 长度等于 `|I|`、`distance`/`service_cost`/`coverage_matrix`/`availability` 维度等于 `|I| x |J|`、`fixed_cost`/`facility_capacity` 长度等于 `|J|`、`facility_distance` 维度等于 `|J| x |J|`、`service_distance_limit`/`opening_budget` 为非负标量、`forced_open`/`forced_closed` 落在 `J` 内。数据可以放在顶层 `parameters`，也可以放在对应块的 `parameters` 里；字符串视为占位说明，不参与校验。

## constraint_blocks 每一项

```json
{
  "block_id": "cardinality_open_p_facilities",
  "parameters": {"p": 2},
  "status": "required",
  "natural_language": "恰好开设2个设施"
}
```

- `block_id`：必须是附录 catalog 表中的标准 id（禁止 `assignment`、`linking`、`forcing`、`custom_constraints`）。
- `parameters`：该块 `required_parameters` 列出的参数必须出现（可用说明文字作为占位值）。
- `status`：`required` | `optional` | `user_specified`

## objective 对象

```json
{
  "sense": "minimize",
  "block_id": "weighted_service_distance_objective",
  "expression": "sum_i sum_j w_i d_ij x_ij",
  "natural_language": "最小化加权总距离"
}
```

- `block_id`：取自 catalog 的 `objective_block_ids`；`sense` 与该块的 `sense` 一致（`covered_demand_objective`、`maximize_min_pairwise_distance_objective` 与 `total_value_objective` 是 maximize，其余为 minimize）。
- 目标块的 `required_parameters` 需在 `objective.parameters` 或顶层 `parameters` 中出现。
- 库中没有对应目标块时，保留原有 `expression` 与 `sense` 并允许它留在 `block_id` 之外；校验会把该目标标为库外目标并给出提示，不会替换成别的目标。

## report 对象

```json
{
  "profile": "location",
  "tables": ["opened_facilities", "assignments", "objective_breakdown"],
  "audience": "learner"
}
```

报表类型由已启用的块推导；显式写出 `profile` 时必须与推导结果一致。`tables` 只能取该类型允许的表，必需表会自动补齐。

| profile | 必需表 |
|---------|--------|
| `location` | `opened_facilities`、`assignments`、`objective_breakdown` |
| `set_covering` | `opened_facilities`、`objective_breakdown` |
| `covering` | `opened_facilities`、`coverage`、`objective_breakdown` |
| `knapsack` | `selected_items`、`objective_breakdown` |
| `dispersion` | `opened_facilities`、`pairwise_distance`、`objective_breakdown` |
| `capacity` | `opened_facilities`、`assignments`、`facility_load`、`objective_breakdown` |
| `covering_capacity` | `opened_facilities`、`coverage`、`facility_load`、`objective_breakdown` |
| `general` | `objective_breakdown` |
