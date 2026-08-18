"""文件写入工具插件：将文本内容写入白名单目录文件（如 data/generated_docs/xxx.md）。

文件访问必须经 ctx.fs（白名单约束），越权抛 PermissionError → FILE_PERMISSION_DENIED。
"""
from nvwa_agent.sdk import BaseToolPlugin, PluginContext, ToolResult


def on_load(ctx: PluginContext) -> "FileWriteTool":
    return FileWriteTool()


class FileWriteTool(BaseToolPlugin):
    tool_name = "file-write-tool:write_text"
    description = (
        "将文本内容写入白名单目录文件（如 data/generated_docs/xxx.md），"
        "用于保存 Agent 生成的文档、笔记、整理结果"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "文件路径（相对仓库根，如 data/generated_docs/x.md）",
            },
            "content": {"type": "string", "description": "要写入的文本内容"},
        },
        "required": ["path", "content"],
    }

    def execute(self, ctx: PluginContext, args: dict) -> ToolResult:
        path = str(args.get("path") or "").strip()
        content = args.get("content")
        if not path:
            return ToolResult.failure("TOOL_EXEC_ERROR", "缺少参数 path")
        if content is None:
            return ToolResult.failure("TOOL_EXEC_ERROR", "缺少参数 content")
        try:
            ctx.fs.write_text(path, str(content))
        except PermissionError as exc:
            return ToolResult.failure("FILE_PERMISSION_DENIED", f"文件访问越权: {exc}")
        except Exception as exc:
            return ToolResult.failure("TOOL_EXEC_ERROR", f"写入失败: {exc}")
        return ToolResult.success(f"已写入: {path}")
