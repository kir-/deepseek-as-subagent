# deepseek-as-subagent

[English](README.md) · **简体中文**

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/PsChina/deepseek-as-subagent?style=social)](https://github.com/PsChina/deepseek-as-subagent)
[![Glama MCP server](https://glama.ai/mcp/servers/PsChina/deepseek-as-subagent/badges/score.svg)](https://glama.ai/mcp/servers/PsChina/deepseek-as-subagent)
[![MCP](https://img.shields.io/badge/protocol-MCP-purple)](https://modelcontextprotocol.io/)
[![Mentioned in Awesome MCP Servers](https://awesome.re/mentioned-badge.svg)](https://github.com/punkpeye/awesome-mcp-servers)
[![Platforms](https://img.shields.io/badge/platforms-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey)](https://github.com/PsChina/deepseek-as-subagent)

> 让 DeepSeek 在 Claude Code / Codex CLI 里作为**真正的 sub-agent** 运行 —— 不只是一个 LLM 接口。
> Claude 留在主战场（你的 Max OAuth、你的上下文、你的判断）。
> DeepSeek 拿到自己的 Read / Write / Edit / Bash / Glob / Grep / NotebookEdit 工具循环，专做批量 / 机械活。

```
       Claude（你的主 agent，Max OAuth，贵但聪明）
         │
         │  判断这是一个批量任务
         │  →  delegate_to_deepseek(task, context)
         ▼
       DeepSeek sub-agent（便宜，在工作区里跑自己的循环）
         │  Read / Write / Edit / Bash / Glob / Grep / NotebookEdit —— 全部本地
         │  迭代直到完成
         ▼
       最终结果冒泡回 Claude
       Claude 抽样核实产物，再向你汇报
```

## 快速开始

```bash
curl -sSL https://raw.githubusercontent.com/PsChina/deepseek-as-subagent/main/curl-install.sh | bash
```

一行命令。把仓库 clone 到 `~/.local/share/deepseek-as-subagent`，在隔离的 venv 里装好 Python 包，把 MCP server 注册到 Claude Code，部署 skill + `/ds` 斜杠命令，并加一个 `pure` shell 别名。

安装后，编辑 `~/.deepseek-mcp/config.json` 填入你的 DeepSeek API key（在 [platform.deepseek.com](https://platform.deepseek.com) 申请）。然后运行 `claude`，试试 `/ds write a python hello world to /tmp/hi.py`。

之后重跑同一条 `curl | bash` 即可升级。其它客户端（Codex、Cursor、Cline）或手动安装见下方 [安装](#安装)。

## 和现有的 DeepSeek MCP server 有何不同？

多数 `deepseek-mcp-server` 项目把 DeepSeek 暴露成**单次 LLM 调用**（`create_chat_completion`、`create_anthropic_message`）。Claude 得自己读每个文件、把内容喂进 prompt —— DeepSeek 只帮你省了"思考"成本，没省"读写"成本。[Composio 的 DeepSeek toolkit](https://composio.dev/toolkits/deepseek/framework/claude-code) 也是如此。

本项目给 DeepSeek **一个完整的 agent 循环**：工具调度、文件 I/O、命令执行、多轮推理 —— 全部在一个沙箱化工作区里。Claude 把整个任务交出去，拿回一条总结。token 是端到端地省。

## 包含什么

- **MCP server**（Python，stdio 传输），暴露一个真正的工具：`delegate_to_deepseek(task, context)`
- **本地 agent 循环**（`agent_loop.py`），OpenAI 兼容的 function calling
- **7 个沙箱工具**供 DeepSeek 使用：Read / Write / Edit / Bash / Glob / Grep / NotebookEdit（Jupyter 单元级编辑）
- **路径沙箱 + 命令黑名单**（`safety.py`）—— DeepSeek 跳不出你的工作区，也跑不了 `rm -rf /`
- **Skill + 斜杠命令**，让 Claude 知道*何时*该委派（以及何时不该）
- **`pure` shell 别名**，一次性"今天不用 DeepSeek"地运行

## 安装

### Claude Code（默认）

```bash
git clone https://github.com/PsChina/deepseek-as-subagent
cd deepseek-as-subagent
./install.sh
```

然后编辑 `~/.deepseek-mcp/config.json` 填入 DeepSeek API key。

在 https://platform.deepseek.com 申请 key（¥20 能用很久）。

### Codex CLI

见 [adapters/codex/](adapters/codex/README.md) —— 把 MCP server 注册给 `codex`，并提供可粘贴进 `AGENTS.md` 的说明。

### Cursor / Cline / Claude Desktop / 其它 MCP 客户端

MCP server 本身与客户端无关。`pip install -e .` 后，把客户端的 MCP 配置指向 `<repo>/.venv/bin/deepseek-mcp`。客户端特定的"何时委派"提示见 [adapters/](adapters/) —— 欢迎为新客户端提 PR。

## 使用

安装后，正常用 `claude` 即可。插件加了：

- `delegate_to_deepseek` —— 任务合适时 Claude 自动调用（见 `skills/delegate-to-deepseek/SKILL.md`）
- `/ds <task>` —— 强制委派，跳过 Claude 自己的判断
- `pure` shell 别名 —— 本次会话禁用 DeepSeek 启动 Claude

## 委派到底什么时候省钱

**铁律**（已写进 skill）：委派决策必须发生在 **Claude 读任何源文件之前**。如果 Claude 先读再委派，Claude 和 DeepSeek 就读了同样的文件 —— 净成本是上升而非下降。

skill 强制：委派决策前只允许 `Glob` / `LS` / 只读 `Bash`。如果不读就没法决定，那就不该委派。

适合委派的甜区：
- ✅ 10–50 个文件，机械模式（i18n 抽取、批量重构、ETL）
- ✅ 大数据 + 简单处理（日志扫描、文件转换）
- ❌ 单文件 < 500 行（DeepSeek 的思考 token 开销 > 省下的）
- ❌ 跨文件设计 / 架构判断
- ❌ 需要 `CLAUDE.md` 里项目特定约定的任务

## 架构

```
┌─────────────────────────────────────────────────────────────────┐
│  Claude Code（CLI 或 VSCode 扩展，你的 Max OAuth）              │
│    ↓ stdio（MCP 协议，不走网络）                                │
│  deepseek-as-subagent（本项目，Python 子进程）                  │
│    ↓ HTTPS                                                      │
│  api.deepseek.com（你的 API key，按 token 付费）                │
└─────────────────────────────────────────────────────────────────┘

除了真正调 DeepSeek API 那一步，一切都留在你机器上。
没有第三方代理，没有云中转。你的代码从不离开你的电脑。
```

## 配置

`~/.deepseek-mcp/config.json`：

```json
{
  "api_key": "sk-...",
  "model": "deepseek-v4-pro",
  "max_turns": 50,
  "allowed_tools": ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "NotebookEdit"]
}
```

**工作区（沙箱根）** 自动跟随你启动 `claude` 的目录 —— DeepSeek 与 Claude 共享同一作用域，无需手动配置。要把沙箱锁到固定路径（不随 cwd 变），在配置里加 `"workspace": "/abs/path"`。

运行时可用环境变量覆盖：`DEEPSEEK_API_KEY`、`DEEPSEEK_WORKSPACE`、`DEEPSEEK_MODE=off`。

## 卸载

```bash
./uninstall.sh
```

移除 MCP 注册、skill 和斜杠命令。不动你的 Claude Code、Max OAuth 或你的项目。

## License

MIT
