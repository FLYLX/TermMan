FROM python:3.10-slim

ARG USE_CHINA_MIRRORS=true

ENV PYTHONUNBUFFERED=1

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/

# Compile bytecode
ENV UV_COMPILE_BYTECODE=1

# uv Cache
ENV UV_LINK_MODE=copy

ENV UV_HTTP_TIMEOUT=1200
ENV UV_CONCURRENT_DOWNLOADS=1
ENV PIP_TIMEOUT=1200

WORKDIR /app/

# Place executables in the environment at the front of the path
ENV PATH="/app/.venv/bin:$PATH"

# Install dependencies
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    if [ "$USE_CHINA_MIRRORS" = "true" ]; then \
        export UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple; \
        export UV_EXTRA_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple; \
        export PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple; \
        export PIP_EXTRA_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple; \
    fi \
    && uv sync --no-install-workspace --no-dev

# Copy daemon code
COPY ./src /app/src
COPY ./test*.py /app/

# Sync the project
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    if [ "$USE_CHINA_MIRRORS" = "true" ]; then \
        export UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple; \
        export UV_EXTRA_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple; \
        export PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple; \
        export PIP_EXTRA_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple; \
    fi \
    && uv sync --no-dev

# 设置环境变量
ENV HOST=0.0.0.0
ENV PORT=9000
ENV API_KEY=TermPaws_daemon_secret_key_2024
ENV TERMINAL_SHELL=/bin/sh
ENV TERMINAL_ENCODING=utf-8
ENV WORKDIR=/app/src/workdir
ENV LOG_DIR=/app/log
ENV DATA_DIR=/app/src/data

# 确保必要的目录存在
RUN mkdir -p /app/src/workdir /app/log /app/src/data/terminals /app/src/data/logs

# 暴露端口
EXPOSE 9000
# server port
EXPOSE 43906

# Install tini for proper PID 1 zombie reaping
RUN apt-get update && apt-get install -y --no-install-recommends tini && rm -rf /var/lib/apt/lists/*

# 设置启动命令
ENTRYPOINT ["tini", "--"]
CMD ["python", "src/main.py"]

# 日志目录说明：
# 容器内日志路径：/app/log
# 建议启动时映射到主机：-v e:/dev/TermPaws/dev/TermPaws/daemon/log:/app/log
