"""插件元数据模型：plugin.json 解析后的内存表示。"""
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PluginMeta:
    plugin_id: str
    name: str
    version: str
    type: str                      # backend_agent / backend_tool / ui_page_plugin / ui_component_plugin
    description: str = ""
    author: str = ""
    bind_ui_plugin_id: str | None = None
    bind_backend_plugin_id: str | None = None
    owner_agent_id: str | None = None   # backend_tool 专用
    priority: int = 50
    dependencies: list[str] = field(default_factory=list)
    private_tool_ids: list[str] = field(default_factory=list)
    model_params: dict = field(default_factory=dict)
    lifecycle: dict = field(default_factory=dict)   # {hook: "./main.py::func"}
    ui: dict = field(default_factory=dict)          # {entry, route_path, slots, target_slot}
    config: dict = field(default_factory=dict)
    file_permissions: dict = field(default_factory=dict)  # {read_dirs, write_dirs, allow_delete}
    dir_path: Path | None = None
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_raw(cls, raw: dict, dir_path: Path) -> "PluginMeta":
        ui = dict(raw.get("ui") or {})
        return cls(
            plugin_id=raw["id"],
            name=raw["name"],
            version=raw.get("version", "1.0.0"),
            type=raw["type"],
            description=raw.get("description", ""),
            author=raw.get("author", ""),
            bind_ui_plugin_id=raw.get("bind_ui_plugin_id"),
            bind_backend_plugin_id=raw.get("bind_backend_plugin_id"),
            owner_agent_id=raw.get("owner_agent_id"),
            priority=int(raw.get("priority", 50)),
            dependencies=list(raw.get("dependencies") or []),
            private_tool_ids=list(raw.get("private_tool_ids") or []),
            model_params=dict(raw.get("model_params") or {}),
            lifecycle=dict(raw.get("lifecycle") or {}),
            ui=ui,
            config=dict(raw.get("config") or {}),
            file_permissions=dict(raw.get("file_permissions") or {}),
            dir_path=dir_path,
            raw=raw,
        )

    @property
    def is_backend(self) -> bool:
        return self.type in ("backend_agent", "backend_tool")

    @property
    def is_agent(self) -> bool:
        return self.type == "backend_agent"

    @property
    def is_tool(self) -> bool:
        return self.type == "backend_tool"

    @property
    def is_ui(self) -> bool:
        return self.type in ("ui_page_plugin", "ui_component_plugin")
