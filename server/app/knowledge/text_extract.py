"""资料库 / 会话附件：从常见文件格式提取可检索正文。"""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

TEXT_EXTS = {
    ".md",
    ".txt",
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".json",
    ".yaml",
    ".yml",
    ".csv",
    ".html",
    ".htm",
    ".xml",
    ".log",
    ".ini",
    ".toml",
    ".sql",
    ".rst",
    ".css",
    ".scss",
}

BINARY_DOC_EXTS = {".pdf", ".docx"}
INDEXABLE_EXTS = TEXT_EXTS | BINARY_DOC_EXTS

MAX_INDEX_BYTES = 2_000_000

_NS_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


class TextExtractError(Exception):
    """正文提取失败（格式不支持、无文本层、依赖缺失等）。"""


def is_indexable_suffix(suffix: str) -> bool:
    return suffix.lower() in INDEXABLE_EXTS


def _extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise TextExtractError("缺少 pypdf 依赖，无法解析 PDF") from exc

    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        raise TextExtractError(f"PDF 打开失败: {exc}") from exc

    parts: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if not text.strip():
            try:
                text = page.extract_text(extraction_mode="layout") or ""
            except TypeError:
                pass
        parts.append(text)
    text = "\n".join(parts).strip()
    if not text:
        raise TextExtractError("PDF 无文本层（可能是扫描件）")
    return text


def _extract_docx_text(path: Path) -> str:
    w = f"{{{_NS_W}}}"
    try:
        with zipfile.ZipFile(path) as zf:
            try:
                root = ET.fromstring(zf.read("word/document.xml"))
            except KeyError as exc:
                raise TextExtractError("DOCX 缺少 document.xml") from exc
            except ET.ParseError as exc:
                raise TextExtractError(f"DOCX XML 解析失败: {exc}") from exc
    except zipfile.BadZipFile as exc:
        raise TextExtractError(f"无效的 DOCX 文件: {exc}") from exc
    except OSError as exc:
        raise TextExtractError(str(exc)) from exc

    lines: list[str] = []
    for para in root.iter(f"{w}p"):
        buf: list[str] = []
        for node in para.iter():
            if node.tag == f"{w}t":
                buf.append(node.text or "")
            elif node.tag == f"{w}tab":
                buf.append("\t")
            elif node.tag in {f"{w}br", f"{w}cr"}:
                buf.append("\n")
        lines.extend("".join(buf).split("\n"))
    text = "\n".join(lines).strip()
    if not text:
        raise TextExtractError("DOCX 无可用正文")
    return text


def extract_text(path: Path, *, max_bytes: int = MAX_INDEX_BYTES) -> str:
    """读取文件正文；不支持或过大时抛出 TextExtractError。"""
    if not path.is_file():
        raise TextExtractError("不是有效文件")
    size = path.stat().st_size
    if size > max_bytes:
        raise TextExtractError(f"文件超过 {max_bytes // 1024 // 1024}MB 索引上限")

    suffix = path.suffix.lower()
    if suffix in TEXT_EXTS:
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".pdf":
        return _extract_pdf_text(path)
    if suffix == ".docx":
        return _extract_docx_text(path)
    raise TextExtractError(f"不支持索引的格式: {suffix or '(无扩展名)'}")


def extract_text_safe(path: Path, *, max_bytes: int = MAX_INDEX_BYTES) -> str | None:
    """提取正文；失败时返回 None（供索引器批量处理）。"""
    try:
        text = extract_text(path, max_bytes=max_bytes)
        return text.strip() or None
    except TextExtractError:
        return None
