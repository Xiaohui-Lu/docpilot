"""Structured JSON logging, request IDs and Prometheus metrics."""

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar

from fastapi import Request
from prometheus_client import Counter, Gauge, Histogram
from starlette.middleware.base import BaseHTTPMiddleware

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

HTTP_REQUESTS = Counter("docpilot_http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_LATENCY = Histogram(
    "docpilot_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
JOBS_PROCESSED = Counter("docpilot_jobs_processed_total", "Background jobs by outcome", ["kind", "outcome"])
JOB_DURATION = Histogram(
    "docpilot_job_duration_seconds",
    "Background job duration",
    ["kind"],
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60, 120),
)
JOB_QUEUE_DEPTH = Gauge("docpilot_job_queue_depth", "Jobs waiting to run")
LLM_REQUESTS = Counter("docpilot_llm_requests_total", "LLM calls", ["provider", "operation", "outcome"])
LLM_TOKENS = Counter("docpilot_llm_tokens_total", "LLM tokens", ["provider", "direction"])
LLM_COST = Counter("docpilot_llm_cost_usd_total", "Estimated LLM spend in USD", ["provider"])
LLM_LATENCY = Histogram(
    "docpilot_llm_request_duration_seconds",
    "LLM call latency",
    ["provider", "operation"],
    buckets=(0.05, 0.25, 0.5, 1, 2, 5, 10, 20, 40, 80),
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        extra = getattr(record, "extra_fields", None)
        if extra:
            entry.update(extra)
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    logging.getLogger("uvicorn.access").disabled = True  # replaced by our access log below


def log_extra(**fields) -> dict:
    return {"extra_fields": fields}


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a request ID, records metrics and writes one structured access-log line per request."""

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["x-request-id"] = rid
            return response
        finally:
            elapsed = time.perf_counter() - start
            route = request.scope.get("route")
            route_path = getattr(route, "path", "unmatched")
            if route_path != "/metrics":
                HTTP_REQUESTS.labels(request.method, route_path, str(status)).inc()
                HTTP_LATENCY.labels(request.method, route_path).observe(elapsed)
                logging.getLogger("docpilot.access").info(
                    "request",
                    extra=log_extra(
                        method=request.method,
                        path=request.url.path,
                        status=status,
                        duration_ms=round(elapsed * 1000, 1),
                    ),
                )
            request_id_var.reset(token)
