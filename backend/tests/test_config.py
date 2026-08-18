"""系统配置（§7.8/§9）单元测试。"""
from nvwa_agent import config
from nvwa_agent.config import (
    DEFAULTS,
    effective_llm_provider,
    get,
    get_task_limits,
    set_many,
)


def test_defaults_initialized():
    """init_defaults 后所有默认 key 均可读取（值可能已被其它测试合法修改）。"""
    for key in DEFAULTS:
        assert get(key) is not None


def test_set_and_get_roundtrip():
    set_many({"model_temperature": 0.2})
    assert get("model_temperature") == 0.2
    set_many({"model_temperature": DEFAULTS["model_temperature"][0]})  # 还原


def test_set_unknown_key_rejected():
    try:
        set_many({"no_such_key": 1})
        assert False, "应抛 KeyError"
    except KeyError:
        pass


def test_effective_provider_mock_when_flag_on():
    set_many({"mock_mode_enabled": True, "llm_provider": "api"})
    assert effective_llm_provider() == "mock"
    set_many({"mock_mode_enabled": False})


def test_effective_provider_passthrough():
    set_many({"mock_mode_enabled": False, "llm_provider": "api"})
    assert effective_llm_provider() == "api"
    set_many({"llm_provider": "vllm"})
    assert effective_llm_provider() == "vllm"
    set_many({"llm_provider": "mock"})
    assert effective_llm_provider() == "mock"
    # 非法值兜底为 mock
    set_many({"llm_provider": "bogus"})
    assert effective_llm_provider() == "mock"
    set_many({"llm_provider": "mock"})


def test_task_limits_capped_by_hard_max():
    set_many({"task_max_duration_sec": 999999, "task_max_tool_calls": 999999})
    duration, calls = get_task_limits()
    assert duration == config.HARD_MAX_TASK_DURATION_SEC
    assert calls == config.HARD_MAX_TASK_CALLS
    set_many({"task_max_duration_sec": 300, "task_max_tool_calls": 50})  # 还原


def test_task_limits_normal_values():
    set_many({"task_max_duration_sec": 120, "task_max_tool_calls": 10})
    assert get_task_limits() == (120, 10)
    set_many({"task_max_duration_sec": 300, "task_max_tool_calls": 50})
