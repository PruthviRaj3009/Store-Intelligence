"""Structured JSON request logging (Part C: observability).

Every request emits one JSON line with: trace_id, store_id, endpoint,
latency_ms, event_count (ingest only), status_code. A trace_id is generated
per request and returned in the `X-Trace-Id` header so logs correlate with
client reports.
"""
from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.config import settings

trace_id_ctx: ContextVar[str] = ContextVar("trace_id", default="-")
# ingest handler stashes the batch size here so the access log can include it
event_count_ctx: ContextVar[int | None] = ContextVar("event_count", default=None)


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(settings.LOG_LEVEL)


def _log(payload: dict) -> None:
    logging.getLogger("access").info(json.dumps(payload, default=str))


def _store_id_from_path(request: Request) -> str | None:
    # /stores/{id}/... -> id
    parts = request.url.path.strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "stores":
        return parts[1]
    return None


class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        trace_id = request.headers.get("X-Trace-Id") or uuid.uuid4().hex[:16]
        trace_id_ctx.set(trace_id)
        event_count_ctx.set(None)
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            _log(
                {
                    "trace_id": trace_id,
                    "store_id": _store_id_from_path(request),
                    "endpoint": request.url.path,
                    "method": request.method,
                    "status_code": status_code,
                    "latency_ms": latency_ms,
                    "event_count": event_count_ctx.get(),
                }
            )
            # attach the trace id to the response for client-side correlation
            if "response" in locals():
                response.headers["X-Trace-Id"] = trace_id
