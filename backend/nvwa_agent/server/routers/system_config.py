"""系统配置 API（§9 系统配置）。"""
from fastapi import APIRouter
from pydantic import BaseModel

from nvwa_agent.config import (
    RESTART_REQUIRED_KEYS,
    get_all,
    get_descriptions,
    set_many,
)
from nvwa_agent.server.errors import ApiError

router = APIRouter()


class ConfigUpdateBody(BaseModel):
    configs: dict


@router.get("/api/v1/system/config")
def read_config():
    values = get_all()
    descriptions = get_descriptions()
    configs = [
        {
            "key": key,
            "value": values.get(key),
            "description": descriptions.get(key, ""),
            "restart_required": key in RESTART_REQUIRED_KEYS,
        }
        for key in sorted(values) if key != "schema_version"
    ]
    return {"configs": configs}


@router.put("/api/v1/system/config")
def update_config(body: ConfigUpdateBody):
    if not body.configs:
        raise ApiError("VALIDATION_ERROR", "configs 不能为空")
    changed_restart = [k for k in body.configs if k in RESTART_REQUIRED_KEYS]
    try:
        set_many(body.configs)
    except KeyError as exc:
        raise ApiError("VALIDATION_ERROR", str(exc)) from exc
    return {
        "updated": list(body.configs.keys()),
        "restart_required_keys": changed_restart,
        "restart_required": bool(changed_restart),
    }
