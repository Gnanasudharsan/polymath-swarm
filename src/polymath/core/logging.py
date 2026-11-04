"""structlog configuration: human-readable in dev, JSON lines in prod."""

from __future__ import annotations

import logging
import sys

import structlog
from opentelemetry import trace


def _add_trace_context(
    _logger: object, _method: str, event_dict: structlog.typing.EventDict
) -> structlog.typing.EventDict:
    """Attach the active OpenTelemetry trace/span ids so logs correlate with traces."""
    ctx = trace.get_current_span().get_span_context()
    if ctx.is_valid:
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict


def configure_logging(level: str = "INFO", *, json: bool = False) -> None:
    log_level = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stderr, level=log_level, force=True)
    # LiteLLM is chatty at INFO; keep it to warnings unless we're debugging.
    logging.getLogger("LiteLLM").setLevel(max(log_level, logging.WARNING))

    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _add_trace_context,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        # Resolve sys.stderr lazily so redirected/replaced streams (e.g. test runners) work.
        logger_factory=lambda *_: structlog.PrintLogger(sys.stderr),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str | None = None) -> structlog.typing.FilteringBoundLogger:
    logger: structlog.typing.FilteringBoundLogger = structlog.get_logger(name)
    return logger
