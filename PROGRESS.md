# Progress

## Phase 0 — Bootstrap (2026-11-04)

**Shipped**
- GitHub repo, uv project (`src/polymath`), Python 3.12, pinned dependencies, `uv.lock`
- ruff (lint + format), mypy strict on `src/`, pytest with `integration` / `live` markers (skipped by default)
- pre-commit: whitespace/EOF/YAML/TOML checks, private-key + gitleaks secret scanning, ruff, mypy
- GitHub Actions CI: gate job (ruff, format, mypy, unit tests) + integration job (docker compose)
- `docker-compose.yml`: Postgres 16 + pgvector 0.8.7 (host :5544), Redis 7.4 (:6379), healthchecks
- Docs: README with Mermaid architecture, `docs/architecture.md`, ADR-0001 (stack), `CLAUDE.md`
- Typer CLI skeleton (`polymath version`)

**Metrics**: 2 unit tests, 2 integration tests — all passing.

**Known gaps**: no runtime logic yet (Phase 1). Langfuse, sandbox, Lean and API services not yet in compose.
