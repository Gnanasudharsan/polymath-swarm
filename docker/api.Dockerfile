# Polymath API (FastAPI + SSE + A2A) and CLI.
# Build:  docker build -f docker/api.Dockerfile -t polymath-api .
# Needs the Docker socket at run time to start sandbox / Lean containers (see docs/security.md).
FROM ghcr.io/astral-sh/uv:0.13.7 AS uv
FROM docker:29.9.3-cli AS dockercli

FROM python:3.12.16-slim
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 POLYMATH_NO_DOTENV=1 LITELLM_MODE=PRODUCTION \
    PATH="/app/.venv/bin:${PATH}"
COPY --from=uv /uv /usr/local/bin/uv
COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker

WORKDIR /app
# Dependencies first (cached layer), then the project.
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY evals/datasets/retrieval ./evals/datasets/retrieval
COPY evals/datasets/research_qa ./evals/datasets/research_qa
RUN uv sync --frozen --no-dev

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=6 \
  CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8000/health'); sys.exit(0)"
ENTRYPOINT ["polymath"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
