# src/rag/chunker.py
import io, re
from typing import List
from pypdf import PdfReader
import pdfplumber

# 保险阈值：单页最多保留多少字符、整份文档最多处理多少字符
MAX_PAGE_CHARS = 200_000      # 20万/页
MAX_DOC_CHARS  = 2_000_000    # 文档总上限（防极端大文件）
CHUNK_SIZE     = 1000
CHUNK_OVERLAP  = 150

def _extract_pypdf(raw: bytes):
    reader = PdfReader(io.BytesIO(raw))
    for i, page in enumerate(reader.pages, start=1):
        yield i, (page.extract_text() or "")

def _extract_pdfplumber(raw: bytes):
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            yield i, (page.extract_text() or "")

def _extract_pages_any(raw: bytes):
    pages = list(_extract_pypdf(raw))
    # 有一定字数就接受 pypdf，否则用 pdfplumber 兜底
    if sum(len((t or "").strip()) for _, t in pages) >= 50:
        return pages
    return list(_extract_pdfplumber(raw))

_ws = re.compile(r"\s+")

def _normalize(text: str) -> str:
    # 去除 NUL、压缩空白，做页级截断
    if not text:
        return ""
    text = text.replace("\x00", " ")
    text = _ws.sub(" ", text).strip()
    if len(text) > MAX_PAGE_CHARS:
        text = text[:MAX_PAGE_CHARS]
    return text

def _iter_chunks(text: str, maxlen: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP):
    # 生成器：避免一次性分配大量切片内存
    text = _normalize(text)
    n = len(text)
    if n == 0:
        return
    i = 0
    while i < n:
        j = min(n, i + maxlen)
        yield text[i:j]
        if j >= n:
            break
        i = max(j - overlap, j) if j - overlap <= 0 else j - overlap

def pdf_to_chunks(doc_id: str, file_name: str, unit_id: str, raw: bytes):
    res = []
    total_chars = 0
    for page, txt in _extract_pages_any(raw):
        norm = _normalize(txt)
        total_chars += len(norm)
        # 超过文档总上限就停止，防崩
        if total_chars > MAX_DOC_CHARS:
            break
        idx = 0
        for chunk in _iter_chunks(norm):
            res.append({
                "doc_id": doc_id,
                "file": file_name,
                "unit_id": unit_id,
                "page": page,
                "chunk_index": idx,
                "text": chunk
            })
            idx += 1
        # 给极端长页一个“保险丝”：单页最多切 2000 个 chunk
        if idx > 2000:
            break
    return res
