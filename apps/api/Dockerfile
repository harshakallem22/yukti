# syntax=docker/dockerfile:1
FROM python:3.12-slim

# git is a runtime dependency, not a build one: workspace provisioning clones the
# repository and the diff tools shell out to the git binary.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY core ./core
COPY agent ./agent
COPY tools ./tools
COPY guardrails ./guardrails
COPY sandbox ./sandbox
COPY evals ./evals
COPY yukti_mcp ./yukti_mcp
COPY apps/api ./apps/api
COPY benchmarks ./benchmarks

RUN pip install --no-cache-dir -e ".[postgres]"

# Runs execute agent-selected test commands. Even with the command allowlist and
# path jail above it, the container process should not be root.
RUN useradd --create-home --uid 10001 yukti \
    && mkdir -p /app/workspaces \
    && chown -R yukti:yukti /app
USER yukti

ENV PYTHONUNBUFFERED=1 \
    YUKTI_WORKSPACE_ROOT=/app/workspaces \
    YUKTI_API_HOST=0.0.0.0 \
    YUKTI_API_PORT=8010

EXPOSE 8010
CMD ["uvicorn", "apps.api.app.main:app", "--host", "0.0.0.0", "--port", "8010"]
