# ABOUTME: OpenTelemetry setup for reading-tracker — tracer and meter singletons.
# ABOUTME: Configure once at app startup; instrument via module-attribute access (avoid stale-binding bugs).

"""
OpenTelemetry instrumentation for the reading-tracker multi-agent system.

Three things we instrument:
  1. Per-agent token usage  — total_tokens per agent per turn (gauge + histogram)
  2. Tool call latency      — wall-clock time per tool call (histogram, by tool name)
  3. Router message events  — which agent was selected, turn count (counter + span)

We also bridge stdlib logging into OTel: configure() attaches a LoggingHandler to the
root logger so log records export over OTLP and carry the active span's trace/span IDs.

Usage: import app.otel as otel; otel.tracer.start_as_current_span(...)
Module-attribute access avoids the stale-binding bug where `from app.otel import tracer`
captures a no-op reference before configure() runs.
"""

from __future__ import annotations

import os
import logging
from contextlib import contextmanager
from typing import Generator

from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

logger = logging.getLogger(__name__)

OTLP_HTTP_ENDPOINT = os.getenv("OTLP_HTTP_ENDPOINT", "http://127.0.0.1:4318")
SERVICE_NAME = "reading-tracker"

_configured = False

# Module-level singletons — resolve via module attribute, not import-time binding.
tracer: trace.Tracer = trace.get_tracer(SERVICE_NAME)
meter: metrics.Meter = metrics.get_meter(SERVICE_NAME)

# Pre-built instruments — created after configure() so they bind to the real SDK.
_agent_tokens: metrics.Histogram | None = None
_tool_latency: metrics.Histogram | None = None
_router_messages: metrics.Counter | None = None


def configure() -> None:
    """Wire up the real OTLP exporters. Safe to call multiple times (no-ops after first)."""
    global _configured, tracer, meter, _agent_tokens, _tool_latency, _router_messages

    if _configured:
        return

    resource = Resource.create({"service.name": SERVICE_NAME})

    # Traces → OTLP HTTP
    trace_provider = TracerProvider(resource=resource)
    trace_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{OTLP_HTTP_ENDPOINT}/v1/traces"))
    )
    trace.set_tracer_provider(trace_provider)
    tracer = trace.get_tracer(SERVICE_NAME)

    # Metrics → OTLP HTTP (push every 5s so we see data quickly during experiments)
    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=f"{OTLP_HTTP_ENDPOINT}/v1/metrics"),
        export_interval_millis=5_000,
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)
    meter = metrics.get_meter(SERVICE_NAME)

    # Pre-build instruments
    _agent_tokens = meter.create_histogram(
        "agent.tokens",
        unit="tokens",
        description="Total tokens consumed per agent per turn",
    )
    _tool_latency = meter.create_histogram(
        "tool.latency",
        unit="ms",
        description="Wall-clock time per tool call, by tool name",
    )
    _router_messages = meter.create_counter(
        "router.messages",
        unit="messages",
        description="Inter-agent messages routed, by from/to agent pair",
    )

    # Logs → OTLP HTTP — bridge stdlib logging into OTel so the logs sink fills and
    # log records carry the active span's trace/span IDs for correlation.
    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=f"{OTLP_HTTP_ENDPOINT}/v1/logs"))
    )
    set_logger_provider(logger_provider)
    root_logger = logging.getLogger()
    root_logger.addHandler(LoggingHandler(level=logging.INFO, logger_provider=logger_provider))
    # Root logger defaults to WARNING, which would gate INFO records before they reach the
    # handler. Lower the threshold so app INFO logs actually flow through the bridge.
    if root_logger.level == logging.NOTSET or root_logger.level > logging.INFO:
        root_logger.setLevel(logging.INFO)

    _configured = True
    logger.info("OTel configured — exporting to %s", OTLP_HTTP_ENDPOINT)


def record_agent_tokens(agent: str, total_tokens: int, duration_ms: int) -> None:
    """Record token usage for a completed agent turn."""
    if _agent_tokens is None:
        return
    _agent_tokens.record(total_tokens, {"agent": agent, "duration_ms": str(duration_ms)})


def record_tool_latency(tool_name: str, duration_ms: float) -> None:
    """Record wall-clock time for a single tool call."""
    if _tool_latency is None:
        return
    _tool_latency.record(duration_ms, {"tool": tool_name})


def record_router_message(from_agent: str, to_agent: str) -> None:
    """Increment the router message counter for this from→to pair."""
    if _router_messages is None:
        return
    _router_messages.add(1, {"from": from_agent, "to": to_agent})


@contextmanager
def span(name: str, **attrs: str) -> Generator[trace.Span, None, None]:
    """Convenience context manager for creating a span with string attributes."""
    with tracer.start_as_current_span(name) as s:
        for k, v in attrs.items():
            s.set_attribute(k, v)
        yield s
