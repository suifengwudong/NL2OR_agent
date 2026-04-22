# NL2OR Agent

> 将自然语言运筹学问题转化为数学模型并自动求解的智能体，基于 [HAMLET](https://github.com/MINDS-THU/HAMLET) 框架构建，使用 [uv](https://github.com/astral-sh/uv) 管理依赖。

---

## 快速开始

### 1. 安装依赖

```bash
# 安装 uv（若尚未安装）
pip install uv

# 在 nl2or_agent 目录下初始化环境并安装依赖
cd nl2or_agent
uv sync
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入你的 LLM API Key
```

`.env` 示例：

```dotenv
HAMLET_MODEL_ID=deepseek/deepseek-chat   # 或 openai/gpt-4o
DEEPSEEK_API_KEY=sk-xxx
NL2OR_WORKSPACE_DIR=./data/workspace
```

### 3. 运行

**命令行模式（默认）**

```bash
uv run python main.py
# 或
uv run python main.py --mode cli
```

**Gradio Web 界面**

```bash
uv run python main.py --mode web
```

---

## 项目结构

```
nl2or_agent/
├── pyproject.toml          # uv 项目配置，依赖声明
├── .python-version         # Python 版本锁定（3.11）
├── .env.example            # 环境变量模板（复制为 .env 后填写）
├── main.py                 # 入口：--mode cli（默认）/ --mode web
│
├── agents/
│   ├── __init__.py
│   └── nl2or_agent.py      # build_nl2or_agent() — 组装 CodeAgent
│
├── tools/
│   ├── __init__.py
│   ├── model_library_tool.py   # QueryModelLibraryTool — 查询 OR 模型模板库
│   └── solver_tool.py          # RunSolverTool — 执行生成的求解代码
│
├── data/
│   ├── model_bank/
│   │   └── models.json     # OR 模型模板库（LP、ILP、运输、指派、背包、选址）
│   └── workspace/          # 生成的求解脚本存储目录
│
└── prompts/
    └── system_prompt.md    # Agent 系统提示词
```

---

## 架构说明

### HAMLET 核心组件映射

| 流程图模块 | HAMLET 组件 | 本项目实现 |
|-----------|-------------|-----------|
| 交互核心 | `CodeAgent` | `agents/nl2or_agent.py` 中的 `build_nl2or_agent()` |
| LLM | `LiteLLMModel` | 通过 `HAMLET_MODEL_ID` 环境变量切换提供商 |
| 模型库接口 | `Tool` 子类 | `tools/model_library_tool.py` — `QueryModelLibraryTool` |
| 求解器接口 | `Tool` 子类 | `tools/solver_tool.py` — `RunSolverTool` |
| 代码生成器 | `CodeAgent` 内置 | CodeAgent 自带 Python 代码生成与执行能力 |
| 本地存储 | 文件系统 | `data/workspace/` 目录，求解脚本按 UUID 命名存储 |
| 用户界面 | `GradioUI` | `main.py --mode web` 启动 Gradio 界面 |

### Agent 工作流（对应 docs/flowchart.md 活动图）

```
用户输入自然语言问题
        │
        ▼
  PARSING（CodeAgent 调用 LLM）
   ├─ 提取：问题类型 / 决策变量 / 目标函数 / 约束 / 参数
   └─ 追问用户确认
        │
        ▼
  CONFIRMING（用户确认或修改）
   ├─ 确认 ──► 进入 MODEL LOOKUP
   └─ 修改 ──► 返回 PARSING
        │
        ▼
  MODEL LOOKUP（QueryModelLibraryTool）
   └─ 从 data/model_bank/models.json 检索匹配模板
        │
        ▼
  CODE GENERATION（CodeAgent 生成 gurobipy 脚本）
        │
        ▼
  SOLVING（RunSolverTool 执行代码，返回求解结果）
        │
        ▼
  返回自然语言解释结果给用户
```

### 自定义 Tool 开发指南

在 `hamlet.core.tools.Tool` 基础上继承即可：

```python
from hamlet.core.tools import Tool

class MyTool(Tool):
    name = "my_tool"
    description = "工具的功能描述（LLM 依此决定何时调用）"
    inputs = {
        "param_name": {
            "type": "string",
            "description": "参数说明",
        }
    }
    output_type = "string"

    def forward(self, param_name: str) -> str:
        # 实现工具逻辑
        return "结果"
```

然后在 `build_nl2or_agent()` 的 `tools` 列表中添加即可。

---

## 扩展指南

### 切换 LLM 提供商

修改 `.env` 中的 `HAMLET_MODEL_ID`，支持的格式遵循 [litellm](https://docs.litellm.ai/docs/providers) 规范：

| 提供商 | 示例 MODEL_ID |
|--------|--------------|
| OpenAI | `openai/gpt-4o` |
| DeepSeek | `deepseek/deepseek-chat` |
| 通义千问 | `openai/qwen-plus`（需配置 `OPENAI_BASE_URL`）|
| 本地 Ollama | `ollama/llama3.2` |

### 添加新的 OR 模型模板

编辑 `data/model_bank/models.json`，按现有格式添加新条目。字段说明：

- `id`: 唯一标识符
- `keywords`: 检索关键词列表（中英文均可）
- `template_code`: 可直接适配的 gurobipy 代码骨架

### 使用 Gradio GUI

```bash
uv run python main.py --mode web
```

GUI 支持：聊天交互、工具调用追踪、文件上传（供 Agent 读取数据文件）。

---

## 一、计划 TODOS

- [ ] **主循环模块撰写**：进行试验性质 User - 交互核心 - LLM 模块初步开发，验证核心流程的可行性与效果；
- [ ] **前端开发**：设计并实现一个简洁的用户界面，内容包括：
  - [ ] 聊天界面：支持用户输入自然语言问题，并展示模型生成的回答；
  - [ ] 模型输出展示：清晰展示生成的运筹学模型对照；
  - [ ] 可能的代码展示：演算代码展示，一是为了提供方便修改的接口，二是为了让用户更好地理解模型构建过程；

> 结构实现可以参考 `../docs/DESIGN.md` 中的设计方案（由于由大模型生成，不保证对），具体细节可根据实际开发进度进行调整与优化。
>

## 二、主循环简易开发文档

> 说明：AI 生成，仅供参考

### 1. 核心目标
实现 `用户 ↔ NL2OR 系统 ↔ LLM` 的对话闭环，完成自然语言问题到中间表示（IR）的解析、确认与修正。

### 2. 主循环状态机（精炼）

- **PARSING**：接收用户输入 → 调用 LLM 生成 IR → 校验 → 追问确认 → 转 **CONFIRMING**
- **CONFIRMING**：用户回复  
  - “确认” → 结束循环（后续转求解）  
  - “修改” → 调用 LLM 矫正 IR → 重新追问 → 保持 **CONFIRMING**

### 3. 技术栈（仅主循环）

| 组件 | 技术 | 说明 |
|------|------|------|
| 交互入口 | CLI (`argparse`+`input`) / FastAPI | CLI 调试，Web 供普通用户 |
| 统一 LLM 接口 | `litellm` | 通过环境变量切换模型（DeepSeek/OpenAI/通义等） |
| IR 校验 | Pydantic | 强制 schema，自动类型转换 |
| 会话状态 | 内存字典 + 可选 SQLite | 存储状态、IR、对话历史 |
| 配置 | `python-dotenv` | `LLM_MODEL`, `API_KEY` 等 |
| 日志 | `structlog`（可选） | 记录 token 数、延迟 |

### 4. 持久化方案（会话级数据存储）

> 将用户上传的数据文件、对话历史、中间表示、生成代码等统一按会话存储。

**目录结构**（轻量方案）：
```
workspace/session_{id}/
├── chat_history.json   # 对话记录、IR、确认状态
├── data/               # 用户上传的 Excel/CSV
├── generated/          # 生成的求解代码
└── outputs/            # 求解结果（可选）
```

**关键操作**：
- 用户上传文件 → 存入 `data/`，系统自动生成摘要（列名、前几行）并记录到 `chat_history.json`
- LLM 生成代码时直接引用文件路径（如 `pd.read_excel("data/input.xlsx")`）
- 会话可整体导出/导入

**扩展建议**：后续可升级为 SQLite + 对象存储（MinIO），但初期文件系统足够。

### 5. 核心数据流（图文简洁版）

```
用户输入 → 系统(PARSING) → litellm(LLM) → IR(JSON) → Pydantic校验 
→ 追问 → 用户确认 → 进入 CONFIRMING
   ├─ 确认 → 结束主循环（输出最终 IR）
   └─ 修改 → litellm 矫正 → 重新追问
```

- 所有中间数据（IR、历史、文件摘要）实时写入 `workspace/session_{id}/chat_history.json`
- 主循环不涉及求解器，只负责生成经过用户确认的 IR。

### 6. 开发顺序（最小可行）

1. **CLI 版状态机**：内存存储，无持久化，调试 LLM 解析与确认流程。
2. **加入持久化**：按会话 ID 读写 JSON 文件，支持断点恢复。
3. **加入文件上传**（Web 模式）：接收 Excel/CSV，存入 `data/`，生成摘要。
4. **Web 封装**：FastAPI 提供 `/chat` 和 `/upload` 端点。

### 7. 注意事项

- **LLM 输出要求**：通过 system prompt 强制输出合法 JSON，若校验失败则自动重试。
- **文件安全**：限制上传大小（如 10MB），对 Excel 用 `pandas` 读取前 5 行做摘要，不全文塞入 LLM。
- **会话清理**：定期删除超过 7 天未活动的会话目录（可配置）。

---