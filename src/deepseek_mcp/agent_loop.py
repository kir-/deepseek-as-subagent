"""DeepSeek agent loop。

接收一个任务描述 → 让 DeepSeek 自己跑 Read/Edit/Bash 等工具循环 → 返回 final message。
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from openai import APIConnectionError, APIError, OpenAI, RateLimitError

from .config import Config
from .contract import TaskContract, effective_allowed_tools
from .tools import build_tool_schemas, execute_tool

logger = logging.getLogger(__name__)

# 单次 API 调用最多重试次数（不含首次）。只对网络 / 限流类瞬态错误生效。
API_RETRY_ATTEMPTS = 2
API_RETRY_BACKOFF_SECONDS = 2.0

# 工具参数日志：含敏感内容的字段（避免写到 server.log）
SENSITIVE_TOOL_ARG_KEYS = {"content", "new_string"}


SYSTEM_PROMPT_TEMPLATE = """You are DeepSeek working as a bounded implementation worker inside a larger research-agent pipeline.

Claude is the planner and final judge.
Codex will perform adversarial review after your changes.

You're given a focused task to complete autonomously within a workspace.
You have local tools: {tools}

Rules:
1. Stay strictly within the workspace: {workspace}
2. Read before editing. Don't guess file contents.
3. For batch tasks (translating, extracting, refactoring many files), iterate file-by-file.
4. Do not make final research judgments.
5. Do not claim that an experiment is valid.
6. Do not decide whether the method is correct.
7. Do not change the task objective, estimator, algorithm, or public behavior unless the task contract explicitly requests it.
8. Follow the task contract strictly.
9. Respect allowed_files, forbidden_files, must_not_change, and success_checks.
10. If the task contract is too vague or conflicts with the requested work, stop and report the issue instead of guessing.
11. When done, return a final message summarizing:
   - changed files
   - commands run
   - checks passed/failed
   - assumptions
   - risks
   - anything Codex should review carefully
12. Don't ask clarifying questions back to the parent. Make reasonable assumptions
   and document them in your final message.
13. If a tool returns "ERROR: ...", read the error and decide: retry with fixed input,
   skip the file, or report and stop. Don't blindly loop on the same error.

{contract}
"""


class AgentLoopError(Exception):
    """Agent loop failed (max turns exceeded, API error, etc)."""


def run_agent(task: str, config: Config, contract: TaskContract | None = None) -> dict:
    """跑完整 agent loop。

    返回 dict:
      - final_message: str (DeepSeek 给的最终答复)
      - turns_used: int
      - tokens: {prompt, completion, total}
      - tool_calls: int
      - duration_seconds: float
    """
    contract = contract or TaskContract.from_dict(None)
    client = OpenAI(api_key=config.api_key, base_url=config.base_url)
    allowed_tools = effective_allowed_tools(config.allowed_tools, contract)
    if not allowed_tools:
        raise AgentLoopError(
            "Resolved to zero available tools (global config allowed_tools "
            f"{config.allowed_tools!r} ∩ mode '{contract.mode}' tools ∩ "
            f"contract.allowed_tools {contract.allowed_tools!r}). Refusing to run "
            "a tool-less turn — DeepSeek would otherwise free-text a fabricated "
            "'completed' response instead of actually executing anything."
        )
    tools = build_tool_schemas(allowed_tools)

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        tools=", ".join(allowed_tools),
        workspace=config.workspace,
        contract=contract.to_prompt_text(),
    )

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": task},
    ]

    total_prompt_tokens = 0
    total_completion_tokens = 0
    tool_call_count = 0
    started = time.time()

    for turn in range(config.max_turns):
        response = _call_with_retry(client, config, messages, tools, turn)

        usage = response.usage
        if usage:
            total_prompt_tokens += usage.prompt_tokens
            total_completion_tokens += usage.completion_tokens

        msg = response.choices[0].message

        # 用 raw dict 保留所有字段，包括 DeepSeek v4-pro thinking mode 的 reasoning_content
        # —— 它要求下一轮必须把 reasoning_content 也回传，否则 400 报错
        raw = response.model_dump(exclude_none=True)
        msg_dict = raw["choices"][0]["message"]
        messages.append(msg_dict)

        # 没有 tool_calls 说明 DeepSeek 决定结束
        if not msg.tool_calls:
            return {
                "final_message": msg.content or "(empty response)",
                "turns_used": turn + 1,
                "tokens": {
                    "prompt": total_prompt_tokens,
                    "completion": total_completion_tokens,
                    "total": total_prompt_tokens + total_completion_tokens,
                },
                "tool_calls": tool_call_count,
                "duration_seconds": round(time.time() - started, 2),
            }

        # 依次执行 tool calls
        for tc in msg.tool_calls:
            tool_call_count += 1
            tool_name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError as e:
                result = f"ERROR: invalid JSON in tool arguments: {e}"
            else:
                logger.info(
                    "Turn %d tool_call: %s(%s)",
                    turn,
                    tool_name,
                    _redact_args_for_log(args),
                )
                result = execute_tool(tool_name, args, config.workspace, contract, allowed_tools)

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                }
            )

    # 跑到 max_turns 没收敛 —— 只展示最后一条 assistant content，不夹带完整 tool_calls blob
    last_text = ""
    for m in reversed(messages):
        if m.get("role") == "assistant" and m.get("content"):
            last_text = str(m["content"])[:500]
            break
    raise AgentLoopError(
        f"Agent loop exceeded max_turns ({config.max_turns}). "
        f"Last assistant text: {last_text or '(none)'}"
    )


def _call_with_retry(client, config, messages, tools, turn):
    """带瞬态错误重试的单次 API 调用。

    只对 network / rate-limit / 5xx 这类瞬态错误重试；4xx 等永久错误直接抛。
    """
    last_exc = None
    for attempt in range(1 + API_RETRY_ATTEMPTS):
        try:
            return client.chat.completions.create(
                model=config.model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
            )
        except (APIConnectionError, RateLimitError) as e:
            last_exc = e
            wait = API_RETRY_BACKOFF_SECONDS * (attempt + 1)
            logger.warning(
                "Turn %d API transient error (attempt %d/%d): %s — retry in %.1fs",
                turn, attempt + 1, 1 + API_RETRY_ATTEMPTS, e, wait,
            )
            time.sleep(wait)
        except APIError as e:
            # 5xx 也重试，4xx 不重试
            status = getattr(e, "status_code", None)
            if status and 500 <= status < 600:
                last_exc = e
                wait = API_RETRY_BACKOFF_SECONDS * (attempt + 1)
                logger.warning(
                    "Turn %d API 5xx (attempt %d/%d): %s — retry in %.1fs",
                    turn, attempt + 1, 1 + API_RETRY_ATTEMPTS, e, wait,
                )
                time.sleep(wait)
                continue
            raise AgentLoopError(f"DeepSeek API error on turn {turn}: {e}") from e
        except Exception as e:
            raise AgentLoopError(f"DeepSeek API error on turn {turn}: {e}") from e
    raise AgentLoopError(
        f"DeepSeek API unreachable after {1 + API_RETRY_ATTEMPTS} attempts on turn {turn}: {last_exc}"
    ) from last_exc


def _redact_args_for_log(args: dict) -> dict:
    """工具参数写日志前脱敏 —— content/new_string 不能进 server.log（可能含 secrets）。"""
    redacted = {}
    for k, v in args.items():
        if k in SENSITIVE_TOOL_ARG_KEYS and isinstance(v, str):
            redacted[k] = f"<{len(v)} chars, redacted>"
        elif isinstance(v, str) and len(v) >= 100:
            redacted[k] = f"<{len(v)} chars>"
        else:
            redacted[k] = v
    return redacted
