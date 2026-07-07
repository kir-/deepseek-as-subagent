"""Per-delegation task contracts for bounded research implementation."""
from __future__ import annotations

import fnmatch
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .safety import SandboxViolation

ALL_TOOLS = ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "NotebookEdit"]

MODE_ALLOWED_TOOLS = {
    "implement": ALL_TOOLS,
    "readonly_scan": ["Read", "Bash", "Glob", "Grep"],
    "test_writer": ALL_TOOLS,
    "logging_diagnostics": ALL_TOOLS,
    "config_plumbing": ALL_TOOLS,
    "docs": ["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
}

DEFAULT_FORBIDDEN_FILES = [
    ".env",
    ".env.*",
    "*.key",
    "*.pem",
    "*.token",
    "secrets/**",
    "wandb/**",
    "outputs/**",
    "runs/**",
    "results/final/**",
    "paper/figures/final/**",
    "paper/tables/final/**",
]

DEFAULT_ALLOWED_FILES = ["**/*"]

WRITE_TOOLS = {"Write", "Edit", "NotebookEdit"}
READ_TOOLS = {"Read"}


@dataclass(frozen=True)
class TaskContract:
    mode: str = "implement"
    allowed_files: list[str] = field(default_factory=lambda: list(DEFAULT_ALLOWED_FILES))
    forbidden_files: list[str] = field(default_factory=lambda: list(DEFAULT_FORBIDDEN_FILES))
    must_not_change: list[str] = field(default_factory=list)
    success_checks: list[str] = field(default_factory=list)
    expected_outputs: list[str] = field(default_factory=list)
    review_after: str = "codex-full-review"
    allowed_tools: list[str] | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "TaskContract":
        if value is None:
            return cls()
        if not isinstance(value, dict):
            raise ValueError("contract must be a JSON object")

        mode = value.get("mode", "implement")
        if not isinstance(mode, str):
            raise ValueError("contract.mode must be a string")
        if mode not in MODE_ALLOWED_TOOLS:
            raise ValueError(
                f"unknown contract.mode '{mode}'. Valid modes: {', '.join(MODE_ALLOWED_TOOLS)}"
            )

        allowed_files = _string_list(value, "allowed_files", DEFAULT_ALLOWED_FILES)
        forbidden_files = _string_list(value, "forbidden_files", DEFAULT_FORBIDDEN_FILES)
        must_not_change = _string_list(value, "must_not_change", [])
        success_checks = _string_list(value, "success_checks", [])
        expected_outputs = _string_list(value, "expected_outputs", [])
        allowed_tools = _optional_string_list(value, "allowed_tools")

        review_after = value.get("review_after", "codex-full-review")
        if not isinstance(review_after, str):
            raise ValueError("contract.review_after must be a string")

        return cls(
            mode=mode,
            allowed_files=allowed_files,
            forbidden_files=forbidden_files,
            must_not_change=must_not_change,
            success_checks=success_checks,
            expected_outputs=expected_outputs,
            review_after=review_after,
            allowed_tools=allowed_tools,
            raw=dict(value),
        )

    def to_prompt_text(self) -> str:
        return (
            "# Task contract\n"
            f"mode: {self.mode}\n"
            f"allowed_files: {self.allowed_files}\n"
            f"forbidden_files: {self.forbidden_files}\n"
            f"must_not_change: {self.must_not_change}\n"
            f"success_checks: {self.success_checks}\n"
            f"expected_outputs: {self.expected_outputs}\n"
            f"review_after: {self.review_after}\n"
        )


def effective_allowed_tools(global_allowed: list[str], contract: TaskContract) -> list[str]:
    mode_allowed = set(MODE_ALLOWED_TOOLS[contract.mode])
    contract_allowed = set(contract.allowed_tools) if contract.allowed_tools is not None else set(ALL_TOOLS)
    return [tool for tool in global_allowed if tool in mode_allowed and tool in contract_allowed]


def check_contract_path(
    path: str,
    workspace: Path,
    contract: TaskContract,
    operation: str,
) -> None:
    rel = _relative_posix(path, workspace)
    if _matches_any(rel, contract.forbidden_files):
        raise SandboxViolation(
            f"Contract blocks {operation} on '{rel}' because it matches forbidden_files."
        )
    if operation in WRITE_TOOLS and not _matches_any(rel, contract.allowed_files):
        raise SandboxViolation(
            f"Contract blocks {operation} on '{rel}' because it is outside allowed_files."
        )


def check_contract_command(command: str, workspace: Path, contract: TaskContract) -> None:
    """Best-effort guard against shell writes aimed at forbidden paths."""
    for token in _command_tokens(command):
        if not _looks_like_path(token):
            continue
        try:
            rel = _relative_posix(token, workspace)
        except SandboxViolation:
            continue
        if _matches_any(rel, contract.forbidden_files):
            raise SandboxViolation(
                f"Contract blocks Bash command because token '{token}' matches forbidden_files."
            )


def _string_list(data: dict[str, Any], key: str, default: list[str]) -> list[str]:
    value = data.get(key, list(default))
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"contract.{key} must be a list of strings")
    return list(value)


def _optional_string_list(data: dict[str, Any], key: str) -> list[str] | None:
    if key not in data:
        return None
    value = data[key]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"contract.{key} must be a list of strings")
    return list(value)


def _relative_posix(path: str, workspace: Path) -> str:
    if not path:
        raise SandboxViolation("empty path is not allowed")
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = workspace / p
    abs_path = p.resolve()
    ws_resolved = workspace.resolve()
    try:
        rel = abs_path.relative_to(ws_resolved)
    except ValueError as e:
        raise SandboxViolation(f"Path {abs_path} is outside workspace {ws_resolved}.") from e
    return rel.as_posix()


def _matches_any(rel_path: str, patterns: list[str]) -> bool:
    return any(_match_pattern(rel_path, pattern) for pattern in patterns)


def _match_pattern(rel_path: str, pattern: str) -> bool:
    pat = pattern.strip().lstrip("/")
    if not pat:
        return False
    if pat in {"**", "**/*"}:
        return True
    candidates = {pat}
    if pat.startswith("**/"):
        candidates.add(pat[3:])
    if "/**/" in pat:
        candidates.add(pat.replace("/**/", "/"))
    if pat.endswith("/**"):
        candidates.add(pat[:-3])
    return any(fnmatch.fnmatchcase(rel_path, candidate) for candidate in candidates)


def _command_tokens(command: str) -> list[str]:
    try:
        tokens = shlex.split(command, comments=False, posix=True)
    except ValueError:
        tokens = command.split()
    return [tok.strip("'\"") for tok in tokens]


def _looks_like_path(token: str) -> bool:
    if not token or token.startswith("-"):
        return False
    return (
        "/" in token
        or token.startswith(".")
        or token in {".env"}
        or any(token.endswith(ext) for ext in (".key", ".pem", ".token"))
    )
