# NL2OR Benchmark

评估 NL2OR Agent 的转化与求解能力。

## 用例集

内置 `cases.json` 包含 6 个覆盖不同问题族的用例（与 `data/model_bank` 对齐）：

| id | 问题族 | 参考最优目标 |
|----|--------|--------------|
| `p_median_community` | P-Median 选址 | 2210 |
| `set_covering_emergency` | 集合覆盖选址 | 6 |
| `maximum_covering_cities` | 最大覆盖选址 | 42 |
| `p_center_emergency` | P-Center 选址 | 25 |
| `facility_location_logistics` | 无容量设施选址 | 174 |
| `knapsack_gadget` | 背包问题 | 220 |

每个用例包含：
- `problem` — 自然语言问题描述（用于 online 端到端）
- `input_ir` — "脏" IR（模拟 LLM 原始输出：别名、非规范 id、`facility_ids` 等）
- `expected` — 归一化后应得的 families / block_ids / objective_block
- `solver_objective` — 参考最优目标值（由 `references/solve_references.py` 计算）

## 真实数据：OR-Library location 实例

`orlib_cases/` 下是由 `import_orlib.py` 从 [OR-Library](https://people.brunel.ac.uk/~mastjjb/jeb/orlib/pmedinfo.html)
（Beasley, 1990）导入的 **真实 p-median 实例**，最优值已用 PuLP/CBC 验证：

| id | n | p | 最优目标 |
|----|---|----|----------|
| `pmed_1` | 100 | 5 | 5819 |
| `pmed_2` | 100 | 10 | 4093 |
| `pmed_3` | 100 | 10 | 4250 |
| `pmed_4` | 100 | 20 | 3034 |
| `pmed_5` | 100 | 33 | 1355 |

```bash
uv run python benchmarks/import_orlib.py             # 默认 pmed1..pmed5（n=100，~1s/个）
uv run python benchmarks/import_orlib.py --ids 6 7 10  # n=200+，CBC 需数分钟
uv run python benchmarks/import_orlib.py --all          # pmed1..pmed40
```

导入的用例自动被 `run_benchmark.py` 加载（与 `cases.json` 合并评测）。

## 三层评测

| 层 | 模式 | 走 agent | 走求解 | 确定性 | 用途 |
|----|------|---------|--------|--------|------|
| **T1 IR** | `offline`（默认） | ❌ | ❌ | ✅ | CI — 锁 IR 归一化 |
| **T2 求解执行** | `solver` | ❌ | ✅ `RunSolverTool` | ✅ | CI — 锁求解链路 |
| **T3 端到端** | `online` | ✅ | ✅ | ❌ | 手动/夜间 — 真实能力 |

### T1 — Offline（IR 归一化，无 LLM，确定性）

把每个用例的脏 IR 送入 `validate_problem_ir`，检查归一化结果是否命中期望的
问题族、约束块集合和目标块。适合 CI / 快速回归。

```bash
uv run python benchmarks/run_benchmark.py                  # 默认 offline
uv run python benchmarks/run_benchmark.py --cases p_median_community,knapsack_gadget
uv run python benchmarks/run_benchmark.py --json            # 机器可读报告
```

### T2 — Solver（求解执行链路，无 LLM，确定性）

把每个用例的参考脚本（`references/solvers/<case_id>.py`）喂给 agent 的
**`RunSolverTool`**（即真实 subprocess 执行路径），断言其输出的目标值与
已知最优一致。这锁定了 `run_solver → subprocess → 正确目标值` 这条链路，
不依赖 LLM。

```bash
uv run python benchmarks/run_benchmark.py --mode solver
```

### T3 — Online（端到端，需 LLM）

用真实 agent 跑自然语言问题（多轮：解析 → 确认 → 查库 → 求解），从最终
回答中鲁棒提取目标值与参考最优比对。

```bash
# 需要 .env 配置 OPENROUTER_API_KEY 和 HAMLET_MODEL_ID
uv run python benchmarks/run_benchmark.py --mode online
uv run python benchmarks/run_benchmark.py --mode online --cases p_median_community
```

注意：online 模式调用真实 LLM，慢、有成本、非确定性，仅作抽样验证。

**已验证结果**（`openrouter/deepseek/deepseek-chat`）：

| 用例 | 结果 | agent 产出的目标值 |
|------|------|-------------------|
| `knapsack_gadget` | ✅ PASS | 220（真实调用 CBC 求解） |
| `p_median_community` | ✅ PASS | 2210 |
| `set_covering_emergency` | ✅ PASS | 6 |

## 参考求解脚本（唯一数据源）

`references/solvers/<case_id>.py` 是每个用例的独立求解脚本，打印 `Objective: <值>`。
它们同时用于：
- 计算 ground truth（`solve_references.py`）——**独立于被测系统**，保证标准答案可信
- T2 求解层的输入（喂给 `RunSolverTool`）

```bash
# 运行所有参考脚本，打印各用例最优值
uv run python benchmarks/references/solve_references.py
```

若修改了用例数据，需同步更新对应脚本与 `cases.json` 中的 `solver_objective`。

## 外部 benchmark 调研

网上已有较多 "自然语言 → 运筹建模/求解" 的 LLM benchmark。按与本项目
（NL2OR 块状 IR + location 建模 + 求解）的相关度列出：

| Benchmark | 规模/内容 | 相关度 | 获取方式 |
|-----------|-----------|--------|----------|
| **NL4OPT** | 289 个 LP 建模题（NeurIPS 竞赛） | 中 — 纯 LP 建模，无 location 结构 | GitHub `ramonamech/NL4OPT` |
| **MAMO** | EasyLP 652 + ComplexLP 211 建模题 | 中 — 数学建模，无块状 IR | GitHub `Cardinal-Operations/MAMO` |
| **IndustryOR** | 100 个工业真实问题，8 行业 | 高 — 真实场景，含设施/选址类 | HuggingFace `CardinalOperations/IndustryOR` (json) |
| **OptiBench** | 端到端 LP/NLP 求解，含表格数据 | 中 — 需调用 solver 出数值 | ICLR 2025 |
| **BWOR** | 82 个教材 OR 题（LaTeX 文本） | 中高 — 建模+求解 | OR-LLM-Agent 发布 |
| **ORAgentBench** | 107 个端到端 agent 任务（含数据文件+提交 schema） | **高** — agentic，最接近本项目 | alphaXiv/社区仓库 |
| **CO-Bench** | 36 个组合优化问题（源自 OR-Library） | 中高 — 真实 CO 实例 | AAAI 2026 |
| **OPT-Engine** | 10 类经典 OR 问题，可控复杂度+可验证最优解 | 中高 — 程序化生成实例 | arXiv 2601.19924 |
| **FrontierOR** | 180 个大规模 OR 算法设计任务 | 低 — 侧重高效算法而非建模 | arXiv 2605.25246 |
| **OR-Library** | p-median / p-center / UFLP 等真实 location 实例，含已发表最优值 | **最高** — location 数据源 | Brunel 大学 |

其中 **OR-Library** 已集成（见上文），为 location 相关用例提供了大量带已发表
最优值的真实数据（p-median 40 组、p-center、无容量/容量仓库选址等），可直接
扩展 `import_orlib.py` 覆盖。

未来若需与社区对齐可比性，可考虑接入 **NL4OPT / MAMO / IndustryOR** 评估
建模准确性；但它们的 schema 是"文本→数学规划"，与本项目的块状 IR 不同，
需要额外的 IR 对齐层才能直接复用。