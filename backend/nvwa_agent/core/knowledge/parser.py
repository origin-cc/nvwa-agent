"""文档解析与切片（§12.6 入库流水线第一步）。

支持 txt / md（纯文本直读）与 pdf（pypdf 提取）；其余扩展名拒绝。
切片策略：固定字符窗口 + 重叠（可配置 chunk_size / chunk_overlap）。
"""

SUPPORTED_SUFFIXES = {".txt", ".md", ".markdown", ".pdf"}
CHUNK_SIZE = 800        # 单切片字符数（v0.1 硬编码，中文小文档友好）
CHUNK_OVERLAP = 100     # 相邻切片重叠字符数


class ParseError(Exception):
    """文档解析失败（KNOWLEDGE_PARSE_FAILED）。"""


def extract_text(path: str, suffix: str) -> str:
    """按扩展名提取全文文本；失败抛 ParseError（友好摘要，不中断其他流程）。"""
    suffix = suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ParseError(f"不支持的文件类型 {suffix or '(无扩展名)'}，仅支持 {sorted(SUPPORTED_SUFFIXES)}")
    try:
        if suffix == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(path)
            pages = [page.extract_text() or "" for page in reader.pages]
            return "\n".join(pages)
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except ParseError:
        raise
    except Exception as exc:
        raise ParseError(f"文档解析失败：{exc}") from exc


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """固定窗口切片：空白压缩后按 size/overlap 切分。"""
    normalized = " ".join(text.split())
    if not normalized:
        return []
    chunks = []
    start = 0
    while start < len(normalized):
        end = min(start + size, len(normalized))
        chunks.append(normalized[start:end])
        if end >= len(normalized):
            break
        start = end - overlap if overlap < size else end
    return chunks
