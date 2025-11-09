# src/rag/index.py
# -----------------
# 功能：
# 1) add_chunks：把分块同时写入 SQLite（便于关键词兜底）与 Chroma（向量检索）
# 2) search：优先向量检索；失败或无结果时，退回 SQLite 关键词检索（分词+评分排序）；
#            若仍无结果，再放宽一次（忽略 unit_id 过滤）

import os
import re
from typing import List, Dict

import chromadb

from .embed import embed_texts
from ..store.db import get_conn, execute, query as sql_query

# ---------- Chroma 初始化 ----------
CHROMA_DIR = os.path.join("data", "chroma")
os.makedirs(CHROMA_DIR, exist_ok=True)
_client = chromadb.PersistentClient(path=CHROMA_DIR)
_collection = _client.get_or_create_collection("leases")


# ---------- SQLite 侧：保存 chunks 作为兜底 ----------
def _save_chunks_sqlite(chunks: List[Dict]) -> None:
    """将文本分块落在 SQLite 的 chunks 表，便于关键词兜底检索。"""
    if not chunks:
        return
    conn = get_conn()
    for c in chunks:
        cid = f"{c['doc_id']}:{c['page']}:{c['chunk_index']}"
        execute(
            conn,
            (
                "INSERT OR REPLACE INTO chunks(id, doc_id, page, chunk_index, text, hash, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, datetime('now'))"
            ),
            (cid, c["doc_id"], c["page"], c["chunk_index"], c.get("text", ""), None),
        )


# ---------- 对外：新增分块 ----------
def add_chunks(chunks: List[Dict]) -> int:
    """
    先将 chunks 写入 SQLite（关键词兜底），再尝试写入向量库。
    即使向量失败（额度/网络/模型不兼容），SQLite 也能支持兜底检索。
    """
    if not chunks:
        return 0

    # 1) SQLite 兜底文本
    _save_chunks_sqlite(chunks)

    # 2) 向量库
    ids, docs, metas = [], [], []
    for c in chunks:
        ids.append(f"{c['doc_id']}:{c['page']}:{c['chunk_index']}")
        docs.append(c.get("text", ""))
        metas.append(
            {
                "doc_id": c["doc_id"],
                "file": c["file"],
                "unit_id": c["unit_id"],
                "page": c["page"],
                "chunk_index": c["chunk_index"],
            }
        )

    # 写向量库失败不抛出，让上层可继续（会自动用关键词兜底）
    try:
        embs = embed_texts(docs)  # 内部已做分批+超时（按你 embed.py 的实现）
        _collection.add(ids=ids, documents=docs, metadatas=metas, embeddings=embs)
    except Exception:
        pass

    return len(ids)


# ---------- 关键词兜底（分词 + 评分） ----------
def _keyword_search(q: str, unit_id: str | None, k: int) -> List[Dict]:
    """
    分词（英文去停用词，中文直接保留），使用 OR 条件命中任意词，
    在 Python 端按“命中次数”进行简单评分排序。
    """
    conn = get_conn()
    text = (q or "").lower()

    # 英文停用词（可按需扩充）；中文保持原样
    stop = {
        "the", "a", "an", "of", "and", "or", "to", "for", "is", "are", "on",
        "in", "at", "by", "with", "when", "what", "how"
    }
    # 英文/数字 token + 中文 token
    tokens = [
        t for t in re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fa5]+", text)
        if len(t) >= 2 and t not in stop
    ]
    if not tokens:
        tokens = [text] if text else []

    if not tokens:
        return []

    # 构造 SQL：任意 token 命中即可
    ors = " OR ".join(["LOWER(c.text) LIKE ?"] * len(tokens))
    params = [f"%{t}%" for t in tokens]

    sql = f"""
      SELECT d.name AS file, c.page, c.text
      FROM chunks c
      JOIN documents d ON d.id = c.doc_id
      WHERE (? IS NULL OR d.unit_id = ?)
        AND ({ors})
      LIMIT 200
    """
    rows = sql_query(conn, sql, (unit_id, unit_id, *params))

    def _score(txt: str) -> int:
        t = (txt or "").lower()
        return sum(t.count(tok) for tok in tokens)

    items: List[Dict] = []
    for r in rows:
        items.append(
            {
                "file": r["file"],
                "page": r["page"],
                "text": r["text"],
                "score": float(_score(r["text"])),
            }
        )
    # 命中次数多 → 更相关；同分时文本更短优先
    items.sort(key=lambda x: (-x["score"], len(x["text"])))
    return items[:k]


# ---------- 对外：检索 ----------
def search(query: str, unit_id: str | None = None, k: int = 4) -> List[Dict]:
    """
    先试向量检索（若可用）；否则退回关键词兜底；
    若兜底仍空且有 unit_id，则再放宽一次（忽略 unit 过滤）。
    """
    # 1) 向量检索（可能因额度/网关问题失败）
    try:
        emb = embed_texts([query])[0]
        where = {"unit_id": unit_id} if unit_id else {}
        res = _collection.query(
            query_embeddings=[emb],
            n_results=max(k, 8),
            where=where,
        )
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        dists = res.get("distances", [[]])[0]
        items: List[Dict] = []
        for d, m, s in zip(docs, metas, dists):
            x = dict(m)
            x["text"] = d
            x["score"] = float(s)
            items.append(x)
        if items:
            return items[:k]
    except Exception:
        # 向量不可用时直接走兜底
        pass

    # 2) 关键词兜底（分词+评分）
    items = _keyword_search(query, unit_id, k)
    if items:
        return items

    # 3) 仍为空：放宽一次（忽略 unit 过滤）
    if unit_id:
        return _keyword_search(query, None, k)

    return []
