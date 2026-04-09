# Copilot Individual Endpoint Compatibility Patch

Date: 2026-04-10

## Summary

`Hermes` was partially hard-coded for `https://api.githubcopilot.com`.
Because of that, when `model.base_url` was set to `https://api.individual.githubcopilot.com`, some code paths treated it as a non-Copilot endpoint.

That caused three classes of failures:

1. `copilot_default_headers()` was not always applied.
2. GitHub/Copilot Responses-mode detection was inconsistent.
3. `hermes setup` and model-selection flows could still fetch the catalog from the default Copilot host instead of the configured personal endpoint.

The patch makes runtime, setup, and auxiliary-provider paths consistently support `api.individual.githubcopilot.com` while preserving the legacy `https://models.github.ai/inference(/v1)` compatibility path.

## Root Cause

The original behavior depended on exact checks such as:

- `api.githubcopilot.com` substring checks
- default Copilot catalog URL constants
- setup flows that ignored configured `model.base_url`

That was not enough for personal Copilot endpoints because:

- `api.individual.githubcopilot.com` needs the same Copilot headers and routing behavior
- `models.github.ai/inference(/v1)` should still map back to the canonical Copilot catalog URL during model probing

## Changes

### 1. Copilot host detection

Strict Copilot host matching now accepts only:

- `githubcopilot.com`
- subdomains of `githubcopilot.com`

This prevents false positives such as unrelated hosts that merely contain the same substring.

Relevant files:

- `hermes_cli/models.py`
- `agent/model_metadata.py`

### 2. Runtime provider resolution

Explicit Copilot runtime resolution now respects configured `model.base_url` instead of silently falling back to the provider default.

Relevant file:

- `hermes_cli/runtime_provider.py`

### 3. Request headers and Responses-mode handling

All Copilot-specific runtime branches now recognize `api.individual.githubcopilot.com` as a Copilot endpoint, including:

- default request headers
- Responses-mode handling
- reasoning payload handling
- auxiliary client construction

Relevant files:

- `run_agent.py`
- `agent/auxiliary_client.py`

### 4. Catalog fetching and probing

Catalog fetches now support a configured Copilot base URL where appropriate, but still normalize the legacy GitHub Models inference URL back to:

`https://api.githubcopilot.com/models`

This preserves older supported flows.

Relevant file:

- `hermes_cli/models.py`

### 5. Setup and model-selection flows

`hermes setup`, Copilot model selection, and Copilot ACP model selection now thread the configured base URL through the catalog lookup path.

Relevant files:

- `hermes_cli/main.py`
- `hermes_cli/setup.py`

## Current Config

The active local config uses:

```yaml
model:
  provider: "copilot"
  base_url: "https://api.individual.githubcopilot.com"
  api_mode: "chat_completions"
```

Source:

- `~/.hermes/config.yaml`

## Tests Added or Updated

Coverage was added for these cases:

1. Explicit Copilot runtime respects configured `api.individual.githubcopilot.com`
2. Probe path adds Copilot headers for the individual endpoint
3. Auxiliary client applies Copilot headers for the individual endpoint
4. Responses-mode logic works for the individual endpoint
5. `models.github.ai/inference/v1` still normalizes to the canonical Copilot catalog URL
6. Setup and model-selection flows use configured individual Copilot base URLs
7. Host matching rejects unrelated domains like `evilgithubcopilot.com`

Relevant test files:

- `tests/hermes_cli/test_runtime_provider_resolution.py`
- `tests/hermes_cli/test_model_validation.py`
- `tests/agent/test_auxiliary_client.py`
- `tests/run_agent/test_run_agent_codex_responses.py`
- `tests/hermes_cli/test_setup_model_selection.py`
- `tests/hermes_cli/test_model_provider_persistence.py`

## Verification

Static verification:

```bash
python3 -m py_compile \
  hermes_cli/models.py \
  hermes_cli/main.py \
  hermes_cli/setup.py \
  hermes_cli/runtime_provider.py \
  agent/auxiliary_client.py \
  agent/model_metadata.py \
  run_agent.py
```

Targeted test verification:

```bash
/Users/imac/.hermes/hermes-agent/venv/bin/pytest -n0 \
  tests/hermes_cli/test_model_validation.py \
  tests/hermes_cli/test_setup_model_selection.py \
  tests/hermes_cli/test_model_provider_persistence.py \
  tests/hermes_cli/test_runtime_provider_resolution.py \
  tests/agent/test_auxiliary_client.py \
  tests/run_agent/test_run_agent_codex_responses.py \
  -k 'copilot or github or individual or reasoning or probe_api_models'
```

Result:

- `40 passed, 237 deselected`

Additional Copilot regression slice:

```bash
/Users/imac/.hermes/hermes-agent/venv/bin/pytest -n0 \
  tests/hermes_cli/test_setup_model_provider.py \
  tests/hermes_cli/test_api_key_providers.py \
  tests/hermes_cli/test_model_provider_persistence.py \
  -k 'copilot or github'
```

Result:

- `22 passed, 125 deselected`

Live end-to-end verification:

```bash
hermes chat -q '안녕. 한 문장으로만 답해.' -Q --max-turns 1
```

Observed response:

- `안녕하세요, Max. 무엇을 도와드릴까요?`
- `session_id: 20260410_024707_e1f6e8`

## Review Outcome

A review pass initially found two real gaps:

1. legacy `models.github.ai/inference(/v1)` compatibility
2. `hermes setup` catalog fetch still using the default Copilot host

Those were patched and re-reviewed. Final review result: no material issues found in the current patch set.

## Notes

- `smart_model_routing` remains disabled in the local config. That is a separate operational choice and not the same issue as the endpoint compatibility bug fixed here.
- `package-lock.json` was already dirty in the worktree and was not part of this patch.
