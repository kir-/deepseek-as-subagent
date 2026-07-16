# deepseek-as-subagent

**English** · [简体中文](README.zh-CN.md)

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/PsChina/deepseek-as-subagent?style=social)](https://github.com/PsChina/deepseek-as-subagent)
[![Glama MCP server](https://glama.ai/mcp/servers/PsChina/deepseek-as-subagent/badges/score.svg)](https://glama.ai/mcp/servers/PsChina/deepseek-as-subagent)
[![MCP](https://img.shields.io/badge/protocol-MCP-purple)](https://modelcontextprotocol.io/)
[![Mentioned in Awesome MCP Servers](https://awesome.re/mentioned-badge.svg)](https://github.com/punkpeye/awesome-mcp-servers)
[![Platforms](https://img.shields.io/badge/platforms-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey)](https://github.com/PsChina/deepseek-as-subagent)

> Run DeepSeek as a **real sub-agent** inside Claude Code / Codex CLI — not just an LLM endpoint.
> Claude stays on the main loop (your Max OAuth, your context, your judgment).
> DeepSeek gets its own Read / Write / Edit / Bash / Glob / Grep / NotebookEdit agent loop for batch / mechanical work.

```
       Claude (your main agent, Max OAuth, expensive but smart)
         │
         │  decides this is a batch task
         │  →  delegate_to_deepseek(task, context)
         ▼
       DeepSeek sub-agent (cheap, runs its own loop inside the workspace)
         │  Read / Write / Edit / Bash / Glob / Grep / NotebookEdit — all local
         │  iterates until done
         ▼
       Final message bubbles back to Claude
       Claude verifies a sample of the output, reports to you
```

## Quick start

```bash
curl -sSL https://raw.githubusercontent.com/PsChina/deepseek-as-subagent/main/curl-install.sh | bash
```

One line. Clones the repo to `~/.local/share/deepseek-as-subagent`, installs
the Python package in an isolated venv, registers the MCP server with Claude
Code, deploys the skill + `/ds` slash command, and adds a `pure` shell alias.

After install, edit `~/.deepseek-mcp/config.json` to paste your DeepSeek API
key (get one at [platform.deepseek.com](https://platform.deepseek.com)). Then
run `claude` and try `/ds write a python hello world to /tmp/hi.py`.

Re-run the same `curl | bash` later to upgrade. For other clients (Codex,
Cursor, Cline) or manual install, see [Install](#install) below.

## How is this different from existing DeepSeek MCP servers?

Most `deepseek-mcp-server` projects expose DeepSeek as a **single LLM call** (`create_chat_completion`, `create_anthropic_message`). Claude has to read every file itself and feed content into the prompt — DeepSeek only saves you the "thinking" cost, not the "reading/writing" cost. Same for [Composio's DeepSeek toolkit](https://composio.dev/toolkits/deepseek/framework/claude-code).

This project gives DeepSeek **its own full agent loop**: tool dispatch, file I/O, command execution, multi-turn reasoning — all inside a sandboxed workspace. Claude hands off the entire task and gets a single summary back. The token savings are end-to-end.

## What's in the box

- **MCP server** (Python, stdio transport) exposing one real tool: `delegate_to_deepseek(task, context, contract=None)`
- **Local agent loop** for DeepSeek (`agent_loop.py`) with OpenAI-compatible function calling
- **7 sandboxed tools** for DeepSeek to use: Read / Write / Edit / Bash / Glob / Grep / NotebookEdit (Jupyter cell-level editing)
- **Path sandbox + command blacklist** (`safety.py`) — DeepSeek can't escape your workspace or run `rm -rf /`
- **Skill + slash command** so Claude knows *when* to delegate (and when not to)
- **`pure` shell alias** for one-shot "no DeepSeek today" runs

## Install

### Claude Code (default)

```bash
git clone https://github.com/PsChina/deepseek-as-subagent
cd deepseek-as-subagent
./install.sh
```

Then create or edit your DeepSeek config:

```bash
mkdir -p ~/.deepseek-mcp
chmod 700 ~/.deepseek-mcp
nano ~/.deepseek-mcp/config.json
```

Paste this JSON, replacing the API key with your real key:

```json
{
  "api_key": "sk-your-deepseek-key-here",
  "model": "deepseek-v4-pro",
  "max_turns": 50,
  "allowed_tools": ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "NotebookEdit"]
}
```

Lock down the file permissions:

```bash
chmod 600 ~/.deepseek-mcp/config.json
```

Get a key at https://platform.deepseek.com (CNY ¥20 lasts a long time).

Verify Claude Code can see the MCP server:

```bash
claude mcp list
```

You should see a `deepseek` entry with `Connected` or `✔ Connected`.

Then launch Claude from the project you want DeepSeek to work in:

```bash
cd /path/to/your/project
claude
```

Test explicit delegation:

```text
/ds write a hello world python script to /tmp/hi.py
```

The workspace follows the directory where you launch `claude`, so running
`claude` inside `/path/to/your/project` makes that project the sandbox DeepSeek
can read and edit.

### Codex CLI

See [adapters/codex/](adapters/codex/README.md) — registers the MCP server
with `codex` and provides instructions you can paste into `AGENTS.md`.

### Cursor / Cline / Claude Desktop / other MCP clients

The MCP server itself is client-agnostic. After `pip install -e .`, point
your client's MCP config at `<repo>/.venv/bin/deepseek-mcp`. For
client-specific "when to delegate" hints, see [adapters/](adapters/) —
PRs welcome for new clients.

## Usage

After install, just use `claude` normally. The plugin adds:

- `delegate_to_deepseek` — Claude auto-invokes it when the task fits (see `skills/delegate-to-deepseek/SKILL.md`)
- `/ds <task>` — force delegation, skip Claude's own judgment
- `/ds-impl <task>` — research-pipeline delegation with an explicit task contract
- `pure` shell alias — start Claude with DeepSeek disabled for this session

## Research-agent pipeline mode

This fork is designed for a three-agent research workflow:

Claude plans.
DeepSeek implements bounded patches.
Codex reviews adversarially.
Claude decides.

DeepSeek should not make final research claims or decide whether a method is correct.

For research implementation tasks, call:

```python
delegate_to_deepseek(
    task="Implement diagnostics under the contract.",
    context="Follow existing trainer logging conventions.",
    contract={
        "mode": "logging_diagnostics",
        "allowed_files": ["src/**/*.py", "tests/**/*.py"],
        "forbidden_files": [".env", "secrets/**", "outputs/**", "results/final/**"],
        "must_not_change": [
            "training objective",
            "environment stepping semantics",
            "evaluation metric definitions"
        ],
        "success_checks": ["pytest tests/"],
        "expected_outputs": ["changed_files", "commands_run", "risks"],
        "review_after": "codex-full-review"
    },
)
```

After DeepSeek returns, inspect the server-generated changed files, git status,
and diff stat. Then run Codex full-review. If any review stage fails and code
changes are made, restart from software review.

## When delegation actually saves money

**Critical rule** (encoded in the skill): the delegation decision must happen **before Claude reads any source files**. If Claude reads first then delegates, both Claude and DeepSeek read the same files — net cost goes up, not down.

The skill enforces: only `Glob` / `LS` / read-only `Bash` are allowed before the delegation decision. If you can't decide without reading, you shouldn't delegate.

Sweet spot for delegation:
- ✅ 10–50 files, mechanical pattern (i18n extract, batch refactor, ETL)
- ✅ Large data + simple processing (log scan, file conversion)
- ❌ Single file < 500 lines (DeepSeek thinking-token overhead > savings)
- ❌ Cross-file design / architectural judgment
- ❌ Tasks needing project-specific idioms from `CLAUDE.md`

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Claude Code (CLI or VSCode extension, your Max OAuth)          │
│    ↓ stdio (MCP protocol, no network)                           │
│  deepseek-as-subagent (this project, Python subprocess)         │
│    ↓ HTTPS                                                      │
│  api.deepseek.com (your API key, paid per token)                │
└─────────────────────────────────────────────────────────────────┘

Everything except the actual DeepSeek API call stays on your machine.
No third-party proxy. No cloud relay. Your code never leaves your laptop.
```

## Configuration

Create `~/.deepseek-mcp/config.json` with private permissions:

```bash
mkdir -p ~/.deepseek-mcp
chmod 700 ~/.deepseek-mcp
nano ~/.deepseek-mcp/config.json
chmod 600 ~/.deepseek-mcp/config.json
```

Use this shape:

```json
{
  "api_key": "sk-your-deepseek-key-here",
  "model": "deepseek-v4-pro",
  "max_turns": 50,
  "allowed_tools": ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "NotebookEdit"]
}
```

Do not put your API key in this repository or commit it to git. The server
loads the key from `DEEPSEEK_API_KEY` first, then from
`~/.deepseek-mcp/config.json`.

**Workspace (sandbox root)** auto-follows the directory where you launch
`claude` — DeepSeek shares the same scope as Claude itself, no manual config
needed. To lock the sandbox to a fixed path regardless of cwd, add
`"workspace": "/abs/path"` to the config.

Override at runtime with env vars: `DEEPSEEK_API_KEY`, `DEEPSEEK_WORKSPACE`, `DEEPSEEK_MODE=off`.

### Task contracts

Contracts restrict a single delegation without granting any tools beyond the
global `allowed_tools` config. Effective tools are:

```text
global_allowed_tools ∩ mode_allowed_tools ∩ contract_allowed_tools
```

Supported modes are `implement`, `readonly_scan`, `test_writer`,
`logging_diagnostics`, `config_plumbing`, and `docs`. Example contracts live in
[`contracts/`](contracts/).

If you set `contract.allowed_tools`, use the exact capitalized tool names —
`Read, Write, Edit, Bash, Glob, Grep, NotebookEdit`. There is no fuzzy or
case-insensitive matching. An unknown name (e.g. `read`, `bash_readonly`)
raises `ValueError` at contract-parse time; if the three-way intersection
above still resolves to zero tools (e.g. a `readonly_scan` mode combined with
a `contract.allowed_tools` that only lists write tools), `delegate_to_deepseek`
raises before calling the API — it will not silently hand DeepSeek an empty
toolset, which previously let it free-text a plausible-looking "completed"
summary without doing any real work. In most cases you don't need
`allowed_tools` in the contract at all: `mode` already picks a sensible tool
set (e.g. `readonly_scan` → `Read/Bash/Glob/Grep`, no write access).

## Uninstall

```bash
./uninstall.sh
```

Removes the MCP registration, skill, and slash command. Doesn't touch your Claude Code, your Max OAuth, or your projects.

## License

MIT
