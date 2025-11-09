# src/rag/index.py — SQLite 内置向量检索（无 chroma）
from __future__ import annotations
import os, re, json
from typing import List, Dict, Optional

import numpy as np  # 用于余弦相似度
from ..store.db import get_conn, execute, query as sql_query
from .embed import embed_texts  # 直接用 OpenAI embedding

# ---------- SQLite 文本兜底 ----------
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

# ---------- 向量表 ----------
def _ensure_vec_table(conn):
    execute(conn, """
    CREATE TABLE IF NOT EXISTS chunk_vecs (
      id TEXT PRIMARY KEY,
      doc_id TEXT,
      unit_id TEXT,
      dim INTEGER,
      vec TEXT
    )""")

def _upsert_vectors(conn, ids: List[str], doc_ids: List[str], unit_ids: List[str], vecs: List[List[float]]):
    _ensure_vec_table(conn)
    dim = len(vecs[0]) if vecs else 0
    for _id, d, u, v in zip(ids, doc_ids, unit_ids, vecs):
        execute(conn,
                "INSERT OR REPLACE INTO chunk_vecs(id, doc_id, unit_id, dim, vec) VALUES (?, ?, ?, ?, ?)",
                (_id, d, u, dim, json.dumps(v)))

def _maybe_backfill_vectors(conn, unit_id: Optional[str]):
    """首次搜索时，如该单元还没有向量，自动为已有分块补嵌入（小库很快，费用也低）"""
    _ensure_vec_table(conn)
    n = sql_query(conn,
                  "SELECT COUNT(1) AS n FROM chunk_vecs WHERE (? IS NULL OR unit_id=?)",
                  (unit_id, unit_id))[0]["n"]
    if n > 0:
        return
    rows = sql_query(conn, """
        SELECT c.id AS cid, c.text, d.id AS doc_id, d.unit_id
        FROM chunks c JOIN documents d ON d.id = c.doc_id
        WHERE (? IS NULL OR d.unit_id=?)
    """, (unit_id, unit_id))
    if not rows:
        return
    ids, texts, doc_ids, units = [], [], [], []
    for r in rows:
        t = (r["text"] or "").strip()
        if not t:
            continue
        ids.append(r["cid"]); texts.append(t); doc_ids.append(r["doc_id"]); units.append(r["unit_id"])
    # 分批嵌入
    B = 64
    for i in range(0, len(texts), B):
        embs = embed_texts(texts[i:i+B])
        _upsert_vectors(conn, ids[i:i+B], doc_ids[i:i+B], units[i:i+B], embs)

# ---------- 对外：新增分块（同时写文本与向量） ----------
def add_chunks(chunks: List[Dict]) -> int:
    if not chunks:
        return 0
    _save_chunks_sqlite(chunks)

    conn = get_conn()
    # 预先准备 ids / texts / doc_ids / unit_ids
    ids, texts, doc_ids, units = [], [], [], []
    for c in chunks:
        ids.append(f"{c['doc_id']}:{c['page']}:{c['chunk_index']}")
        texts.append(c.get("text", ""))
        doc_ids.append(c["doc_id"])
        units.append(c["unit_id"])
    # 嵌入并写入向量表
    B = 64
    for i in range(0, len(texts), B):
        embs = embed_texts(texts[i:i+B])
        _upsert_vectors(conn, ids[i:i+B], doc_ids[i:i+B], units[i:i+B], embs)
    return len(chunks)

# ---------- 关键词兜底（BM25-lite） ----------
def _keyword_search(q: str, unit_id: Optional[str], k: int) -> List[Dict]:
    conn = get_conn()
    text = (q or "").lower()
    stop = {"the","a","an","of","and","or","to","for","is","are","on","in","at","by","with","when","what","how"}
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
    items = [{"file": r["file"], "page": r["page"], "text": r["text"], "score": float(_score(r["text"]))} for r in rows]
    items.sort(key=lambda x: (-x["score"], len(x["text"])))
    return items[:k]

# ---------- 向量检索 ----------
def _vector_search(q: str, unit_id: Optional[str], k: int) -> List[Dict]:
    conn = get_conn()
    _maybe_backfill_vectors(conn, unit_id)
    cnt = sql_query(conn,
                    "SELECT COUNT(1) AS n FROM chunk_vecs WHERE (? IS NULL OR unit_id=?)",
                    (unit_id, unit_id))[0]["n"]
    if cnt == 0:
        return []

    qvec = np.array(embed_texts([q])[0], dtype=np.float32)
    # 取指定单元的全部向量（小库够快），计算余弦相似度
    rows = sql_query(conn,
        "SELECT id, vec FROM chunk_vecs WHERE (? IS NULL OR unit_id=?)",
        (unit_id, unit_id)
    )
    ids, sims = [], []
    qn = np.linalg.norm(qvec) + 1e-9
    for r in rows:
        v = np.array(json.loads(r["vec"]), dtype=np.float32)
        s = float(np.dot(qvec, v) / (qn * (np.linalg.norm(v) + 1e-9)))
        ids.append(r["id"]); sims.append(s)

    # 取 topK id，再回表拿文本与文件名
    if not sims:
        return []
    order = np.argsort(-np.array(sims))[:max(k, 12)]
    top_ids = [ids[i] for i in order]

    ph = ",".join(["?"] * len(top_ids))
    rows = sql_query(conn, f"""
        SELECT c.id AS cid, d.name AS file, c.page, c.text
        FROM chunks c JOIN documents d ON d.id = c.doc_id
        WHERE c.id IN ({ph})
    """, tuple(top_ids))

    # 保持与相似度同序
    pos = {cid:i for i, cid in enumerate(top_ids)}
    items = [{"file": r["file"], "page": r["page"], "text": r["text"], "score": float(1 - 0.001*pos[r["cid"]])}
             for r in rows if r["cid"] in pos]
    items.sort(key=lambda x: (-x["score"], len(x["text"])))
    return items[:k]

# ---------- 总入口 ----------
def search(query: str, unit_id: Optional[str] = None, k: int = 4) -> List[Dict]:
    # 先用向量检索（SQLite 嵌入）；失败或无向量时才走关键词兜底
    try:
        items = _vector_search(query, unit_id, k)
        if items:
            return items
    except Exception:
        pass
    items = _keyword_search(query, unit_id, k)
    if items:
        return items
    if unit_id:
        return _keyword_search(query, None, k)  # 放宽一次
    return []
