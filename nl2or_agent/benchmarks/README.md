# NL2OR Benchmark

评估 NL2OR Agent 的建模与求解能力。所有用例（`cases.json` 与 `orlib_cases/*.json`）使用同一套 schema，五层评测共用同一份加载与报告接口。

## 用例 schema

```json
{
  "id": "p_median_community",
  "name": "P-Median 社区服务中心",
  "family": "p_median",            // 分组用，缺省取 expected.families[0]
  "scale": "s",                    // s / m / l，分组用
  "tiers": ["ir", "solver", "online", "tightness", "what_if"],
  "problem": "自然语言题面（online 输入）",
  "input_ir": { },                 // 脏 IR：别名、占位值，并携带可执行数据与 entities
  "expected": {                    // T1 必须得到的判定；只断言写出来的键
    "valid": true,
    "families": ["p_median"],
    "block_ids": ["assign_each_demand_once", "..."],
    "objective_block": "weighted_service_distance_objective",
    "substituted_blocks": [],      // 允许出现的同类别可选块替代
    "warning_contains": [],        // 必须命中的提示
    "error_contains": []           // 必须命中的错误
  },
  "solver_objective": 2210.0,      // 参考最优值
  "tight_blocks": ["..."],         // 去掉即改变最优值的块
  "nonbinding_blocks": ["..."],    // 去掉不改变最优值的块
  "scenarios": [                   // what_if 层：参数情景与各自应有的结果
    {"id": "p=2", "overrides": {"p": 2}, "expected_objective": 2400},
    {"id": "p=6", "overrides": {"p": 6}, "expected_status": "Infeasible"}
  ]
}
```

用例按 `expected` 自动分成三类，加载时校验一致性（`kind` 会出现在报告里）：

| kind | 判据 | 要求 |
|------|------|------|
| `positive` | `expected.valid` 为 true 且无 `warning_contains` | 通过判定 + 骨架干净 |
| `warning` | `expected.valid` 为 true 且有 `warning_contains` | 判定通过且命中指定提示（例如库外目标不替换、缺目标只提示） |
| `negative` | `expected.valid` 为 false | 命中指定错误 |

`warning` 与 `negative` 用例不进求解层。`tiers` 声明该用例参与哪些层；声明 `what_if` 就必须给出 `solver_objective` 与 `scenarios`，反之亦然；每个情景需要且只需要 `expected_objective` 与 `expected_status` 之一，`expected_status` 必须是求解器状态词，情景 `id` 在同一用例内唯一。`tight_blocks` 与 `nonbinding_blocks` 由 `--mode tightness --write` 计算并写回，该命令同时刷新由 IR 派生的参考脚本。

## 可执行语义（单一实现）

`references/block_model.py` 是块的**可执行语义**：输入归一化后的 IR，输出 PuLP 模型。

```python
solve_ir(ir)                  # 求解
solve_ir(ir, drop=[block_id]) # 去掉某个约束块后再求解
render_script(ir, drop=[...]) # 渲染成独立脚本（打印 Objective: <值>）
analyze_tightness(ir)         # 逐个去掉约束块，判断是否改变最优值
```

导入器（算真值）、参考脚本、紧约束分析、T2 的变体对照全部走这一份实现，因此块的语义只有一处定义。建造的模型由 `constraint_blocks` + `objective` 决定，与生成代码的写法无关。

`tests/test_benchmark.py::test_every_catalog_block_has_executable_semantics` 保证目录里的每个块都有对应实现。

## 用例集

| 来源 | 用例 | family | scale |
|------|------|--------|-------|
| 手工 | `p_median_community` 2210 | p_median | s |
| 手工 | `set_covering_emergency` 6 | set_covering | s |
| 手工 | `maximum_covering_cities` 42 | maximum_covering | s |
| 手工 | `maximum_covering_at_most_p` 42 | maximum_covering | s |
| 手工 | `p_center_emergency` 25 | p_center | s |
| 手工 | `facility_location_logistics` 174 | facility_location | s |
| 手工 | `knapsack_gadget` 220 | knapsack | s |
| 手工 | `p_median_force_open` 2240 | p_median | s |
| 手工 | `p_median_force_closed` 2290 | p_median | s |
| 手工 | `p_median_force_closed_nonbinding` 2210 | p_median | s |
| 手工 | `hybrid_p_median_custom`（库外规则，仅 ir 层） | p_median | s |
| 负例 ×8 | 漏块 / 方向冲突 / 依赖未满足 / 未知块 / 库外规则当块 / 维度不符 / p 超限 / 强制设施越界 | — | s |
| 提示类 ×3 | 库外目标不被替换 / 缺目标只提示 / 目标与声明的族不一致 | — | s |
| OR-Library | `pmed_1..pmed_5`（n=100，已发表最优） | p_median | m |
| OR-Library | `pmed_6`、`pmed_10`（n=200，仅 ir 层） | p_median | l |
| OR-Library | `uflp_cap71`、`uflp_cap101` | facility_location | m |
| OR-Library | `cflp_cap61` | capacitated_facility_location | m |
| OR-Library | `cappmed_1..3`（有容量 p-median，文件自带最优） | capacitated_p_median | m |
| 手工 | `cappmed_emergency_network`（12 需求点 × 8 设施，容量 + 强制开/关） | capacitated_p_median | m |

OR-Library 的最优值取自 `pmedopt.txt`、`uncapopt.txt`、`capopt.txt` 与 `pmedcap1.txt` 自身；导入时会用 `block_model` 独立复算并比对（n>100 的 p-median 不复算，直接采用已发表值）。

`cap41` 未收录：Beasley 的 cap 系列允许需求拆分，而库里的 `assign_each_demand_once` 是单源分配；cap41 有一个客户需求 12912、单仓容量仅 5000，单源模型下不可行。导入器现在会先检查求解状态，遇到这种情况直接报错而不是写入一个不可行的用例。

导入：

```bash
uv run python benchmarks/import_orlib.py                          # 默认子集（各 family 一个）
uv run python benchmarks/import_orlib.py --family uflp --ids 71 101
uv run python benchmarks/import_orlib.py --family cflp --ids 61
uv run python benchmarks/import_orlib.py --family cappmed --ids 1 2 3
uv run python benchmarks/import_orlib.py --family pmed --ids 1 5 6 10
```

## 五层评测

| 层 | 模式 | 走 agent | 走求解 | 确定性 | 用途 |
|----|------|---------|--------|--------|------|
| T1 判定 | `offline`（默认） | 否 | 否 | 是 | CI — 锁 IR 判定与骨架校验 |
| T2 求解 | `solver` | 否 | 是（`RunSolverTool`） | 是 | CI — 锁求解链路与紧约束对照 |
| T3 端到端 | `online` | 是 | 是 | 否 | 抽样 — 真实能力与效率 |
| T4 紧约束 | `tightness` | 否 | 是 | 是 | 刷新用例元数据 |
| T5 情景对比 | `what_if` | 否 | 是（块语义） | 是 | CI — 锁参数情景与差值方向 |

标题里的 T1–T5 与 `--mode` 的取值对应：`offline`、`solver`、`online`、`tightness`、`what_if`。

### T1 — 判定

把 `input_ir` 送入 `validate_problem_ir`，逐项断言 `expected`，并且正例还要求骨架干净（无缺失块、无不一致块、无维度问题）。新增用例的判定项：`substituted_blocks`、`skeleton_clean`、`warnings`；负例断言 `errors` 命中。

### T2 — 求解执行

把参考脚本喂给 `RunSolverTool`（真实 subprocess 路径），断言输出的目标值等于 `solver_objective`；再对 `tight_blocks` 里的每个块渲染"去掉该块"的变体脚本，断言目标值**改变**；对 `nonbinding_blocks` 断言目标值**不变**。这样"某个块在该实例上是否可被检出"成为被断言的事实，而不是假设。

### T3 — 端到端

每次尝试新建 agent 与独立工作目录，跑完后做两项检查：

| 检查 | 内容 |
|------|------|
| `claimed` | 答复里的目标值：先取 `Objective: <值>`，再取带标签的数字（目标值、最优值、总成本、总价值、最大距离…）。不带标签的孤立数字不计入 |
| `artifact` | 把它产出（或由 `solve_ir` 落盘）的求解脚本用 `RunSolverTool` 回放一遍，检查它真正算出的目标值 |

两者都通过才算一次通过。`claimed` 通过而 `artifact` 失败说明答复与产物不一致；`artifact` 通过而 `claimed` 失败属于汇报错误（模型自己编了数字）。报告给出 `claim_pass_rate`、`artifact_pass_rate` 与两者合并的 `attempt_pass_rate`。

`run_solver` 会把脚本打印的目标值以 `[RESULT] Objective: <值>` 回显在返回文本的最后一行，提示词要求最终答复引用该行。

```bash
uv run python benchmarks/run_benchmark.py --mode online --agent-mode automatic --repeats 3
uv run python benchmarks/run_benchmark.py --mode online --agent-mode interactive --turns 4
uv run python benchmarks/run_benchmark.py --mode online --budget-seconds 120 --budget-tokens 200000
```

`--repeats N` 每个用例重复 N 次，报告逐次通过率、耗时均值与样本标准差、token 均值与 time-to-success；超过 `--budget-seconds` / `--budget-tokens` 的单次尝试判定为失败（注：当前 HAMLET 版本在部分路径下 `token_usage` 为 `None`，此时 token 记为 0，token 预算不生效）。

### T4 — 紧约束分析

```bash
uv run python benchmarks/run_benchmark.py --mode tightness          # 只看结果
uv run python benchmarks/run_benchmark.py --mode tightness --write   # 写回用例与参考脚本
```

### T5 — 情景对比

```bash
uv run python benchmarks/run_benchmark.py --mode what_if
uv run python benchmarks/run_benchmark.py --mode what_if --cases p_median_community
```

每个声明了 `scenarios` 的用例：先解基准（并与 `solver_objective` 核对），再逐个应用 `overrides` 求解，断言目标值等于 `expected_objective`，或状态等于 `expected_status`（用来锁住"不可行不被跳过"）。`overrides` 走的是与 `solve_ir` 工具同一套校验（`block_model.prepare_overrides`）：键必须由该用例启用的块读取，值的长度与维度必须与实体规模一致，写错键名或写错长度都不会静默放过；单条情景或单个用例求解失败只记为不通过，不会中断整层。

目前 12 个用例共 29 个情景，覆盖：设施数量扫描（p=1/2/4/5）、越界不可行（p=6，|J|=5）、最大化方向的饱和（容量 60 起不再变化）、成本矩阵覆盖关系（改小成本但覆盖不到某需求点则不变）、强制开设（置空回到无约束最优、强制最优解本身不变、强制非最优解变差）、OR-Library 实例上的固定成本置零与容量减半（`cappmed_1/2/3`、`cflp_cap61`、`uflp_cap71/101`，其中 p=4 与容量减半锁住不可行）。

## 报告

每层都输出按 `family` 与 `scale` 分组的通过率。`--json` 给出机器可读报告（含 `groups`）。

## 外部 benchmark 调研

网上已有较多 "自然语言 → 运筹建模/求解" 的 LLM benchmark。按与本项目（NL2OR 块状 IR + location 建模 + 求解）的相关度列出：

| Benchmark | 规模/内容 | 相关度 | 获取方式 |
|-----------|-----------|--------|----------|
| **NL4OPT** | 289 个 LP 建模题（NeurIPS 竞赛） | 中 — 纯 LP 建模，无 location 结构 | GitHub `ramonamech/NL4OPT` |
| **MAMO** | EasyLP 652 + ComplexLP 211 建模题 | 中 — 数学建模，无块状 IR | GitHub `Cardinal-Operations/MAMO` |
| **IndustryOR** | 100 个工业真实问题，8 行业 | 高 — 真实场景，含设施/选址类 | HuggingFace `CardinalOperations/IndustryOR` |
| **OptiBench** | 端到端 LP/NLP 求解，含表格数据 | 中 — 需调用 solver 出数值 | ICLR 2025 |
| **BWOR** | 82 个教材 OR 题（LaTeX 文本） | 中高 — 建模+求解 | OR-LLM-Agent 发布 |
| **ORAgentBench** | 107 个端到端 agent 任务（含数据文件与提交 schema） | 高 — agentic，最接近本项目 | alphaXiv/社区仓库 |
| **CO-Bench** | 36 个组合优化问题（源自 OR-Library） | 中高 — 真实 CO 实例 | AAAI 2026 |
| **OPT-Engine** | 10 类经典 OR 问题，可控复杂度+可验证最优解 | 中高 — 程序化生成实例 | arXiv 2601.19924 |
| **FrontierOR** | 180 个大规模 OR 算法设计任务 | 低 — 侧重高效算法而非建模 | arXiv 2605.25246 |
| **OR-Library** | location 段落五个数据集：p-median、无容量仓库选址、有容量仓库选址、有容量 p-median、p-hub | 最高 — location 数据源，带已发表最优值 | Brunel 大学 |

OR-Library 的 location 段落中，p-median、UFLP、CFLP、有容量 p-median 已集成（p-hub 结构差异大，暂未纳入）。同一批 cap 文件同时支撑 UFLP 与 CFLP，差别在是否使用容量数字；两者最优值分别来自 `uncapopt.txt` 与 `capopt.txt`。
