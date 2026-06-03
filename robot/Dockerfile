FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
ENV UV_EXTRA_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ENV UV_HTTP_TIMEOUT=1200
ENV UV_CONCURRENT_DOWNLOADS=1
ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
ENV PIP_EXTRA_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ENV PIP_TIMEOUT=1200

WORKDIR /app/robot
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
ENV PATH="/app/.venv/bin:$PATH"

COPY ./robot/pyproject.toml /app/robot/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-install-project

COPY ./robot /app/robot
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync

CMD ["python", "-m", "termman_robot"]
