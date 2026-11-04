# ADR-0002: LLM gateway, retries, cost and structured output

- **Status:** Accepted
- **Date:** 2026-11-04

## Context

Every agent needs LLM access with per-role model choice, resilience to provider errors, cost
accounting, hard budget ceilings and typed (Pydantic) outputs, all testable without paid calls.

## Decision

- **One `LLMGateway`** wraps `litellm.acompletion`. Agents never call LiteLLM directly.
- **Role → model map** in `Settings.role_models` (env `POLYMATH_ROLE_MODELS` as JSON). Defaults:
  Opus 5.5 for supervisor/reasoner/formalizer, Sonnet 5.5 for the others; fallbacks
  `gpt-5`, `gemini/gemini-2.5-pro`; degraded model `claude-haiku-5-5`.
- **Retries are ours, not LiteLLM's** (`num_retries=0`): transient errors (rate limit, connection,
  timeout, 5xx) retry with exponential backoff on the same model; anything else (auth, bad request,
  missing key) moves straight to the next model in the chain. This keeps behaviour visible and unit-testable.
- **Timeouts** are enforced twice: LiteLLM's `timeout` and an outer `asyncio.timeout`.
- **`drop_params=True`**: Claude 5.x rejects sampling params such as `temperature`.
- **Cost** comes from LiteLLM's bundled price map via `cost_per_token`; unpriced models cost 0 with a
  warning. Every call is appended to a `CostTracker` and charged to the run's `BudgetTracker`.
- **Budget** is checked *before* each call. Once any dimension passes `degrade_threshold` (0.8), the
  degraded model is put first in the chain.
- **Structured output** is provider-agnostic: the JSON schema goes into a system message, the reply is
  parsed leniently (fences, surrounding prose) and validated; on failure the validation error is fed
  back for up to `max_repairs` repair turns. Native `response_format` remains available on `complete()`.
- **Tracing**: each attempt is an OTel span `llm.complete` with `gen_ai.*` attributes plus
  `polymath.agent.role` and `polymath.cost.usd`.
- **Testing**: the completion function and sleep are injectable; unit tests use a scripted fake;
  the CLI test uses LiteLLM's offline `mock_response`. Live tests (`-m live`) use the cheapest
  available provider and a $0.10 cap.

## Consequences

- Swapping providers or models is configuration only.
- Prompt-embedded schemas cost some input tokens versus native structured output, but behave the
  same across Claude, OpenAI, Gemini and Ollama.
- LiteLLM's price map lags new models; unpriced models show $0 until LiteLLM is upgraded.
