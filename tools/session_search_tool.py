#!/usr/bin/env python3
"""
Session Search Tool - Long-Term Conversation Recall

Searches past session transcripts in SQLite via FTS5, then summarizes the top
matching sessions using the configured session_search auxiliary model.
Returns focused summaries of past conversations rather than raw transcripts,
keeping the main model's context window clean.

Flow:
  1. FTS5 search finds matching messages ranked by relevance
  2. Groups by session, takes the top N unique sessions (default 3)
  3. Loads each session's conversation, truncates to ~100k chars centered on matches
  4. Summarizes sessions one at a time with a focused recall prompt
  5. Returns per-session summaries with metadata
"""

import asyncio
import concurrent.futures
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Union

from agent.auxiliary_client import async_call_llm, extract_content_or_reasoning
MAX_SESSION_CHARS = 100_000
MAX_SUMMARY_TOKENS = 10000
SESSION_SUMMARY_MAX_RETRIES = 1
HERMES_HOME = Path.home() / ".hermes"
CASES_ROOT = HERMES_HOME / "learning" / "cases"
WORK_KNOWLEDGE_ROOT = HERMES_HOME / "learning" / "work"
PROMOTION_QUEUE_ROOT = HERMES_HOME / "learning" / "queue" / "promotions"
_REVIEW_READY_CASE_VERDICTS = {"approved", "addressed"}


def _format_timestamp(ts: Union[int, float, str, None]) -> str:
    """Convert a Unix timestamp (float/int) or ISO string to a human-readable date.

    Returns "unknown" for None, str(ts) if conversion fails.
    """
    if ts is None:
        return "unknown"
    try:
        if isinstance(ts, (int, float)):
            from datetime import datetime
            dt = datetime.fromtimestamp(ts)
            return dt.strftime("%B %d, %Y at %I:%M %p")
        if isinstance(ts, str):
            if ts.replace(".", "").replace("-", "").isdigit():
                from datetime import datetime
                dt = datetime.fromtimestamp(float(ts))
                return dt.strftime("%B %d, %Y at %I:%M %p")
            return ts
    except (ValueError, OSError, OverflowError) as e:
        # Log specific errors for debugging while gracefully handling edge cases
        logging.debug("Failed to format timestamp %s: %s", ts, e, exc_info=True)
    except Exception as e:
        logging.debug("Unexpected error formatting timestamp %s: %s", ts, e, exc_info=True)
    return str(ts)


def _format_conversation(messages: List[Dict[str, Any]]) -> str:
    """Format session messages into a readable transcript for summarization."""
    parts = []
    for msg in messages:
        role = msg.get("role", "unknown").upper()
        content = msg.get("content") or ""
        tool_name = msg.get("tool_name")

        if role == "TOOL" and tool_name:
            # Truncate long tool outputs
            if len(content) > 500:
                content = content[:250] + "\n...[truncated]...\n" + content[-250:]
            parts.append(f"[TOOL:{tool_name}]: {content}")
        elif role == "ASSISTANT":
            # Include tool call names if present
            tool_calls = msg.get("tool_calls")
            if tool_calls and isinstance(tool_calls, list):
                tc_names = []
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        name = tc.get("name") or tc.get("function", {}).get("name", "?")
                        tc_names.append(name)
                if tc_names:
                    parts.append(f"[ASSISTANT]: [Called: {', '.join(tc_names)}]")
                if content:
                    parts.append(f"[ASSISTANT]: {content}")
            else:
                parts.append(f"[ASSISTANT]: {content}")
        else:
            parts.append(f"[{role}]: {content}")

    return "\n\n".join(parts)


def _local_now() -> datetime:
    return datetime.now().astimezone()


def _compact_text(value: Any, limit: int = 280) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 14].rstrip() + " ...[truncated]"


def _coerce_text_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [item for item in (_compact_text(v) for v in value) if item]
    if value is None:
        return []
    text = _compact_text(value)
    return [text] if text else []


def _parse_query_terms(query: str) -> tuple[List[str], List[str]]:
    lowered = " ".join((query or "").lower().split())
    phrases: List[str] = []
    seen_phrases = set()
    for match in re.finditer(r'"([^"]+)"', lowered):
        phrase = " ".join(match.group(1).split())
        if phrase and phrase not in seen_phrases:
            phrases.append(phrase)
            seen_phrases.add(phrase)

    tokens: List[str] = []
    seen_tokens = set()
    for token in re.findall(r"[a-z0-9_./:-]+", lowered):
        if token in {"and", "or", "not"}:
            continue
        if len(token) < 2 and not any(ch.isdigit() for ch in token):
            continue
        if token not in seen_tokens:
            tokens.append(token)
            seen_tokens.add(token)

    return phrases, tokens


def _should_search_learning_artifacts(query: str) -> bool:
    phrases, tokens = _parse_query_terms(query)
    return bool(phrases) or len(tokens) >= 2


def _recent_query_window(query: str) -> Optional[tuple[str, datetime.date, datetime.date]]:
    normalized = " ".join((query or "").strip().lower().split())
    today = _local_now().date()

    if normalized in {"today", "오늘"}:
        return ("today", today, today)
    if normalized in {"yesterday", "어제"}:
        target = today - timedelta(days=1)
        return ("yesterday", target, target)
    if normalized in {"recent", "recently", "lately", "최근"}:
        return ("recent", today - timedelta(days=6), today)
    return None


def _field_match_score(value: Any, phrases: List[str], terms: List[str], weight: int = 1) -> tuple[int, set[str]]:
    text = str(value or "").strip()
    if not text:
        return 0, set()

    lowered = text.lower()
    score = 0
    matched: set[str] = set()
    for phrase in phrases:
        if phrase in lowered:
            score += 12 * weight
            matched.add(phrase)
    for term in terms:
        if term in lowered:
            score += 4 * weight
            matched.add(term)
    return score, matched


def _matched_snippet(value: Any, phrases: List[str], terms: List[str], limit: int = 320) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return ""

    lowered = text.lower()
    needles = [*phrases, *terms]
    first_match = None
    for needle in needles:
        pos = lowered.find(needle)
        if pos != -1 and (first_match is None or pos < first_match):
            first_match = pos

    if first_match is None:
        return _compact_text(text, limit)

    start = max(0, first_match - (limit // 3))
    end = min(len(text), start + limit)
    if end - start < limit and start > 0:
        start = max(0, end - limit)

    snippet = text[start:end]
    if start > 0:
        snippet = "...[truncated] " + snippet
    if end < len(text):
        snippet = snippet + " ...[truncated]"
    return snippet


def _safe_load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _artifact_sort_timestamp(date_str: Optional[str], fallback_path: Path) -> float:
    if date_str:
        try:
            return datetime.strptime(str(date_str), "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
        except Exception:
            pass
    try:
        return fallback_path.stat().st_mtime
    except Exception:
        return 0.0


def _timestamp_to_local_date(ts: Union[int, float, str, None]) -> Optional[datetime.date]:
    if ts is None:
        return None
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(float(ts)).astimezone().date()
        if isinstance(ts, str):
            stripped = ts.strip()
            if not stripped:
                return None
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", stripped):
                return datetime.strptime(stripped, "%Y-%m-%d").date()
            if stripped.replace(".", "").replace("-", "").isdigit():
                return datetime.fromtimestamp(float(stripped)).astimezone().date()
            iso = stripped.replace("Z", "+00:00")
            return datetime.fromisoformat(iso).astimezone().date()
    except Exception:
        return None
    return None


def _search_promoted_cases(query: str, limit: int) -> List[Dict[str, Any]]:
    phrases, terms = _parse_query_terms(query)
    if not phrases and not terms:
        return []
    if not CASES_ROOT.exists():
        return []

    hits: List[Dict[str, Any]] = []
    for path in sorted(CASES_ROOT.rglob("*.json")):
        path_str = str(path)
        if path.name == "schema-case-v1.json" or "/pending/" in path_str or "/dismissed/" in path_str:
            continue

        case = _safe_load_json(path)
        if not case:
            continue
        if str(case.get("review_verdict") or "").strip() not in _REVIEW_READY_CASE_VERDICTS:
            continue
        if str(case.get("promotion_decision") or "").strip() != "promoted":
            continue

        score = 0
        matched: set[str] = set()
        for value, weight in (
            (case.get("case_id"), 5),
            (case.get("objective"), 5),
            (case.get("root_cause"), 4),
            (" ".join(_coerce_text_list(case.get("what_worked"))), 3),
            (" ".join(_coerce_text_list(case.get("what_failed"))), 2),
            (" ".join(_coerce_text_list(case.get("tooling_used"))), 2),
            (" ".join(_coerce_text_list(case.get("artifacts"))), 1),
            (case.get("notes"), 1),
        ):
            field_score, field_matched = _field_match_score(value, phrases, terms, weight)
            score += field_score
            matched.update(field_matched)

        if score <= 0:
            continue

        summary_text = "\n".join(
            part for part in (
                case.get("objective"),
                case.get("root_cause"),
                "Worked: " + "; ".join(_coerce_text_list(case.get("what_worked"))[:2]) if case.get("what_worked") else "",
                "Failed: " + "; ".join(_coerce_text_list(case.get("what_failed"))[:2]) if case.get("what_failed") else "",
                case.get("notes"),
            ) if part
        )

        hits.append({
            "artifact_type": "case",
            "artifact_id": str(case.get("case_id") or path.stem),
            "when": str(case.get("date") or _format_timestamp(path.stat().st_mtime)),
            "source": f"reviewed_case:{case.get('domain') or 'unknown'}",
            "model": (case.get("registration") or {}).get("source") or (case.get("models_and_agents") or [None])[0],
            "title": _compact_text(case.get("objective") or case.get("case_id") or path.stem, 140),
            "summary": _matched_snippet(summary_text, phrases, terms),
            "path": str(path),
            "_priority": 0,
            "_score": score + len(matched),
            "_sort_ts": _artifact_sort_timestamp(case.get("date"), path),
            "_case_id": str(case.get("case_id") or path.stem),
        })

    hits.sort(key=lambda item: (-item["_score"], -item["_sort_ts"], item["artifact_id"]))
    return hits[:limit]


def _read_work_doc_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or fallback
    return fallback


def _search_work_docs(query: str, limit: int) -> List[Dict[str, Any]]:
    phrases, terms = _parse_query_terms(query)
    if not phrases and not terms:
        return []
    if not WORK_KNOWLEDGE_ROOT.exists():
        return []

    hits: List[Dict[str, Any]] = []
    for path in sorted(WORK_KNOWLEDGE_ROOT.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".md", ".markdown"}:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            continue

        title = _read_work_doc_title(content, path.stem)
        score = 0
        matched: set[str] = set()
        for value, weight in ((title, 5), (content, 2), (path.as_posix(), 1)):
            field_score, field_matched = _field_match_score(value, phrases, terms, weight)
            score += field_score
            matched.update(field_matched)

        if score <= 0:
            continue

        relative_path = path.relative_to(WORK_KNOWLEDGE_ROOT).as_posix()
        hits.append({
            "artifact_type": "work_knowledge",
            "artifact_id": relative_path,
            "when": _format_timestamp(path.stat().st_mtime),
            "source": "work_knowledge",
            "model": None,
            "title": _compact_text(title, 140),
            "summary": _matched_snippet(content, phrases, terms),
            "path": str(path),
            "_priority": 1,
            "_score": score + len(matched),
            "_sort_ts": path.stat().st_mtime,
            "_case_id": None,
        })

    hits.sort(key=lambda item: (-item["_score"], -item["_sort_ts"], item["artifact_id"]))
    return hits[:limit]


def _search_promotion_packets(query: str, limit: int, excluded_case_ids: set[str]) -> List[Dict[str, Any]]:
    phrases, terms = _parse_query_terms(query)
    if not phrases and not terms:
        return []
    if not PROMOTION_QUEUE_ROOT.exists():
        return []

    hits: List[Dict[str, Any]] = []
    for path in sorted(PROMOTION_QUEUE_ROOT.rglob("*.json")):
        packet = _safe_load_json(path)
        if not packet:
            continue

        case_ids = [str(item).strip() for item in packet.get("source_case_ids") or [] if str(item).strip()]
        primary_case_id = case_ids[0] if case_ids else None
        if primary_case_id and primary_case_id in excluded_case_ids:
            continue

        evidence_bundle = packet.get("evidence_bundle") or {}
        score = 0
        matched: set[str] = set()
        for value, weight in (
            (packet.get("packet_id"), 4),
            (" ".join(case_ids), 4),
            (packet.get("notes"), 2),
            (" ".join(_coerce_text_list(evidence_bundle.get("worked"))), 3),
            (" ".join(_coerce_text_list(evidence_bundle.get("failed"))), 2),
            (" ".join(_coerce_text_list(evidence_bundle.get("files"))), 1),
        ):
            field_score, field_matched = _field_match_score(value, phrases, terms, weight)
            score += field_score
            matched.update(field_matched)

        if score <= 0:
            continue

        summary_text = "\n".join(
            part for part in (
                packet.get("notes"),
                "Worked: " + "; ".join(_coerce_text_list(evidence_bundle.get("worked"))[:2]) if evidence_bundle.get("worked") else "",
                "Failed: " + "; ".join(_coerce_text_list(evidence_bundle.get("failed"))[:2]) if evidence_bundle.get("failed") else "",
            ) if part
        )

        hits.append({
            "artifact_type": "promotion_packet",
            "artifact_id": str(packet.get("packet_id") or path.stem),
            "when": _format_timestamp(path.stat().st_mtime),
            "source": "promotion_queue",
            "model": packet.get("generator_owner"),
            "title": _compact_text(f"Promotion packet for {primary_case_id or path.stem}", 140),
            "summary": _matched_snippet(summary_text, phrases, terms),
            "path": str(path),
            "_priority": 2,
            "_score": score + len(matched),
            "_sort_ts": path.stat().st_mtime,
            "_case_id": primary_case_id,
        })

    hits.sort(key=lambda item: (-item["_score"], -item["_sort_ts"], item["artifact_id"]))
    return hits[:limit]


def _search_learning_artifacts(query: str, limit: int) -> List[Dict[str, Any]]:
    case_hits = _search_promoted_cases(query, limit)
    work_hits = _search_work_docs(query, limit)
    excluded_case_ids = {
        hit["_case_id"] for hit in case_hits if hit.get("_case_id")
    }
    packet_hits = _search_promotion_packets(query, limit, excluded_case_ids)

    ordered_hits = [*case_hits, *work_hits, *packet_hits]
    ordered_hits.sort(key=lambda item: (item["_priority"], -item["_score"], -item["_sort_ts"], item["artifact_id"]))

    results: List[Dict[str, Any]] = []
    seen = set()
    for hit in ordered_hits:
        key = (hit["artifact_type"], hit["artifact_id"])
        if key in seen:
            continue
        seen.add(key)
        results.append({
            "artifact_type": hit["artifact_type"],
            "artifact_id": hit["artifact_id"],
            "when": hit["when"],
            "source": hit["source"],
            "model": hit["model"],
            "title": hit["title"],
            "summary": hit["summary"],
            "path": hit["path"],
        })
        if len(results) >= limit:
            break

    return results


def _date_in_window(value: Optional[datetime.date], start_date: datetime.date, end_date: datetime.date) -> bool:
    return bool(value and start_date <= value <= end_date)


def _search_recent_promoted_cases(limit: int, start_date: datetime.date, end_date: datetime.date) -> List[Dict[str, Any]]:
    if not CASES_ROOT.exists():
        return []

    hits: List[Dict[str, Any]] = []
    for path in sorted(CASES_ROOT.rglob("*.json")):
        path_str = str(path)
        if path.name == "schema-case-v1.json" or "/pending/" in path_str or "/dismissed/" in path_str:
            continue

        case = _safe_load_json(path)
        if not case:
            continue
        if str(case.get("review_verdict") or "").strip() not in _REVIEW_READY_CASE_VERDICTS:
            continue
        if str(case.get("promotion_decision") or "").strip() != "promoted":
            continue

        case_date = _timestamp_to_local_date(case.get("date"))
        if not _date_in_window(case_date, start_date, end_date):
            continue

        summary = "\n".join(
            part for part in (
                case.get("objective"),
                case.get("root_cause"),
                "Worked: " + "; ".join(_coerce_text_list(case.get("what_worked"))[:2]) if case.get("what_worked") else "",
                "Failed: " + "; ".join(_coerce_text_list(case.get("what_failed"))[:2]) if case.get("what_failed") else "",
            ) if part
        )

        hits.append({
            "artifact_type": "case",
            "artifact_id": str(case.get("case_id") or path.stem),
            "when": str(case.get("date") or _format_timestamp(path.stat().st_mtime)),
            "source": f"reviewed_case:{case.get('domain') or 'unknown'}",
            "model": (case.get("registration") or {}).get("source") or (case.get("models_and_agents") or [None])[0],
            "title": _compact_text(case.get("objective") or case.get("case_id") or path.stem, 140),
            "summary": _compact_text(summary, 320),
            "path": str(path),
            "_priority": 0,
            "_sort_ts": _artifact_sort_timestamp(case.get("date"), path),
            "_case_id": str(case.get("case_id") or path.stem),
        })

    hits.sort(key=lambda item: (-item["_sort_ts"], item["artifact_id"]))
    return hits[:limit]


def _search_recent_work_docs(limit: int, start_date: datetime.date, end_date: datetime.date) -> List[Dict[str, Any]]:
    if not WORK_KNOWLEDGE_ROOT.exists():
        return []

    hits: List[Dict[str, Any]] = []
    for path in sorted(WORK_KNOWLEDGE_ROOT.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".md", ".markdown"}:
            continue

        modified_date = _timestamp_to_local_date(path.stat().st_mtime)
        if not _date_in_window(modified_date, start_date, end_date):
            continue

        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            continue

        title = _read_work_doc_title(content, path.stem)
        hits.append({
            "artifact_type": "work_knowledge",
            "artifact_id": path.relative_to(WORK_KNOWLEDGE_ROOT).as_posix(),
            "when": _format_timestamp(path.stat().st_mtime),
            "source": "work_knowledge",
            "model": None,
            "title": _compact_text(title, 140),
            "summary": _compact_text(content, 320),
            "path": str(path),
            "_priority": 1,
            "_sort_ts": path.stat().st_mtime,
            "_case_id": None,
        })

    hits.sort(key=lambda item: (-item["_sort_ts"], item["artifact_id"]))
    return hits[:limit]


def _search_recent_promotion_packets(limit: int, start_date: datetime.date, end_date: datetime.date, excluded_case_ids: set[str]) -> List[Dict[str, Any]]:
    if not PROMOTION_QUEUE_ROOT.exists():
        return []

    hits: List[Dict[str, Any]] = []
    for path in sorted(PROMOTION_QUEUE_ROOT.rglob("*.json")):
        modified_date = _timestamp_to_local_date(path.stat().st_mtime)
        if not _date_in_window(modified_date, start_date, end_date):
            continue

        packet = _safe_load_json(path)
        if not packet:
            continue

        case_ids = [str(item).strip() for item in packet.get("source_case_ids") or [] if str(item).strip()]
        primary_case_id = case_ids[0] if case_ids else None
        if primary_case_id and primary_case_id in excluded_case_ids:
            continue

        evidence_bundle = packet.get("evidence_bundle") or {}
        summary = "\n".join(
            part for part in (
                packet.get("notes"),
                "Worked: " + "; ".join(_coerce_text_list(evidence_bundle.get("worked"))[:2]) if evidence_bundle.get("worked") else "",
                "Failed: " + "; ".join(_coerce_text_list(evidence_bundle.get("failed"))[:2]) if evidence_bundle.get("failed") else "",
            ) if part
        )

        hits.append({
            "artifact_type": "promotion_packet",
            "artifact_id": str(packet.get("packet_id") or path.stem),
            "when": _format_timestamp(path.stat().st_mtime),
            "source": "promotion_queue",
            "model": packet.get("generator_owner"),
            "title": _compact_text(f"Promotion packet for {primary_case_id or path.stem}", 140),
            "summary": _compact_text(summary, 320),
            "path": str(path),
            "_priority": 2,
            "_sort_ts": path.stat().st_mtime,
            "_case_id": primary_case_id,
        })

    hits.sort(key=lambda item: (-item["_sort_ts"], item["artifact_id"]))
    return hits[:limit]


def _search_recent_learning_artifacts(limit: int, start_date: datetime.date, end_date: datetime.date) -> List[Dict[str, Any]]:
    case_hits = _search_recent_promoted_cases(limit, start_date, end_date)
    work_hits = _search_recent_work_docs(limit, start_date, end_date)
    excluded_case_ids = {
        hit["_case_id"] for hit in case_hits if hit.get("_case_id")
    }
    packet_hits = _search_recent_promotion_packets(limit, start_date, end_date, excluded_case_ids)

    ordered_hits = [*case_hits, *work_hits, *packet_hits]
    ordered_hits.sort(key=lambda item: (-item["_sort_ts"], item["_priority"], item["artifact_id"]))

    results: List[Dict[str, Any]] = []
    seen = set()
    for hit in ordered_hits:
        key = (hit["artifact_type"], hit["artifact_id"])
        if key in seen:
            continue
        seen.add(key)
        results.append({
            "artifact_type": hit["artifact_type"],
            "artifact_id": hit["artifact_id"],
            "when": hit["when"],
            "source": hit["source"],
            "model": hit["model"],
            "title": hit["title"],
            "summary": hit["summary"],
            "path": hit["path"],
        })
        if len(results) >= limit:
            break
    return results


def _list_recent_sessions_window(db, limit: int, current_session_id: str, start_date: datetime.date, end_date: datetime.date) -> List[Dict[str, Any]]:
    try:
        sessions = db.list_sessions_rich(limit=max(limit + 10, 20), exclude_sources=list(_HIDDEN_SESSION_SOURCES))
    except Exception:
        return []

    current_root = None
    if current_session_id:
        try:
            sid = current_session_id
            visited = set()
            while sid and sid not in visited:
                visited.add(sid)
                s = db.get_session(sid)
                parent = s.get("parent_session_id") if s else None
                sid = parent if parent else None
            current_root = max(visited, key=len) if visited else current_session_id
        except Exception:
            current_root = current_session_id

    results: List[Dict[str, Any]] = []
    for session in sessions:
        sid = session.get("id", "")
        if current_root and (sid == current_root or sid == current_session_id):
            continue
        if session.get("parent_session_id"):
            continue

        session_date = _timestamp_to_local_date(session.get("started_at") or session.get("last_active"))
        if not _date_in_window(session_date, start_date, end_date):
            continue

        results.append({
            "artifact_type": "recent_session",
            "session_id": sid,
            "when": _format_timestamp(session.get("started_at") or session.get("last_active")),
            "source": session.get("source", ""),
            "model": session.get("model"),
            "title": session.get("title") or None,
            "summary": _compact_text(session.get("preview") or "No preview available.", 320),
            "message_count": session.get("message_count", 0),
        })
        if len(results) >= limit:
            break

    return results


def _truncate_around_matches(
    full_text: str, query: str, max_chars: int = MAX_SESSION_CHARS
) -> str:
    """
    Truncate a conversation transcript to *max_chars*, choosing a window
    that maximises coverage of positions where the *query* actually appears.

    Strategy (in priority order):
    1. Try to find the full query as a phrase (case-insensitive).
    2. If no phrase hit, look for positions where all query terms appear
       within a 200-char proximity window (co-occurrence).
    3. Fall back to individual term positions.

    Once candidate positions are collected the function picks the window
    start that covers the most of them.
    """
    if len(full_text) <= max_chars:
        return full_text

    text_lower = full_text.lower()
    query_lower = query.lower().strip()
    match_positions: list[int] = []

    # --- 1. Full-phrase search ------------------------------------------------
    phrase_pat = re.compile(re.escape(query_lower))
    match_positions = [m.start() for m in phrase_pat.finditer(text_lower)]

    # --- 2. Proximity co-occurrence of all terms (within 200 chars) -----------
    if not match_positions:
        terms = query_lower.split()
        if len(terms) > 1:
            # Collect every occurrence of each term
            term_positions: dict[str, list[int]] = {}
            for t in terms:
                term_positions[t] = [
                    m.start() for m in re.finditer(re.escape(t), text_lower)
                ]
            # Slide through positions of the rarest term and check proximity
            rarest = min(terms, key=lambda t: len(term_positions.get(t, [])))
            for pos in term_positions.get(rarest, []):
                if all(
                    any(abs(p - pos) < 200 for p in term_positions.get(t, []))
                    for t in terms
                    if t != rarest
                ):
                    match_positions.append(pos)

    # --- 3. Individual term positions (last resort) ---------------------------
    if not match_positions:
        terms = query_lower.split()
        for t in terms:
            for m in re.finditer(re.escape(t), text_lower):
                match_positions.append(m.start())

    if not match_positions:
        # Nothing at all — take from the start
        truncated = full_text[:max_chars]
        suffix = "\n\n...[later conversation truncated]..." if max_chars < len(full_text) else ""
        return truncated + suffix

    # --- Pick window that covers the most match positions ---------------------
    match_positions.sort()

    best_start = 0
    best_count = 0
    for candidate in match_positions:
        ws = max(0, candidate - max_chars // 4)  # bias: 25% before, 75% after
        we = ws + max_chars
        if we > len(full_text):
            ws = max(0, len(full_text) - max_chars)
            we = len(full_text)
        count = sum(1 for p in match_positions if ws <= p < we)
        if count > best_count:
            best_count = count
            best_start = ws

    start = best_start
    end = min(len(full_text), start + max_chars)

    truncated = full_text[start:end]
    prefix = "...[earlier conversation truncated]...\n\n" if start > 0 else ""
    suffix = "\n\n...[later conversation truncated]..." if end < len(full_text) else ""
    return prefix + truncated + suffix


async def _summarize_session(
    conversation_text: str, query: str, session_meta: Dict[str, Any]
) -> Optional[str]:
    """Summarize a single session conversation focused on the search query."""
    system_prompt = (
        "You are reviewing a past conversation transcript to help recall what happened. "
        "Summarize the conversation with a focus on the search topic. Include:\n"
        "1. What the user asked about or wanted to accomplish\n"
        "2. What actions were taken and what the outcomes were\n"
        "3. Key decisions, solutions found, or conclusions reached\n"
        "4. Any specific commands, files, URLs, or technical details that were important\n"
        "5. Anything left unresolved or notable\n\n"
        "Be thorough but concise. Preserve specific details (commands, paths, error messages) "
        "that would be useful to recall. Write in past tense as a factual recap."
    )

    source = session_meta.get("source", "unknown")
    started = _format_timestamp(session_meta.get("started_at"))

    user_prompt = (
        f"Search topic: {query}\n"
        f"Session source: {source}\n"
        f"Session date: {started}\n\n"
        f"CONVERSATION TRANSCRIPT:\n{conversation_text}\n\n"
        f"Summarize this conversation with focus on: {query}"
    )

    # Fail fast and fall back to raw previews instead of blocking recall on
    # repeated retries from a slow auxiliary backend.
    max_retries = SESSION_SUMMARY_MAX_RETRIES
    for attempt in range(max_retries):
        try:
            response = await async_call_llm(
                task="session_search",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
                max_tokens=MAX_SUMMARY_TOKENS,
            )
            content = extract_content_or_reasoning(response)
            if content:
                return content
            # Reasoning-only / empty — let the retry loop handle it
            logging.warning("Session search LLM returned empty content (attempt %d/%d)", attempt + 1, max_retries)
            if attempt < max_retries - 1:
                await asyncio.sleep(1 * (attempt + 1))
                continue
            return content
        except RuntimeError:
            logging.warning("No auxiliary model available for session summarization")
            return None
        except Exception as e:
            if attempt < max_retries - 1:
                await asyncio.sleep(1 * (attempt + 1))
            else:
                logging.warning(
                    "Session summarization failed after %d attempts: %s",
                    max_retries,
                    e,
                    exc_info=True,
                )
                return None


# Sources that are excluded from session browsing/searching by default.
# Third-party integrations (Paperclip agents, etc.) tag their sessions with
# HERMES_SESSION_SOURCE=tool so they don't clutter the user's session history.
_HIDDEN_SESSION_SOURCES = ("tool",)


def _list_recent_sessions(db, limit: int, current_session_id: str = None) -> str:
    """Return metadata for the most recent sessions (no LLM calls)."""
    try:
        sessions = db.list_sessions_rich(limit=limit + 5, exclude_sources=list(_HIDDEN_SESSION_SOURCES))  # fetch extra to skip current

        # Resolve current session lineage to exclude it
        current_root = None
        if current_session_id:
            try:
                sid = current_session_id
                visited = set()
                while sid and sid not in visited:
                    visited.add(sid)
                    s = db.get_session(sid)
                    parent = s.get("parent_session_id") if s else None
                    sid = parent if parent else None
                current_root = max(visited, key=len) if visited else current_session_id
            except Exception:
                current_root = current_session_id

        results = []
        for s in sessions:
            sid = s.get("id", "")
            if current_root and (sid == current_root or sid == current_session_id):
                continue
            # Skip child/delegation sessions (they have parent_session_id)
            if s.get("parent_session_id"):
                continue
            results.append({
                "session_id": sid,
                "title": s.get("title") or None,
                "source": s.get("source", ""),
                "started_at": s.get("started_at", ""),
                "last_active": s.get("last_active", ""),
                "message_count": s.get("message_count", 0),
                "preview": s.get("preview", ""),
            })
            if len(results) >= limit:
                break

        return json.dumps({
            "success": True,
            "mode": "recent",
            "results": results,
            "count": len(results),
            "message": f"Showing {len(results)} most recent sessions. Use a keyword query to search specific topics.",
        }, ensure_ascii=False)
    except Exception as e:
        logging.error("Error listing recent sessions: %s", e, exc_info=True)
        return tool_error(f"Failed to list recent sessions: {e}", success=False)


def session_search(
    query: str,
    role_filter: str = None,
    limit: int = 3,
    db=None,
    current_session_id: str = None,
) -> str:
    """
    Search past sessions and return focused summaries of matching conversations.

    Uses FTS5 to find matches, then summarizes the top sessions with Gemini Flash.
    The current session is excluded from results since the agent already has that context.
    """
    if db is None:
        return tool_error("Session database not available.", success=False)

    limit = min(limit, 5)  # Cap at 5 sessions to avoid excessive LLM calls

    # Recent sessions mode: when query is empty, return metadata for recent sessions.
    # No LLM calls — just DB queries for titles, previews, timestamps.
    if not query or not query.strip():
        return _list_recent_sessions(db, limit, current_session_id)

    query = query.strip()

    try:
        recent_window = None
        artifact_hits: List[Dict[str, Any]] = []
        recent_session_hits: List[Dict[str, Any]] = []

        # Parse role filter
        role_list = None
        if role_filter and role_filter.strip():
            role_list = [r.strip() for r in role_filter.split(",") if r.strip()]
        else:
            recent_window = _recent_query_window(query)
            if recent_window:
                _, start_date, end_date = recent_window
                artifact_hits = _search_recent_learning_artifacts(limit, start_date, end_date)
                if len(artifact_hits) < limit:
                    recent_session_hits = _list_recent_sessions_window(
                        db,
                        limit=max(0, limit - len(artifact_hits)),
                        current_session_id=current_session_id,
                        start_date=start_date,
                        end_date=end_date,
                    )
                combined_recent_results = [*artifact_hits, *recent_session_hits]
                if artifact_hits and recent_session_hits:
                    search_strategy = "recent_artifact_then_sessions"
                elif artifact_hits:
                    search_strategy = "recent_artifact_only"
                elif recent_session_hits:
                    search_strategy = "recent_sessions_only"
                else:
                    search_strategy = "recent_sessions_only"

                return json.dumps({
                    "success": True,
                    "query": query,
                    "results": combined_recent_results,
                    "count": len(combined_recent_results),
                    "artifact_results": len(artifact_hits),
                    "sessions_searched": 0,
                    "search_strategy": search_strategy,
                }, ensure_ascii=False)

            if _should_search_learning_artifacts(query):
                artifact_hits = _search_learning_artifacts(query, limit)
            if len(artifact_hits) >= limit:
                return json.dumps({
                    "success": True,
                    "query": query,
                    "results": artifact_hits,
                    "count": len(artifact_hits),
                    "artifact_results": len(artifact_hits),
                    "sessions_searched": 0,
                    "search_strategy": "artifact_only",
                }, ensure_ascii=False)

        remaining_limit = max(0, limit - len(artifact_hits))
        if remaining_limit == 0:
            return json.dumps({
                "success": True,
                "query": query,
                "results": artifact_hits,
                "count": len(artifact_hits),
                "artifact_results": len(artifact_hits),
                "sessions_searched": 0,
                "search_strategy": "artifact_only",
            }, ensure_ascii=False)

        # FTS5 search -- get matches ranked by relevance
        raw_results = db.search_messages(
            query=query,
            role_filter=role_list,
            exclude_sources=list(_HIDDEN_SESSION_SOURCES),
            limit=50,  # Get more matches to find unique sessions
            offset=0,
        )

        if not raw_results:
            if artifact_hits:
                return json.dumps({
                    "success": True,
                    "query": query,
                    "results": artifact_hits,
                    "count": len(artifact_hits),
                    "artifact_results": len(artifact_hits),
                    "sessions_searched": 0,
                    "search_strategy": "artifact_only",
                }, ensure_ascii=False)
            return json.dumps({
                "success": True,
                "query": query,
                "results": [],
                "count": 0,
                "message": "No matching sessions found.",
            }, ensure_ascii=False)

        # Resolve child sessions to their parent — delegation stores detailed
        # content in child sessions, but the user's conversation is the parent.
        def _resolve_to_parent(session_id: str) -> str:
            """Walk delegation chain to find the root parent session ID."""
            visited = set()
            sid = session_id
            while sid and sid not in visited:
                visited.add(sid)
                try:
                    session = db.get_session(sid)
                    if not session:
                        break
                    parent = session.get("parent_session_id")
                    if parent:
                        sid = parent
                    else:
                        break
                except Exception as e:
                    logging.debug(
                        "Error resolving parent for session %s: %s",
                        sid,
                        e,
                        exc_info=True,
                    )
                    break
            return sid

        current_lineage_root = (
            _resolve_to_parent(current_session_id) if current_session_id else None
        )

        # Group by resolved (parent) session_id, dedup, skip the current
        # session lineage. Compression and delegation create child sessions
        # that still belong to the same active conversation.
        seen_sessions = {}
        for result in raw_results:
            raw_sid = result["session_id"]
            resolved_sid = _resolve_to_parent(raw_sid)
            # Skip the current session lineage — the agent already has that
            # context, even if older turns live in parent fragments.
            if current_lineage_root and resolved_sid == current_lineage_root:
                continue
            if current_session_id and raw_sid == current_session_id:
                continue
            if resolved_sid not in seen_sessions:
                result = dict(result)
                result["session_id"] = resolved_sid
                seen_sessions[resolved_sid] = result
            if len(seen_sessions) >= remaining_limit:
                break

        # Prepare all sessions for parallel summarization
        tasks = []
        for session_id, match_info in seen_sessions.items():
            try:
                messages = db.get_messages_as_conversation(session_id)
                if not messages:
                    continue
                session_meta = db.get_session(session_id) or {}
                conversation_text = _format_conversation(messages)
                conversation_text = _truncate_around_matches(conversation_text, query)
                tasks.append((session_id, match_info, conversation_text, session_meta))
            except Exception as e:
                logging.warning(
                    "Failed to prepare session %s: %s",
                    session_id,
                    e,
                    exc_info=True,
                )

        # Summarize sessions sequentially so a single auxiliary backend does
        # not get flooded with concurrent long-context recalls.
        async def _summarize_all() -> List[Union[str, Exception]]:
            """Summarize sessions one at a time in ranking order."""
            results: List[Union[str, Exception]] = []
            for _, _, text, meta in tasks:
                try:
                    results.append(await _summarize_session(text, query, meta))
                except Exception as exc:
                    results.append(exc)
            return results

        try:
            # Use _run_async() which properly manages event loops across
            # CLI, gateway, and worker-thread contexts.  The previous
            # pattern (asyncio.run() in a ThreadPoolExecutor) created a
            # disposable event loop that conflicted with cached
            # AsyncOpenAI/httpx clients bound to a different loop,
            # causing deadlocks in gateway mode (#2681).
            from model_tools import _run_async
            results = _run_async(_summarize_all())
        except concurrent.futures.TimeoutError:
            logging.warning(
                "Session summarization timed out before all summaries completed",
                exc_info=True,
            )
            return json.dumps({
                "success": False,
                "error": "Session summarization timed out. Try a more specific query or reduce the limit.",
            }, ensure_ascii=False)

        summaries = []
        for (session_id, match_info, conversation_text, _), result in zip(tasks, results):
            if isinstance(result, Exception):
                logging.warning(
                    "Failed to summarize session %s: %s",
                    session_id, result, exc_info=True,
                )
                result = None

            entry = {
                "session_id": session_id,
                "when": _format_timestamp(match_info.get("session_started")),
                "source": match_info.get("source", "unknown"),
                "model": match_info.get("model"),
            }

            if result:
                entry["summary"] = result
            else:
                # Fallback: raw preview so matched sessions aren't silently
                # dropped when the summarizer is unavailable (fixes #3409).
                preview = (conversation_text[:500] + "\n…[truncated]") if conversation_text else "No preview available."
                entry["summary"] = f"[Raw preview — summarization unavailable]\n{preview}"

            summaries.append(entry)

        combined_results = [*artifact_hits, *summaries]
        if artifact_hits and summaries:
            search_strategy = "artifact_then_session"
        elif artifact_hits:
            search_strategy = "artifact_only"
        else:
            search_strategy = "session_only"

        return json.dumps({
            "success": True,
            "query": query,
            "results": combined_results,
            "count": len(combined_results),
            "artifact_results": len(artifact_hits),
            "sessions_searched": len(seen_sessions),
            "search_strategy": search_strategy,
        }, ensure_ascii=False)

    except Exception as e:
        logging.error("Session search failed: %s", e, exc_info=True)
        return tool_error(f"Search failed: {str(e)}", success=False)


def check_session_search_requirements() -> bool:
    """Requires SQLite state database and an auxiliary text model."""
    try:
        from hermes_state import DEFAULT_DB_PATH
        return DEFAULT_DB_PATH.parent.exists()
    except ImportError:
        return False


SESSION_SEARCH_SCHEMA = {
    "name": "session_search",
    "description": (
        "Search your long-term memory of past conversations, or browse recent sessions. This is your recall -- "
        "every past session is searchable, and this tool summarizes what happened.\n\n"
        "TWO MODES:\n"
        "1. Recent sessions (no query): Call with no arguments to see what was worked on recently. "
        "Returns titles, previews, and timestamps. Zero LLM cost, instant. "
        "Start here when the user asks what were we working on or what did we do recently.\n"
        "Exact recent-time queries like today/오늘/yesterday/어제/recent/최근 also stay on the "
        "fast path: they return recent promoted artifacts and recent session previews without "
        "transcript summarization.\n"
        "2. Keyword search (with query): Search reviewed learning artifacts first "
        "(promoted cases, work knowledge docs, staged promotion packets), then "
        "fall back to raw past sessions only if needed. "
        "Returns artifact summaries and/or session summaries.\n\n"
        "USE THIS PROACTIVELY when:\n"
        "- The user says 'we did this before', 'remember when', 'last time', 'as I mentioned'\n"
        "- The user asks about a topic you worked on before but don't have in current context\n"
        "- The user references a project, person, or concept that seems familiar but isn't in memory\n"
        "- You want to check if you've solved a similar problem before\n"
        "- The user asks 'what did we do about X?' or 'how did we fix Y?'\n\n"
        "Don't hesitate to search when it is actually cross-session -- it's fast and cheap. "
        "Better to search and confirm than to guess or ask the user to repeat themselves.\n\n"
        "Search syntax: keywords joined with OR for broad recall (elevenlabs OR baseten OR funding), "
        "phrases for exact match (\"docker networking\"), boolean (python NOT java), prefix (deploy*). "
        "IMPORTANT: Use OR between keywords for best results — FTS5 defaults to AND which misses "
        "sessions that only mention some terms. If a broad OR query returns nothing, try individual "
        "keyword searches in parallel. Returns summaries of the top matching sessions."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query — keywords, phrases, or boolean expressions to find in past sessions. Omit this parameter entirely to browse recent sessions instead (returns titles, previews, timestamps with no LLM cost).",
            },
            "role_filter": {
                "type": "string",
                "description": "Optional: only search messages from specific roles (comma-separated). E.g. 'user,assistant' to skip tool outputs.",
            },
            "limit": {
                "type": "integer",
                "description": "Max sessions to summarize (default: 3, max: 5).",
                "default": 3,
            },
        },
        "required": [],
    },
}


# --- Registry ---
from tools.registry import registry, tool_error

registry.register(
    name="session_search",
    toolset="session_search",
    schema=SESSION_SEARCH_SCHEMA,
    handler=lambda args, **kw: session_search(
        query=args.get("query") or "",
        role_filter=args.get("role_filter"),
        limit=args.get("limit", 3),
        db=kw.get("db"),
        current_session_id=kw.get("current_session_id")),
    check_fn=check_session_search_requirements,
    emoji="🔍",
)
