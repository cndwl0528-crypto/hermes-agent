# Hermes Upstream Patch Set

This directory contains local compatibility patches that are replayed after
Hermes upstream changes.

The watcher intentionally separates status classes:

- `detected`: upstream remote SHA changed.
- `dry_run_passed`: patches apply cleanly with `git apply --check`.
- `applied_candidate`: patches were applied on a candidate branch/worktree.
- `held_conflict`: at least one patch failed dry-run.
- `test_failed`: patch dry-run/apply succeeded, but verification failed.
- `no_update`: remote SHA matches the last recorded SHA.

Operational rule:

- Automatic detection is allowed.
- Automatic patch dry-run is allowed.
- Automatic tests are allowed.
- Automatic merge to `main` is not allowed.
- Rust-lane preservation and original Hermes feature preservation are one gate:
  an upstream update is not accepted if chat, update, plugin, memory, session,
  gateway, or assistant-style CLI behavior regresses, even when patches apply.
- Hermes-rs owns routing, context, model-lane, and runtime policy hot paths.
  Original Hermes remains the compatibility/update/assistant feature surface
  until a surface has an explicit parity gate.

Patch files must use the `.patch` extension and are applied in lexical order.
