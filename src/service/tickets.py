# src/service/tickets.py
from __future__ import annotations
import datetime as dt
from typing import Dict, List, Any

from ..store.db import query as sql_query, execute as sql_execute

# --- 工具：读取当前 tickets 表列名 ---
def _ticket_columns(conn) -> List[str]:
    rows = sql_query(conn, "PRAGMA table_info(tickets)")
    # 兼容你的 query() 返回 dict 或 tuple 的两种情况
    cols = []
    for r in rows:
        cols.append(r["name"] if isinstance(r, dict) else r[1])
    return cols

# --- 创建工单：按表结构动态插入 ---
def create_ticket(conn,
                  unit_id: str,
                  category: str,
                  priority: str,
                  summary: str,
                  access_window: str) -> int:
    cols = _ticket_columns(conn)
    now = dt.datetime.utcnow().isoformat(timespec="seconds")

    # 可能存在的列统一在这里补默认值（只有表里真的有，才会写入）
    base: Dict[str, Any] = {
        "unit_id": unit_id,
        "category": category,
        "priority": priority,
        "summary": summary,
        "access_window": access_window,
        "status": "open",
        "created_at": now,
        "updated_at": now,
    }
    # 常见可选列（若表存在则写入）
    if "hazard_flag" in cols:
        base.setdefault("hazard_flag", 0)
    if "assigned_to" in cols:
        base.setdefault("assigned_to", None)
    if "closed_at" in cols:
        base.setdefault("closed_at", None)
    if "source" in cols:
        base.setdefault("source", "chat")

    insert_cols = [c for c in base.keys() if c in cols]
    placeholders = ", ".join(["?"] * len(insert_cols))
    sql = f"INSERT INTO tickets ({', '.join(insert_cols)}) VALUES ({placeholders})"
    params = tuple(base[c] for c in insert_cols)

    # 直接用 conn.cursor() 以拿到 lastrowid（不依赖外部封装返回值）
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    return int(cur.lastrowid)

# --- 列表 ---
def list_tickets(conn):
    cols = _ticket_columns(conn)
    # 只选存在的列，避免字段不一致报错
    want = [c for c in ["id","unit_id","category","priority","status","summary","access_window","created_at","updated_at"] if c in cols]
    sql = f"SELECT {', '.join(want)} FROM tickets ORDER BY COALESCE(created_at, datetime('now')) DESC"
    return sql_query(conn, sql)

# --- 状态更新 ---
def update_status(conn, ticket_id: int, new_status: str):
    cols = _ticket_columns(conn)
    if "status" not in cols:
        return  # 表里没有 status 列就忽略
    sql_execute(conn, "UPDATE tickets SET status=?, updated_at=datetime('now') WHERE id=?", (new_status, ticket_id))

# --- 删除 ---
def delete_ticket(conn, ticket_id: int):
    sql_execute(conn, "DELETE FROM tickets WHERE id=?", (ticket_id,))

# --- 简单去重：2小时内，同 unit，摘要相似 ---
def recent_duplicate_exists(conn, unit_id: str, summary: str) -> bool:
    key = (summary or "").strip()[:40]
    rows = sql_query(
        conn,
        "SELECT COUNT(*) AS n FROM tickets "
        "WHERE unit_id=? AND summary LIKE ? AND created_at > datetime('now','-2 hours')",
        (unit_id, f"%{key}%")
    )
    n = rows[0]["n"] if rows else 0
    return n > 0
