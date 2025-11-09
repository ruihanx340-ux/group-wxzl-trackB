# src/rag/retrieval.py
from __future__ import annotations
from typing import List, Dict, Optional
import textwrap

try:
    from openai import OpenAI  # openai>=1.x
except Exception:
    OpenAI = None


def _build_context(hits: List[Dict], max_chars: int = 6000) -> str:
    """把命中的分块拼成一个可控长度的上下文，并附上 [#] 号索引"""
    buf = []
    used = 0
    for i, h in enumerate(hits, start=1):
        file = h.get("file", "Doc")
        page = h.get("page", "?")
        txt = (h.get("text") or "").strip().replace("\n", " ")
        if not txt:
            continue
        snippet = f"[{i}] ({file} p.{page}) {txt}"
        if used + len(snippet) > max_chars:
            break
        buf.append(snippet)
        used += len(snippet)
    return "\n".join(buf)


def _refs(hits: List[Dict]) -> str:
    """生成简洁的引用尾注"""
    uniq = []
    seen = set()
    for h in hits:
        key = (h.get("file", "Doc"), h.get("page", "?"))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(f"{key[0]} p.{key[1]}")
    if not uniq:
        return ""
    return "References: [" + "; ".join(uniq[:8]) + "]"


def answer_with_citations(
    question: str,
    hits: List[Dict],
    unit_id: Optional[str] = None,
    *,
    # 可选：传入现成 client（推荐 app.py 这样做）
    client: Optional["OpenAI"] = None,
    # 也可不传 client，改用 key/base_url 初始化
    model: str = "gpt-4o-mini",
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    max_ctx_chars: int = 6000,
) -> str:
    """
    生成带引用的回答。
    - 兼容两种调用方式：传 client=... 或用 api_key/base_url 初始化
    - hits: 形如 [{'file':..., 'page':..., 'text':...}, ...]
    返回：纯文本答案（末尾附 References）
    """
    if not hits:
        return "I couldn't find this in your documents."

    # 没有 client 时，尝试自己初始化（用于云端兜底）
    if client is None:
        if OpenAI is None:
            # 本地/云端没装 openai 时的兜底
            return _refs(hits)
        client = OpenAI(api_key=api_key, base_url=base_url)

    context = _build_context(hits, max_chars=max_ctx_chars)
    sys = (
        "You are a helpful assistant for a landlord/tenant portal. "
        "Answer ONLY using the provided context. "
        "If something is not in the context, say you cannot find it. "
        "Be concise and factual."
    )
    user = (
        f"Active Unit: {unit_id or 'N/A'}\n\n"
        f"Question:\n{question}\n\n"
        f"Context (each line is a cited snippet):\n{context}\n\n"
        "Write a short answer first. Do not fabricate details."
    )

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": sys},
                {"role": "user", "content": user},
            ],
        )
        answer = resp.choices[0].message.content.strip()
    except Exception as e:
        # API 失败时兜底：返回空答案+引用
        answer = f"(generation failed: {e})"

    refs = _refs(hits)
    if refs:
        answer = f"{answer}\n\n{refs}"
    return answer
