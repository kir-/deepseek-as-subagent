"""沙箱：路径限制 + 命令黑名单。

设计目标：DeepSeek 是"听话的助手但不一定可靠"——它可能误读路径、误跑命令。
不上 docker（启动慢、依赖重），用进程内的轻量检查防住 95% 的误操作。

注意：黑名单 ≠ 安全边界。真正的对抗性攻击应该用 docker / bubblewrap / sandbox-exec
之类的真沙箱包起来。这里的检查只是"防 DeepSeek 走神"的护栏。
"""
from __future__ import annotations

import shlex
from pathlib import Path

# 危险命令检测的两种粒度：
#   1) DANGEROUS_TOKENS：第一个 token（程序名）整体匹配，难以用 \ 编码绕过
#   2) DANGEROUS_PHRASES：完整短语子串匹配（rm -rf / 这种"不可能合法"的组合）
DANGEROUS_TOKENS = {
    "sudo",
    "su",
    "nc", "ncat", "netcat",
    "ssh", "scp", "sftp", "rsync",
    "curl", "wget",
    "telnet",
    "socat",
}

# 配套程序名集合（出现在 token 流任意位置即拒绝）
DANGEROUS_ANYWHERE_TOKENS = {
    "sudo", "su",
}

# 完整短语匹配（保留旧风格，专门抓"形态独特"的危险组合）
DANGEROUS_PHRASES = [
    "rm -rf /",
    "rm -rf ~",
    "rm -rf $HOME",
    "rm -rf *",
    "rm -rf .",
    ":(){:|:&};:",  # fork bomb
    "mkfs.",
    "> /dev/sd",
    "chmod -R 777 /",
    "dd if=/dev/zero",
    "dd if=/dev/random",
    "/dev/tcp/",
    "/dev/udp/",
]

# Python / shell / 解释器 -c 后内联代码：很容易藏恶意命令，统一拒绝
DANGEROUS_INLINE_INTERPRETERS = {
    ("python", "-c"), ("python3", "-c"),
    ("perl", "-e"), ("ruby", "-e"),
    ("node", "-e"), ("php", "-r"),
    ("awk", "-e"),
    ("sh", "-c"), ("bash", "-c"), ("zsh", "-c"), ("ksh", "-c"), ("dash", "-c"),
}

# 包管理"装东西"动作：易被滥用装恶意包
PACKAGE_INSTALL_PREFIXES = [
    ("pip", "install"), ("pip3", "install"),
    ("pipx", "install"),
    ("npm", "install"), ("npm", "i"),
    ("yarn", "add"),
    ("pnpm", "install"), ("pnpm", "add"),
    ("uv", "pip"),
    ("uv", "add"),
    ("gem", "install"),
    ("cargo", "install"),
    ("brew", "install"),
    ("apt", "install"), ("apt-get", "install"),
    ("dnf", "install"), ("yum", "install"),
]

# 发布 / 推送动作：写到外部世界的"出口"
PUBLISH_PREFIXES = [
    ("git", "push"),
    ("npm", "publish"),
    ("twine", "upload"),
    ("cargo", "publish"),
    ("gh", "release"),
]


class SandboxViolation(Exception):
    """工具调用违反沙箱规则。返回给 DeepSeek 让它知道为什么失败。"""


def resolve_safe_path(rel_or_abs: str, workspace: Path) -> Path:
    """把 DeepSeek 传来的路径解析到绝对路径，并校验在 workspace 内。

    返回值：解析后的绝对路径。
    抛出：SandboxViolation 如果路径逃出 workspace。
    """
    if not rel_or_abs:
        raise SandboxViolation("empty path is not allowed")
    if "\x00" in rel_or_abs:
        raise SandboxViolation("null byte in path is not allowed")

    p = Path(rel_or_abs).expanduser()
    if not p.is_absolute():
        p = workspace / p
    abs_path = p.resolve()
    ws_resolved = workspace.resolve()

    try:
        abs_path.relative_to(ws_resolved)
    except ValueError as e:
        raise SandboxViolation(
            f"Path {abs_path} is outside workspace {ws_resolved}. "
            f"Tools can only access files within the configured workspace."
        ) from e

    return abs_path


def _tokenize(command: str) -> list[str]:
    """安全分词。命令引号不闭合时 shlex 会抛错；回退到 split。"""
    try:
        return shlex.split(command, comments=False, posix=True)
    except ValueError:
        return command.split()


def check_command(command: str) -> None:
    """检查 Bash 命令是否在黑名单里。抛 SandboxViolation 即拒绝。

    多层检查（任一命中即拒）：
      1) DANGEROUS_PHRASES：粗粒度子串
      2) DANGEROUS_TOKENS：分词后程序名（第一个 token 或管道后第一个 token）
      3) DANGEROUS_ANYWHERE_TOKENS：sudo / su 出现在任何位置
      4) DANGEROUS_INLINE_INTERPRETERS：python -c / perl -e 等
      5) PACKAGE_INSTALL_PREFIXES：装包动作
      6) PUBLISH_PREFIXES：发布动作（git push / npm publish 等）
    """
    if not command or not command.strip():
        raise SandboxViolation("empty command")

    lower = command.lower()

    # 1) 短语匹配（不分词，专抓特殊组合）
    for phrase in DANGEROUS_PHRASES:
        if phrase.lower() in lower:
            raise SandboxViolation(
                f"Command blocked by sandbox: contains dangerous phrase '{phrase}'."
            )

    # 2-6) 分词后逐段检查（按 ; && || | 分子句）
    # 简单切分；不追求 100% bash 解析，目的是不让 'a; rm -rf /' 漏掉
    clauses = _split_clauses(command)
    for clause in clauses:
        tokens = _tokenize(clause)
        if not tokens:
            continue

        first = _strip_cmd_prefix(tokens[0])

        # 任意位置出现 sudo / su
        for tok in tokens:
            if _strip_cmd_prefix(tok) in DANGEROUS_ANYWHERE_TOKENS:
                raise SandboxViolation(
                    f"Command blocked by sandbox: '{tok}' not allowed."
                )

        # 程序名黑名单
        if first in DANGEROUS_TOKENS:
            raise SandboxViolation(
                f"Command blocked by sandbox: program '{first}' not allowed "
                f"(network / privilege escalation tools are disabled)."
            )

        # 内联解释器
        if len(tokens) >= 2:
            sig = (first, tokens[1])
            if sig in DANGEROUS_INLINE_INTERPRETERS:
                raise SandboxViolation(
                    f"Command blocked by sandbox: inline code via '{first} {tokens[1]}' "
                    f"is not allowed (write a file then run it instead)."
                )

        # 装包 / 发布
        if len(tokens) >= 2:
            sig = (first, tokens[1])
            if sig in PACKAGE_INSTALL_PREFIXES:
                raise SandboxViolation(
                    f"Command blocked by sandbox: package install '{first} {tokens[1]}' "
                    f"is not allowed."
                )
            if sig in PUBLISH_PREFIXES:
                raise SandboxViolation(
                    f"Command blocked by sandbox: publish action '{first} {tokens[1]}' "
                    f"is not allowed."
                )


def _split_clauses(command: str) -> list[str]:
    """按 ; && || | 切分子句（粗粒度，不考虑引号内的分隔符 — 用足够好就行）。"""
    out: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(command)
    in_single = False
    in_double = False
    while i < n:
        c = command[i]
        # 简单引号跟踪，避免 ';' 在引号里被当分隔符
        if c == "'" and not in_double:
            in_single = not in_single
            buf.append(c)
            i += 1
            continue
        if c == '"' and not in_single:
            in_double = not in_double
            buf.append(c)
            i += 1
            continue
        if not in_single and not in_double:
            two = command[i:i+2]
            if c in ";|&" or two in ("&&", "||"):
                if buf:
                    out.append("".join(buf).strip())
                    buf = []
                i += 2 if two in ("&&", "||") else 1
                continue
        buf.append(c)
        i += 1
    if buf:
        out.append("".join(buf).strip())
    return [c for c in out if c]


def _strip_cmd_prefix(tok: str) -> str:
    """剥掉 'command'/'\\'/'/path/to/' 等程序名前缀，归一化判断。"""
    # 'command curl' / '\curl' / '/usr/bin/curl' → 'curl'
    if tok.startswith("\\"):
        tok = tok[1:]
    if "/" in tok:
        tok = tok.rsplit("/", 1)[-1]
    return tok.lower()
