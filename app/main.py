"""amp-watchdog — FastAPI entry point."""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI

from app.checkers import load_checkers
from app.clients.amp import close_amp_client
from app.config import settings
from app.database import init_db
from app.notifiers import load_notifiers
from app.routers import api_router, pages_router, partials_router, sse_router
from app.services.scheduler import scheduler_loop

log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
logging.basicConfig(
    level=log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

_scheduler_task: Optional[asyncio.Task] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler_task

    logger.info("Starting amp-watchdog...")
    await init_db()
    load_checkers()
    load_notifiers()
    _scheduler_task = asyncio.create_task(scheduler_loop())
    logger.info("amp-watchdog ready")

    yield

    logger.info("Shutting down amp-watchdog...")
    if _scheduler_task:
        _scheduler_task.cancel()
        try:
            await _scheduler_task
        except asyncio.CancelledError:
            pass
    await close_amp_client()
    logger.info("Shutdown complete")


app = FastAPI(
    title="amp-watchdog",
    description="Watchlist status monitor for CubeCoders AMP instances",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(api_router)
app.include_router(partials_router)
app.include_router(sse_router)
app.include_router(pages_router)
