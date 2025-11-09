import os, sqlite3

DB_PATH = os.path.join("data", "sqlite", "app.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    with open(os.path.join("src","store","schema.sql"), "r", encoding="utf-8") as f:
        ddl = f.read()
    with get_conn() as conn:
        conn.executescript(ddl)

def execute(conn, sql, params=()):
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    return cur

def query(conn, sql, params=()):
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description] if cur.description else []
    return [dict(zip(cols, r)) for r in rows]
