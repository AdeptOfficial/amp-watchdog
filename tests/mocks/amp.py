"""A fake AMP ADS server behind httpx.MockTransport.

Mirrors the real API's quirks: session as `sessionID` (capital ID),
HTTP 200 + {"Title": "Unauthorized Access"} on bad sessions.
"""

import json

import httpx

UNAUTHORIZED = {
    "Title": "Unauthorized Access",
    "Message": "You do not have permission to use this method (ADSModule.GetInstances) at this time. "
               "This method requires the Session.Exists permission.",
    "StackTrace": "   at GSMyAdmin.WebServer...",
}

DEFAULT_INSTANCES = [
    {"InstanceID": "ads-guid", "InstanceName": "ADS01", "FriendlyName": "ADS01",
     "Module": "ADS", "AppState": -1, "Running": True},
    {"InstanceID": "gnomes-guid", "InstanceName": "GracefulGardenGnomes01",
     "FriendlyName": "Graceful Garden Gnomes", "Module": "Minecraft", "AppState": 50, "Running": True},
    {"InstanceID": "lyd-guid", "InstanceName": "LOCKYOURDOOR01",
     "FriendlyName": "LOCK YOUR DOOR", "Module": "Minecraft", "AppState": 50, "Running": True},
    {"InstanceID": "tsu-guid", "InstanceName": "tsu01",
     "FriendlyName": "tsu", "Module": "GenericModule", "AppState": 0, "Running": False},
]


class FakeAMP:
    def __init__(self, password: str = "pw", instances: list | None = None):
        self.password = password
        self.instances = [dict(i) for i in (instances if instances is not None else DEFAULT_INSTANCES)]
        self.valid_sessions: set[str] = set()
        self.login_count = 0
        self.call_count: dict[str, int] = {}
        self.always_unauthorized = False  # simulate a permission (not session) problem
        self.network_down = False

    def set_state(self, instance_id: str, app_state: int) -> None:
        for inst in self.instances:
            if inst["InstanceID"] == instance_id:
                inst["AppState"] = app_state

    def expire_sessions(self) -> None:
        self.valid_sessions.clear()

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.network_down:
            raise httpx.ConnectError("connection refused", request=request)
        path = request.url.path
        self.call_count[path] = self.call_count.get(path, 0) + 1
        body = json.loads(request.content or b"{}")

        if path == "/API/Core/Login":
            self.login_count += 1
            if body.get("password") == self.password:
                session_id = f"sess-{self.login_count}"
                self.valid_sessions.add(session_id)
                return httpx.Response(200, json={
                    "result": 10, "success": True, "sessionID": session_id,
                    "resultReason": "", "permissions": [],
                })
            return httpx.Response(200, json={"success": False, "resultReason": "Invalid credentials"})

        if self.always_unauthorized or body.get("SESSIONID") not in self.valid_sessions:
            return httpx.Response(200, json=UNAUTHORIZED)

        if path == "/API/ADSModule/GetInstances":
            return httpx.Response(200, json={"result": [{"AvailableInstances": self.instances}]})

        return httpx.Response(200, json=UNAUTHORIZED)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)
