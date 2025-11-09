# src/rag/index.py  —— Chroma 可选 + 关键词兜底
from __future__ import annotations
import os, re
from typing import List, Dict

from ..store.db import get_conn, execute, query as sql_query

# --- 尝试导入 Chroma；失败则仅走关键词兜底 ---
CHROMA_OK = False
try:
    import chromadb  # type: ignore
    CHROMA_OK = True
except Exception:
    CHROMA_OK = False

if CHROMA_OK:
    try:
        CHROMA_DIR = os.path.join("data", "chroma")
        os.makedirs(CHROMA_DIR, exist_ok=True)
        _client = chromadb.PersistentClient(path=CHROMA_DIR)
        _collection = _client.get_or_create_collection("leases")
    except Exception:
        CHROMA_OK = False

# ---------- SQLite 侧：保存 chunks 作为兜底 ----------
def _save_chunks_sqlite(chunks: List[Dict]) -> None:
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
    if not chunks:
        return 0

    # 1) SQLite 兜底文本
    _save_chunks_sqlite(chunks)

    # 2) 向量库（可选）
    if CHROMA_OK:
        try:
            from .embed import embed_texts
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
            embs = embed_texts(docs)
            _collection.add(ids=ids, documents=docs, metadatas=metas, embeddings=embs)
        except Exception:
            # 向量失败不影响整体
            pass

    return len(chunks)

# ---------- 关键词兜底（分词 + 简单评分） ----------
def _keyword_search(q: str, unit_id: str | None, k: int) -> List[Dict]:
    conn = get_conn()
    text = (q or "").lower()
    stop = {
        "the","a","an","of","and","or","to","for","is","are","on","in","at","by","with","when","what","how"
    }
    tokens = [t for t in re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fa5]+", text) if len(t) >= 2 and t not in stop]
    if not tokens and text:
        tokens = [text]

    if not tokens:
        return []

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
        items.append({"file": r["file"], "page": r["page"], "text": r["text"], "score": float(_score(r["text"]))})
    items.sort(key=lambda x: (-x["score"], len(x["text"])))
    return items[:k]

# ---------- 对外：检索 ----------
def search(query: str, unit_id: str | None = None, k: int = 4) -> List[Dict]:
    # 1) 向量检索（若可用）
    if CHROMA_OK:
        try:
            from .embed import embed_texts
            emb = embed_texts([query])[0]
            where = {"unit_id": unit_id} if unit_id else {}
            res = _collection.query(query_embeddings=[emb], n_results=max(k, 8), where=where)
            docs = res.get("documents", [[]])[0]
            metas = res.get("metadatas", [[]])[0]
            dists = res.get("distances", [[]])[0]
            items: List[Dict] = []
            for d, m, s in zip(docs, metas, dists):
                x = dict(m); x["text"] = d; x["score"] = float(s)
                items.append(x)
            if items:
                return items[:k]
        except Exception:
            pass

    # 2) 关键词兜底
    items = _keyword_search(query, unit_id, k)
    if items:
        return items

    # 3) 放宽一次 unit 过滤
    if unit_id:
        return _keyword_search(query, None, k)
    return []
