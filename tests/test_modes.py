from deepseek_mcp.contract import MODE_ALLOWED_TOOLS, TaskContract, effective_allowed_tools


def test_all_required_modes_exist():
    assert set(MODE_ALLOWED_TOOLS) == {
        "implement",
        "readonly_scan",
        "test_writer",
        "logging_diagnostics",
        "config_plumbing",
        "docs",
    }


def test_docs_mode_does_not_expose_notebookedit_by_default():
    contract = TaskContract.from_dict({"mode": "docs"})

    assert "NotebookEdit" not in effective_allowed_tools(
        ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "NotebookEdit"],
        contract,
    )


def test_contract_allowed_tools_intersects_mode_tools():
    contract = TaskContract.from_dict(
        {"mode": "readonly_scan", "allowed_tools": ["Read", "Write", "Grep"]}
    )

    assert effective_allowed_tools(["Read", "Write", "Grep"], contract) == ["Read", "Grep"]
