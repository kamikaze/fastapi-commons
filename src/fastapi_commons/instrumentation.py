import os

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

OTLP_GRPC_ENDPOINT = os.environ.get('OTLP_GRPC_ENDPOINT', 'http://tempo:4317')


def setup_opentelemetry(
    app: FastAPI,
    app_name: str,
    *,
    log_correlation: bool = True,
) -> None:
    if not OTLP_GRPC_ENDPOINT:
        return
    # Setting OpenTelemetry
    resource = Resource.create(attributes={'service.name': app_name, 'compose_service': app_name})

    # Set the tracer provider
    tracer = TracerProvider(resource=resource)
    trace.set_tracer_provider(tracer)

    tracer.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=OTLP_GRPC_ENDPOINT)))

    if log_correlation:
        LoggingInstrumentor().instrument(set_logging_format=True)

    FastAPIInstrumentor.instrument_app(app, tracer_provider=tracer)
