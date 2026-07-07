"""Structured post-run handoff helpers."""
from __future__ import annotations

from typing import Any

from .contract import TaskContract


def build_structured_handoff(
    result: dict[str, Any],
    task_contract: TaskContract,
    git_summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "status": "completed",
        "mode": task_contract.mode,
        "changed_files": git_summary["changed_files"],
        "commands_run": [],
        "success_checks": {check: "not_reported_by_server" for check in task_contract.success_checks},
        "assumptions": [],
        "risks": ["Inspect DeepSeek final message and git diff before accepting."],
        "needs_codex_review": True,
        "next_step": "run_codex_full_review",
        "restart_policy": "If any review stage fails and code changes are made, restart from software-review.",
        "review_after": task_contract.review_after,
        "git_status": git_summary["git_status"],
        "diff_stat": git_summary["diff_stat"],
        "usage": {
            "turns_used": result["turns_used"],
            "tool_calls": result["tool_calls"],
            "tokens": result["tokens"],
            "duration_seconds": result["duration_seconds"],
        },
    }


def merge_changed_files(diff_files: list[str], git_status: str) -> list[str]:
    seen = set()
    out = []
    for path in diff_files + paths_from_status(git_status):
        if path and path not in seen:
            seen.add(path)
            out.append(path)
    return out


def paths_from_status(git_status: str) -> list[str]:
    if git_status.startswith("ERROR:"):
        return []
    paths = []
    for line in git_status.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.append(path)
    return paths
