# NL2OR Agent 实现约定

本文是 agent 与维护者共同遵守的绑定约定。`docs/DESIGN.md` 与 `docs/flowchart.md` 是设计参考（DESIGN.md 由 AI 生成，不保证正确）；与本文冲突时以本文为准。改动触及下列任一条约定时，同步更新本文与对应测试。

每条约定附验收方式；约定没有自动验收信号的，列人工判定点。

---

## 1. 系统提示词恒定大小：模型库不入提示词

系统提示词只由三部分组成（`core/prompt_loader.py`）：

1. `system.prompt.md`（模式无关核心）；
2. `workflow.<mode>.prompt.md`（当前模式工作流）；
3. `problem_ir_format.prompt.md`（IR 字段结构）。

| 规则 | 说明 |
|------|------|
| 模型库静态注入禁止复活 | `models.json` / `constraint_blocks.json` 的条目、块名、LaTeX 公式不得静态拼进提示词；`catalog_markdown` 一类目录渲染函数不得重新出现在提示词路径上 |
| 检索两阶段 | `search_model_library(keywords)` 给候选索引 → `describe_model(model_id)` 给单个模板的必需骨架。实现归 `core/model_library.py`，工具层只做参数适配 |
| 检索输出上限 | 有关键词：最多 8 个模型 + 10 个积木块；无关键词：返回全部模型（当前 19 个），积木块不展示 |
| 检索输出不含公式 | 候选索引与模板细节都不带 LaTeX；公式唯一来源是 `model_math` / `render_model_document` |
| 模板视图只列必需块 | `describe_model` 不列族的可选块，避免无关变体污染判断；额外约束由 agent 用 `search_model_library` 按题面关键词查找 |
| 静态附录不得枚举参数名 | `problem_ir_format.prompt.md` 是静态文件，不写积木块参数枚举（会随库演化漂移）；参数名一律来自检索工具输出 |

验收：`tests/test_agent.py::test_prompt_size_is_independent_of_the_block_catalog`（150 个合成块注入后提示词长度不变）、`test_modes_share_core_and_ir_appendix_without_the_catalog`。

背景：2026-11-12 之前，全量目录（25 块，5,896 字符）与 what_if 手册静态挂在提示词末尾，占单轮上下文约三成，并导致 agent 在纯正 UFLP 上把 `demand` 塞进 parameters、在 custom_constraints 里逐条排除上下文中看到的其他块（会话 c1e3c75f55da）。

## 2. 校验报告只承载结论

`validate_problem_ir` 返回且仅返回：`valid`、`normalized_ir`、`errors`、`warnings`、`skeleton`。

| 规则 | 说明 |
|------|------|
| 不回显目录 | 不返回 `catalog_block_ids`、`catalog_objective_ids`、`constraint_context`；块定义与公式不进对话历史 |
| 缺必需块 → 错误带候选 | `_substitute_candidates` 在报错文本中列出可替代的同类别可选块；骨架完整时不预告任何可选块 |
| 未消费数值参数 | solve_ir 路径（存在约束块且目标块在目录中）判为**错误**，错误信息列出读取该键的块；库外模型（`lp_general` 等，走 `run_solver`）保留**警告** |
| 持久化 | `write_model_of_record` 整份报告落盘，无需剥离派生键（已无派生键） |

验收：`tests/test_ir_schema.py`（报告五键、未消费参数错误/警告分路径、缺块候选）、`tests/test_utils.py::test_model_of_record_persists_the_whole_report`。

## 3. IR 内容约定

| 主题 | 约定 |
|------|------|
| 缺数据先反问 | `describe_model` 列出的必需数据在题面缺失且无法从文字推出时，先用 `final_answer` 列出具体缺失项并停止；不得编造数值、不得用占位字符串凑出一个「可校验」的模型。IR 只用用户真实给出的数据构建 |
| `custom_constraints` | 只收题面明确提出、库无法表达的额外限制；「不考虑容量」「不限定开设数量」这类说明某库块不适用的语句是建模假设，进答复的「模型假设」章节，禁止写入 IR |
| `entities.*.ids` | 按题面出现的写法抄录（中文题面用中文名，不替换成括号内外文）；无名称时用 `I1…`、`J1…` |
| `parameters` | 只放被启用块或目标块读取的键；派生数据（如每单费率 × 订单量）先算好再放入，原始输入若无人读取则删除 |
| 基准用例 | `benchmarks/**` 的 `input_ir.parameters` 同样只含块读取键；`benchmarks/import_orlib.py` 生成的 IR 与该规则同步（UFLP 变体不带 `demand` / `facility_capacity`，CFLP 保留） |

`custom_constraints` 的语义判定（题面额外限制 vs 说明某块不适用）没有自动信号，属人工判定点：review 时逐条核对 custom_constraints 是否对应题面中的一个真实限制。

## 4. 最终答复：运行时占位符填充

LLM 不抄写数学模型与结果报表；答复中的两段权威文本由运行时填充（`core/output_format.py::expand_placeholders`，`agents/runtime.py::run_turn` 调用）。

| 项 | 约定 |
|----|------|
| 占位符形状 | `[MODEL_MATH]`、`[SOLVE_RESULT]`，各自单独一行，原样书写，不带反斜杠或 LaTeX 转义；展开时把 `[MODEL_MATH\]` 这类转义变体按同一占位符处理 |
| Jinja 限制 | hamlet 的 `populate_template` 用 Jinja `StrictUndefined` 渲染系统提示词；**提示词与模板文件中禁止出现 `{{ }}` 与 `{% %}`**（`{{MODEL_MATH}}` 会让 agent 构造直接抛 `UndefinedError`）。需要占位符语义时用 `[名字]` 形状 |
| `[MODEL_MATH]` 来源 | `render_model_document(model.json 的 normalized_ir)` 现场渲染，永远对应最后一次校验通过的模型 |
| `[SOLVE_RESULT]` 来源 | 会话 `solve_result.json`（`format_solution + render_report`）；仅基准 `solve_ir` 落盘，情景变体不覆盖 |
| 指纹配对 | `solve_result.json` 带归一化 IR 的 MD5 指纹（`core/problem_ir.py::fingerprint`）；展开时与当前 `model.json` 比对，失配报「模型已变更」并要求重新求解 |
| 失败语义 | 占位符未解析（无模型 / 无产物 / 指纹失配）→ 本回合计为错误终止，不把字面量留给用户 |
| 标题合并 | 粘贴的数学文档自带 `## 数学模型` 标题；agent 若在占位符前另写该标题，相邻重复标题合并为一个 |
| 收益 | 防止 LLM 手抄改写公式、删减报表列、翻译实体名；同时免去逐字复述大段 LaTeX 的输出耗时 |

验收：`tests/test_output_format.py::TestExpandPlaceholders`（来源渲染、指纹失配、未解析报错、标题合并）、`tests/test_what_if.py::test_baseline_saves_a_solve_result_artifact` 与 `test_scenario_solves_do_not_overwrite_the_artifact`。

## 5. 数学文档渲染

| 规则 | 说明 |
|------|------|
| 符号说明自洽 | `_render_parameters` 的候选集限制为 `readable_keys(ir)`：符号说明中出现的每个参数都必须出现在某条公式里（悬空符号如 `d_i` 在渲染层不可能出现） |
| 实体名排版 | 非 `[A-Za-z0-9_-]+` 的实体名（中文、带空格）包 `\text{}`，避免数学模式拆分或渲染失败 |
| 数域写进约束 | 决策变量的取值域作为 s.t. 的尾部显式列出（`**变量取值范围**`，位于结构约束与库外规则之后）：0-1 变量写 `x_{ij} \in \{0,1\}, \quad \forall i \in I,\ j \in J`，连续变量写 `w \ge 0`。数域不能只写在符号说明的变量定义里；量词由符号下标推出（`x_ij` → `i \in I, j \in J`） |

验收：`tests/test_model_document.py`（含 `test_all_valid_documents_hide_catalog_ids`：文档不得泄漏目录 id）。

## 6. 对 minds-hamlet 的补丁

对 `minds-hamlet` 的所有补丁集中在 `agents/nl2or_agent.py`，带上游位置注释；`.venv` 里的文件不改（重装即失效）。

| 补丁 | 上游问题 | 位置 |
|------|----------|------|
| `_patch_hamlet_code_parsing` | `parse_several_code_blobs` 只接受「单块」或「多块 + Early Stop」两种形状；模型常见退化：每个工具调用各写一块、单块后跟空的 Early Stop、DeepSeek 原生 `<｜DSML｜ invoke>` 标记、裸 `final_answer(...)` 无围栏。补丁在原始解析失败后依次：解包 DSML 的 code 参数、裁掉 Early Stop 段、按顺序合并多块、最后把裸代码当单个动作 | `hamlet/core/utils.py::parse_several_code_blobs` |
| `_silence_system_prompt_print` | `CodeAgent.initialize_system_prompt()` 末尾硬编码 `print(system_prompt)`（`hamlet/core/agents.py:1486`）；`__init__` 与每次 `run()` 都求值 `self.system_prompt`，整份提示词每回合打印两次，`verbosity_level=0` 不起作用 | `hamlet/core/agents.py:1486` |

解析修复只处理输出形状，不改写代码内容与语义：纯文本答复（没有 ```python 块）不猜测包裹，交给提示词要求「每条消息必须是一个 python 块、答复放在 final_answer 内」；Python 里的 LaTeX 转义（`\]`、`\{`）仍按语法错误交给执行器反馈。占位符的 `[MODEL_MATH\]` 变体在展开时按同一占位符处理。验收：`tests/test_agent.py` 的解析用例（裸代码、正常围栏、多块合并、空 Early Stop、DSML 解包、原生 Early Stop 不受影响、纯文本答复被拒收）。

补丁用 `contextlib.redirect_stdout` 只包住提示词构建，求解输出与日志不受影响。验收：`tests/test_agent.py::test_build_and_prompt_evaluation_are_silent`（capsys）。

## 7. Agent 构造与环境

| 主题 | 约定 |
|------|------|
| 工厂签名 | `agent_factory: Callable[[mode], Any]`；`get_agent: Callable[[sid, mode], Any]`。web 首次构造使用 UI 当前选中的模式（`web/app.py::_get_or_create_agent(sid, mode, factory)`），消除「以 interactive 构造、实际以 automatic 运行」的错配与二次提示词求值 |
| 模式缓存 | `apply_agent_mode` 依赖构造时写入的 `agent._nl2or_mode`：同模式回合跳过重载，异模式才替换模板 |
| 启动横幅 | `build_nl2or_agent` 的 `print("Using model: ...")` 仅 `verbosity_level >= 1` 输出 |
| LiteLLM 价格表 | `os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "true")` 必须写在项目内**第一次导入 hamlet/litellm 之前**（`agents/nl2or_agent.py` 模块顶部）；litellm 在 import 时读取该变量，`true` 时直接读本地备份，不发 HTTPS 请求。价格表对当前模型 id 本来无用途 |

验收：`tests/test_agent.py::test_startup_banner_follows_verbosity`、`tests/test_main.py::test_first_agent_build_uses_the_selected_mode`、`tests/test_runtime.py::test_factory_receives_the_turn_mode`；人工判定点：CLI 启动输出无提示词、无 `Failed to fetch remote model cost map` 告警。

## 8. 测试面与文档同步

改上述任一约定时同步改动的测试与文档：

- `tests/test_agent.py`（提示词内容与静音）、`tests/test_ir_schema.py`（报告契约）、`tests/test_what_if.py`（solve_ir 产物）、`tests/test_output_format.py`（占位符）、`tests/test_model_library.py`（检索契约）、`tests/test_ir_catalog.py`（无目录渲染函数）；
- `nl2or_agent/README.md`（目录树、结构图、更新记录）、`issues/README.md`（归档）、本文；
- `docs/flowchart.md` 的 HAMLET 实现映射段。
