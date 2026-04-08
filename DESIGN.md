## 一、整体架构分层（MVC 扩展）

| 层次 | 对应模块 | 职责 |
|------|----------|------|
| **表示层 (View)** | CLI / Web API / 消息接口 | 接收用户自然语言输入，展示输出结果（含追问、矫正信息、最终解） |
| **控制层 (Controller)** | 交互核心 (InteractCore) | 编排对话流程：调用 LLM 解析、管理状态、决策何时查询模型库、何时调用求解器 |
| **服务层 (Service)** | LLM 服务、模型库服务、求解器服务、代码生成服务、知识库服务 | 提供领域能力：LLM 调用、模型检索/矫正、求解器适配、代码生成、范例检索 |
| **数据层 (Data)** | 模型库、本地存储、知识库 | 持久化存储：预定义模型、用户会话、历史记录、范例/知识片段 |

> **MVC 映射**：  
> - View = 用户界面（CLI/API）  
> - Controller = 交互核心  
> - Model = 服务层 + 数据层（领域模型与数据访问）

---

## 二、目录结构（Python 项目示例）

```
nl2or_agent/
├── app.py                     # 应用入口（CLI 或 FastAPI 启动）
├── config.py                  # 配置（LLM API key，求解器路径等）
├── requirements.txt
│
├── controller/                # 控制层
│   ├── __init__.py
│   └── interact_core.py       # 交互核心：状态机、对话管理、决策逻辑
│
├── service/                   # 服务层（领域能力）
│   ├── llm_service.py         # 封装 LLM 调用：自然语言解析、中间表示生成、模型矫正
│   ├── model_library_service.py  # 模型库接口：检索、添加、更新模型
│   ├── solver_service.py      # 求解器接口：统一调用 ortools/gurobi 等
│   ├── code_gen_service.py    # 代码生成工具：将模型转成 Python/MPS 等格式
│   └── knowledge_service.py   # 知识库服务（TODO）：检索范例 / 具体化示例
│
├── data/                      # 数据层
│   ├── model_library/         # 模型库存储（JSON / 数据库）
│   │   ├── lp_models.json
│   │   └── milp_models.json
│   ├── local_storage/         # 本地存储（会话、历史）
│   │   └── sessions.db        # sqlite 或文件
│   └── knowledge_base/        # 知识库（范例、流程说明）
│       └── examples.yaml
│
├── domain/                    # 领域模型（数据结构定义）
│   ├── __init__.py
│   ├── conversation.py        # 对话状态、消息记录
│   ├── or_model.py            # 中间表示（变量、目标、约束）
│   └── solution.py            # 求解结果
│
├── adapter/                   # 外部接口适配器
│   ├── solver_adapter/        # 具体求解器适配
│   │   ├── base.py
│   │   ├── ortools_adapter.py
│   │   └── gurobi_adapter.py
│   └── llm_adapter/           # LLM 适配（OpenAI, Claude, 本地模型）
│       ├── base.py
│       └── openai_adapter.py
│
├── utils/                     # 辅助工具
│   ├── logger.py
│   └── validator.py           # 模型合法性校验
│
└── tests/                     # 单元测试
```

---

## 三、核心模块职责详解

### 1. 交互核心（`interact_core.py`）
- **状态机管理**：对话阶段（`parsing` → `confirming` → `model_fixing` → `solving` → `done`）
- **编排服务**：根据当前状态调用 `LLMService`、`ModelLibraryService`、`SolverService`
- **对话上下文**：存储用户历史输入、LLM 返回的中间表示、矫正后的模型
- **决策逻辑**（对应序列图的 alt 分支）：
  - 若模型类型明确 → 查询模型库
  - 若模型信息缺失/不准确 → 调用 LLM 矫正
  - 若用户确认求解 → 调用求解器

### 2. LLM 服务（`llm_service.py`）
- `parse_natural_language(user_input: str) -> IntermediateRepresentation`  
  将自然语言转为结构化中间表示（JSON schema 定义变量、目标、约束）
- `correct_model(model_ir: dict, user_feedback: str) -> IntermediateRepresentation`  
  根据用户反馈矫正模型
- `generate_explanation(model_ir: dict) -> str`  
  生成解释性自然语言（供用户确认）

### 3. 模型库服务（`model_library_service.py`）
- `search_model(keywords: str, model_type: str) -> ModelTemplate`  
  从模型库中匹配预定义模板
- `save_model(model_ir: dict, name: str)`  
  将用户确认后的新模型存入模型库（扩展）
- `get_model_info(model_id: str) -> dict`  
  获取模型元数据（变量数、约束类型等）

### 4. 求解器服务（`solver_service.py`）
- 统一接口 `solve(model_ir: dict, solver_name: str = "ortools") -> Solution`
- 内部通过适配器模式调用具体求解器，返回标准解结构（目标值、变量值、状态）

### 5. 代码生成服务（`code_gen_service.py`）
- `generate_code(model_ir: dict, language="python") -> str`  
  生成可执行脚本（如 ortools 或 pulp 代码），便于用户离线使用

### 6. 知识库服务（`knowledge_service.py`）
- `retrieve_examples(problem_description: str) -> List[Example]`  
  根据用户问题检索相似范例（具体化流程），用于 Few-shot 提示 LLM 或指导模型矫正

---

## 四、交互流程（对应活动图实现）

1. **用户输入** → `InteractCore` 接收
2. **解析阶段**：调用 `LLMService.parse` → 得到中间表示 `ir`
3. **确认阶段**：`InteractCore` 将 `ir` 转为自然语言追问用户确认
4. **模型矫正分支**：
   - 若用户确认模型类型 → 调用 `ModelLibraryService.search_model` 获取模板，填充参数
   - 若用户指出错误 → 调用 `LLMService.correct_model`，生成新 `ir`，再次确认
5. **求解阶段**：用户确认后 → 调用 `SolverService.solve` → 返回结果
6. **输出**：展示解 + 可选生成代码（调用 `CodeGenService`）

---

## 五、技术选型建议

| 组件 | 推荐技术 | 说明 |
|------|----------|------|
| 后端框架 | FastAPI / Flask | 提供 REST API，便于集成 Web 前端 |
| LLM 集成 | OpenAI API / 本地 vLLM | 支持函数调用（function calling）可增强结构化输出 |
| 求解器 | OR-Tools, PuLP, Gurobi | 优先 OR-Tools（开源、支持多种问题类型） |
| 模型库存储 | SQLite + JSON | 简单场景用 JSON，复杂场景用 SQLite |
| 代码生成 | Jinja2 模板 | 基于模板生成 Python 求解代码 |
| 对话状态 | 内存字典 + Redis（可选） | 维护会话状态，支持多轮 |

---

## 六、扩展性说明

- **新增求解器**：只需实现 `adapter/solver_adapter/base.py` 接口，并在配置中注册。
- **新增 LLM 提供商**：实现 `adapter/llm_adapter/base.py`。
- **知识库增强**：可接入向量数据库（Chroma）实现语义检索范例。
- **MVC 分离**：控制层不依赖具体服务实现，通过依赖注入（如使用 `abc` 抽象类）降低耦合。

这个架构能够完整覆盖你提供的流程图与活动图，并且遵循了 TODO 中提到的“知识库、流程范例、MVC 架构”要求。你可以基于此架构逐步实现运筹学智能体。