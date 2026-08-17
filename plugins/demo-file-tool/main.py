"""示例工具插件：白名单目录内文本文件读取（全局工具，§3.7.4）。"""
from nvwa_agent.sdk import BaseToolPlugin, PluginContext, ToolResult


class DemoFileTool(BaseToolPlugin):
    tool_name = "demo-file-tool:read_text"
    description = "读取白名单目录内的文本文件内容（如 uploads/xxx.txt），返回文件文本"
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件相对路径（基于data目录，如 uploads/a.txt）"},
        },
        "required": ["path"],
    }

    def execute(self, ctx: PluginContext, args: dict) -> ToolResult:
        path = str(args.get("path", "")).strip()
        if not path:
            return ToolResult.failure("TOOL_EXEC_ERROR", "缺少参数 path")
        try:
            content = ctx.fs.read_text(path)
        except PermissionError as exc:
            return ToolResult.failure("TOOL_FORBIDDEN", f"路径不在白名单内: {exc}")
        except FileNotFoundError:
            return ToolResult.failure("TOOL_EXEC_ERROR", f"文件不存在: {path}")
        except Exception as exc:
            return ToolResult.failure("TOOL_EXEC_ERROR", f"读取失败: {exc}")
        return ToolResult.success(content[:8000])


def on_load(ctx: PluginContext) -> BaseToolPlugin:
    ctx.logger.info("示例文件读取工具加载")
    return DemoFileTool()
