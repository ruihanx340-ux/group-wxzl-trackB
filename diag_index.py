# diag_index.py — end-to-end check: extract -> chunk -> index (sqlite+vector) -> search
import os, sys, glob
from src.store.db import init_db, get_conn, execute, query
from src.rag.chunker import pdf_to_chunks
from src.rag.index import add_chunks, search

ROOT = os.path.dirname(os.path.abspath(__file__))
print("ROOT:", ROOT)

# 0) 初始化DB（确保有 chunks 表）
init_db()
conn = get_conn()
has_chunks = bool(query(conn, "SELECT name FROM sqlite_master WHERE type='table' AND name='chunks'"))
print("has chunks table:", has_chunks)

# 1) 选一个PDF（命令行参数优先，否则挑当前目录或 data/sample_docs 里的第一份）
arg_path = sys.argv[1] if len(sys.argv) > 1 else None
candidates = ([arg_path] if arg_path else []) + glob.glob("*.pdf") + glob.glob("data/sample_docs/*.pdf")
if not candidates:
    raise SystemExit("No PDF found. Put a PDF beside this script or pass a path: python diag_index.py your.pdf")
pdf_path = candidates[0]
print("using file:", pdf_path)

# 2) 读取 & 切块
with open(pdf_path, "rb") as f:
    raw = f.read()

doc_id = "doc_diag"
name = os.path.basename(pdf_path)
unit_id = "A-101"

# 清理同名旧记录
execute(conn, "DELETE FROM chunks WHERE doc_id=?", (doc_id,))
execute(conn, "DELETE FROM documents WHERE id=?", (doc_id,))

# 插入 documents 记录
execute(conn, """
INSERT INTO documents(id, name, unit_id, doc_type, version, effective_from, pages, size_kb, uploaded_at)
VALUES (?, ?, ?, 'lease', 1, datetime('now'), 0, 0, datetime('now'))
""", (doc_id, name, unit_id))

chunks = pdf_to_chunks(doc_id, name, unit_id, raw)
print("chunks extracted:", len(chunks))
if chunks:
    print("sample chunk:", (chunks[0]["text"] or "")[:120].replace("\n", " "))

# 3) 写入索引（先SQLite，向量失败也无所谓）
added = add_chunks(chunks)
print("add_chunks returned:", added)

# 4) 验证 SQLite 中是否真的有文本
n_sql = query(conn, "SELECT COUNT(1) AS n FROM chunks WHERE doc_id=?", (doc_id,))[0]["n"]
print("chunks in sqlite:", n_sql)

# 5) 做一次检索（向量ok就向量；失败则应自动走关键词兜底）
hits = search("rent due", unit_id="A-101", k=3)
print("search hits:", len(hits))
for h in hits:
    print("-", h.get("file"), "p", h.get("page"), "|", (h.get("text","")[:80]).replace("\n"," "))
