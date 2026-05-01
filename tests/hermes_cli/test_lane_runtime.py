from hermes_cli.lane_runtime import resolve_lane_kwargs


def test_default_cli_lane_kwargs_preserve_empty_maps():
    kwargs = resolve_lane_kwargs("cli", config={"lane_routing": {}})

    assert kwargs["lane_stage"] == "normal_turn"
    assert kwargs["lane_node"] == "air5"
    assert kwargs["lane_risk"] == "low"
    assert kwargs["lane_model_map"] == {}
    assert kwargs["lane_runtime_map"] == {}
    assert kwargs["lane_toolset_map"] == {}


def test_entrypoint_override_and_maps_are_normalized():
    kwargs = resolve_lane_kwargs(
        "gateway_background",
        config={
            "lane_routing": {
                "defaults": {"node": "imac"},
                "entrypoints": {
                    "gateway_background": {
                        "stage": "diagnose",
                        "risk": "high",
                    },
                },
                "model_map": {"ministral_3b_reasoning": "local/3b-reasoning"},
                "runtime_map": {
                    "ministral_3b_reasoning": {
                        "provider": "custom",
                        "base_url": "http://127.0.0.1:8003/v1",
                    }
                },
                "toolset_map": {"read_only": "file, terminal"},
            },
        },
    )

    assert kwargs["lane_stage"] == "diagnose"
    assert kwargs["lane_node"] == "imac"
    assert kwargs["lane_risk"] == "high"
    assert kwargs["lane_model_map"] == {"ministral_3b_reasoning": "local/3b-reasoning"}
    assert kwargs["lane_runtime_map"] == {
        "ministral_3b_reasoning": {
            "provider": "custom",
            "base_url": "http://127.0.0.1:8003/v1",
        }
    }
    assert kwargs["lane_toolset_map"] == {"read_only": ["file", "terminal"]}


def test_disabled_lane_routing_returns_no_kwargs():
    assert resolve_lane_kwargs("cli", config={"lane_routing": {"enabled": False}}) == {}


def test_manual_model_override_can_suppress_lane_model_map():
    kwargs = resolve_lane_kwargs(
        "gateway",
        config={
            "lane_routing": {
                "model_map": {"ministral_8b_instruct": "local/8b"},
                "runtime_map": {"ministral_8b_instruct": {"base_url": "http://127.0.0.1:8008/v1"}},
                "toolset_map": {"selected": ["file"]},
            },
        },
        apply_model_map=False,
    )

    assert kwargs["lane_model_map"] == {}
    assert kwargs["lane_runtime_map"] == {}
    assert kwargs["lane_toolset_map"] == {"selected": ["file"]}
