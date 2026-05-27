# Problem IR 规范（与 constraint_blocks.json 对齐）

## 顶层字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `problem_families` | list | `{id, name, confidence, notes}`；`id` 用 `p_median`、`facility_location` 等 |
| `is_hybrid` | bool | 多族组合或含自定义约束时为 true |
| `parameters` | object | 数值数据：p、distance、weight、forced_open 等 |
| `decision_variables` | list | `{symbol, type, meaning}` |
| `objective` | object | 必须含 `block_id`（目标块），见下表 objective 类 |
| `constraint_blocks` | list | 仅含库中**约束**块，每项见下 |
| `custom_constraints` | list[str] | **仅**非库标准规则的自然语言/公式，不得作为 block_id |
| `missing_data` | list[str] | 缺失数据说明 |

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

## Step 1 代码流程（必须）

1. 可选：`list_block_catalog()` 查看标准 id  
2. 构建 Python `dict` 作为 `ir`  
3. `report = json.loads(validate_problem_ir(json.dumps(ir)))`  
4. 若 `report["valid"]` 为 false，根据 `errors` 修正后重新 validate  
5. `final_answer("请确认：\n" + json.dumps(report["normalized_ir"], ensure_ascii=False, indent=2))`

写入代码时用 `False`/`True`，禁止 JSON 的 `false`/`true`。
