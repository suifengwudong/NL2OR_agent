# 运筹学“智能体”

## 一、探索与需求分析

### 1.1 计划的 Milestone

- [ ] 完成核心流程验证，实现初步**Demo 原型**；
- [ ] 开发面向运筹学入门学生的**教学版本**，支持学习理解、课堂教学与成果演示；
- [ ] 迭代开发面向行业应用的**工程版本**，支持实际场景下的选址决策与模型构建。

> 说明：本次SRT项目周期内，目标为完成前两个Milestone；第三个面向行业落地的Milestone，作为项目后续延伸与迭代方向，暂不纳入本阶段实施范围。

### 1.2 需求分析

核心定位：**端到端教学型NL2OR选址智能体**
- 输入：自然语言问题描述 + 结构化数据集
- 处理流程：全自动运筹模型生成 → 外部求解器调用与求解 → 结果解析
- 输出：**双模式解释结果**
  1. 自然语言解释（人话）：面向入门学习者，清晰说明选址方案、优化逻辑与结果意义；
  2. 专业技术表述（鬼话）：给出标准运筹学数学模型、公式定义、建模逻辑与求解过程信息。

一、系统输入规范（遵循运筹学问题工程化范式）
1. 自然语言：用于描述**建模语义**，包括模型类型（P-median/P-center）、设施数量P、优化目标、约束条件等问题意图；
2. 结构化数据集文件（如CSV格式）：用于承载需求点、候选设施点、需求量等**大规模数值数据**。

端到端约束：自然语言与数据集为必要输入组合，系统基于二者完成完整的自动化建模与求解。

二、数据质量与鲁棒性需求
1. 系统具备数据集合法性与完整性校验能力，可识别缺失值、异常坐标、非法参数、重复节点等典型数据问题；
2. 受限于项目范围与开发资源，**不实现全自动数据清洗功能**，但需以自然语言形式向学习者反馈数据异常原因与修正建议，辅助教学与问题排查。
3. 数据校验模块定位为**增强性功能**，在项目开发中优先级低于核心端到端流程，可根据进度灵活安排实现。

### 其他

> 模型库写得太死板了，不好组装；
>
> constraint 模块和 objective 模块的设计过于细粒度，导致模型定义过于冗长，难以维护；
> templates?
> 识别目标函数和约束 -> templates 爬取 -> 生成  ------ pipeline

```json
{
  "id": "p_median",
  "family": "location_problem",
  "name": "P-Median 选址",
  "description": "正好开设 p 个设施，最小化所有需求点到其服务设施的总需求加权距离。",
  "blocks": [
    "cardinality_open_p_facilities"
  ],
  "objective_block": "weighted_service_distance_objective",
  "variables": [
    {
      "symbol": "y_j",
      "type": "binary",
      "meaning": "若在候选点 j 开设设施则为 1，否则为 0"
    },
    {
      "symbol": "x_ij",
      "type": "binary",
      "meaning": "若需求点 i 由候选设施 j 服务则为 1，否则为 0"
    }
  ],
  "objective": "minimize sum_{i in I} sum_{j in J} h_i * d_ij * x_ij",
  "constraints": [
    "sum_{j in J} x_ij = 1, for all i in I",
    "sum_{j in J} y_j = p",
    "x_ij <= y_j, for all i in I, j in J",
    "x_ij in {0,1}, for all i in I, j in J",
    "y_j in {0,1}, for all j in J"
  ],
  "parameters": [
    {
      "name": "p",
      "type": "integer",
      "required": true,
      "description": "需要开设的设施数量"
    },
    {
      "name": "distance",
      "type": "dict",
      "required": true,
      "description": "d_ij，需求点 i 到候选设施 j 的距离或服务成本"
    },
    {
      "name": "demand",
      "type": "dict",
      "required": false,
      "description": "h_i，需求点 i 的需求权重；若未给出可默认为 1"
    },
    {
      "name": "weight",
      "type": "dict",
      "required": false,
      "description": "兼容旧字段：需求权重，可与 demand 等价"
    }
  ],
  "solver_hint": "0-1 integer programming; use Gurobi binary variables y[j], x[i,j].",
  "keywords": [
    "P-Median",
    "p-median",
    "p median",
    "p中位",
    "p中位数",
    "中位选址",
    "加权距离",
    "总距离最小",
    "average distance",
    "minimize total demand-weighted distance"
  ]
},
```