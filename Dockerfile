# syntax=docker/dockerfile:1

# ============================================================
# Stage 1: Builder — resolve dependências com uv (lockfile)
# ============================================================
FROM python:3.13-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Camada de dependências (cacheável — só invalida se o lock mudar)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project

# Instala o pacote do projeto
COPY pyproject.toml uv.lock readme.md ./
COPY marvin_hue/ marvin_hue/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ============================================================
# Stage 2: Runtime — imagem mínima, usuário não-root
# ============================================================
FROM python:3.13-slim-bookworm

# UID/GID 1000 para compatibilidade com bind mounts do host
RUN groupadd -g 1000 appgroup \
    && useradd -u 1000 -g appgroup -m -d /home/appuser appuser

WORKDIR /app

COPY --from=builder --chown=appuser:appgroup /app/.venv .venv
COPY --chown=appuser:appgroup marvin_hue/ marvin_hue/
COPY --chown=appuser:appgroup web/ web/
COPY --chown=appuser:appgroup .res/ .res/
COPY --chown=appuser:appgroup app.py main.py ./

# phue grava o token de registro do bridge em $HOME/.python_hue
ENV PATH="/app/.venv/bin:$PATH" \
    HOME=/home/appuser \
    PYTHONUNBUFFERED=1

RUN mkdir -p /app/logs && chown appuser:appgroup /app/logs

USER appuser

EXPOSE 5081

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "5081"]
