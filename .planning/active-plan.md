## Event

User fixed the layer model: 3B is the right router/state keeper. The working hierarchy is L1 Ministral 3B, L2 Ministral 8B, L3 SuperGemma 26B, L4 Devstral 24B.

## Function

Packet AU maps the layer decision into Hermes-rs/Hermes operational state:

- record the model hierarchy in the Hermes compatibility plan.
- adjust Python fallback lane policy so `worker_task` no longer collapses to 3B.
- adjust active `mini` profile lane runtime so worker tasks can use SuperGemma.
- update handoff/local notes and push only scoped repo files.

Out of scope: adding a first-class Devstral enum to lane policy, broad test expansion, or changing upstream Hermes merge status.

## Steps

1. `discover` - completed
   - active profile is `mini -> qwen27b`.
   - Hermes-rs lane policy is active in the profile.
   - current Python fallback maps `worker_task` to 3B, which conflicts with the new hierarchy.
2. `implement` - in progress
   - update fallback policy/test and active profile runtime map.
   - record hierarchy in docs and handoff.
3. `verify`
   - targeted lane-policy tests.
   - live active-profile AIAgent lane probe.
   - diff hygiene.
4. `closeout`
   - commit/push scoped changes where possible and report local-only env/config separately.

## Verify

- `./venv/bin/python -m pytest tests/hermes_cli/test_lane_policy.py tests/run_agent/test_lane_policy_wiring.py -q`
- active profile AIAgent probe with `HERMES_HOME=/Users/maxmcair/.hermes/profiles/qwen27b`
- `git diff --check`

## Closeout

- `installed`: no install.
- `applied in code`: pending hierarchy mapping.
- `user-sealed decision`: 3B is Router/State Keeper; SuperGemma is worker; Devstral remains precision engineer.
- `hold / excluded`: Devstral first-class lane enum and broad routing refactor.

## Event

User asked to proceed from the applied invariant and make the runtime actually use it. Binding requirement: Hermes-rs structure stays active while original Hermes assistant/update/plugin/session features remain preserved.

## Function

Packet AT enables the Hermes-rs lane-policy path locally and verifies only the required surfaces:

- enable `HERMES_RUST_LANE_POLICY=1` in the local Hermes env.
- keep Rust chat primary disabled unless explicitly promoted later.
- verify bridge health, Hermes command surface, upstream watcher dry-run, and targeted lane-policy tests.

Out of scope: enabling Rust plain-chat primary, merging upstream into main, modifying secrets, or running broad test suites.

## Steps

1. `discover` - completed
   - current `.env` had no Hermes-rs lane-policy flag.
   - config already maps lane runtime for `ministral_3b_instruct`.
   - bridge is expected on `127.0.0.1:4319`.
2. `implement` - in progress
   - append bounded Hermes-rs lane-policy env settings.
3. `verify`
   - bridge health.
   - Hermes command surface smoke.
   - targeted lane-policy tests.
   - upstream watcher dry-run.
4. `closeout`
   - report whether actual runtime is now enabled and what remains held.

## Verify

- `curl -sS http://127.0.0.1:4319/healthz`
- `hermes --version`
- `hermes --help`
- `./venv/bin/python -m pytest tests/run_agent/test_lane_policy_wiring.py -q`
- `./scripts/watch-hermes-upstream.sh --no-fetch --dry-run`

## Closeout

- `installed`: no install.
- `applied in code`: pending env activation.
- `user-sealed decision`: Hermes-rs lane-policy may be active; original Hermes assistant/update/plugin/session surfaces must remain available.
- `hold / excluded`: Rust chat primary, upstream merge to main, Python Hermes removal, broad test expansion.

## Event

User clarified the core requirement: keep the Hermes-rs structure, preserve upstream update intake, and preserve original Hermes assistant features. This is binding.

## Function

Packet AS records the compatibility invariant in the upstream patch documentation:

- Hermes-rs remains the Rust nervous-system lane for routing/context/model control.
- Original Hermes remains the assistant/update/plugin/session feature surface unless a specific surface passes parity gates.
- Upstream updates are not considered usable if they break original Hermes assistant features, even when Rust patches apply cleanly.

Out of scope: merging upstream into main, adding new runtime behavior, changing provider/model credentials, or removing Python Hermes.

## Steps

1. `discover` - completed
   - upstream patch README and compatibility guardrail already exist.
   - watcher detects upstream changes and patch dry-run status.
   - targeted Hermes-rs tests passed before this packet.
2. `implement` - in progress
   - add the preservation invariant to upstream patch docs.
3. `verify`
   - run markdown/diff hygiene for touched docs.
4. `closeout`
   - report the fixed invariant and next update path.

## Verify

- `git diff --check -- .planning/active-plan.md .planning/harness.json patches/hermes-upstream/README.md docs/plans/2026-05-01-hermes-rust-upstream-compatibility.md`

## Closeout

- `installed`: no install.
- `applied in code`: pending documentation-only invariant update.
- `user-sealed decision`: Hermes-rs structure + Hermes original assistant features + upstream update intake must be preserved together.
- `hold / excluded`: upstream merge to main, Python Hermes removal, live provider/model credential changes.

## Event

User asked to continue Hermes Rustification. Binding decision: original Hermes behavior stays intact; Python remains a compatibility/fallback shim while Rust becomes the preferred local lane-policy authority.

## Function

Packet AR wires Hermes Python to optionally use the local Rust lane-policy endpoint:

- add `HERMES_RUST_LANE_POLICY` switch.
- request `/runtime/lane-select-preview` when enabled.
- apply returned model/toolset/runtime map keys.
- fail open to existing Python `hermes_cli.lane_policy`.
- keep upstream patch watcher compatible.

Out of scope: removing Python Hermes, rewriting the synchronous agent loop, enabling remote dispatch, or changing provider/model credentials.

## Steps

1. `discover` - completed
   - `AIAgent` lane initialization already supports model/runtime/toolset maps.
   - local Rust preview helpers already exist in `run_agent.py`.
   - upstream watcher patch files must stay replayable.
2. `implement` - completed
   - added Rust lane-policy request helper and env switch.
   - added `lane_policy_source`.
   - added fallback test and Rust-primary wiring test.
   - refreshed affected upstream patch files.
3. `verify` - completed
   - targeted Python tests passed.
   - py_compile passed.
   - upstream watcher dry-run passed.
4. `closeout` - in progress
   - report changed files and remaining gaps.

## Verify

- `/Users/maxmcair/hermes-agent/venv/bin/python -m py_compile /Users/maxmcair/hermes-agent/run_agent.py`
- `/Users/maxmcair/hermes-agent/venv/bin/python -m pytest /Users/maxmcair/hermes-agent/tests/run_agent/test_lane_policy_wiring.py -q`
- `/Users/maxmcair/hermes-agent/scripts/watch-hermes-upstream.sh --no-fetch --dry-run`
- `git diff --check -- run_agent.py tests/run_agent/test_lane_policy_wiring.py`

## Closeout

- `installed`: no install.
- `applied in code`: optional Rust lane-policy primary path with Python fallback.
- `user-sealed decision`: Hermes Rustification proceeds without breaking original Hermes update compatibility.
- `hold / excluded`: full Python rewrite/removal, live dispatch execution, provider credential changes.

## Event

User asked to continue after local route outbox anchoring landed. Binding decision: the next packet may strengthen Mario review evidence, but remote SSH dispatch and Mario ingestion remain held.

## Function

Packet AQ enriches local route outbox packets with Mario review envelope fields:

- `target_authority=imac_mario`
- `raw_child_data=false`
- `privacy_class=operator_route_packet`
- preflight evidence placeholders for route plan/export boundary/expected receipt

Out of scope: SSH dispatch execution, Mario judgment ingestion, Rust tool execution, gateway/CLI rewrite, and Memory Palace promotion.

## Steps

1. implement: enrich saved outbox packets with Mario review envelope metadata.
2. test: assert envelope fields are present in saved JSON and credential-free short-circuit remains.
3. verify: run targeted route gate tests and diff hygiene.
4. closeout: record Mario review envelope state.

## Verify

Target checks:

- `./venv/bin/python -m pytest tests/hermes_cli/test_background_route_gate.py -q`
- `git diff --check -- .planning/active-plan.md .planning/harness.json hermes_cli/dispatch_outbox.py tests/hermes_cli/test_background_route_gate.py`

## Closeout

- installed: none
- applied in code: saved outbox packets now include Mario review envelope fields and targeted file assertions cover them
- user-sealed decision: Mario review envelope evidence is allowed; remote dispatch remains held
- hold / excluded: SSH dispatch execution, Mario judgment ingestion, Memory Palace promotion
