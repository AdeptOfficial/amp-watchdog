# amp-watchdog — agent entry point

Watchlist status monitor for CubeCoders AMP instances. FastAPI + async SQLAlchemy/SQLite + htmx + vanilla AdepT token CSS (`app/static/style.css` — branding rules in `~/git/AGENTS.md`, canonical doc `~/git/adeptproductions/branding/README.md`) + SSE, Docker-deployed.

## Startup

1. **Read `inbox.txt`** and run `~/git/workflows/process-inbox.md` (one new record per line, then clear the processed lines).
2. **Read the newest `DIARY.md` entry** only; its `Next:` line is the resume point. Diary rule:
   `~/git/homeserver-apps/AGENTS.md` → Resuming.

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
- Production: LXC <dashboard-prod>, https://<internal-hostname> (LAN/Tailscale), source `/opt/amp-watchdog`. Updates still require explicit production authorization.
- `ops/deploy-dev.sh` targets dev LXC <dashboard-dev>, currently stopped after cutover. Never restart the copied production channels on dev alongside production; use isolated test settings.
- Run `pytest` before any deploy.

## Infra docs

Homeserver repo: `configs/prod/services/amp-watchdog/README.md` (production/rollback),
`configs/dev/services/amp-watchdog/README.md` (stopped dev), `context/domains/amp-watchdog.md` (AMP API facts), `docs/game-servers.md` § Status Monitoring.
