"""MCP server 入口。

暴露两个工具给 Claude Code:
  - ping: 健康检查
  - delegate_to_deepseek: 真正的 sub-agent，把任务外包给 DeepSeek 跑完整 agent loop

环境变量:
  - DEEPSEEK_MODE=off: delegate 工具会立即返回 disabled 提示，Claude 不会再调
  - DEEPSEEK_API_KEY: 覆盖配置文件中的 api_key
  - DEEPSEEK_WORKSPACE: 覆盖配置文件中的 workspace
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

# Windows 上 asyncio 默认用 ProactorEventLoop，跟 stdio 子进程不兼容会卡死
# 必须在 import FastMCP / 启动事件循环之前切到 SelectorEventLoopPolicy
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from mcp.server.fastmcp import FastMCP

from . import __version__
from .agent_loop import AgentLoopError, run_agent
from .config import Config
from .contract import TaskContract
from .handoff import build_structured_handoff, merge_changed_files

# 日志写到 ~/.deepseek-mcp/（不污染 stdout，stdout 是 MCP 协议通道）
# log 目录 700、文件 600 —— 含路径 / task 摘要，多用户机器上不该世界可读
_LOG_DIR = Path.home() / ".deepseek-mcp"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_SERVER_LOG = _LOG_DIR / "server.log"
_USAGE_LOG = _LOG_DIR / "usage.log"

# Windows 不支持 POSIX 权限位，os.chmod 是 no-op；失败不致命
try:
    os.chmod(_LOG_DIR, 0o700)
except OSError:
    pass

# 创建文件后立即 chmod（basicConfig 用 default umask 创建，可能是 644）
for _p in (_SERVER_LOG, _USAGE_LOG):
    if not _p.exists():
        try:
            _p.touch(mode=0o600)
        except OSError:
            pass
    try:
        os.chmod(_p, 0o600)
    except OSError:
        pass

logging.basicConfig(
    filename=str(_SERVER_LOG),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


mcp = FastMCP("deepseek-mcp")


@mcp.tool()
def ping() -> str:
    """Health check. Confirms the deepseek-mcp server is alive.

    Use this before delegate_to_deepseek if you're not sure whether DeepSeek is configured.
    Returns version, mode (auto/off), and whether config is loadable.
    """
    mode = os.getenv("DEEPSEEK_MODE", "auto")
    try:
        cfg = Config.load()
        ws_short = _shorten_path(cfg.workspace)
        config_status = f"workspace={ws_short} (sandbox), model={cfg.model}"
    except Exception as e:
        config_status = f"NOT_CONFIGURED ({e})"
    return f"pong from deepseek-mcp v{__version__} | mode={mode} | {config_status}"


def _shorten_path(p: Path) -> str:
    """长路径压成 ~ + 最后几段，避免 ping 输出爆屏。"""
    s = str(p)
    home = str(Path.home())
    if s.startswith(home):
        s = "~" + s[len(home):]
    if len(s) > 60:
        parts = s.split("/")
        if len(parts) > 4:
            s = "/".join(parts[:2] + ["..."] + parts[-2:])
    return s


@mcp.tool()
def delegate_to_deepseek(task: str, context: str = "", contract: dict[str, Any] | None = None) -> str:
    """Delegate a focused task to DeepSeek as a real sub-agent.

    DeepSeek runs its own agent loop with local tools inside the configured
    workspace. In research pipeline mode, pass a contract so DeepSeek acts as a
    bounded implementer rather than a planner or final judge.

    Good fits:
      - Extract i18n keys from N files into JSON
      - Translate large chunks of text
      - Scan logs for patterns
      - Bulk refactors with a clear pattern
      - One-off ETL scripts

    Bad fits (do it yourself instead):
      - Architectural design / cross-file judgment
      - Bug root-cause analysis
      - Tasks requiring project-specific idioms from CLAUDE.md or other repo conventions

    Args:
        task: Clear description of what DeepSeek should accomplish, including
              success criteria and file paths involved.
        context: Optional additional context — project conventions, related
                 files DeepSeek should consider, output format requirements.
                 Include this when project-specific knowledge matters.
        contract: Optional bounded-task contract. Supported keys include mode,
                  allowed_files, forbidden_files, must_not_change,
                  success_checks, expected_outputs, review_after, and
                  allowed_tools. Contract tools can only restrict the global
                  config tools, never expand them.

    Returns:
        A summary of what DeepSeek did, server-generated git handoff metadata,
        turns used, tokens consumed, and any issues. Always inspect the diff
        before accepting the result.
    """
    mode = os.getenv("DEEPSEEK_MODE", "auto")
    if mode == "off":
        return (
            "DeepSeek delegation is disabled (DEEPSEEK_MODE=off). "
            "Continue the task yourself in the main conversation."
        )

    try:
        config = Config.load()
    except Exception as e:
        return f"ERROR: deepseek-mcp not configured: {e}"

    try:
        task_contract = TaskContract.from_dict(contract)
    except ValueError as e:
        return f"ERROR: invalid DeepSeek task contract: {e}"

    full_task = task
    if context:
        full_task = f"{task}\n\n# Additional context\n{context}"

    logger.info(
        "delegate_to_deepseek invoked. Task length=%d, context length=%d, mode=%s",
        len(task),
        len(context),
        task_contract.mode,
    )

    try:
        result = run_agent(full_task, config, task_contract)
    except AgentLoopError as e:
        logger.exception("Agent loop failed")
        return f"ERROR: DeepSeek agent loop failed: {e}"
    except Exception as e:
        logger.exception("Unexpected error during delegation")
        return f"ERROR: unexpected failure: {e}"

    logger.info(
        "delegate_to_deepseek done. mode=%s turns=%d tool_calls=%d tokens=%d duration=%.2fs",
        task_contract.mode,
        result["turns_used"],
        result["tool_calls"],
        result["tokens"]["total"],
        result["duration_seconds"],
    )

    # 用量记录（人类可读追加到 usage.log）
    # 注意：只记 task 前 60 字符摘要，不记 context（context 可能含项目敏感细节）
    try:
        # 简单大小控制：>10MB 时轮转一次（rename 为 .1）
        if _USAGE_LOG.exists() and _USAGE_LOG.stat().st_size > 10 * 1024 * 1024:
            try:
                _USAGE_LOG.replace(_USAGE_LOG.with_suffix(".log.1"))
            except OSError:
                pass
        with open(_USAGE_LOG, "a", encoding="utf-8") as f:
            f.write(
                f"{result['duration_seconds']:.1f}s  "
                f"turns={result['turns_used']:>2}  "
                f"tools={result['tool_calls']:>2}  "
                f"tokens={result['tokens']['total']:>6}  "
                f"task={task[:60]!r}\n"
            )
        try:
            os.chmod(_USAGE_LOG, 0o600)
        except OSError:
            pass
    except Exception:
        pass  # 日志失败不影响主流程

    git_summary = _collect_git_summary(config.workspace)
    structured = build_structured_handoff(result, task_contract, git_summary)

    return (
        f"{result['final_message']}\n\n"
        f"---\n"
        f"[deepseek-mcp structured handoff]\n"
        f"{json.dumps(structured, ensure_ascii=False, indent=2)}\n\n"
        f"[deepseek-mcp] {result['turns_used']} turns, "
        f"{result['tool_calls']} tool calls, "
        f"{result['tokens']['total']} tokens, "
        f"{result['duration_seconds']}s"
    )


def _collect_git_summary(workspace: Path) -> dict[str, Any]:
    diff_files = _git_lines(workspace, ["diff", "--name-only"])
    git_status = _git_text(workspace, ["status", "--short"])
    return {
        "changed_files": merge_changed_files(diff_files, git_status),
        "git_status": git_status,
        "diff_stat": _git_text(workspace, ["diff", "--stat"]),
    }


def _git_lines(workspace: Path, args: list[str]) -> list[str]:
    text = _git_text(workspace, args)
    if text.startswith("ERROR:"):
        return []
    return [line for line in text.splitlines() if line.strip()]


def _git_text(workspace: Path, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception as e:
        return f"ERROR: git {' '.join(args)} failed: {e}"
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        return f"ERROR: git {' '.join(args)} exited {result.returncode}: {err}"
    return result.stdout.strip()


def main() -> None:
    """CLI entrypoint."""
    logger.info("deepseek-mcp v%s starting (mode=%s)", __version__, os.getenv("DEEPSEEK_MODE", "auto"))
    try:
        mcp.run()
    except Exception as e:
        logger.exception("MCP server crashed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
