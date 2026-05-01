#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${HERMES_UPSTREAM_WATCH_STATE_DIR:-$HOME/.hermes/upstream-watch}"
REPORT_DIR="$STATE_DIR/reports"
STATE_FILE="$STATE_DIR/state.json"
PATCH_DIR="${HERMES_UPSTREAM_PATCH_DIR:-$ROOT/patches/hermes-upstream}"
REMOTE="${HERMES_UPSTREAM_REMOTE:-upstream}"
BRANCH="${HERMES_UPSTREAM_BRANCH:-main}"
MODE="dry-run"
FETCH="1"
CREATE_BRANCH="0"
RUN_TESTS="1"

usage() {
  cat <<'USAGE'
watch-hermes-upstream.sh [options]

Options:
  --dry-run             Check whether local patches apply cleanly. Default.
  --apply               Apply patches on the current branch/worktree.
  --candidate-branch    Create/switch to hermes-upstream-sync/<timestamp> before apply.
  --no-fetch            Do not fetch remote refs; use existing local refs.
  --no-tests            Skip verification commands.
  --remote NAME         Git remote to check. Default: upstream.
  --branch NAME         Remote branch to check. Default: main.
  -h, --help            Show this help.

Environment:
  HERMES_UPSTREAM_WATCH_STATE_DIR
  HERMES_UPSTREAM_PATCH_DIR
  HERMES_UPSTREAM_REMOTE
  HERMES_UPSTREAM_BRANCH
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      MODE="dry-run"
      shift
      ;;
    --apply)
      MODE="apply"
      shift
      ;;
    --candidate-branch)
      CREATE_BRANCH="1"
      shift
      ;;
    --no-fetch)
      FETCH="0"
      shift
      ;;
    --no-tests)
      RUN_TESTS="0"
      shift
      ;;
    --remote)
      REMOTE="${2:?missing remote name}"
      shift 2
      ;;
    --branch)
      BRANCH="${2:?missing branch name}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

mkdir -p "$STATE_DIR" "$REPORT_DIR"

now_utc="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
stamp="$(date -u +"%Y%m%dT%H%M%SZ")"
report="$REPORT_DIR/$stamp.json"

json_escape() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//$'\n'/\\n}"
  printf '%s' "$value"
}

read_last_remote_sha() {
  if [[ ! -f "$STATE_FILE" ]]; then
    return 0
  fi
  sed -n 's/.*"last_remote_sha"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$STATE_FILE" | tail -1
}

write_json() {
  local path="$1"
  local status="$2"
  local remote_sha="$3"
  local local_sha="$4"
  local message="$5"
  local patch_status="$6"
  cat > "$path" <<JSON
{
  "updated_at": "$now_utc",
  "repo": "$(json_escape "$ROOT")",
  "remote": "$(json_escape "$REMOTE")",
  "branch": "$(json_escape "$BRANCH")",
  "mode": "$(json_escape "$MODE")",
  "status": "$(json_escape "$status")",
  "local_sha": "$(json_escape "$local_sha")",
  "remote_sha": "$(json_escape "$remote_sha")",
  "last_remote_sha": "$(json_escape "${last_remote_sha:-}")",
  "patch_dir": "$(json_escape "$PATCH_DIR")",
  "patch_status": "$(json_escape "$patch_status")",
  "message": "$(json_escape "$message")"
}
JSON
}

cd "$ROOT"

if [[ "$FETCH" == "1" ]]; then
  git fetch "$REMOTE" "$BRANCH"
fi

local_sha="$(git rev-parse HEAD)"
remote_ref="$REMOTE/$BRANCH"
remote_sha="$(git rev-parse "$remote_ref")"
last_remote_sha="$(read_last_remote_sha)"

patches=()
if [[ -d "$PATCH_DIR" ]]; then
  while IFS= read -r patch_file; do
    patches+=("$patch_file")
  done < <(find "$PATCH_DIR" -maxdepth 1 -type f -name '*.patch' | sort)
fi

if [[ "${#patches[@]}" -eq 0 ]]; then
  status="detected"
  if [[ -n "$last_remote_sha" && "$last_remote_sha" == "$remote_sha" ]]; then
    status="no_update"
  fi
  write_json "$report" "$status" "$remote_sha" "$local_sha" "no patch files found" "no_patches"
  cp "$report" "$STATE_FILE"
  echo "$status: no patch files found"
  echo "report: $report"
  exit 0
fi

if [[ "$MODE" == "apply" && "$CREATE_BRANCH" == "1" ]]; then
  candidate_branch="hermes-upstream-sync/$stamp"
  git switch -c "$candidate_branch"
fi

patch_message=""
patch_status="dry_run_passed"
already_applied_count=0
for patch_file in "${patches[@]}"; do
  if ! output="$(git apply --ignore-space-change --ignore-whitespace --check "$patch_file" 2>&1)"; then
    if git apply --ignore-space-change --ignore-whitespace --reverse --check "$patch_file" >/dev/null 2>&1; then
      already_applied_count=$((already_applied_count + 1))
      continue
    fi
    patch_status="held_conflict"
    patch_message="$patch_file: $output"
    write_json "$report" "held_conflict" "$remote_sha" "$local_sha" "$patch_message" "$patch_status"
    cp "$report" "$STATE_FILE"
    echo "held_conflict: $patch_file"
    echo "$output"
    echo "report: $report"
    exit 1
  fi
done

if [[ "$MODE" == "apply" ]]; then
  for patch_file in "${patches[@]}"; do
    if git apply --ignore-space-change --ignore-whitespace --reverse --check "$patch_file" >/dev/null 2>&1; then
      continue
    fi
    git apply --ignore-space-change --ignore-whitespace "$patch_file"
  done
  patch_status="applied_candidate"
fi

test_status="not_run"
if [[ "$RUN_TESTS" == "1" ]]; then
  if "$ROOT/venv/bin/python" -m py_compile "$ROOT/cli.py" "$ROOT/run_agent.py" "$ROOT/hermes_cli/config.py" "$ROOT/hermes_cli/main.py"; then
    test_status="passed"
  else
    test_status="failed"
    write_json "$report" "test_failed" "$remote_sha" "$local_sha" "py_compile failed" "$patch_status"
    cp "$report" "$STATE_FILE"
    echo "test_failed: py_compile"
    echo "report: $report"
    exit 1
  fi
fi

status="detected"
if [[ -n "$last_remote_sha" && "$last_remote_sha" == "$remote_sha" ]]; then
  status="no_update"
elif [[ "$MODE" == "apply" ]]; then
  status="applied_candidate"
elif [[ "$patch_status" == "dry_run_passed" ]]; then
  status="dry_run_passed"
fi

write_json "$report" "$status" "$remote_sha" "$local_sha" "tests=$test_status patches=${#patches[@]} already_applied=$already_applied_count" "$patch_status"
cp "$report" "$STATE_FILE"

echo "$status: remote=$remote_sha local=$local_sha patches=${#patches[@]} already_applied=$already_applied_count tests=$test_status"
echo "report: $report"
