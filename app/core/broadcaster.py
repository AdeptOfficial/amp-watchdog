"""SSE broadcasting for live dashboard updates (status-tracker pattern)."""

import asyncio
import logging
from typing import AsyncGenerator, Optional

logger = logging.getLogger(__name__)

SSE_HEARTBEAT_INTERVAL = 15


class Broadcaster:
    def __init__(self):
        self._clients: list[asyncio.Queue] = []

    async def subscribe(self) -> AsyncGenerator[Optional[dict], None]:
        """Yield {'event': ..., 'data': ...} dicts, or None for heartbeats."""
        queue: asyncio.Queue = asyncio.Queue()
        self._clients.append(queue)
        logger.info("SSE client connected (total: %d)", len(self._clients))
        try:
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=SSE_HEARTBEAT_INTERVAL)
                    yield data
                except asyncio.TimeoutError:
                    yield None
        except asyncio.CancelledError:
            pass
        finally:
            self._clients.remove(queue)
            logger.info("SSE client disconnected (total: %d)", len(self._clients))

    async def broadcast(self, event_type: str, data: dict) -> None:
        message = {"event": event_type, "data": data}
        for queue in self._clients:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                logger.warning("SSE client queue full, dropping message")

    @property
    def client_count(self) -> int:
        return len(self._clients)


broadcaster = Broadcaster()
