# Hermes Rust Upstream Compatibility Guardrail

Date: 2026-05-01

## Decision

Complete Rust transition is allowed, but it must not mean losing Hermes upstream updates.

The fixed invariant is:

- keep the Hermes-rs nervous-system structure;
- keep upstream update intake alive;
- keep original Hermes assistant features alive.

These three conditions are one compatibility gate. Passing only the Rust patch
dry-run is not enough if the update breaks the original Hermes chat, update,
plugin, memory, session, gateway, or assistant-style CLI surface.

Python Hermes stays as:

- upstream sync source
- behavior reference
- fallback runtime
- parity test oracle

Rust Hermes becomes:

- execution owner for approved hot paths
- context/runtime contract owner
- route/dispatch owner after parity gates pass

## Upstream Sync Ledger

Every upstream Hermes update is classified before merge:

| Class | Action |
| --- | --- |
| Security/auth/session persistence | merge or port before Rust promotion continues |
| Provider API compatibility | port to Rust adapter or keep Python fallback active |
| Tool execution behavior | keep Python authoritative until Rust tool executor is proven |
| CLI/TUI/gateway UX | merge Python-side unless it conflicts with Rust-owned contracts |
| Prompt/context policy | compare against Rust contract, then port intentionally |
| Cosmetic/docs-only | merge normally |

Do not treat an upstream update as applied to Rust until the matching parity row below is checked.

Do not treat an upstream update as accepted for local use until the original
Hermes assistant surface still works. Hermes-rs may take over hot paths, but it
does not silently delete upstream behavior.

## Feature Parity Checklist

| Surface | Current owner | Rust owner target | Gate |
| --- | --- | --- | --- |
| Plain chat response | Python primary, Rust opt-in preview | Rust primary | fallback test + live smoke |
| Context packing | Python primary, Rust preview/apply opt-in | Rust primary | transcript safety + token budget tests |
| Runtime contract | Rust preview | Rust primary | deterministic system-message contract |
| Provider fallback | Python | Python until later | no regression in fallback chain |
| Tool execution | Python | later Rust executor | tool transcript invariants proven |
| Session persistence | Python | later shared store | no lost assistant/user turns |
| Gateway/CLI | Python | later adapter shell | UX and plugin hooks preserved |

## Promotion Rule

A surface can move from Python primary to Rust primary only when:

1. Rust has deterministic tests for the surface.
2. Python fallback still works when Rust is disabled or unavailable.
3. Upstream Hermes changes for that surface are classified in this ledger.
4. The migration does not bypass Hermes tool/session/plugin semantics.

## Fallback Rule

Rust failure must be boring:

- timeout: continue Python path
- endpoint down: continue Python path
- Rust response with `fallback_reason`: continue Python path
- tool transcript present: continue Python path
- tool definitions active: continue Python path

This keeps upstream updates useful while Rust ownership expands.

## Model Layer Hierarchy

The active Hermes-rs hierarchy is:

| Layer | Model | Primary task | Strategic reason |
| --- | --- | --- | --- |
| L1 Gateway / State Keeper | Ministral 3B | intent classification, routing, state summary, simple CLI judgment | fastest always-on path; correct home for lane policy and state recall |
| L2 Planner | Ministral 8B | work planning, document reference, prompt shaping, medium reasoning | better judgment than 3B without Devstral-level cost |
| L3 Worker / Synthesizer | SuperGemma 26B | sustained work, comparison, synthesis, structured outputs | high throughput for its size; best default work lane |
| L4 Precision Engineer | Devstral 24B | complex code, debugging, deep review, reasoning-heavy patches | slower but reserved for precise coding and difficult failures |

Operational mapping:

- `normal_turn` stays on the 3B router/state lane.
- `worker_task` maps to the worker model class and the active profile may bind
  that class to SuperGemma.
- Devstral remains on-demand until a first-class precision-engineer lane is
  added to the policy enum.
