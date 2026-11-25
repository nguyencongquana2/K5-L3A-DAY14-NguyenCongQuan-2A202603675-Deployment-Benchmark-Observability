"""
Production AI Agent — Part 6 Final Project
"""
import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import redis_healthy
from utils.mock_llm import ask as llm_ask


class JsonFormatter(logging.Formatter):
    """Đảm bảo mọi dòng log của app là một JSON object hợp lệ."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "lvl": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        return json.dumps(payload, ensure_ascii=False)


handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
logger = logging.getLogger("agent")

_is_ready = False
_in_flight = 0


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _is_ready
    _is_ready = True
    logger.info(json.dumps({"event": "startup", "env": settings.environment, "port": settings.port}))
    yield
    _is_ready = False
    logger.info(json.dumps({"event": "shutdown_start", "in_flight": _in_flight}))
    deadline = time.time() + 8.0
    while _in_flight > 0 and time.time() < deadline:
        await asyncio.sleep(0.05)
    logger.info(json.dumps({"event": "shutdown_complete", "in_flight": _in_flight}))


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


@app.middleware("http")
async def track_and_log_requests(request: Request, call_next):
    global _in_flight
    _in_flight += 1
    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        _in_flight -= 1
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.info(
            json.dumps(
                {
                    "event": "request",
                    "method": request.method,
                    "path": request.url.path,
                    "status": status_code,
                    "ms": elapsed_ms,
                }
            )
        )


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = None


@app.get("/health")
def health():
    """Liveness probe — luôn trả 200 khi process còn chạy."""
    return {"status": "ok"}


@app.get("/ready")
def ready():
    """Readiness probe — 200 khi sẵn sàng, 503 khi Redis không kết nối được."""
    if not _is_ready or not redis_healthy():
        return JSONResponse(status_code=503, content={"status": "not ready"})
    return {"status": "ready"}


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)
    check_budget()
    answer = llm_ask(body.question)
    in_tokens = max(1, len(body.question.split()))
    out_tokens = max(1, len(answer.split()))
    record_cost(in_tokens, out_tokens)
    return {"question": body.question, "answer": answer}
