"""SSE endpoint for live dashboard updates."""

import json
import logging

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from app.core.broadcaster import broadcaster

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["sse"])


@router.get("/sse")
async def sse_endpoint():
    async def event_generator():
        yield {"event": "connected", "data": '{"status": "connected"}'}
        async for message in broadcaster.subscribe():
            if message is None:
                yield {"comment": "heartbeat"}
                continue
            data = message.get("data", {})
            yield {
                "event": message.get("event", "message"),
                "data": json.dumps(data) if isinstance(data, dict) else str(data),
            }

    return EventSourceResponse(event_generator())
