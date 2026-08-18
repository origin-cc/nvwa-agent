"""M9 三层插件元数据校验单元测试（v1.0 §3.2 / §3.3）。"""
import json

from nvwa_agent.core.plugin_runtime.schema_validator import (
    validate_plugin_json,
    validate_plugin_refs,
    validate_plugin_values,
)


def _agent(**overrides):
    raw = {
        "id": "demo-agent-plugin", "name": "示例", "version": "1.0.0",
        "type": "backend_agent", "description": "desc", "author": "nvwa",
        "dependencies": [], "priority": 50,
        "private_tool_ids": [], "model_params": {},
        "lifecycle": {"on_load": "./main.py::on_load"},
    }
    raw.update(overrides)
    return raw


def _tool(**overrides):
    raw = {
        "id": "demo-tool", "name": "工具", "version": "1.0.0",
        "type": "backend_tool", "description": "desc", "author": "nvwa",
        "dependencies": [], "priority": 50,
        "lifecycle": {"on_load": "./main.py::on_load"},
    }
    raw.update(overrides)
    return raw


def _page(**overrides):
    raw = {
        "id": "demo-page", "name": "页面", "version": "1.0.0",
        "type": "ui_page_plugin", "description": "desc", "author": "nvwa",
        "dependencies": [], "priority": 50,
        "ui": {"entry": "./index.js", "route_path": "/x", "slots": []},
    }
    raw.update(overrides)
    return raw


def _component(**overrides):
    raw = {
        "id": "demo-comp", "name": "组件", "version": "1.0.0",
        "type": "ui_component_plugin", "description": "desc", "author": "nvwa",
        "dependencies": [], "priority": 50,
        "ui": {"entry": "./index.js", "target_slot": "chat:side"},
    }
    raw.update(overrides)
    return raw


# ---------------------------------------------------------------------------
# 第1层：结构校验（JSON Schema）→ PLUGIN_SCHEMA_INVALID
# ---------------------------------------------------------------------------
def test_struct_invalid_type():
    assert validate_plugin_json(_agent(type="unknown_type"))


def test_struct_missing_required():
    raw = _agent()
    del raw["name"]
    assert validate_plugin_json(raw)


# ---------------------------------------------------------------------------
# 第2层：字段值校验（§3.2）→ PLUGIN_METADATA_INVALID
# ---------------------------------------------------------------------------
def test_value_id_must_match_dir():
    assert any("id" in e for e in validate_plugin_values(_agent(id="other-id"),
                                                         "demo-agent-plugin"))


def test_value_version_semver():
    assert any("version" in e for e in validate_plugin_values(_agent(version="latest")))


def test_value_priority_range():
    assert any("priority" in e for e in validate_plugin_values(_agent(priority=-1)))
    assert any("priority" in e for e in validate_plugin_values(_agent(priority=1001)))


def test_value_dependencies_dup_and_empty():
    assert any("dependencies" in e
               for e in validate_plugin_values(_agent(dependencies=["a", "a"])))
    assert any("dependencies" in e
               for e in validate_plugin_values(_agent(dependencies=[""])))


def test_value_private_tool_only_agent():
    assert any("private_tool_ids" in e
               for e in validate_plugin_values(_tool(private_tool_ids=["x"])))


def test_value_private_tool_dup():
    assert any("private_tool_ids" in e
               for e in validate_plugin_values(_agent(private_tool_ids=["a", "a"])))


def test_value_model_params_only_agent():
    assert any("model_params" in e
               for e in validate_plugin_values(_tool(model_params={"temperature": 0.5})))


def test_value_model_params_temperature_range():
    assert any("temperature" in e
               for e in validate_plugin_values(_agent(model_params={"temperature": 5})))


def test_value_model_params_max_tokens_positive():
    assert any("max_tokens" in e
               for e in validate_plugin_values(_agent(model_params={"max_tokens": -1})))


def test_value_hook_path_format():
    assert any("on_load" in e
               for e in validate_plugin_values(_agent(lifecycle={"on_load": "main.py::on_load"})))


def test_value_backend_on_load_required():
    assert any("on_load" in e for e in validate_plugin_values(_agent(lifecycle={})))


def test_value_ui_page_route_required():
    assert any("route_path" in e
               for e in validate_plugin_values(_page(ui={"entry": "./index.js", "slots": []})))


def test_value_ui_page_route_slash():
    assert any("route_path" in e for e in validate_plugin_values(
        _page(ui={"entry": "./index.js", "route_path": "chat", "slots": []})))


def test_value_ui_component_target_slot_required():
    assert any("target_slot" in e
               for e in validate_plugin_values(_component(ui={"entry": "./index.js"})))


def test_value_ui_component_no_slots():
    assert any("slots" in e for e in validate_plugin_values(
        _component(ui={"entry": "./index.js", "target_slot": "x", "slots": ["a"]})))


def test_value_valid_agent_passes():
    assert validate_plugin_values(_agent(), "demo-agent-plugin") == []


# ---------------------------------------------------------------------------
# 第3层：交叉引用与存在性校验（§3.3）
# ---------------------------------------------------------------------------
def test_ref_hook_file_missing(tmp_path):
    errors, _ = validate_plugin_refs(_agent(lifecycle={"on_load": "./missing.py::on_load"}),
                                     tmp_path)
    assert any("on_load" in e for e in errors)


def test_ref_hook_func_missing(tmp_path):
    (tmp_path / "main.py").write_text("def other():\n    pass\n")
    errors, _ = validate_plugin_refs(_agent(), tmp_path)
    assert any("on_load" in e for e in errors)


def test_ref_hook_valid(tmp_path):
    (tmp_path / "main.py").write_text("def on_load(ctx):\n    pass\n")
    errors, warnings = validate_plugin_refs(_agent(), tmp_path)
    assert errors == []


def test_ref_ui_entry_missing(tmp_path):
    errors, _ = validate_plugin_refs(_page(ui={"entry": "./missing.js",
                                               "route_path": "/x", "slots": []}),
                                     tmp_path)
    assert any("entry" in e for e in errors)


def test_ref_bind_missing_warns(tmp_path):
    (tmp_path / "main.py").write_text("def on_load(ctx):\n    pass\n")
    errors, warnings = validate_plugin_refs(_agent(bind_ui_plugin_id="ghost"),
                                            tmp_path, plugins_root=tmp_path)
    assert errors == []
    assert any("bind_ui_plugin_id" in w for w in warnings)


# ---------------------------------------------------------------------------
# 扫描集成：错误码分层（§3.1）
# ---------------------------------------------------------------------------
def test_scan_disk_field_value_error_code(tmp_path, monkeypatch):
    sub = tmp_path / "bad-plugin"
    sub.mkdir()
    (sub / "plugin.json").write_text(json.dumps(_agent(id="bad-plugin", version="latest")))
    monkeypatch.setattr("nvwa_agent.core.plugin_runtime.scanner.get_config",
                        lambda k, d=None: str(tmp_path))
    from nvwa_agent.core.plugin_runtime.scanner import scan_disk

    valid, entries = scan_disk()
    assert valid == []
    assert len(entries) == 1
    assert entries[0].plugin_id == "bad-plugin"
    assert entries[0].error_code == "PLUGIN_METADATA_INVALID"


def test_scan_disk_struct_error_code(tmp_path, monkeypatch):
    sub = tmp_path / "bad2"
    sub.mkdir()
    (sub / "plugin.json").write_text(json.dumps(_agent(id="bad2", type="unknown_type")))
    monkeypatch.setattr("nvwa_agent.core.plugin_runtime.scanner.get_config",
                        lambda k, d=None: str(tmp_path))
    from nvwa_agent.core.plugin_runtime.scanner import scan_disk

    valid, entries = scan_disk()
    assert valid == []
    assert len(entries) == 1
    assert entries[0].plugin_id == "bad2"
    assert entries[0].error_code == "PLUGIN_SCHEMA_INVALID"
