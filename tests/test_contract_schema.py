import pytest

from deepseek_mcp.contract import DEFAULT_FORBIDDEN_FILES, TaskContract


def test_missing_contract_is_allowed_with_defaults():
    contract = TaskContract.from_dict(None)

    assert contract.mode == "implement"
    assert ".env" in contract.forbidden_files
    assert contract.allowed_files == ["**/*"]


def test_unknown_mode_fails_clearly():
    with pytest.raises(ValueError, match="unknown contract.mode"):
        TaskContract.from_dict({"mode": "planner"})


def test_invalid_allowed_files_type_fails_clearly():
    with pytest.raises(ValueError, match="contract.allowed_files"):
        TaskContract.from_dict({"allowed_files": "src/**/*.py"})


def test_forbidden_files_defaults_are_applied():
    contract = TaskContract.from_dict({"mode": "readonly_scan"})

    assert contract.forbidden_files == DEFAULT_FORBIDDEN_FILES
