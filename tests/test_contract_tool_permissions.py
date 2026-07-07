from deepseek_mcp.contract import TaskContract, effective_allowed_tools
from deepseek_mcp.tools import execute_tool


def test_readonly_scan_blocks_write_edit_notebookedit(tmp_path):
    contract = TaskContract.from_dict({"mode": "readonly_scan"})
    allowed = effective_allowed_tools(
        ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "NotebookEdit"],
        contract,
    )

    assert "Read" in allowed
    assert "Write" not in allowed
    assert "Edit" not in allowed
    assert "NotebookEdit" not in allowed
    result = execute_tool("Write", {"path": "x.txt", "content": "x"}, tmp_path, contract, allowed)
    assert "not allowed by this task contract" in result


def test_implement_allows_write_when_path_allowed(tmp_path):
    contract = TaskContract.from_dict({"mode": "implement", "allowed_files": ["src/**/*.py"]})
    allowed = effective_allowed_tools(["Read", "Write"], contract)

    result = execute_tool("Write", {"path": "src/foo.py", "content": "x = 1\n"}, tmp_path, contract, allowed)

    assert result.startswith("OK:")
    assert (tmp_path / "src/foo.py").read_text() == "x = 1\n"


def test_contract_tools_cannot_exceed_global_config_tools():
    contract = TaskContract.from_dict(
        {"mode": "implement", "allowed_tools": ["Read", "Write", "Bash"]}
    )

    assert effective_allowed_tools(["Read"], contract) == ["Read"]
