"""Hermes lane/model/cache/toolset selection policy.

This mirrors the Rust `runtime-core::lane` contract so Python Hermes can adopt
the runtime router incrementally before direct Rust integration is wired.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


class IngressStage(StrEnum):
    INGRESS_CLASSIFY = "ingress_classify"
    ROUTE_PLAN = "route_plan"
    NORMAL_TURN = "normal_turn"
    WORKER_TASK = "worker_task"
    DIAGNOSE = "diagnose"
    COMPLEX_PLAN = "complex_plan"
    PATCH_GENERATE = "patch_generate"
    VERIFY = "verify"
    CLOSEOUT = "closeout"
    USER_RENDER = "user_render"


class HermesLane(StrEnum):
    GENERAL = "general"
    REASONING = "reasoning"
    RUNTIME = "runtime"
    RENDER = "render"


class ModelClass(StrEnum):
    NONE = "none"
    MINISTRAL_3B_INSTRUCT = "ministral_3b_instruct"
    MINISTRAL_3B_REASONING = "ministral_3b_reasoning"
    MINISTRAL_8B_INSTRUCT = "ministral_8b_instruct"
    MINISTRAL_8B_REASONING = "ministral_8b_reasoning"


class NodeClass(StrEnum):
    AIR5 = "air5"
    IMAC = "imac"
    AIR1 = "air1"


class TaskRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CacheProfile(StrEnum):
    NONE = "none"
    SHORT_PREFIX = "short_prefix"
    ROUTING = "routing"
    HOT_SESSION = "hot_session"
    SMALL_WORKER = "small_worker"
    FAILURE = "failure"
    EXPANDED = "expanded"
    ALLOWED_FILES = "allowed_files"
    SUMMARY = "summary"
    PERSONA = "persona"


class ToolsetProfile(StrEnum):
    NONE = "none"
    MINIMAL = "minimal"
    ROUTE_ONLY = "route_only"
    SELECTED = "selected"
    RESTRICTED_WORKER = "restricted_worker"
    READ_ONLY = "read_only"
    REPO_READ_ONLY = "repo_read_only"
    FILE_PATCH = "file_patch"
    TERMINAL_VERIFY = "terminal_verify"


class PersonaProfile(StrEnum):
    NONE = "none"
    MINIMAL = "minimal"
    ALICE_CANONICAL = "alice_canonical"


@dataclass(frozen=True)
class LaneInput:
    stage: IngressStage
    node: NodeClass
    risk: TaskRisk


@dataclass(frozen=True)
class LaneDecision:
    lane: HermesLane
    model: ModelClass
    target_node: NodeClass
    cache: CacheProfile
    toolset: ToolsetProfile
    persona: PersonaProfile
    runtime_first: bool
    escalate: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def select_lane(lane_input: LaneInput) -> LaneDecision:
    stage = lane_input.stage
    node = lane_input.node
    risk = lane_input.risk

    if stage == IngressStage.INGRESS_CLASSIFY:
        return LaneDecision(
            lane=HermesLane.GENERAL,
            model=ModelClass.MINISTRAL_3B_INSTRUCT,
            target_node=node,
            cache=CacheProfile.SHORT_PREFIX,
            toolset=ToolsetProfile.MINIMAL,
            persona=PersonaProfile.NONE,
            runtime_first=False,
            escalate=False,
        )

    if stage == IngressStage.ROUTE_PLAN:
        return LaneDecision(
            lane=HermesLane.GENERAL,
            model=_instruct_model_for_node(node),
            target_node=node,
            cache=CacheProfile.ROUTING,
            toolset=ToolsetProfile.ROUTE_ONLY,
            persona=PersonaProfile.NONE,
            runtime_first=False,
            escalate=False,
        )

    if stage == IngressStage.NORMAL_TURN:
        return LaneDecision(
            lane=HermesLane.GENERAL,
            model=_instruct_model_for_node(node),
            target_node=node,
            cache=CacheProfile.HOT_SESSION,
            toolset=ToolsetProfile.SELECTED,
            persona=PersonaProfile.MINIMAL,
            runtime_first=False,
            escalate=False,
        )

    if stage == IngressStage.WORKER_TASK:
        return LaneDecision(
            lane=HermesLane.GENERAL,
            model=ModelClass.MINISTRAL_8B_INSTRUCT,
            target_node=node,
            cache=CacheProfile.SMALL_WORKER,
            toolset=ToolsetProfile.RESTRICTED_WORKER,
            persona=PersonaProfile.NONE,
            runtime_first=False,
            escalate=False,
        )

    if stage == IngressStage.DIAGNOSE:
        model = (
            ModelClass.MINISTRAL_8B_REASONING
            if node == NodeClass.AIR5
            else ModelClass.MINISTRAL_3B_REASONING
        )
        return LaneDecision(
            lane=HermesLane.REASONING,
            model=model,
            target_node=node,
            cache=CacheProfile.FAILURE,
            toolset=ToolsetProfile.READ_ONLY,
            persona=PersonaProfile.NONE,
            runtime_first=False,
            escalate=False,
        )

    if stage == IngressStage.COMPLEX_PLAN:
        return LaneDecision(
            lane=HermesLane.REASONING,
            model=ModelClass.MINISTRAL_8B_REASONING,
            target_node=NodeClass.AIR5,
            cache=CacheProfile.EXPANDED,
            toolset=ToolsetProfile.REPO_READ_ONLY,
            persona=PersonaProfile.NONE,
            runtime_first=False,
            escalate=node != NodeClass.AIR5 or risk != TaskRisk.LOW,
        )

    if stage == IngressStage.PATCH_GENERATE:
        model = (
            ModelClass.MINISTRAL_8B_INSTRUCT
            if risk == TaskRisk.LOW
            else ModelClass.MINISTRAL_8B_REASONING
        )
        return LaneDecision(
            lane=HermesLane.REASONING,
            model=model,
            target_node=NodeClass.AIR5,
            cache=CacheProfile.ALLOWED_FILES,
            toolset=ToolsetProfile.FILE_PATCH,
            persona=PersonaProfile.NONE,
            runtime_first=False,
            escalate=node != NodeClass.AIR5,
        )

    if stage == IngressStage.VERIFY:
        return LaneDecision(
            lane=HermesLane.RUNTIME,
            model=ModelClass.NONE,
            target_node=node,
            cache=CacheProfile.NONE,
            toolset=ToolsetProfile.TERMINAL_VERIFY,
            persona=PersonaProfile.NONE,
            runtime_first=True,
            escalate=False,
        )

    if stage == IngressStage.CLOSEOUT:
        return LaneDecision(
            lane=HermesLane.GENERAL,
            model=_instruct_model_for_node(node),
            target_node=node,
            cache=CacheProfile.SUMMARY,
            toolset=ToolsetProfile.NONE,
            persona=PersonaProfile.MINIMAL,
            runtime_first=False,
            escalate=False,
        )

    if stage == IngressStage.USER_RENDER:
        return LaneDecision(
            lane=HermesLane.RENDER,
            model=ModelClass.MINISTRAL_8B_INSTRUCT,
            target_node=NodeClass.AIR5,
            cache=CacheProfile.PERSONA,
            toolset=ToolsetProfile.NONE,
            persona=PersonaProfile.ALICE_CANONICAL,
            runtime_first=False,
            escalate=node != NodeClass.AIR5,
        )

    raise ValueError(f"unsupported ingress stage: {stage}")


def _instruct_model_for_node(node: NodeClass) -> ModelClass:
    if node == NodeClass.AIR5:
        return ModelClass.MINISTRAL_8B_INSTRUCT
    return ModelClass.MINISTRAL_3B_INSTRUCT


# === Lane A Mario Wiring P2 anchor (2026-04-29) ===
# Constitutional / harness anchors for `select_lane()` IngressStage variants.
# This module mirrors the Rust `runtime-core::lane::select_lane` contract;
# the anchor mapping is identical to the Rust side (see lane.rs P2 anchor).
# Read-only references — these comments must not drift from upstream §:
#   INGRESS_CLASSIFY → constitution-v1#3 Plan stage prelude
#                       (WORK_PROCESS_RULES.md "Issue" precision-layer)
#   ROUTE_PLAN       → constitution-v1#3 Plan stage
#                       (WORK_PROCESS_RULES.md Stage 2 Plan)
#   NORMAL_TURN      → constitution-v1#3 Work stage
#                       (WORK_PROCESS_RULES.md Stage 3 Execute)
#   WORKER_TASK      → constitution-v1#3 Work stage (executor lane)
#                      maps to the worker class; active profiles may bind this
#                      model class to SuperGemma for fast sustained work.
#                       + super-mario-constitution#4 Reviewer Cross Rule
#   DIAGNOSE         → constitution-v1#3 Review stage
#                       (WORK_PROCESS_RULES.md Stage 4 Review)
#   COMPLEX_PLAN     → constitution-v1#3 Plan stage (loop_work / milestone_work)
#                       + harness-rules#5 Wiring Law
#   PATCH_GENERATE   → constitution-v1#3 Work stage (patch executor)
#                       + harness-rules#5 Wiring Law (file scope)
#   VERIFY           → constitution-v1#3 Verify stage
#                       (WORK_PROCESS_RULES.md Stage 5 Verify)
#   CLOSEOUT         → constitution-v1#3 Closeout stage
#                       (WORK_PROCESS_RULES.md Stage 6 Closeout)
#   USER_RENDER      → constitution-v1#3 Closeout artifact + persona policy
#                       (WORK_PROCESS_RULES.md Stage 7 Report precision-layer)
# Mario role anchor:
#   Lane A Mario dispatch is Option A — Mario is a separate Hermes profile
#   instance at ~/.hermes/profiles/mario/ (per ~/.hermes/SOUL.md:5,8,17-19,95
#   and super-mario-constitution-v1.md:65). select_lane() does NOT itself pick
#   Mario; the central control center is selected by profile resolution in
#   `hermes_cli/main.py::_apply_profile_override` (see Lane A P2b anchor).
# Bidirectional integrity (matrix v1 Block H row 2):
#   포괄: every constitution §3 stage maps to >= 1 IngressStage above.
#   보호: every IngressStage member cites a constitution / harness § anchor.
# Forbidden: editing this anchor block from any packet other than Lane A
#            packets that explicitly include this file in allowed_files.
# === end anchor ===
