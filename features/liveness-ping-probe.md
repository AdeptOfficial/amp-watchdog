# Out-of-band liveness probe (server-list ping) for Minecraft watches

**Origin:** 2026-10-17 LYD incident — AMP's wake-on-connect sleep listener wedged:
TCP 31575 open but no ping response and no wake, while `GetInstances` kept reporting
AppState 50 (Sleeping) / `Running: true`. Every AMP-API-based monitor stayed silent;
the server was unjoinable. Full post-mortem:
`homeserver/issues/bugs/lyd-amp-sleep-listener-wedged.md`.

## Problem

The AMP checker trusts AMP's self-reported AppState. A healthy sleep listener answers
real server-list pings while sleeping (verified on Gnomes: 0.01s, MOTD, while
AppState 50), so "sleeping" is normally a safe healthy bucket — but a wedged listener
is indistinguishable from a healthy one through `GetInstances` alone.

## Implementation and verification status (2026-10-17)

The liveness fix and response-validation hardening are deployed to internal production. Actual implementation uses optional
`ping_host`/`ping_port` per watch, a five-second timeout and two failed checks
before overriding online/sleeping to **offline** (not a new degraded bucket).
Failure count persists in SQLite; successful probes reset it. Transitions and
mentions follow existing rules, so recovery notification requires enabling its
corresponding rule (offline → sleeping is disabled by default).

An independent review verified health and two configured enabled watches, both
sleeping with zero failures. The 65-test suite passes, including real local TCP
servers for healthy/stalled responses and scheduler persistence/alert capture.
Malformed-response validation was tightened and shipped after all 65 tests passed
in the exact production image. Production uses the internal NPM hostname; dev is stopped.
Live game servers were not disrupted and no Discord messages were sent.

## Original design sketch (superseded where noted above)

- New per-watch option: `liveness_probe` (off by default; Minecraft module only, v1).
- Probe = real server-list ping (handshake + status request, protocol as in the
  incident diagnosis), against the instance's game endpoint, with a short timeout (~8s)
  and one retry to avoid flapping on world-load pauses.
- Rule: `bucket in {online, sleeping}` **and** probe times out (N consecutive checks,
  default 2) → new `degraded` state → alert through the normal notifier path
  ("port open but not answering — sleep listener likely wedged; instance stop/start
  needed, app restart may not rebind the port").
- `degraded` never auto-suppresses like transitional states: this is exactly the state
  AMP lies about.
- Needs endpoint config per watch (host defaults to the AMP host, port per instance —
  AMP API exposes instance ports via GetInstances `ApplicationEndpoints`; verify).
- The probe must never wake a healthy sleeper: a status request does not trigger
  wake-on-connect (verified in the incident — Gnomes answered pings while staying
  asleep). Join-handshake packets are never sent.

## Out of scope (v1)

- Remediation (auto stop/start). Alert only; the n8n auto-heal workflow or the human
  acts on it.
- Non-Minecraft modules (A2S etc.) — the checker plugin model leaves room for these
  later.
