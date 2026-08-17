"""知识库检索工具插件（§12.4）：FAISS 检索 → chunk_id → 原文返回。

通过 PluginContext.kb 只读访问全局知识库（SDK BaseKnowledgeAccessor），
插件自身不依赖 FAISS/Embedding 实现，保持内核解耦。
"""
from nvwa_agent.sdk.base import BaseToolPlugin, ToolResult


def on_load(ctx):
    return KbRetrievalTool()


class KbRetrievalTool(BaseToolPlugin):
    tool_name = "kb-retrieval-tool:search"
    description = (
        "知识库语义检索：在用户已上传的知识库文档中检索与查询最相关的原文片段。"
        "当问题可能涉及用户私有文档/资料/手册时调用本工具。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "检索查询文本（用完整自然语言描述）"},
            "top_k": {"type": "integer", "description": "返回片段数，默认5（1-10）"},
        },
        "required": ["query"],
    }

    def execute(self, ctx, args: dict) -> ToolResult:
        query = str(args.get("query", "")).strip()
        if not query:
            return ToolResult.failure("TOOL_EXEC_ERROR", "缺少参数 query")
        if ctx.kb is None:
            return ToolResult.failure("TOOL_EXEC_ERROR", "知识库能力不可用（ctx.kb 未注入）")
        try:
            top_k = max(1, min(int(args.get("top_k", 5)), 10))
            hits = ctx.kb.search(query, top_k=top_k)
        except Exception as exc:
            return ToolResult.failure("TOOL_EXEC_ERROR", f"知识库检索失败：{exc}")
        if not hits:
            return ToolResult.success("知识库为空或无相关内容（可提示用户先上传文档）")

        lines = [f"[{i+1}] 来源：{h['file_name']}（相似度{h['score']}）\n{h['content']}"
                 for i, h in enumerate(hits)]
        return ToolResult.success("\n\n".join(lines))
