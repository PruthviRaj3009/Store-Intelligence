"""FastAPI entrypoint for the Store Intelligence API."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import Depends, FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session as DBSession

from app import anomalies as anomalies_mod
from app import funnel as funnel_mod
from app import health as health_mod
from app import metrics as metrics_mod
from app.config import settings
from app.db import DatabaseUnavailable, SessionLocal, get_db, init_db
from app.ingestion import ingest_events, ingest_jsonl
from app.logging_mw import (AccessLogMiddleware, configure_logging,
                            event_count_ctx, trace_id_ctx)
from app.models import IngestBatch
from app.pos import load_pos

log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    init_db()
    # seed POS + auto-ingest any prepared events so /metrics works on cold start
    with SessionLocal() as db:
        try:
            n_pos = load_pos(db)
            log.info('{"event":"startup_pos_loaded","count":%d}', n_pos)
            if settings.AUTO_INGEST_ON_STARTUP:
                res = ingest_jsonl(db, settings.EVENTS_PATH)
                log.info('{"event":"startup_events_ingested","accepted":%d,"duplicates":%d}',
                         res.accepted, res.duplicates)
        except SQLAlchemyError as exc:  # don't let seeding crash startup
            log.warning('{"event":"startup_seed_failed","error":%r}', str(exc))
    yield


app = FastAPI(title="Store Intelligence API", version="1.0.0", lifespan=lifespan)
app.add_middleware(AccessLogMiddleware)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


# ----------------------------- error handling -----------------------------

def _error_body(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "trace_id": trace_id_ctx.get()}},
    )


@app.exception_handler(DatabaseUnavailable)
async def _db_unavailable(request: Request, exc: DatabaseUnavailable):
    return _error_body("DATABASE_UNAVAILABLE", "The database is currently unavailable.", 503)


@app.exception_handler(OperationalError)
async def _op_error(request: Request, exc: OperationalError):
    return _error_body("DATABASE_UNAVAILABLE", "The database is currently unavailable.", 503)


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    # no raw stack traces in responses; full detail goes to logs
    log.exception("unhandled error")
    return _error_body("INTERNAL_ERROR", "An unexpected error occurred.", 500)


# ----------------------------- routes -----------------------------

@app.get("/health")
def health(db: DBSession = Depends(get_db)):
    return health_mod.compute_health(db)


@app.post("/events/ingest")
def ingest(batch: IngestBatch, db: DBSession = Depends(get_db)):
    event_count_ctx.set(len(batch.events))
    if len(batch.events) > settings.INGEST_MAX_BATCH:
        return _error_body(
            "BATCH_TOO_LARGE",
            f"Batch of {len(batch.events)} exceeds max {settings.INGEST_MAX_BATCH}.",
            413,
        )
    # validate at the item level for partial success: re-dump to dicts
    raw = [e.model_dump(mode="json") for e in batch.events]
    result = ingest_events(db, raw)
    return result.model_dump()


@app.post("/events/ingest/raw")
async def ingest_raw(request: Request, db: DBSession = Depends(get_db)):
    """Lenient variant: accepts arbitrary JSON list so malformed events can be
    partially accepted instead of failing whole-batch validation."""
    payload = await request.json()
    events = payload.get("events", payload) if isinstance(payload, dict) else payload
    event_count_ctx.set(len(events))
    result = ingest_events(db, events)
    return result.model_dump()


@app.get("/stores/{store_id}/metrics")
def metrics(store_id: str, date: str | None = Query(None), db: DBSession = Depends(get_db)):
    return metrics_mod.compute_metrics(db, store_id, date)


@app.get("/stores/{store_id}/funnel")
def funnel(store_id: str, date: str | None = Query(None), db: DBSession = Depends(get_db)):
    return funnel_mod.compute_funnel(db, store_id, date)


@app.get("/stores/{store_id}/heatmap")
def heatmap(store_id: str, date: str | None = Query(None), db: DBSession = Depends(get_db)):
    return metrics_mod.compute_heatmap(db, store_id, date)


@app.get("/stores/{store_id}/anomalies")
def anomalies(store_id: str, date: str | None = Query(None), db: DBSession = Depends(get_db)):
    return anomalies_mod.compute_anomalies(db, store_id, date)


_DASHBOARD = Path(__file__).resolve().parents[1] / "dashboard" / "index.html"


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    if _DASHBOARD.exists():
        return _DASHBOARD.read_text(encoding="utf-8")
    return "<h1>dashboard/index.html not found</h1>"


@app.get("/")
def root():
    return {"service": "store-intelligence", "version": "1.0.0",
            "docs": "/docs", "dashboard": "/dashboard"}
