import pytest

from deepseek_mcp.contract import TaskContract, check_contract_path
from deepseek_mcp.safety import SandboxViolation
from deepseek_mcp.tools import execute_tool


def test_write_to_allowed_src_file_is_allowed(tmp_path):
    contract = TaskContract.from_dict({"allowed_files": ["src/**/*.py"]})

    check_contract_path("src/foo.py", tmp_path, contract, "Write")


def test_default_allowed_files_include_root_files(tmp_path):
    contract = TaskContract.from_dict(None)

    check_contract_path("README.md", tmp_path, contract, "Write")


def test_write_to_outputs_is_blocked(tmp_path):
    contract = TaskContract.from_dict({"allowed_files": ["**/*"]})

    with pytest.raises(SandboxViolation, match="forbidden_files"):
        check_contract_path("outputs/result.csv", tmp_path, contract, "Write")


def test_edit_env_is_blocked(tmp_path):
    contract = TaskContract.from_dict({"allowed_files": ["**/*"]})

    with pytest.raises(SandboxViolation, match="forbidden_files"):
        check_contract_path(".env", tmp_path, contract, "Edit")


def test_read_env_is_blocked_if_forbidden(tmp_path):
    contract = TaskContract.from_dict(None)

    with pytest.raises(SandboxViolation, match="forbidden_files"):
        check_contract_path(".env", tmp_path, contract, "Read")


def test_notebook_edit_obeys_write_policy(tmp_path):
    contract = TaskContract.from_dict({"allowed_files": ["notebooks/**/*.ipynb"]})

    blocked = execute_tool(
        "NotebookEdit",
        {"path": "outputs/run.ipynb", "edit_mode": "insert", "new_source": "x = 1"},
        tmp_path,
        contract,
        ["NotebookEdit"],
    )
    allowed = execute_tool(
        "NotebookEdit",
        {"path": "notebooks/run.ipynb", "edit_mode": "insert", "new_source": "x = 1"},
        tmp_path,
        contract,
        ["NotebookEdit"],
    )

    assert "forbidden_files" in blocked
    assert allowed.startswith("OK:")
