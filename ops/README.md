# AMP Watchdog — operations runbook

How to build, run, deploy, verify and roll back this app on any host. Instance
state for the AdepT homelab lives in
`~/git/homeserver/configs/prod/services/amp-watchdog/README.md` (production, LXC <dashboard-prod>)
and `configs/dev/services/amp-watchdog/README.md` (dev, LXC <dashboard-dev>, stopped). The
promotion gate is `~/git/workflows/promote-to-prod.md`. Facts below come from
`docker-compose.yml`, `Dockerfile`, `.env.template`, `ops/deploy-dev.sh` and those docs.

## Runtime shape

| Item | Value |
|------|-------|
| Process | `uvicorn app.main:app` on container port 8000, published on host port 8200 |
| Image | built from `Dockerfile` (python:3.12-slim, multi-stage, curl for the healthcheck) |
| Data | SQLite at `/config/watchdog.db`, host volume `/opt/appdata/amp-watchdog` |
| Backend | the AMP ADS instance in `AMP_BASE_URL`, read with a least-privilege account |
| Health | `GET /api/health` (compose healthcheck every 30 s); SSE kept alive by `--timeout-keep-alive 60` |
| Config | `.env` from `.env.template`; alert channel webhooks live in the database, not in files |
| Access | none in the app: LAN/Tailscale only, behind the internal reverse proxy, never a public tunnel |

## Run anywhere

```bash
cp .env.template .env                  # fill in values
docker compose up -d --build
curl -f http://localhost:8200/api/health
```

## Database

| Item | Value |
|------|-------|
| Engine | SQLite, via `DATABASE_URL=sqlite:////config/watchdog.db` |
| Data path | `/opt/appdata/amp-watchdog/watchdog.db` on the host |
| Backup | app running: `sqlite3 watchdog.db ".backup '<private-dir>/watchdog.db'"`; stopped app: copy the file |
| Integrity | `sqlite3 watchdog.db "PRAGMA quick_check;"` (used at the production cutover) |
| Restore check | point `DATABASE_URL` at a copy in a disposable path and run `pytest` |
| Migrations | add-column-only dict in `app/database.py`; no Alembic; never rename or remove columns |

**Backups are secrets:** alert channel rows hold webhook URLs. Mode 600, private
paths, never in the repo. Follow `~/git/workflows/database-change.md` before any
schema change, repair or restore.

## Before any deploy

```bash
pytest
```

Run tests with networking disabled and an isolated database; never mount the
production database into a test.

## Deploy to DEV

Procedure: `~/git/workflows/deploy-to-dev.md`. `ops/deploy-dev.sh` tars the source (excluding `.git`, `.venv`, caches, `data`
and `.env`), copies it to the dev Proxmox host, pushes it into LXC <dashboard-dev> at
`/opt/amp-watchdog` preserving the existing `.env`, and runs
`docker compose up -d --build`. Dev is currently **stopped** after the production
cutover: do not start it with production notification channels enabled, because
both copies would alert on the same servers. Use isolated test settings.

## Deploy to production

The dev script does not target production. Production follows the gate in
`~/git/workflows/promote-to-prod.md`, then the steps recorded in the homeserver
prod README:

1. Transfer a source archive (same exclusions as the dev script); keep the
   production `.env` and data directory in place.
2. Build a versioned image in `/opt/amp-watchdog`, for example
   `amp-watchdog:<tag>-<date>`, and run the tests inside it with networking off.
3. Tag the validated image as the compose image name and run
   `docker compose up -d --no-build`.
4. Verify (below) and record the image tag, archive hash and backup path.

## Backup and rollback

Before replacing the running service: keep the prior source, tag the prior image,
and take a consistent SQLite backup (stopped app or online backup) to a dated
private folder. Rollback is retagging the prior image and
`docker compose up -d --no-build`; keep newer history and settings rather than
restoring an old snapshot over them.

## Verify after a deploy

- Container `healthy`; health endpoint 200 through the HTTPS proxy; HTTP redirects.
- SSE delivers connected/heartbeat events on the dashboard.
- `PRAGMA quick_check` on the database returns ok (read only safe aggregate
  fields; channel rows contain secrets).
- Enabled watches show fresh successful checks and zero backend errors.
- Record results in `DIARY.md` and the homeserver service README.

## Where things are

- Logs: `docker logs amp-watchdog`.
- Database: `/opt/appdata/amp-watchdog/watchdog.db` on the host.
- Reverse proxy and TLS: documented on the homeserver side only.
