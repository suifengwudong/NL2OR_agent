# 主循环函数调用
<!-- 
│
├──
└ 
-->

```
main.py: main()
├──parse args
├──if mode == "cli"
│   └──_run_cli()
│       ├──build_nl2or_agent()
│       │   ├──resolve model_id / workspace_dir
│       │   ├──load_system_prompt()
│       │   ├──load_tools
│       │   │   ├──model_library_tool.py: QueryModelLibraryTool(Tool)
│       │   │   │   └──forward(keywords) -> query_model_library
│       │   │   ├──solver_tool.py: RunSolverTool(Tool)
│       │   │   │   └──forward(code) -> save_code() -> subprocess.run()
│       │   │   └──// 这里一定要重载 forward() 方法
│       │   └──set_up CodeAgent
│       ├──while True: input("用户 > ")
│       ├──agent.run(user_input, reset=False)
│       │   └──hamlet.core.agents.py: MultiStepAgent.run()
│       │       ├──set task / validate_input()
│       │       ├──reset=False -> 保留 memory / state
│       │       ├──写入 system_prompt 和 TaskStep
│       │       ├──_run_stream()
│       │       │   ├──可选 planning step
│       │       │   └──ActionStep 循环
│       │       │       └──CodeAgent._step_stream()
│       │       │           ├──write_memory_to_messages()
│       │       │           ├──model.generate(...)
│       │       │           ├──parse_several_code_blobs()
│       │       │           ├──python_executor(code_action)
│       │       │           │   ├──必要时调用 query_model_library
│       │       │           │   ├──生成/执行求解代码
│       │       │           │   └──必要时调用 run_solver
│       │       │           └──返回 ActionOutput / FinalAnswerStep
│       │       └──最终返回 result / output
│       └──print(result)
└──if mode == "web"
    └──_run_web()
        ├──build_nl2or_agent()
        └──GradioUI(...).launch()
```

## _step_stream 详细调用流拆解（需要重点理解）

```
入口：MultiStepAgent.run()
    └──_run_stream()
            └──CodeAgent._step_stream(memory_step)
                    ├──[1] 准备输入上下文
                    │   ├──write_memory_to_messages()
                    │   └──memory_step.model_input_messages = input_messages
                    ├──[2] 让模型生成“代码动作”
                    │   └──model.generate(..., stop_sequences=["Observation:", "Calling tools:"])
                    ├──[3] 解析代码块
                    │   ├──parse_several_code_blobs(output_text, code_block_tags)
                    │   └──得到 code_actions + early_stop_strategy + early_stop_details
                    ├──[4] 分支判断：len(code_actions)
                    │   ├──A. 单代码块（最常见）
                    │   │   ├──yield ToolCall(name="python_interpreter", arguments=code_action)
                    │   │   ├──code_output = python_executor(code_action)
                    │   │   ├──写入 memory_step.observations / action_output
                    │   │   └──yield ActionOutput(output=code_output.output, is_final_answer=code_output.is_final_answer)
                    │   └──B. 多代码块并发
                    │       ├──逐个 yield ToolCall(name="python_interpreter", ...)
                    │       ├──ProcessPoolExecutor 并发执行全部 code_action
                    │       ├──若 early_stop_strategy != "none"
                    │       │   ├──边收集结果边评估是否提前结束（code 或 prompt）
                    │       │   └──命中提前结束后，取消其余任务并返回命中结果
                    │       └──若 early_stop_strategy == "none"
                    │           ├──收集所有执行结果
                    │           └──yield ActionOutput(output=all_code_outputs, is_final_answer=False)
                    └──[5] _run_stream 依据 ActionOutput.is_final_answer 决定是否结束本轮
```

### 关于 python_interpreter “写死”

> 关联 NOTE

注意：这里的 `python_interpreter` 更像是一个“action 标签”，而不是在 tools 列表里查找并调用同名 Tool。

```
真实执行者：self.python_executor(...)
ToolCall(name="python_interpreter", ...) 的作用：
    1) 统一记录到 memory_step.tool_calls
    2) 给日志/UI/追踪层一个可读的调用名
    3) 表示“这一段是代码解释器执行动作”，而不是某个业务 Tool（如 query_model_library / run_solver）
```

可以这样理解三层关系：

```
LLM 生成代码  ->  python_executor 执行代码  ->  代码内部再调用真正业务 Tool
                (标签名是 python_interpreter)   (例如 query_model_library, run_solver)
```

所以 `python_interpreter` 目前是框架里约定的固定命名；即使改名，多数情况下只影响可观测性（日志/追踪展示），不改变核心执行语义。
