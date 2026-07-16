import pytest

from deepseek_mcp.agent_loop import AgentLoopError, run_agent
from deepseek_mcp.config import Config
from deepseek_mcp.contract import TaskContract


def test_run_agent_refuses_zero_resolved_tools(tmp_path):
    # readonly_scan mode only exposes Read/Bash/Glob/Grep; restricting the
    # contract to Write/Edit intersects to nothing. Must fail before any API
    # call rather than silently letting DeepSeek free-text a fake result.
    config = Config(api_key="sk-test", workspace=tmp_path, allowed_tools=["Write", "Edit"])
    contract = TaskContract.from_dict({"mode": "readonly_scan"})

    with pytest.raises(AgentLoopError, match="zero available tools"):
        run_agent("do something", config, contract)
