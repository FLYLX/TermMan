FROM python:3.10

ENV PYTHONUNBUFFERED=1

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/

# Compile bytecode
ENV UV_COMPILE_BYTECODE=1

# uv Cache
ENV UV_LINK_MODE=copy

# China mirror configuration
ENV UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
ENV UV_EXTRA_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ENV UV_HTTP_TIMEOUT=1200
ENV UV_CONCURRENT_DOWNLOADS=1
ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
ENV PIP_EXTRA_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ENV PIP_TIMEOUT=1200

WORKDIR /app/

# Place executables in the environment at the front of the path
ENV PATH="/app/.venv/bin:$PATH"

# Install dependencies
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --no-install-workspace

# Copy daemon code
COPY ./src /app/src
COPY ./test*.py /app/

# Sync the project
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync

# 设置环境变量
ENV HOST=0.0.0.0
ENV PORT=9000
ENV API_KEY=termman_daemon_secret_key_2024
ENV TERMINAL_SHELL=/bin/sh
ENV TERMINAL_ENCODING=utf-8
ENV WORKDIR=/app/src/workdir
ENV LOG_DIR=/app/log
ENV DATA_DIR=/app/src/data

# 确保必要的目录存在
RUN mkdir -p /app/src/workdir /app/log /app/src/data/terminals /app/src/data/logs

# 暴露端口
EXPOSE 9000

# 设置启动命令
CMD ["python", "src/main.py"]

# 日志目录说明：
# 容器内日志路径：/app/log
# 建议启动时映射到主机：-v e:/dev/TermMan/dev/TermMan/daemon/log:/app/log
