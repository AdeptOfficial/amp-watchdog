"""Async client for the AMP (CubeCoders) ADS HTTP API.

API shape (verified live against AMP 2.8.0.8):
- Every call is POST /API/<Module>/<Method> with a JSON body.
- Core/Login body: {username, password, token: "", rememberMe: false}
  -> response carries the session as `sessionID` (capital ID).
- Authenticated calls carry `SESSIONID` in the body.
- Auth/permission failures come back as HTTP 200 with a JSON body like
  {"Title": "Unauthorized Access", "Message": ...} — detect by shape,
  then re-login and retry exactly once (sessions expire server-side).
"""

import asyncio
import logging
from dataclasses import dataclass

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class AMPError(Exception):
    pass


class AMPConnectionError(AMPError):
    """AMP unreachable / network problem. Not evidence that instances are down."""


class AMPAuthError(AMPError):
    """Login rejected or session could not be established."""


@dataclass
class AMPInstance:
    instance_id: str
    instance_name: str
    friendly_name: str
    app_state: int | None
    running: bool
    module: str = ""


class AMPClient:
    def __init__(
        self,
        base_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._username = username if username is not None else settings.AMP_USERNAME
        self._password = password if password is not None else settings.AMP_PASSWORD
        self._client = httpx.AsyncClient(
            base_url=(base_url or settings.AMP_BASE_URL),
            timeout=15,
            headers={"Accept": "application/json"},
            transport=transport,
        )
        self._session_id: str | None = None
        self._login_lock = asyncio.Lock()

    async def close(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _looks_unauthorized(data) -> bool:
        return isinstance(data, dict) and data.get("Title") == "Unauthorized Access"

    async def _post(self, endpoint: str, body: dict) -> dict | list:
        try:
            resp = await self._client.post(f"/API/{endpoint}", json=body)
        except httpx.HTTPError as e:
            raise AMPConnectionError(f"AMP unreachable: {e!r}") from e
        try:
            return resp.json()
        except ValueError as e:
            raise AMPConnectionError(f"AMP returned non-JSON (HTTP {resp.status_code})") from e

    async def _ensure_login(self) -> None:
        """Login once even under concurrent callers (double-checked lock)."""
        if self._session_id is not None:
            return
        async with self._login_lock:
            if self._session_id is not None:
                return
            data = await self._post(
                "Core/Login",
                {
                    "username": self._username,
                    "password": self._password,
                    "token": "",
                    "rememberMe": False,
                },
            )
            if not isinstance(data, dict) or not data.get("success") or not data.get("sessionID"):
                reason = data.get("resultReason", "") if isinstance(data, dict) else ""
                raise AMPAuthError(f"AMP login failed: {reason or 'success=false'}")
            self._session_id = data["sessionID"]
            logger.info("AMP login OK (user %s)", self._username)

    async def call(self, endpoint: str, **params) -> dict | list:
        """Authenticated API call with one re-login retry on session expiry."""
        for attempt in (1, 2):
            await self._ensure_login()
            data = await self._post(endpoint, {**params, "SESSIONID": self._session_id})
            if self._looks_unauthorized(data):
                logger.info("AMP session rejected on %s (attempt %d), re-logging in", endpoint, attempt)
                self._session_id = None
                continue
            return data
        raise AMPAuthError(f"AMP still unauthorized after re-login: {endpoint}")

    async def get_instances(self) -> list[AMPInstance]:
        data = await self.call("ADSModule/GetInstances")
        targets = data.get("result", data) if isinstance(data, dict) else data
        if not isinstance(targets, list):
            targets = [targets]
        instances: list[AMPInstance] = []
        for target in targets:
            if not isinstance(target, dict):
                continue
            for inst in target.get("AvailableInstances") or []:
                raw_state = inst.get("AppState")
                try:
                    app_state = int(raw_state)
                except (TypeError, ValueError):
                    app_state = None
                instances.append(
                    AMPInstance(
                        instance_id=str(inst.get("InstanceID", "")),
                        instance_name=inst.get("InstanceName", ""),
                        friendly_name=inst.get("FriendlyName") or inst.get("InstanceName", ""),
                        app_state=app_state,
                        running=bool(inst.get("Running")),
                        module=inst.get("Module") or "",
                    )
                )
        return instances


_client: AMPClient | None = None


def get_amp_client() -> AMPClient:
    global _client
    if _client is None:
        _client = AMPClient()
    return _client


async def close_amp_client() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None
