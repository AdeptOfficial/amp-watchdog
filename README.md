# amp-watchdog

Watchlist-based status monitor for [CubeCoders AMP](https://cubecoders.com/AMP) game-server instances, with a web UI and pluggable notifications.

AMP supplies the **online**, **sleeping** and **offline** state. Optional Minecraft server-list pings cross-check online/sleeping claims to catch a wedged wake-on-connect listener. A bare TCP connection is insufficient: the probe requires a complete, bounded status frame containing a JSON object. Leave probes disabled on servers that intentionally disable status responses (`enable-status=false`).

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
| Deployed | Internal production: https://amp-watch.internal.adeptlab.dev (LAN/Tailscale) |

## Liveness checks

Set the Minecraft host and port in a watch's edit form. Two failed checks override
an online/sleeping AMP state to offline; a successful response resets the failure
count. Existing quiet hours, transition rules and offline re-alerts still apply.
Recovery notifications require the corresponding rule (offline → sleeping is off
by default). Offline messages may mention you; recovery messages do not.

The probe sends a status handshake, not a join. Healthy sleeping listeners answered
without waking on the AMP version tested; recheck this behavior after AMP upgrades.
It detects failure, but does not restart a game server or prove players can join.

## Operations

Production runs on LXC 112 at port 8200 behind the internal NPM HTTPS hostname.
Source: `/opt/amp-watchdog`; database: `/opt/appdata/amp-watchdog/watchdog.db`.
The former dev instance on LXC 212 is stopped to prevent duplicate alerts. Do not
restart it with production notification channels enabled. `scripts/deploy.sh`
still targets dev only. Production instructions and rollback are recorded in the
homeserver repository at `configs/prod/services/amp-watchdog/README.md`.

No public tunnel is configured for this unauthenticated internal app.

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
