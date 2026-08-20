"""system_config 读写封装与默认值初始化（§7.8）。

value 统一 JSON 序列化存储；llm_provider 为 llm 推理后端三态开关
（mock / vllm / api），与文档的 mock_mode_enabled 语义兼容并存。
"""
import json

from nvwa_agent.core.log import get_core_logger
from nvwa_agent.database import session_scope
from nvwa_agent.models.misc import SystemConfig

# key -> (默认值, 说明)
DEFAULTS: dict[str, tuple] = {
    "vllm_model_path": ("", "vLLM 模型权重本地路径"),
    "model_temperature": (0.7, "默认生成温度"),
    "model_max_tokens": (2048, "默认最大生成 token 数"),
    "model_top_p": (1.0, "默认核采样参数"),
    "mock_mode_enabled": (False, "模拟模型调试模式开关，true 时不调用真实推理"),
    "llm_provider": ("mock", "LLM推理后端：mock / vllm / api（OpenAI兼容接口，如DeepSeek）"),
    "api_base_url": ("https://api.deepseek.com", "OpenAI兼容API地址（llm_provider=api时生效）"),
    "api_key": ("", "OpenAI兼容API密钥（llm_provider=api时生效）"),
    "api_model": ("deepseek-v4-flash", "API模型名（llm_provider=api时生效）"),
    "embedding_model_path": (
        "BAAI/bge-small-zh-v1.5",
        "知识库向量化Embedding模型（sentence-transformers格式，支持HF标识符自动下载）",
    ),
    "file_access_whitelist_dirs": (
        ["./data/uploads", "./data/generated_docs"],
        "文件读写工具可访问的白名单目录（JSON数组）",
    ),
    "task_max_duration_sec": (300, "单任务最大执行时长（秒）"),
    "task_max_tool_calls": (50, "单任务内工具调用最大次数"),
    "conversation_context_window_chars": (20000, "会话上下文窗口（假设的模型上下文，字符数，约2字符≈1token，即约10k token）"),
    "conversation_retain_ratio": (0.2, "压缩时保留最近原文占窗口的比例（触发阈值比例固定1.0，历史达窗口才压缩）"),
    "subagent_max_concurrency": (3, "核心智能体编排时，同一时刻并行运行的子智能体最大并发数"),
    "upload_max_file_size_mb": (100, "上传单文件大小上限（MB）"),
    "plugins_dir": ("./plugins", "插件根目录"),
    "data_dir": ("./data", "数据根目录"),
}

# 修改后需重启服务生效的 key（§9 系统配置）
RESTART_REQUIRED_KEYS = {"plugins_dir", "data_dir", "vllm_model_path", "embedding_model_path"}

# 硬编码兜底上限（PRD 9.5：可配置但不可配置为无限值）
HARD_MAX_TASK_DURATION_SEC = 3600
HARD_MAX_TASK_CALLS = 200


def init_defaults() -> None:
    """启动时补齐缺失的默认配置（已存在的 key 不覆盖）。"""
    with session_scope() as db:
        for key, (default, desc) in DEFAULTS.items():
            if db.get(SystemConfig, key) is None:
                db.add(SystemConfig(key=key, value=json.dumps(default), description=desc))
    get_core_logger().info("system_config 默认值初始化完成（%d 项）", len(DEFAULTS))


def get(key: str, default=None):
    """读取单项配置并反序列化；不存在时返回 DEFAULTS 后备默认值。"""
    with session_scope() as db:
        row = db.get(SystemConfig, key)
        if row is None:
            base = DEFAULTS.get(key)
            return base[0] if base else default
        try:
            return json.loads(row.value)
        except (TypeError, json.JSONDecodeError):
            return default


def get_all() -> dict[str, object]:
    """读取全部配置（含 schema_version 等系统内部 key）。"""
    result = {k: v[0] for k, v in DEFAULTS.items()}
    with session_scope() as db:
        for row in db.query(SystemConfig).all():
            try:
                result[row.key] = json.loads(row.value)
            except (TypeError, json.JSONDecodeError):
                continue
    return result


def get_descriptions() -> dict[str, str]:
    return {k: v[1] for k, v in DEFAULTS.items()}


def set_many(mapping: dict) -> None:
    """批量更新配置；不存在的 key 拒绝写入（防止拼写错误产生脏配置）。"""
    unknown = [k for k in mapping if k not in DEFAULTS and k != "schema_version"]
    if unknown:
        raise KeyError(f"未知的系统配置项: {unknown}")
    with session_scope() as db:
        for key, value in mapping.items():
            if key == "schema_version":
                continue
            row = db.get(SystemConfig, key)
            serialized = json.dumps(value, ensure_ascii=False)
            if row is None:
                desc = DEFAULTS.get(key, ("", ""))[1]
                db.add(SystemConfig(key=key, value=serialized, description=desc))
            else:
                row.value = serialized
                if not row.description and key in DEFAULTS:
                    row.description = DEFAULTS[key][1]


def effective_llm_provider() -> str:
    """实际生效的推理后端：mock_mode_enabled=true 或 llm_provider=mock 时为 mock。"""
    if get("mock_mode_enabled") is True or get("llm_provider") == "mock":
        return "mock"
    provider = get("llm_provider")
    return provider if provider in ("vllm", "api") else "mock"


def get_task_limits() -> tuple[int, int]:
    """任务兜底上限：配置值与硬编码上限取较小者。"""
    duration = min(int(get("task_max_duration_sec", 300)), HARD_MAX_TASK_DURATION_SEC)
    calls = min(int(get("task_max_tool_calls", 50)), HARD_MAX_TASK_CALLS)
    return duration, calls
