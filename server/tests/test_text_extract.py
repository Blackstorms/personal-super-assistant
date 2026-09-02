"""文本提取单元测试。"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from app.knowledge.text_extract import (
    TextExtractError,
    extract_text,
    extract_text_safe,
    is_indexable_suffix,
)


def test_is_indexable_suffix():
    assert is_indexable_suffix(".pdf")
    assert is_indexable_suffix(".docx")
    assert is_indexable_suffix(".md")
    assert not is_indexable_suffix(".doc")
    assert not is_indexable_suffix(".png")


def test_extract_plain_text(tmp_path: Path):
    f = tmp_path / "note.txt"
    f.write_text("你好，资料库测试", encoding="utf-8")
    assert extract_text(f) == "你好，资料库测试"


def test_extract_docx(tmp_path: Path):
    docx = tmp_path / "sample.docx"
    body = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>新能源十五五规划</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>第二段内容</w:t></w:r></w:p></w:body></w:document>"
    )
    with zipfile.ZipFile(docx, "w") as zf:
        zf.writestr("word/document.xml", body)
    text = extract_text(docx)
    assert "新能源十五五规划" in text
    assert "第二段内容" in text


def test_extract_docx_empty_raises(tmp_path: Path):
    docx = tmp_path / "empty.docx"
    body = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body></w:body></w:document>"
    )
    with zipfile.ZipFile(docx, "w") as zf:
        zf.writestr("word/document.xml", body)
    with pytest.raises(TextExtractError):
        extract_text(docx)


def test_extract_unsupported(tmp_path: Path):
    f = tmp_path / "image.png"
    f.write_bytes(b"\x89PNG")
    with pytest.raises(TextExtractError):
        extract_text(f)


def test_extract_text_safe_returns_none(tmp_path: Path):
    f = tmp_path / "bad.pdf"
    f.write_bytes(b"%PDF-1.4 not a real pdf")
    assert extract_text_safe(f) is None
