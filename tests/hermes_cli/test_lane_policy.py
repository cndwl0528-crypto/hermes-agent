from hermes_cli.lane_policy import (
    CacheProfile,
    HermesLane,
    IngressStage,
    LaneInput,
    ModelClass,
    NodeClass,
    PersonaProfile,
    TaskRisk,
    ToolsetProfile,
    select_lane,
)


def test_air5_normal_turn_uses_8b_instruct():
    decision = select_lane(
        LaneInput(
            stage=IngressStage.NORMAL_TURN,
            node=NodeClass.AIR5,
            risk=TaskRisk.LOW,
        )
    )

    assert decision.lane == HermesLane.GENERAL
    assert decision.model == ModelClass.MINISTRAL_8B_INSTRUCT
    assert decision.target_node == NodeClass.AIR5
    assert decision.cache == CacheProfile.HOT_SESSION
    assert decision.toolset == ToolsetProfile.SELECTED


def test_air1_worker_task_uses_worker_instruct_without_persona():
    decision = select_lane(
        LaneInput(
            stage=IngressStage.WORKER_TASK,
            node=NodeClass.AIR1,
            risk=TaskRisk.LOW,
        )
    )

    assert decision.model == ModelClass.MINISTRAL_8B_INSTRUCT
    assert decision.cache == CacheProfile.SMALL_WORKER
    assert decision.toolset == ToolsetProfile.RESTRICTED_WORKER
    assert decision.persona == PersonaProfile.NONE


def test_imac_diagnose_uses_3b_reasoning():
    decision = select_lane(
        LaneInput(
            stage=IngressStage.DIAGNOSE,
            node=NodeClass.IMAC,
            risk=TaskRisk.MEDIUM,
        )
    )

    assert decision.lane == HermesLane.REASONING
    assert decision.model == ModelClass.MINISTRAL_3B_REASONING
    assert decision.cache == CacheProfile.FAILURE
    assert decision.toolset == ToolsetProfile.READ_ONLY


def test_high_risk_complex_plan_escalates_to_air5_8b_reasoning():
    decision = select_lane(
        LaneInput(
            stage=IngressStage.COMPLEX_PLAN,
            node=NodeClass.AIR1,
            risk=TaskRisk.HIGH,
        )
    )

    assert decision.lane == HermesLane.REASONING
    assert decision.model == ModelClass.MINISTRAL_8B_REASONING
    assert decision.target_node == NodeClass.AIR5
    assert decision.escalate is True


def test_user_render_is_only_canonical_alice_boundary():
    render = select_lane(
        LaneInput(
            stage=IngressStage.USER_RENDER,
            node=NodeClass.AIR5,
            risk=TaskRisk.LOW,
        )
    )
    diagnose = select_lane(
        LaneInput(
            stage=IngressStage.DIAGNOSE,
            node=NodeClass.AIR5,
            risk=TaskRisk.LOW,
        )
    )

    assert render.lane == HermesLane.RENDER
    assert render.persona == PersonaProfile.ALICE_CANONICAL
    assert diagnose.persona == PersonaProfile.NONE


def test_verify_is_runtime_first_without_llm():
    decision = select_lane(
        LaneInput(
            stage=IngressStage.VERIFY,
            node=NodeClass.IMAC,
            risk=TaskRisk.MEDIUM,
        )
    )

    assert decision.lane == HermesLane.RUNTIME
    assert decision.model == ModelClass.NONE
    assert decision.toolset == ToolsetProfile.TERMINAL_VERIFY
    assert decision.runtime_first is True
