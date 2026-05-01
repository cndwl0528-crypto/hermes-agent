from hermes_cli.config import DEFAULT_CONFIG, get_lane_routing_config


def test_default_lane_routing_config_is_empty():
    cfg = get_lane_routing_config(DEFAULT_CONFIG)

    assert cfg == {"model_map": {}, "runtime_map": {}, "toolset_map": {}}


def test_lane_routing_config_normalizes_maps():
    cfg = get_lane_routing_config(
        {
            "lane_routing": {
                "model_map": {
                    "ministral_8b_instruct": "local/ministral-8b",
                    "blank": "",
                },
                "runtime_map": {
                    "ministral_3b_instruct": {
                        "model": "local/ministral-3b",
                        "provider": "custom",
                        "base_url": "http://127.0.0.1:8003/v1",
                        "api_key": "local",
                        "api_mode": "chat_completions",
                        "ignored": "value",
                    },
                    "blank": {"base_url": ""},
                    "ignored": "not-a-dict",
                },
                "toolset_map": {
                    "read_only": ["file", "terminal", ""],
                    "selected": "file,terminal, memory ",
                    "ignored": 123,
                },
            }
        }
    )

    assert cfg["model_map"] == {"ministral_8b_instruct": "local/ministral-8b"}
    assert cfg["runtime_map"] == {
        "ministral_3b_instruct": {
            "model": "local/ministral-3b",
            "provider": "custom",
            "base_url": "http://127.0.0.1:8003/v1",
            "api_key": "local",
            "api_mode": "chat_completions",
        }
    }
    assert cfg["toolset_map"] == {
        "read_only": ["file", "terminal"],
        "selected": ["file", "terminal", "memory"],
    }
