"""AMP ApplicationState mapping and bucketing.

Buckets drive all alert logic:
- online / sleeping / offline are STABLE buckets — transitions between them
  are recorded and may notify.
- transitional (Starting, Stopping, ...) and unknown never notify and never
  overwrite a watch's last stable bucket, so a routine restart
  (online -> Starting -> online) produces zero alerts.
"""

APP_STATE_NAMES: dict[int, str] = {
    -1: "Undefined",
    0: "Stopped",
    5: "PreStart",
    7: "Configuring",
    10: "Starting",
    20: "Ready",
    30: "Restarting",
    40: "Stopping",
    45: "PreparingForSleep",
    50: "Sleeping",
    60: "Waiting",
    70: "Installing",
    75: "Updating",
    80: "AwaitingUserInput",
    100: "Failed",
    200: "Suspended",
    250: "Maintenance",
    999: "Indeterminate",
}

BUCKET_ONLINE = "online"
BUCKET_SLEEPING = "sleeping"
BUCKET_OFFLINE = "offline"
BUCKET_TRANSITIONAL = "transitional"
BUCKET_UNKNOWN = "unknown"

STABLE_BUCKETS = {BUCKET_ONLINE, BUCKET_SLEEPING, BUCKET_OFFLINE}

_BUCKETS: dict[int, str] = {
    20: BUCKET_ONLINE,
    45: BUCKET_SLEEPING,
    50: BUCKET_SLEEPING,
    0: BUCKET_OFFLINE,
    80: BUCKET_OFFLINE,
    100: BUCKET_OFFLINE,
    200: BUCKET_OFFLINE,
    250: BUCKET_OFFLINE,
    5: BUCKET_TRANSITIONAL,
    7: BUCKET_TRANSITIONAL,
    10: BUCKET_TRANSITIONAL,
    30: BUCKET_TRANSITIONAL,
    40: BUCKET_TRANSITIONAL,
    60: BUCKET_TRANSITIONAL,
    70: BUCKET_TRANSITIONAL,
    75: BUCKET_TRANSITIONAL,
}


def state_name(app_state: int | None) -> str:
    if app_state is None:
        return "Unknown"
    return APP_STATE_NAMES.get(app_state, f"Unknown({app_state})")


def bucket_of(app_state: int | None) -> str:
    if app_state is None:
        return BUCKET_UNKNOWN
    return _BUCKETS.get(app_state, BUCKET_UNKNOWN)
