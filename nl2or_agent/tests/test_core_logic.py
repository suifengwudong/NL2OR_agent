import pytest
import os
from pathlib import Path
from agents import build_nl2or_agent
from hamlet.core import CodeAgent

def test_agent_initialization():
    """测试 Agent 是否能成功初始化且工具加载正确。"""
    agent = build_nl2or_agent(verbosity_level=0)
    assert isinstance(agent, CodeAgent)
    assert agent.name == "NL2OR"
    
    # 检查工具是否加载
    tool_names = [tool.name for tool in agent.tools.values()]
    assert "query_model_library" in tool_names
    assert "run_solver" in tool_names

def test_authorized_imports():
    """测试沙箱是否正确允许了必要的库导入。"""
    agent = build_nl2or_agent(verbosity_level=0)
    # 尝试运行一个简单的导入代码
    code = "import numpy as np; import scipy; import gurobipy; final_answer('success')"
    # 注意：CodeAgent.run 内部会处理 Thought/Code 逻辑，我们这里模拟一次简单的调用
    # 实际上我们检查 agent 实例的参数更直接
    assert "numpy" in agent.python_executor.authorized_imports
    assert "scipy.optimize" in agent.python_executor.authorized_imports

def test_parsing_step_one():
    """测试 Step 1：解析阶段。
    由于涉及真实的 LLM 调用，这里主要验证接口连通性和初步返回的格式。
    注意：这需要环境变量中有有效的 API Key。
    """
    if not os.getenv("OPEN_ROUTER_API_KEY") and not os.getenv("OR_API_KEY"):
        pytest.skip("跳过需要 API Key 的测试")
        
    agent = build_nl2or_agent(verbosity_level=1)
    question = "我有100元，想买单价3元的橘子，最多买多少个？"
    
    # 我们期望 Agent 返回一个包含 'final_answer' 的结果，而不是陷入死循环
    result = agent.run(question)
    
    assert isinstance(result, str)
    assert len(result) > 0
    # 检查是否包含关键解析词（中文或英文）
    assert any(word in result.lower() for word in ["橘子", "orange", "3", "100"])
