# amp-watchdog Development Diary

## 2026-10-17: v0.1.0 — initial implementation

- Full app built in one pass following the homeserver New App Template (status-tracker
  patterns): FastAPI + async SQLAlchemy/SQLite, htmx/Tailwind-CDN UI, SSE live dashboard.
- **AMP client** (`app/clients/amp.py`): session caching with double-checked asyncio lock,
  re-login + single retry on AMP's HTTP-200 `Unauthorized Access` error shape. API facts
  verified live against AMP 2.8.0.8 earlier the same day (sessionID capital-ID quirk, etc.).
- **Stable-bucket evaluator**: transitional states (Starting/Restarting/...) update display
  only — alerts fire solely on stable-bucket changes (online/sleeping/offline) per-watch
  rules, with quiet hours (midnight wrap), offline re-alert cooldown, and suppress reasons
  persisted on every transition row.
- **Scheduler**: single asyncio ticker over DB `next_check_at` (no APScheduler); due watches
  batch into ONE GetInstances call per sweep; checker failures record errors without
  fabricating offline transitions. "Check now" wakes the ticker via asyncio.Event.
- **Plugins**: checkers (amp) and notifiers (discord) auto-load by directory scan; a
  notifier's `config_fields` drives its add-channel form, so ntfy/email drop in later with
  zero UI work.
- **Tests**: 45 passing (states, client incl. concurrency/expiry, evaluator, scheduler
  batching/errors, notifier payload/truncation/dispatch logging, API CRUD + pages) via
  httpx.MockTransport fake AMP and in-memory SQLite. Run in the python:3.12-slim image
  (host Python 3.14 is too new for the pins).
- Target deployment: dev LXC 212 (dashboard-dev) @ 10.0.2.12:8200. Supersedes the n8n
  "Minecraft LYD Status → Discord" workflow once verified live.
