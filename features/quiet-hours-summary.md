# Feature: Quiet-hours end summary

**Status:** Planned (v1.1)

V1 quiet hours *suppress* notifications (the transition is still recorded with
`suppress_reason='quiet_hours'`). The re-alert loop already covers the important
case — a server still offline when quiet hours end will re-ping — but one-shot
events that happened overnight (e.g. went offline and came back) are only visible
on the dashboard, never pushed.

**Proposal:** when a check runs and quiet hours have just ended, send one digest
message per watch summarizing suppressed transitions since quiet-start.

**Notes:**
- Needs a "quiet window just ended" edge detector in the evaluator (compare previous
  check's local time window membership vs now).
- Query `transitions` where `suppress_reason='quiet_hours'` and `created_at` within
  the window; skip if none.
