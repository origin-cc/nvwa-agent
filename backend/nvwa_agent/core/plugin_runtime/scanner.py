"""插件扫描器（§3.3）与启动/手动扫描 reconcile（§3.6）。

- 扫描只读元数据不执行业务代码；
- ID 冲突：全部标记故障（PLUGIN_ID_CONFLICT）；
- 磁盘缺失/损坏：内存标记 fault，不修改数据库记录（§11 场景1）；
- 版本升级：注销旧实例 -> 按数据库原状态重新加载（§3.3.4）。
"""
import json
from dataclasses import dataclass, field
from pathlib import Path

from nvwa_agent.config import get as get_config
from nvwa_agent.core.log import get_core_logger
from nvwa_agent.core.paths import resolve_path
from nvwa_agent.core.plugin_runtime.meta import PluginMeta
from nvwa_agent.core.plugin_runtime.schema_validator import load_and_validate

_log = get_core_logger()


@dataclass
class ScanEntry:
    dir_name: str
    errors: list[str] = field(default_factory=list)
    plugin_id: str | None = None
    meta: "PluginMeta | None" = None  # ID冲突时保留首个元数据用于故障登记


def scan_disk() -> tuple[list[PluginMeta], list[ScanEntry]]:
    """扫描插件根目录，返回（校验通过的元数据列表, 问题条目列表）。"""
    root = resolve_path(get_config("plugins_dir", "./plugins"))
    valid: list[PluginMeta] = []
    entries: list[ScanEntry] = []

    if not root.exists():
        return valid, entries

    for sub in sorted(root.iterdir()):
        if not sub.is_dir():
            continue
        pj = sub / "plugin.json"
        if not pj.is_file():
            entries.append(ScanEntry(dir_name=sub.name,
                                     errors=[f"[{sub.name}] 缺少 plugin.json"]))
            continue
        raw, errors = load_and_validate(pj)
        if raw is None or errors:
            pid = raw.get("id") if isinstance(raw, dict) else None
            entries.append(ScanEntry(dir_name=sub.name, errors=errors, plugin_id=pid))
            continue
        valid.append(PluginMeta.from_raw(raw, sub))

    # ID 冲突检测：同 id 多目录 -> 全部置为无效
    by_id: dict[str, list[PluginMeta]] = {}
    for meta in valid:
        by_id.setdefault(meta.plugin_id, []).append(meta)
    conflicted_ids = {pid for pid, metas in by_id.items() if len(metas) > 1}
    if conflicted_ids:
        kept: list[PluginMeta] = []
        for meta in valid:
            if meta.plugin_id in conflicted_ids:
                dirs = ", ".join(m.dir_path.name for m in by_id[meta.plugin_id])
                if meta is by_id[meta.plugin_id][0]:  # 保留第一个用于故障登记
                    entries.append(ScanEntry(
                        dir_name=meta.dir_path.name, plugin_id=meta.plugin_id, meta=meta,
                        errors=[f"PLUGIN_ID_CONFLICT: 多个插件目录声明了相同 id（{dirs}）"],
                    ))
            else:
                kept.append(meta)
        valid = kept
    return valid, entries
