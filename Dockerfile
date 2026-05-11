# MCP server for deepseek-as-subagent
# Used by Glama (https://glama.ai/mcp/servers) for automated introspection checks.
# Local users should still use install.sh — this image runs the bare MCP server
# without skill / slash-command / Claude registration.

FROM python:3.12-slim

WORKDIR /app

# 缓存层：先 copy 元数据，下次代码改动时跳过装依赖
COPY pyproject.toml ./
COPY README.md ./
COPY LICENSE ./
COPY src ./src

# --no-cache-dir 减小镜像；只装运行时依赖（pyproject 已锁版本）
RUN pip install --no-cache-dir -e .

# MCP server 走 stdio，无端口暴露
# 没 DEEPSEEK_API_KEY 时 ping 返回 NOT_CONFIGURED 而非 crash —— 适合 Glama
# introspection（仅启动 + 列工具，不实际派工）
ENTRYPOINT ["deepseek-mcp"]
