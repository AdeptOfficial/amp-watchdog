# Claude Context: amp-watchdog

Watchlist status monitor for CubeCoders AMP instances. FastAPI + async SQLAlchemy/SQLite + htmx/Tailwind-CDN + SSE, Docker-deployed.

## Startup

1. **Read `inbox.txt`** — process items under Issues:/Features: into `issues/` / `features/`, then clear them.
2. **Read `DIARY.md`** for recent history. Write a dated entry (newest on top) after meaningful changes.

## Architecture (read before changing code)

- `app/clients/amp.py` — AMP API client. Session id is `sessionID` (capital ID) from `Core/Login`; every call body carries `SESSIONID`. AMP returns **HTTP 200 with `{"Title": "Unauthorized Access"}` JSON** on auth/permission failures — detected by body shape, re-login + retry once.
- `app/core/states.py` — AppState int → name → bucket (online/sleeping/offline/transitional/unknown). Transitional/unknown never alert and never overwrite `last_bucket` (stable-bucket model: prevents alert flapping on restarts).
- `app/services/scheduler.py` — single asyncio ticker; due watches (`next_check_at <= now`) are checked **batched per checker type** (one GetInstances per tick). No APScheduler: the DB is the only schedule state.
- `app/services/evaluator.py` — pure transition/notify/suppress logic. All alert-rule changes go here, with tests.
- Plugins auto-load by directory scan: `app/checkers/` (CheckerPlugin) and `app/notifiers/` (NotifierPlugin). A notifier's `config_fields` drives its add-channel form — new channels need no UI work.
- Migrations: add-column-only dict in `app/database.py` (no Alembic). Never rename/remove columns.

## Rules

- No auth on the app ("the network is the auth") — internal LAN/Tailscale only, never expose via tunnel.
- Secrets only in `.env` (gitignored). Channel webhook URLs live in the DB — the repo is public, never commit a real webhook URL, `.env`, or dumps of `watchdog.db`.
- Deploy: `scripts/deploy.sh` → dev LXC 212 (10.0.2.12:8200). Prod requires explicit user approval.
- Run `pytest` before any deploy.

## Infra docs

Homeserver repo: `configs/dev/services/amp-watchdog/README.md` (deploy notes), `context/domains/amp-watchdog.md` (AMP API facts), `docs/game-servers.md` § Status Monitoring.
