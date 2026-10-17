# amp-watchdog Development Diary

## 2026-10-17: Chrome standard + discover-list polish

- Shared app chrome per branding doc: header exactly 56px, footer `20px 24px` with
  required `<app> v<version>` line — pixel-matched against domain-watcher.
- AMP's literal `Undefined` state renders as `—` (discover list + dashboard).
- ADS controller row shows "always on" instead of a WATCH button — we query state
  through the panel, so watching it is meaningless; `features/amp-unreachable-alert.md`
  records the right way to detect a dead panel (global consecutive-error threshold).
- Docs: README/CLAUDE.md stack lines updated — Tailwind CDN is gone, vanilla token CSS.

## 2026-10-17: Mention semantics — @-ping only on offline

- `{mention}` now renders only on transitions INTO offline and still-offline
  re-alerts. Sleep cycles and recoveries send regular messages without a ping
  (user rule: "if the server is offline, ping me; online -> sleep is a regular
  message"). Test added; form hint documents it.

## 2026-10-17: AdepT branding + vanilla token CSS (Tailwind CDN removed)

- Full restyle to the AdepT brand (canonical: `adeptproductions/branding/README.md`):
  terminal-dossier look — dark tokens, cyan `// headings`, uppercase letter-spaced
  labels, motd prompt line per page, square status lights, blinking-cursor busy states,
  `// code-signed by AdepT_X` footer.
- **Tailwind Play CDN removed** per the global rule (~/git/AGENTS.md): self-contained
  apps use hand-rolled token CSS served from `/static/style.css` — no external style
  dependency, works offline on LAN. htmx stays (CDN for now).
- All 11 templates converted to semantic classes; `app/static/` is new (style.css,
  emblem.png — the real A emblem as header mark + favicon) and `/static` is now
  mounted in `app/main.py`.
- Verified: 48/48 tests pass (python:3.12 container), dashboard + channels pages
  screenshot-checked against the brand.

## 2026-10-17: UX audit round + channel editing (user feedback)

- **Disabled-state audit** after the user caught greyed-out action buttons: rows now dim
  content cells only — Enable/Resume/Edit/Delete stay fully clickable, with "disabled"/
  "paused" badges. Dashboard: paused watches show a "paused" chip instead of a
  Check-now button that the scheduler would silently ignore; Check-now gives "Queued ✓"
  feedback. Send test on a disabled channel is greyed and unclickable (tooltip explains).
  Lesson recorded: dim content, never controls; audit every disabled/paused/empty state.
- **Channels are now editable**: per-row Edit form (name, plugin config fields, custom
  test message). New nullable `channels.test_message` column — first live use of the
  add-column migration dict, applied cleanly on deploy. "Send test" sends the custom
  message, or a built-in preview showing all three alert shapes (offline/sleeping/online)
  with a note that real alerts carry the live state.
- Removed the user's real Discord ID from the mention-field placeholder (public repo).
- 48 tests. Redeployed to LXC 212 several times through the round.

## 2026-10-17: UI polish after first user feedback

- Dashboard SSE indicator is now a pulsing green dot (amber when reconnecting) instead
  of the "live" text label.
- Watches page: the discover panel loads automatically on page open (big "Add watch"
  button removed); clicking **Watch** flips the row to "watching ✓" instantly via
  `HX-Trigger: refresh-watches, refresh-discover` response events, and deleting a watch
  flips the discover row back the same way. 45 tests still green; redeployed to LXC 212.

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
