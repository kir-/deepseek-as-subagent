#!/usr/bin/env bash
# uninstall.sh — 拆掉 deepseek-mcp。

set -euo pipefail

echo "▶ deepseek-mcp uninstaller"

# 1. 从 Claude Code 移除注册
echo "[1/4] 从 Claude Code 移除 mcp..."
if command -v claude >/dev/null 2>&1; then
    claude mcp remove deepseek -s user 2>/dev/null || echo "       未注册或已移除"
else
    echo "       claude CLI 不在 PATH，跳过"
fi

# 2. 删 skill / command 链接（或目录 —— 部署时可能是 symlink 也可能是 cp）
echo "[2/4] 删 skill / command 部署..."
rm -rf "$HOME/.claude/skills/delegate-to-deepseek"
rm -f "$HOME/.claude/commands/ds.md"

# 3. 提示用户决定是否删配置
echo "[3/4] 配置目录:"
if [ -d "$HOME/.deepseek-mcp" ]; then
    echo "       $HOME/.deepseek-mcp 仍存在（含 API key 和日志）"
    echo "       要删请手动: rm -rf $HOME/.deepseek-mcp"
fi

# 4. 遍历所有可能的 shell rc，提示用户清 pure alias
echo "[4/4] shell rc 里的 pure alias:"
FOUND_RC=0
for rc in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.bash_profile"; do
    if [ -f "$rc" ] && grep -q "===== deepseek-orchestrator:" "$rc" 2>/dev/null; then
        echo "       $rc 里仍有，请手动删除以下段落:"
        echo "         ===== deepseek-orchestrator: 切换 alias ====="
        echo "         alias pure='DEEPSEEK_MODE=off claude'"
        echo "         ===== end deepseek-orchestrator ====="
        FOUND_RC=1
    fi
done
[ "$FOUND_RC" = "0" ] && echo "       未发现，已清理"

echo ""
echo "✅ 主战场 claude 完全不受影响"
echo "   项目目录 $(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd) 本身没删，你可以保留代码"
