"""PluginRuntime 核心：状态机、实例管理、生命周期、工具调用（§3.2–§3.5）。"""
import time

from nvwa_agent.config import get_task_limits
from nvwa_agent.core import taskctx
from nvwa_agent.core.log import get_core_logger
from nvwa_agent.core.plugin_runtime.event_bus import event_bus
from nvwa_agent.core.plugin_runtime.loader import (
    PluginLoadError,
    execute_hook,
    execute_on_load,
)
from nvwa_agent.core.plugin_runtime.meta import PluginMeta
from nvwa_agent.core.plugin_runtime import runtime_db
from nvwa_agent.sdk.base import ToolResult

_log = get_core_logger()

VALID_STATES = {"loaded", "activated", "deactivated", "unloaded", "fault"}


class PluginOpError(Exception):
    """REST 层可感知的插件操作错误（409）。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ToolCallLimitExceeded(Exception):
    """单任务工具调用次数超限（TASK_TOOL_CALL_LIMIT）。"""


class PluginRuntime:
    """进程内单例：插件状态机与实例管理器。"""

    def __init__(self) -> None:
        self._metas: dict[str, PluginMeta] = {}
        self._states: dict[str, str] = {}
        self._errors: dict[str, str] = {}
        self._instances: dict[str, object] = {}
        self._graphs: dict[str, object] = {}
        self._ctxs: dict[str, object] = {}
        self._tool_calls_by_task: dict[str, int] = {}

    # ------------------------------ 查询 ------------------------------
    def has(self, plugin_id: str) -> bool:
        return plugin_id in self._metas

    def get_meta(self, plugin_id: str) -> PluginMeta | None:
        return self._metas.get(plugin_id)

    def get_state(self, plugin_id: str) -> str | None:
        return self._states.get(plugin_id)

    def get_instance(self, plugin_id: str) -> object | None:
        return self._instances.get(plugin_id)

    def get_graph(self, plugin_id: str):
        return self._graphs.get(plugin_id)

    def get_ctx(self, plugin_id: str):
        return self._ctxs.get(plugin_id)

    def all_ids(self) -> list[str]:
        return list(self._metas.keys())

    def activated_agents(self) -> list[tuple[PluginMeta, object, object]]:
        return [
            (m, self._instances[i], self._graphs[i])
            for i, m in self._metas.items()
            if m.is_agent and self._states.get(i) == "activated"
        ]

    def register_meta(self, meta: PluginMeta, state: str, error: str | None = None) -> None:
        """登记元数据与内存状态（供扫描/恢复流程使用）。"""
        self._metas[meta.plugin_id] = meta
        self._states[meta.plugin_id] = state
        self._errors[meta.plugin_id] = error or ""

    def drop_instance(self, plugin_id: str, run_unload_hook: bool = False) -> None:
        """移除内存实例（版本升级/卸载）；可选执行 on_unload 钩子。"""
        meta = self._metas.get(plugin_id)
        ctx = self._ctxs.get(plugin_id)
        if run_unload_hook and meta is not None and ctx is not None:
            try:
                execute_hook(meta, "on_unload", ctx)
            except PluginLoadError as exc:
                _log.warning("插件 %s on_unload 钩子异常: %s", plugin_id, exc)
        self._instances.pop(plugin_id, None)
        self._graphs.pop(plugin_id, None)
        self._ctxs.pop(plugin_id, None)

    # ------------------------------ 生命周期 ------------------------------
    def _set(self, plugin_id: str, state: str, error: str | None = None,
             persist: bool = True) -> None:
        self._states[plugin_id] = state
        self._errors[plugin_id] = error or ""
        meta = self._metas.get(plugin_id)
        if persist and meta is not None:
            runtime_db.db_update_state(meta.type, plugin_id, state, error_msg=error)

    def load(self, plugin_id: str, *, notify: bool = True) -> bool:
        """加载后端插件：on_load + build_graph；失败置 fault。返回是否成功。"""
        meta = self._metas.get(plugin_id)
        if meta is None or not meta.is_backend:
            return False
        missing = [d for d in meta.dependencies if d not in self._metas]
        if missing:
            self.mark_fault(plugin_id, "PLUGIN_DEPENDENCY_MISSING",
                            f"依赖插件缺失: {missing}", notify=notify)
            return False
        try:
            from nvwa_agent.core.plugin_runtime.services import build_context
            ctx = build_context(meta)
            instance = execute_on_load(meta, ctx)
            if meta.is_agent:
                self._graphs[plugin_id] = instance.build_graph(ctx)
        except PluginLoadError as exc:
            self.drop_instance(plugin_id)
            self.mark_fault(plugin_id, exc.code, str(exc), notify=notify)
            return False
        self._ctxs[plugin_id] = ctx
        self._instances[plugin_id] = instance
        self._set(plugin_id, "loaded")
        if notify:
            event_bus.publish("plugin:loaded", {
                "plugin_id": plugin_id, "plugin_type": meta.type, "state": "loaded",
            })
        return True

    def activate(self, plugin_id: str) -> None:
        meta = self._metas.get(plugin_id)
        if meta is None:
            raise PluginOpError("NOT_FOUND", f"插件 {plugin_id} 不存在")
        state = self._states.get(plugin_id)
        if state == "fault":
            raise PluginOpError("PLUGIN_STATE_INVALID",
                                f"插件 {plugin_id} 处于故障状态，禁止激活：{self._errors.get(plugin_id)}")
        if meta.is_backend and plugin_id not in self._instances:
            if state in ("unloaded", "loaded"):
                if not self.load(plugin_id):
                    raise PluginOpError("PLUGIN_STATE_INVALID",
                                        f"插件 {plugin_id} 加载失败：{self._errors.get(plugin_id)}")
                state = "loaded"
            else:
                raise PluginOpError("PLUGIN_STATE_INVALID", f"插件 {plugin_id} 当前状态 {state} 不可激活")
        # 依赖必须已激活（PRD 3.1.2）
        for dep in meta.dependencies:
            dep_state = self._states.get(dep)
            if dep_state != "activated":
                self.mark_fault(plugin_id, "PLUGIN_DEPENDENCY_MISSING",
                                f"依赖插件 {dep} 未激活（状态 {dep_state}）")
                raise PluginOpError("PLUGIN_STATE_INVALID",
                                    f"依赖插件 {dep} 未激活，{plugin_id} 已标记故障")
        if meta.is_backend:
            try:
                execute_hook(meta, "on_activate", self._ctxs.get(plugin_id))
            except PluginLoadError as exc:
                self.mark_fault(plugin_id, exc.code, str(exc))
                raise PluginOpError("PLUGIN_STATE_INVALID", str(exc)) from exc
        self._set(plugin_id, "activated")
        event_bus.publish("plugin:activated", {"plugin_id": plugin_id})
        if meta.is_agent:
            self._cascade_ui_binding(meta, activate=True)

    def deactivate(self, plugin_id: str, *, cascade: bool = True) -> None:
        meta = self._metas.get(plugin_id)
        if meta is None:
            raise PluginOpError("NOT_FOUND", f"插件 {plugin_id} 不存在")
        if self._states.get(plugin_id) != "activated":
            raise PluginOpError("PLUGIN_STATE_INVALID",
                                f"插件 {plugin_id} 当前状态 {self._states.get(plugin_id)}，仅 activated 可禁用")
        if meta.is_backend:
            try:
                execute_hook(meta, "on_deactivate", self._ctxs.get(plugin_id))
            except PluginLoadError as exc:
                self.mark_fault(plugin_id, exc.code, str(exc))
                raise PluginOpError("PLUGIN_STATE_INVALID", str(exc)) from exc
        self._set(plugin_id, "deactivated")
        event_bus.publish("plugin:deactivated", {"plugin_id": plugin_id})
        if meta.is_agent and cascade:
            self._cascade_ui_binding(meta, activate=False)

    def unload(self, plugin_id: str) -> None:
        meta = self._metas.get(plugin_id)
        if meta is None:
            raise PluginOpError("NOT_FOUND", f"插件 {plugin_id} 不存在")
        state = self._states.get(plugin_id)
        if state == "activated":
            raise PluginOpError("PLUGIN_STATE_INVALID",
                                f"插件 {plugin_id} 处于运行中，禁止直接卸载，请先禁用")
        if state not in ("loaded", "deactivated", "fault"):
            raise PluginOpError("PLUGIN_STATE_INVALID", f"插件 {plugin_id} 当前状态 {state} 不可卸载")
        self.drop_instance(plugin_id, run_unload_hook=True)
        self._set(plugin_id, "unloaded")
        event_bus.publish("plugin:unloaded", {"plugin_id": plugin_id})
        if meta.is_agent:
            self._cascade_ui_binding(meta, activate=False, only_if_bound=True)

    def mark_fault(self, plugin_id: str, code: str, message: str,
                   *, persist: bool = True, notify: bool = True) -> None:
        """置为故障；persist=False 用于磁盘缺失场景（不修改数据库，§11 场景1）。"""
        self._set(plugin_id, "fault", f"[{code}] {message}", persist=persist)
        if notify:
            event_bus.publish("plugin:error", {
                "plugin_id": plugin_id, "error_msg": message, "error_code": code,
            })

    def _cascade_ui_binding(self, agent_meta: PluginMeta, activate: bool,
                            only_if_bound: bool = False) -> None:
        """后端Agent与绑定UI插件联动（bind_ui_plugin_id 为权威绑定方向）。"""
        ui_id = agent_meta.bind_ui_plugin_id
        if not ui_id:
            return
        ui_meta = self._metas.get(ui_id)
        if ui_meta is None or not ui_meta.is_ui:
            event_bus.publish("plugin:error", {
                "plugin_id": agent_meta.plugin_id,
                "error_msg": f"绑定UI插件 {ui_id} 不存在（bind_ui_plugin_id）",
                "error_code": "BIND_UI_PLUGIN_NOT_FOUND",
            })  # 告警不阻断（§11 场景2）
            return
        try:
            if activate and self._states.get(ui_id) != "activated":
                self.activate(ui_id)
            elif not activate and self._states.get(ui_id) == "activated":
                if not only_if_bound:
                    self.deactivate(ui_id, cascade=False)
        except PluginOpError as exc:
            _log.warning("UI插件联动失败 %s: %s", ui_id, exc)

    # ------------------------------ 工具调用 ------------------------------
    def _resolve_tool(self, tool_id: str) -> PluginMeta | None:
        meta = self._metas.get(tool_id)
        if meta is not None and meta.is_tool:
            return meta
        for m in self._metas.values():  # tool_name 别名兜底
            if m.is_tool and getattr(self._instances.get(m.plugin_id), "tool_name", "") == tool_id:
                return m
        return None

    def call_tool(self, tool_id: str, args: dict, caller_agent_id: str) -> dict:
        """统一工具调用入口：状态/权限校验 + tool:call/result/error 事件（§10）。"""
        _, max_calls = get_task_limits()
        tid = taskctx.get_current_task()
        count = self._tool_calls_by_task.get(tid, 0) + 1
        if count > max_calls:
            raise ToolCallLimitExceeded(f"单任务工具调用次数超过上限 {max_calls}")
        self._tool_calls_by_task[tid] = count

        meta = self._resolve_tool(tool_id)
        if meta is None:
            raise _forbidden("TOOL_NOT_FOUND", f"工具 {tool_id} 不存在")
        if self._states.get(meta.plugin_id) != "activated":
            raise _forbidden("TOOL_FORBIDDEN", f"工具 {meta.plugin_id} 未激活或已禁用")
        if meta.owner_agent_id and meta.owner_agent_id != caller_agent_id:
            raise _forbidden("TOOL_FORBIDDEN",
                             f"工具 {meta.plugin_id} 为私有工具，仅 {meta.owner_agent_id} 可调用")

        event_bus.publish("tool:call", {
            "task_id": tid, "tool_id": meta.plugin_id,
            "call_args": args or {},
        })
        started = time.time()
        instance = self._instances.get(meta.plugin_id)
        try:
            result: ToolResult = instance.execute(self._ctxs.get(meta.plugin_id), args or {})
        except Exception as exc:
            _log.exception("工具 %s 执行异常", meta.plugin_id)
            event_bus.publish("tool:error", {
                "task_id": tid, "tool_id": meta.plugin_id,
                "error_msg": f"工具执行失败: {exc}", "error_code": "TOOL_EXEC_ERROR",
            })
            return {"ok": False, "error_code": "TOOL_EXEC_ERROR", "error_msg": str(exc)}

        elapsed = round(time.time() - started, 3)
        if result.ok:
            payload_data = result.data if isinstance(result.data, str) else (result.data or {})
            event_bus.publish("tool:result", {
                "task_id": tid, "tool_id": meta.plugin_id,
                "result": payload_data, "elapsed_sec": elapsed,
            })
            return {"ok": True, "data": payload_data}
        event_bus.publish("tool:error", {
            "task_id": tid, "tool_id": meta.plugin_id,
            "error_msg": result.error_msg or "工具执行失败",
            "error_code": result.error_code or "TOOL_EXEC_ERROR",
        })
        return {"ok": False, "error_code": result.error_code or "TOOL_EXEC_ERROR",
                "error_msg": result.error_msg}

    def reset_tool_counter(self, task_id: str) -> None:
        self._tool_calls_by_task.pop(task_id, None)

    def tool_specs_for(self, caller_agent_id: str) -> list[dict]:
        """当前可调用工具清单（全局 + 自身私有），供 Agent function calling。"""
        specs = []
        for pid, meta in self._metas.items():
            if not meta.is_tool or self._states.get(pid) != "activated":
                continue
            if meta.owner_agent_id and meta.owner_agent_id != caller_agent_id:
                continue
            instance = self._instances.get(pid)
            specs.append({
                "tool_id": pid,
                "tool_name": getattr(instance, "tool_name", pid),
                "description": getattr(instance, "description", ""),
                "parameters_schema": getattr(instance, "parameters_schema", {}) or {},
            })
        return specs


    # ------------------------------ 绑定校验 / 列表 ------------------------------
    def validate_bindings(self) -> list[str]:
        """私有工具双向声明一致性校验（§3.5）；违规插件置 fault（PLUGIN_BINDING_MISMATCH）。"""
        issues: list[str] = []
        for pid, meta in self._metas.items():
            if not meta.is_agent:
                continue
            for tid in meta.private_tool_ids:
                tmeta = self._metas.get(tid)
                bad = (tmeta is None or not tmeta.is_tool
                       or self._states.get(tid) in (None, "fault")
                       or tmeta.owner_agent_id != pid)
                if bad:
                    issues.append(f"{pid} -> {tid}")
                    if self._states.get(pid) != "fault":
                        self.mark_fault(pid, "PLUGIN_BINDING_MISMATCH",
                                        f"私有工具 {tid} 不存在、未加载或归属不一致")
        for pid, meta in self._metas.items():
            if not meta.is_tool or not meta.owner_agent_id:
                continue
            ameta = self._metas.get(meta.owner_agent_id)
            if (ameta is None or not ameta.is_agent
                    or self._states.get(meta.owner_agent_id) in (None, "fault")):
                issues.append(f"{pid} -> {meta.owner_agent_id}")
                if self._states.get(pid) != "fault":
                    self.mark_fault(pid, "PLUGIN_BINDING_MISMATCH",
                                    f"归属Agent {meta.owner_agent_id} 不存在或未加载")
        return issues

    def list_plugins(self) -> list[dict]:
        """全部插件状态（DB 行 + 内存有效状态），供 GET /plugins/list。"""
        import json as _json

        result = []
        for row in runtime_db.db_all_rows():
            meta = self._metas.get(row.id)
            try:
                deps = _json.loads(row.dependencies or "[]")
            except (TypeError, ValueError):
                deps = []
            item = {
                "plugin_id": row.id, "name": row.name, "type": row.type,
                "version": row.version,
                "state": self._states.get(row.id) or row.state,
                "error_msg": self._errors.get(row.id) or row.error_msg,
                "priority": getattr(row, "priority", 50) or 50,
                "dependencies": deps,
                "bind_ui_plugin_id": getattr(row, "bind_ui_plugin_id", None),
                "bind_backend_plugin_id": getattr(row, "bind_backend_plugin_id", None),
                "owner_agent_id": getattr(row, "owner_agent_id", None),
                "disk_missing": meta is None,
                "dir_name": meta.dir_path.name if meta is not None and meta.dir_path else None,
            }
            if row.type == "backend_agent":
                for key in ("private_tool_ids", "model_params"):
                    try:
                        item[key] = _json.loads(getattr(row, key) or ("{}" if key == "model_params" else "[]"))
                    except (TypeError, ValueError):
                        item[key] = {} if key == "model_params" else []
            if row.type == "backend_tool":
                instance = self._instances.get(row.id)
                item["tool_name"] = getattr(instance, "tool_name", "") or row.id
                item["description"] = getattr(instance, "description", "") or item.get("description", "")
                item["parameters_schema"] = getattr(instance, "parameters_schema", None) or {}
            if str(row.type).startswith("ui_"):
                try:
                    slots = _json.loads(row.slots or "[]")
                except (TypeError, ValueError):
                    slots = []
                item["ui"] = {
                    "route_path": row.route_path,
                    "slots": slots,
                    "target_slot": row.target_slot,
                    "entry": row.entry_path,
                }
            try:
                item["plugin_config"] = _json.loads(row.plugin_config or "{}")
            except (TypeError, ValueError):
                item["plugin_config"] = {}
            result.append(item)
        result.sort(key=lambda x: (x["type"], x["plugin_id"]))
        return result


def _forbidden(code: str, message: str):
    from nvwa_agent.sdk.context import ToolForbiddenError
    return ToolForbiddenError(f"[{code}] {message}")


_runtime: PluginRuntime | None = None


def get_runtime() -> PluginRuntime:
    global _runtime
    if _runtime is None:
        _runtime = PluginRuntime()
    return _runtime
