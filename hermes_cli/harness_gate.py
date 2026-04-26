"""Plan-first harness gate for Hermes mutating tools.

This mirrors the Claude `.planning` gate for Hermes tool dispatch.
"""

from __future__ import annotations

import json
import os
import re
import shlex
from pathlib import Path
from typing import Any, Iterable


READ_ONLY_COMMANDS = {
    "cat",
    "find",
    "git",
    "head",
    "ls",
    "nl",
    "pwd",
    "rg",
    "sed",
    "tail",
    "wc",
}
READ_ONLY_GIT_SUBCOMMANDS = {
    "branch",
    "diff",
    "log",
    "ls-files",
    "rev-parse",
    "show",
    "status",
}
SKIPPABLE_PREFIX_WORDS = {"env", "command", "builtin", "exec", "noglob", "sudo", "nohup"}
PREFIX_OPTION_VALUE_WORDS = {
    "env": {"-u", "-C", "-S", "--unset", "--chdir", "--split-string"},
    "sudo": {
        "-u",
        "-g",
        "-h",
        "-p",
        "-r",
        "-t",
        "-C",
        "--user",
        "--group",
        "--host",
        "--prompt",
        "--role",
        "--type",
        "--close-from",
    },
}
EXECUTION_STAGES = {"packet_a_execution", "packet_a_verify", "packet_a_verified"}
REQUIRED_PLAN_HEADINGS = ("## Event", "## Function", "## Steps", "## Verify", "## Closeout")
PATCH_FILE_RE = re.compile(r"^\*\*\* (?:Update|Add|Delete) File: (.+)$")
MCP_TOOL_SUFFIXES = ("write_file", "patch", "terminal")


def _is_planning_path(file_path: str) -> bool:
    return "/.planning/" in file_path or file_path.startswith(".planning/")


def _canonical_tool_name(tool_name: str) -> str:
    if tool_name in {"terminal", "write_file", "patch"}:
        return tool_name
    if not tool_name.startswith("mcp_"):
        return tool_name
    for suffix in MCP_TOOL_SUFFIXES:
        if tool_name.endswith(f"_{suffix}"):
            return suffix
    return tool_name


def _normalize_relative(cwd: str, target_path: str) -> str:
    absolute = os.path.abspath(target_path if os.path.isabs(target_path) else os.path.join(cwd, target_path))
    return os.path.relpath(absolute, cwd).replace(os.sep, "/")


def _read_harness_state(cwd: str) -> dict[str, Any]:
    planning_dir = os.path.join(cwd, ".planning")
    plan_path = os.path.join(planning_dir, "active-plan.md")
    state_path = os.path.join(planning_dir, "harness.json")

    if not os.path.exists(plan_path):
        return {"ok": False, "reason": "missing-plan", "plan_path": plan_path, "state_path": state_path}

    plan_content = Path(plan_path).read_text(encoding="utf-8")
    missing_headings = [heading for heading in REQUIRED_PLAN_HEADINGS if heading not in plan_content]
    if missing_headings:
        return {
            "ok": False,
            "reason": "incomplete-plan",
            "plan_path": plan_path,
            "state_path": state_path,
            "missing_headings": missing_headings,
        }

    if not os.path.exists(state_path):
        return {"ok": False, "reason": "missing-state", "plan_path": plan_path, "state_path": state_path}

    try:
        state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "ok": False,
            "reason": "invalid-state-json",
            "plan_path": plan_path,
            "state_path": state_path,
            "error": str(exc),
        }

    if not isinstance(state, dict):
        return {"ok": False, "reason": "invalid-state-shape", "plan_path": plan_path, "state_path": state_path}

    if not isinstance(state.get("stage"), str) or not state["stage"]:
        return {"ok": False, "reason": "missing-stage", "plan_path": plan_path, "state_path": state_path}
    if not isinstance(state.get("packet"), str) or not state["packet"]:
        return {"ok": False, "reason": "missing-packet", "plan_path": plan_path, "state_path": state_path}
    if not isinstance(state.get("allowed_files"), list):
        return {"ok": False, "reason": "missing-allowed-files", "plan_path": plan_path, "state_path": state_path}

    return {"ok": True, "plan_path": plan_path, "state_path": state_path, "state": state}


def _is_execution_ready(check: dict[str, Any]) -> bool:
    state = check.get("state") or {}
    return bool(
        check.get("ok")
        and state.get("stage") in EXECUTION_STAGES
        and state.get("packet") == "A"
        and isinstance(state.get("allowed_files"), list)
        and len(state["allowed_files"]) > 0
    )


def _is_allowed_target(cwd: str, state: dict[str, Any], target_path: str) -> bool:
    relative_target = _normalize_relative(cwd, target_path)
    if not relative_target or relative_target.startswith(".."):
        return False

    for entry in state.get("allowed_files", []):
        if not isinstance(entry, str) or not entry.strip():
            continue
        normalized_entry = entry.replace("\\", "/").rstrip("/")
        if relative_target == normalized_entry or relative_target.startswith(f"{normalized_entry}/"):
            return True
    return False


def _tokenize_shell(command: str) -> list[str]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars="|&;")
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def _split_shell_segments(command: str) -> list[list[str]]:
    if not command.strip():
        return []
    segments: list[list[str]] = []
    current: list[str] = []
    for token in _tokenize_shell(command):
        if token in {"|", "||", "&", "&&", ";"}:
            if current:
                segments.append(current)
                current = []
            continue
        current.append(token)
    if current:
        segments.append(current)
    return segments


def _leading_command_tokens(tokens: list[str]) -> list[str]:
    active_wrapper = None
    skip_next_value = False
    result: list[str] = []

    for token in tokens:
        if skip_next_value:
            skip_next_value = False
            continue
        if token == "--":
            active_wrapper = None
            continue
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=.*$", token):
            continue
        normalized = os.path.basename(token).lower()
        if normalized in SKIPPABLE_PREFIX_WORDS:
            active_wrapper = normalized
            continue
        if active_wrapper and token.startswith("-") and token in PREFIX_OPTION_VALUE_WORDS.get(active_wrapper, set()):
            skip_next_value = True
            continue
        result.append(token)
    return result


def _is_read_only_bash_command(command: str) -> bool:
    segments = _split_shell_segments(command)
    if not segments:
        return True

    for segment in segments:
        tokens = _leading_command_tokens(segment)
        if not tokens:
            continue
        command_word = os.path.basename(tokens[0]).lower()
        if command_word not in READ_ONLY_COMMANDS:
            return False
        if command_word == "git":
            if len(tokens) < 2 or tokens[1] not in READ_ONLY_GIT_SUBCOMMANDS:
                return False
    return True


def _explain_missing_plan(check: dict[str, Any]) -> str:
    lines = [
        "Harness gate blocked this tool call: plan-first workflow is mandatory before mutating tools or non-read-only terminal commands.",
        f"Required plan file: {check['plan_path']}",
        f"Required state file: {check['state_path']}",
        "Create .planning/active-plan.md with headings: ## Event, ## Function, ## Steps, ## Verify, ## Closeout.",
        'Create .planning/harness.json with at least: {"stage":"packet_a_execution","packet":"A","allowed_files":["path/to/file"]}.',
        "Only .planning/* writes and read-only inventory commands are allowed before that.",
    ]
    missing = check.get("missing_headings")
    if missing:
        lines.insert(4, f"Missing plan headings: {', '.join(missing)}")
    error = check.get("error")
    if error:
        lines.insert(4, f"State file JSON error: {error}")
    return "\n".join(lines)


def _extract_patch_paths(patch_text: str) -> list[str]:
    paths: list[str] = []
    for line in patch_text.splitlines():
        match = PATCH_FILE_RE.match(line.strip())
        if match:
            paths.append(match.group(1).strip())
    return paths


def _iter_mutation_targets(tool_name: str, args: dict[str, Any]) -> Iterable[str]:
    if tool_name == "write_file":
        path = args.get("path")
        if isinstance(path, str) and path:
            yield path
        return

    if tool_name != "patch":
        return

    mode = args.get("mode", "replace")
    if mode == "replace":
        path = args.get("path")
        if isinstance(path, str) and path:
            yield path
        return

    patch_text = args.get("patch")
    if isinstance(patch_text, str):
        for path in _extract_patch_paths(patch_text):
            yield path


def check_tool_gate(tool_name: str, args: dict[str, Any] | None, cwd: str | None = None) -> str | None:
    """Return an error message when a mutating tool should be blocked."""
    args = args or {}
    cwd = os.path.abspath(cwd or os.getcwd())
    canonical_tool_name = _canonical_tool_name(tool_name)

    if canonical_tool_name == "terminal":
        command = str(args.get("command") or "").strip()
        if _is_read_only_bash_command(command):
            return None
        check = _read_harness_state(cwd)
        if not _is_execution_ready(check):
            return _explain_missing_plan(check)
        return None

    if canonical_tool_name not in {"write_file", "patch"}:
        return None

    targets = list(_iter_mutation_targets(canonical_tool_name, args))
    if not targets:
        return None

    non_planning_targets = [path for path in targets if not _is_planning_path(path)]
    if not non_planning_targets:
        return None

    check = _read_harness_state(cwd)
    if not _is_execution_ready(check):
        return _explain_missing_plan(check)

    state = check["state"]
    for target in non_planning_targets:
        if not _is_allowed_target(cwd, state, target):
            relative_target = _normalize_relative(cwd, target)
            allowed = ", ".join(state.get("allowed_files", []))
            return (
                "Harness gate blocked this tool call: scope creep outside locked packet file set.\n"
                f"Target: {relative_target}\n"
                f"Allowed files: {allowed}\n"
                "Update .planning/harness.json only after closing packet A and explicitly widening scope."
            )

    return None
