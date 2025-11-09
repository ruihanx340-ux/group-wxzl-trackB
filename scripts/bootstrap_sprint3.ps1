# Sprint 3 skeleton bootstrapper
$ErrorActionPreference = "Stop"

function Write-File($Path, $Content) {
  $dir = Split-Path $Path -Parent
  if ($dir) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
  $Content | Out-File -FilePath $Path -Encoding utf8 -Force
  Write-Host "Wrote $Path"
}

# --- folders ---
@(
  "src/store",
  "src/rag",
  "src/service",
  "data/sample_docs",
  "data/sqlite",
  "data/chroma",
  "docs"
) | ForEach-Object { New-Item -ItemType Directory -Force -Path $_ | Out-Null }

# --- schema.sql ---
$schema = @"
CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  unit_id TEXT,
  doc_type TEXT,
  version INTEGER DEFAULT 1,
  effective_from TEXT,
  pages INTEGER,
  size_kb REAL,
  uploaded_at TEXT
);
CREATE TABLE IF NOT EXISTS chunks (
  id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL,
  page INTEGER,
  chunk_index INTEGER,
  text TEXT,
  hash TEXT,
  created_at TEXT,
  FOREIGN KEY(doc_id) REFERENCES documents(id)
);
CREATE TABLE IF NOT EXISTS tickets (
  id TEXT PRIMARY KEY,
  unit_id TEXT NOT NULL,
  category TEXT NOT NULL,
  priority TEXT NOT NULL,
  status TEXT NOT NULL,
  summary TEXT NOT NULL,
  reporter TEXT,
  access_window TEXT,
  assignee TEXT,
  eta TEXT,
  hazard_flag INTEGER DEFAULT 0,
  created_at TEXT,
  updated_at TEXT,
  closed_at TEXT
);
"@
Write-File "src/store/schema.sql" $schema

# --- db.py ---
$db_py = @"
import os, sqlite3
DB_PATH = os.path.join("data","sqlite","app.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    with open(os.path.join("src","store","schema.sql"), "r", encoding="utf-8") as f:
        ddl = f.read()
    with get_conn() as conn:
        conn.executescript(ddl)

def execute(conn, sql, params=()):
    cur = conn.cursor(); cur.execute(sql, params); conn.commit(); return cur

def query(conn, sql, params=()):
    cur = conn.cursor(); cur.execute(sql, params); rows = cur.fetchall()
    cols = [d[0] for d in cur.description] if cur.description else []
    return [dict(zip(cols, r)) for r in rows]
"@
Write-File "src/store/db.py" $db_py

# --- chunker.py ---
$chunker_py = @"
import io
from typing import List
from pypdf import PdfReader

def extract_pages(raw: bytes):
    reader = PdfReader(io.BytesIO(raw))
    for i, page in enumerate(reader.pages, start=1):
        yield i, (page.extract_text() or "").strip()

def chunk_text(text: str, maxlen: int = 1000, overlap: int = 150) -> List[str]:
    out, i, n = [], 0, len(text)
    if not text.strip(): return out
    while i < n:
        j = min(n, i+maxlen); out.append(text[i:j]); i = j - overlap; i = i if i>0 else j
    return [c for c in out if c.strip()]

def pdf_to_chunks(doc_id: str, file_name: str, unit_id: str, raw: bytes):
    res = []
    for page, txt in extract_pages(raw):
        for idx, chunk in enumerate(chunk_text(txt)):
            res.append({"doc_id":doc_id,"file":file_name,"unit_id":unit_id,"page":page,"chunk_index":idx,"text":chunk})
    return res
"@
Write-File "src/rag/chunker.py" $chunker_py

# --- embed.py ---
$embed_py = @"
from typing import List
from openai import OpenAI

def embed_texts(texts: List[str], model: str = "text-embedding-3-small") -> List[List[float]]:
    client = OpenAI()
    r = client.embeddings.create(model=model, input=texts)
    return [d.embedding for d in r.data]
"@
Write-File "src/rag/embed.py" $embed_py

# --- index.py ---
$index_py = @"
import os, chromadb
from typing import List, Dict
from .embed import embed_texts

CHROMA_DIR = os.path.join("data","chroma")
os.makedirs(CHROMA_DIR, exist_ok=True)
_client = chromadb.PersistentClient(path=CHROMA_DIR)
_collection = _client.get_or_create_collection("leases")

def add_chunks(chunks: List[Dict]):
    if not chunks: return 0
    ids, docs, metas = [], [], []
    for c in chunks:
        ids.append(f"{c['doc_id']}:{c['page']}:{c['chunk_index']}")
        docs.append(c["text"])
        metas.append({"doc_id":c["doc_id"],"file":c["file"],"unit_id":c["unit_id"],"page":c["page"],"chunk_index":c["chunk_index"]})
    _collection.add(ids=ids, documents=docs, metadatas=metas, embeddings=embed_texts(docs))
    return len(ids)

def search(query: str, unit_id: str = None, k: int = 4) -> List[Dict]:
    emb = embed_texts([query])[0]
    where = {"unit_id": unit_id} if unit_id else {}
    res = _collection.query(query_embeddings=[emb], n_results=max(k,8), where=where)
    docs = res.get("documents",[[]])[0]; metas = res.get("metadatas",[[]])[0]; dists = res.get("distances",[[]])[0]
    items = []
    for d,m,s in zip(docs,metas,dists):
        x = dict(m); x["text"]=d; x["score"]=float(s); items.append(x)
    return items[:k]
"@
Write-File "src/rag/index.py" $index_py

# --- retrieval.py ---
$retrieval_py = @"
from openai import OpenAI
from .index import search

def answer_with_citations(user_q: str, unit_id: str = None, k: int = 4, model: str = "gpt-4o-mini") -> str:
    ctx = search(user_q, unit_id=unit_id, k=k)
    if not ctx:
        return "I couldn't find this in your documents. Please upload the relevant lease or rules."
    blocks = []; cites = []
    for i,c in enumerate(ctx,1):
        blocks.append(f"[{i}] ({c['file']} p.{c['page']})\n{c['text']}")
        cites.append(f"{c['file']} p.{c['page']}")
    sys = ("You are a property assistant. Only answer using the CONTEXT. "
           "If not in the context, say you can't find it. Always include citations.")
    usr = "QUESTION:\n"+user_q+"\n\nCONTEXT:\n"+("\n\n".join(blocks))
    client = OpenAI()
    rs = client.responses.create(model=model, input=[{"role":"system","content":sys},{"role":"user","content":usr}])
    ans = rs.output[0].content[0].text
    tail = "References: [" + "; ".join(dict.fromkeys(cites)) + "]"
    return ans + "\n\n" + tail
"@
Write-File "src/rag/retrieval.py" $retrieval_py

# --- tickets.py ---
$tickets_py = @"
from typing import Optional, List, Dict
from datetime import datetime, timedelta
from ..store.db import execute, query

def now_iso(): return datetime.now().isoformat(timespec="seconds")

def create_ticket(conn, unit_id: str, category: str, priority: str, summary: str,
                  reporter: str = None, access_window: str = None,
                  assignee: str = None, eta: str = None, hazard_flag: int = 0) -> str:
    tid = f"tkt_{datetime.now().strftime('%y%m%d%H%M%S%f')[-10:]}"
    execute(conn, "INSERT INTO tickets(id,unit_id,category,priority,status,summary,reporter,access_window,assignee,eta,hazard_flag,created_at,updated_at,closed_at) VALUES (?,?,?,?, 'Open',?,?,?,?,?, ?, ?, NULL)",
            (tid,unit_id,category,priority,summary,reporter,access_window,assignee,eta,hazard_flag,now_iso(),now_iso()))
    return tid

def list_tickets(conn, unit_id: Optional[str] = None, status: Optional[str] = None) -> List[Dict]:
    sql = "SELECT * FROM tickets WHERE 1=1"; params=[]
    if unit_id: sql += " AND unit_id=?"; params.append(unit_id)
    if status:  sql += " AND status=?";  params.append(status)
    sql += " ORDER BY updated_at DESC"; return query(conn, sql, tuple(params))

def update_status(conn, ticket_id: str, new_status: str):
    closed_at = now_iso() if new_status == "Closed" else None
    execute(conn, "UPDATE tickets SET status=?, updated_at=?, closed_at=? WHERE id=?", (new_status, now_iso(), closed_at, ticket_id))

def delete_ticket(conn, ticket_id: str): execute(conn, "DELETE FROM tickets WHERE id=?", (ticket_id,))

def recent_duplicate_exists(conn, unit_id: str, category: str, within_hours: int = 2) -> bool:
    since = (datetime.now() - timedelta(hours=within_hours)).isoformat(timespec="seconds")
    rows = query(conn, "SELECT 1 FROM tickets WHERE unit_id=? AND category=? AND status IN ('Open','In Progress') AND created_at>=? LIMIT 1", (unit_id,category,since))
    return len(rows)>0
"@
Write-File "src/service/tickets.py" $tickets_py

# --- autoschema.py ---
$autoschema_py = @"
AUTO_TICKET_TOOL = {
  "type": "function",
  "function": {
    "name": "create_ticket_draft",
    "description": "Extract maintenance intent from user text as a ticket draft",
    "parameters": {
      "type": "object",
      "properties": {
        "unit_id": {"type":"string"},
        "category": {"type":"string", "enum":["plumbing","electrical","noise","hvac","other"]},
        "priority": {"type":"string", "enum":["high","medium","low"]},
        "summary": {"type":"string"},
        "access_window": {"type":"string"},
        "confidence": {"type":"number"}
      },
      "required": ["unit_id","category","priority","summary","confidence"]
    }
  }
}
def high_confidence(draft: dict, threshold: float = 0.8) -> bool:
  try: return float(draft.get("confidence",0)) >= threshold
  except: return False
"@
Write-File "src/service/autoschema.py" $autoschema_py

# --- docs snippet ---
$doc = @"
# Sprint 3 Integration Guide (Snippet)

1) Init DB in `app.py`:
```python
from src.store.db import init_db, get_conn
init_db(); conn = get_conn()
from src.rag.chunker import pdf_to_chunks
from src.rag.index import add_chunks
chunks = pdf_to_chunks(doc_id, file_name, unit_id, raw_bytes)
add_chunks(chunks)
from src.rag.retrieval import answer_with_citations
answer = answer_with_citations(user_text, unit_id="A-101", k=4)
from src.rag.retrieval import answer_with_citations
answer = answer_with_citations(user_text, unit_id="A-101", k=4)
from src.service.tickets import create_ticket, list_tickets
tid = create_ticket(conn, unit_id="A-101", category="plumbing", priority="high", summary="Leak under sink")
rows = list_tickets(conn, unit_id="A-101")
from src.service.autoschema import AUTO_TICKET_TOOL, high_confidence
# call model with tools=[AUTO_TICKET_TOOL]; if high_confidence(draft): create_ticket(conn, **draft)
