# amp-watchdog

Watchlist-based status monitor for [CubeCoders AMP](https://cubecoders.com/AMP) game-server instances, with a web UI and pluggable notifications.

AMP-managed game servers can't be monitored from the outside: AMP holds the game port even while an instance is stopped or sleeping, and hardened servers (`enable-status=false`) ignore status pings entirely. amp-watchdog asks AMP itself — the only source that knows the difference between **online**, **sleeping** (wake-on-connect), and **offline**.

## Features

- **Watchlist UI** — discover instances live from AMP's API and pick which to watch
- **Per-watch rules** — check interval, which state transitions alert (e.g. alert on offline, stay quiet about sleep cycles), re-alert while still down, quiet hours
- **Custom messages** — per-watch template with placeholders (`{name}`, `{from_state}`, `{to_state}`, `{app_state}`, `{mention}`, `{time}`)
- **Pluggable notifiers** — Discord webhook today; new channels (ntfy, email) drop in as single-file plugins that auto-generate their own config and edit forms
- **Channel management** — add, edit, enable/disable, delete; per-channel custom test message with a send-test button that previews the real alert format
- **Pluggable checkers** — AMP today; the watch schema is checker-agnostic (HTTP, A2S, … later)
- **Live dashboard** — SSE-pushed status dots, transition history, Check Now button
- **No flapping** — transitional states (Starting/Restarting/Stopping) never alert; only stable-state changes do

## Current Status

| Item | Status |
|------|--------|
| Version | 0.1.0 |
| AMP checker | ✅ Login/session cache/re-login, batched GetInstances |
| Discord notifier | ✅ |
| ntfy / email notifiers | Planned (plugin slots ready) |
| Deployed | DEV LXC 212 @ 10.0.2.12:8200 |

## Stack

FastAPI · SQLAlchemy 2 (async, SQLite) · htmx + hand-rolled AdepT token CSS (no build step, no CDN styles) · SSE · Docker

## Quick start

```bash
cp .env.template .env      # fill AMP_PASSWORD (a read-only AMP user; see below)
docker compose up -d --build
# open http://localhost:8200
```

### The AMP service account

Create a dedicated AMP user (e.g. `status-reader`): Super Admin **off**, "Cannot Change Password" **on**, and grant it only the per-instance **Manage** permission for each instance you want visible. In AMP's model, Manage = visibility; Start/Stop/Restart/Update are the action rights and stay off. An instance appears in `GetInstances` only if the user holds at least one permission on it.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
pytest
uvicorn app.main:app --reload   # uses sqlite:///./data/watchdog.db
```

## License

MIT
