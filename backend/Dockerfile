FROM python:3.11-slim

ARG USE_CHINA_MIRRORS=true

ENV PYTHONUNBUFFERED=1

# Install uv
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#installing-uv
COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/

# Compile bytecode
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#compiling-bytecode
ENV UV_COMPILE_BYTECODE=1

# uv Cache
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#caching
ENV UV_LINK_MODE=copy

ENV UV_HTTP_TIMEOUT=1200
ENV UV_CONCURRENT_DOWNLOADS=1
ENV UV_TORCH_BACKEND=cpu
ENV PIP_TIMEOUT=1200

WORKDIR /app/

# Place executables in the environment at the front of the path
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#using-the-environment
ENV PATH="/app/.venv/bin:$PATH"

# Install dependencies
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#intermediate-layers
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=/tmp/uv.lock \
    --mount=type=bind,source=pyproject.toml,target=/tmp/pyproject.toml \
    cp /tmp/uv.lock uv.lock \
    && cp /tmp/pyproject.toml pyproject.toml \
    && if [ "$USE_CHINA_MIRRORS" = "true" ]; then \
        export UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple; \
        export UV_EXTRA_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple; \
        export PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple; \
        export PIP_EXTRA_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple; \
        export HF_ENDPOINT=https://hf-mirror.com; \
    else \
        sed -i \
            -e 's|https://pypi.tuna.tsinghua.edu.cn/simple|https://pypi.org/simple|g' \
            -e 's|https://pypi.tuna.tsinghua.edu.cn/packages|https://files.pythonhosted.org/packages|g' \
            -e 's|https://mirrors.aliyun.com/pypi/simple|https://pypi.org/simple|g' \
            -e 's|https://mirror.sjtu.edu.cn/pytorch-wheels/cpu|https://download.pytorch.org/whl/cpu|g' \
            uv.lock pyproject.toml; \
    fi \
    && uv sync --frozen --no-install-workspace --package app

COPY ./backend/scripts /app/backend/scripts

COPY ./backend/pyproject.toml ./backend/alembic.ini /app/backend/

COPY ./backend/app /app/backend/app

COPY ./backend/skills /app/backend/skills

COPY ./backend/mcp_servers.json /app/mcp_servers.json

# Sync the project
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#intermediate-layers
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=/tmp/uv.lock \
    --mount=type=bind,source=pyproject.toml,target=/tmp/pyproject.toml \
    cp /tmp/uv.lock uv.lock \
    && cp /tmp/pyproject.toml pyproject.toml \
    && if [ "$USE_CHINA_MIRRORS" = "true" ]; then \
        export UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple; \
        export UV_EXTRA_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple; \
        export PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple; \
        export PIP_EXTRA_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple; \
        export HF_ENDPOINT=https://hf-mirror.com; \
    else \
        sed -i \
            -e 's|https://pypi.tuna.tsinghua.edu.cn/simple|https://pypi.org/simple|g' \
            -e 's|https://pypi.tuna.tsinghua.edu.cn/packages|https://files.pythonhosted.org/packages|g' \
            -e 's|https://mirrors.aliyun.com/pypi/simple|https://pypi.org/simple|g' \
            -e 's|https://mirror.sjtu.edu.cn/pytorch-wheels/cpu|https://download.pytorch.org/whl/cpu|g' \
            uv.lock pyproject.toml backend/pyproject.toml; \
    fi \
    && uv sync --frozen --package app

# Pre-download sentence-transformers model during build
RUN if [ "$USE_CHINA_MIRRORS" = "true" ]; then \
        export HF_ENDPOINT=https://hf-mirror.com; \
    fi \
    && python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')" || \
    echo "Warning: Failed to download model, will download at runtime"

WORKDIR /app/backend/

CMD ["bash", "scripts/run_backend.sh"]
