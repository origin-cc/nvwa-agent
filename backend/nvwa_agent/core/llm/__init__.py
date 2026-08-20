"""LLM 推理客户端（§10）：mock / vllm / api 三态 provider（llm_provider 配置）。

- 全局采样参数来自 system_config；Agent 局部 model_params 字段级覆盖由
  services.LlmServiceImpl 在调用前完成合并后传入；
- api 客户端为 OpenAI 兼容接口（DeepSeek 等），M8 落地；vllm 客户端后续版本实现。
"""
from nvwa_agent.config import effective_llm_provider, get
from nvwa_agent.core.log import get_core_logger
from nvwa_agent.core.llm.mock_client import MockLlmClient

_log = get_core_logger()


class LlmProviderError(Exception):
    """推理后端不可用 / 调用失败（LLM_INFER_FAILED）。"""


class TaskCancelledError(Exception):
    """任务被用户取消（流式推理中断）。"""


def get_llm_client(params: dict | None = None):
    """按当前配置返回推理客户端。

    params: 已合并的采样参数 {model_path, temperature, max_tokens, top_p, stop_sequences}
    """
    provider = effective_llm_provider()
    params = params or {}
    if provider == "mock":
        return MockLlmClient(params)
    if provider == "api":
        from nvwa_agent.core.llm.api_client import ApiLlmClient  # M8 提供

        return ApiLlmClient(
            base_url=get("api_base_url", ""),
            api_key=get("api_key", ""),
            model=get("api_model", ""),
            params=params,
        )
    if provider == "vllm":
        from nvwa_agent.core.llm.vllm_client import VllmLlmClient  # 后续版本提供

        return VllmLlmClient(model_path=params.get("model_path") or get("vllm_model_path", ""),
                             params=params)
    return MockLlmClient(params)


def merge_model_params(agent_model_params: dict | None) -> dict:
    """全局模型配置 + Agent 局部 model_params 字段级合并（§10）。

    仅对本次任务生效，不写回全局配置。
    """
    merged = {
        "model_path": get("vllm_model_path", ""),
        "temperature": get("model_temperature", 0.7),
        "max_tokens": get("model_max_tokens", 2048),
        "top_p": get("model_top_p", 1.0),
        "stop_sequences": [],
    }
    for key in ("model_path", "temperature", "max_tokens", "top_p", "stop_sequences"):
        if agent_model_params and key in agent_model_params:
            merged[key] = agent_model_params[key]
    return merged
