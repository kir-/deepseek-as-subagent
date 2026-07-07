from deepseek_mcp.contract import TaskContract
from deepseek_mcp.handoff import build_structured_handoff, merge_changed_files


def test_structured_response_includes_review_handoff_fields():
    contract = TaskContract.from_dict(
        {"mode": "implement", "success_checks": ["pytest tests/test_example.py"]}
    )
    result = {
        "turns_used": 2,
        "tool_calls": 3,
        "tokens": {"prompt": 10, "completion": 5, "total": 15},
        "duration_seconds": 1.2,
    }
    git_summary = {
        "changed_files": ["src/foo.py"],
        "git_status": " M src/foo.py",
        "diff_stat": "src/foo.py | 2 ++",
    }

    handoff = build_structured_handoff(result, contract, git_summary)

    assert handoff["changed_files"] == ["src/foo.py"]
    assert handoff["git_status"] == " M src/foo.py"
    assert handoff["next_step"] == "run_codex_full_review"
    assert handoff["needs_codex_review"] is True


def test_changed_files_include_git_status_paths():
    assert merge_changed_files(["src/foo.py"], "?? tests/test_foo.py\nR  old.py -> new.py") == [
        "src/foo.py",
        "tests/test_foo.py",
        "new.py",
    ]
