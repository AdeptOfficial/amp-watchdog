# Feature: alert when the AMP panel itself is unreachable

The ADS controller can't be a watch (we query state THROUGH it — if it's down, every
check errors rather than producing a transition). The discover list shows it as
"always on" instead of a WATCH button.

The real signal for "AMP is down" already exists: `consecutive_errors` climbs on every
watch simultaneously. Feature: a global threshold (e.g. 3 consecutive error sweeps
across all watches) that sends a single "⚠ AMP panel unreachable" alert to a chosen
channel, with a recovery message when checks succeed again. One alert, not one per
watch.
