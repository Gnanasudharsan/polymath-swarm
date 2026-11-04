"""OpenTelemetry setup. Spans follow the GenAI semantic conventions where they apply."""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
)

from polymath import __version__

TRACER_NAME = "polymath"

_provider: TracerProvider | None = None


def setup_tracing(
    *,
    service_name: str = "polymath",
    otlp_endpoint: str | None = None,
    console: bool = False,
    exporter: SpanExporter | None = None,
) -> TracerProvider:
    """Install a global tracer provider (idempotent: later calls return the first provider).

    ``exporter`` is for tests (e.g. an in-memory exporter); it is wired synchronously.
    """
    global _provider
    if _provider is not None:
        return _provider

    provider = TracerProvider(
        resource=Resource.create({"service.name": service_name, "service.version": __version__})
    )
    if exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    if otlp_endpoint:
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))
    if console:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    _provider = provider
    return provider


def shutdown_tracing() -> None:
    if _provider is not None:
        _provider.shutdown()


def get_tracer() -> trace.Tracer:
    return trace.get_tracer(TRACER_NAME, __version__)
