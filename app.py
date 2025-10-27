#!/usr/bin/env python3
"""
Tenant Assistant (Track B) — Sprint 2 Step 1

This is the main Streamlit entrypoint. It exposes 3 tabs:
- Chat               (placeholder bot for now)
- Knowledge Base     (upload PDFs, tag with unit_id, track metadata)
- Service Desk       (create & track maintenance tickets)

Later steps:
- RAG retrieval over uploaded docs
- Persistent DB (SQLite / Postgres)
- Tool calling from chat to auto-create tickets
"""

from __future__ import annotations
import os
import io
import glob
import uuid
from datetime import datetime, date
from typing import List, Dict, Any
from openai import OpenAI
import streamlit as st
from dotenv import load_dotenv
load_dotenv()

try:
    from pypdf import PdfReader  # lightweight page count
except Exception:
    PdfReader = None
def get_api_key():
    # 线上部署时：从 Streamlit Cloud 的 secrets 里拿
    try:
        import streamlit as st
        if "OPENAI_API_KEY" in st.secrets:
            return st.secrets["OPENAI_API_KEY"]
    except Exception:
        pass

    # 本地开发时：优先从环境变量 / .env 读取
    # 你可以用 python-dotenv，也可以手动 set 环境变量
    return os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=get_api_key())
# --------------------------
# Page config
# --------------------------
st.set_page_config(
    page_title="Tenant Assistant — Sprint 2",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --------------------------
# Helpers
# --------------------------

def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")




def preload_demo_documents():
    """
    把 data/sample_docs/ 里的 PDF 自动放进 session_state.documents，
    这样网页一打开就会显示“已有文档”。
    只在 session_state.documents 还没任何内容的时候做，
    避免重复添加。
    """
    if st.session_state.documents:
        # 已经有用户上传的内容了，就不重复塞 demo
        return

    sample_folder = os.path.join("data", "sample_docs")
    pdf_paths = glob.glob(os.path.join(sample_folder, "*.pdf"))

    for path in pdf_paths:
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except Exception:
            continue

        pages = _pdf_page_count(raw)
        file_name = os.path.basename(path)

        # 这里我们随便给一个默认的元数据
        # 你可以按需要改，比如 unit_id、doc_type
        demo_doc = {
            "id": _gen_id("doc"),
            "name": file_name,
            "unit_id": "A-101",                # 你可以硬编码成示例单元
            "doc_type": "lease" if "lease" in file_name.lower() else "house_rules",
            "effective_from": date.today().isoformat(),
            "pages": pages,
            "size_kb": round(len(raw) / 1024, 1),
            "uploaded_at": _now_str(),
            "raw_bytes": raw,
        }

        st.session_state.documents.append(demo_doc)


def _gen_id(prefix: str) -> str:
    import uuid as _uuid
    return f"{prefix}_{_uuid.uuid4().hex[:8]}"


def _pdf_page_count(raw_bytes: bytes) -> int | None:
    if PdfReader is None:
        return None
    try:
        reader = PdfReader(io.BytesIO(raw_bytes))
        return len(reader.pages)
    except Exception:
        return None

# --------------------------
# Init session state
# --------------------------

def init_state():
    """Ensure session_state keys exist."""
    if "messages" not in st.session_state:
        st.session_state.messages: List[Dict[str, Any]] = [
            {
                "role": "assistant",
                "content": (
                    "Hi! Upload contracts in Knowledge Base, then ask me things like"
                    "'When is rent due for unit A-101?' or 'Report a leak in bathroom'."
                    "Service Desk tab tracks your tickets."
                ),
            }
        ]
    if "documents" not in st.session_state:
        # each doc:
        #   {id, name, unit_id, doc_type, effective_from, pages,
        #    size_kb, uploaded_at, raw_bytes}
        st.session_state.documents: List[Dict[str, Any]] = []
    if "tickets" not in st.session_state:
        # each ticket:
        #   {id, tenant_name, unit_id, category, priority,
        #    status, scheduled_at, created_at, notes}
        st.session_state.tickets: List[Dict[str, Any]] = []
    preload_demo_documents()
# --------------------------
# Chat tab (placeholder bot)
# --------------------------

def _chatbot_reply(user_text: str) -> str:
    """
    Real model call using gpt-4o-mini (a cheaper/faster GPT family model).
    We'll later enhance this to inject retrieved contract text.
    """

    # 1. 组织我们要发给模型的对话
    # system 提示是它的角色，user 是租户提的问题
    messages = [
        {
            "role": "system",
            "content": (
                "You are a helpful property management assistant. "
                "If the user is reporting a maintenance problem (leak, noise, AC broken), "
                "classify the issue and suggest creating a service ticket. "
                "If the user is asking about lease terms, answer politely. "
            ),
        },
        {
            "role": "user",
            "content": user_text,
        },
    ]

    # 2. 调用 gpt-4o-mini
    try:
        response = client.responses.create(
            model="gpt-4o-mini",
            input=messages,
        )

        # 3. 从返回结构里取文本
        model_answer = response.output[0].content[0].text

    except Exception as e:
        # 如果有错误（例如没绑信用卡 / key无效 / 网断），给个可解释 fallback
        model_answer = (
            "I'm having trouble reaching the model right now. "
            f"(Details: {e})"
        )

    return model_answer


def tab_chat():
    st.subheader("💬 Tenant Chat")

    with st.expander("Chat settings (Step 1)", expanded=False):
        st.markdown(
            "This is a placeholder bot. It will become contract-aware and able to create tickets automatically."
        )

    # render history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    # chat input
    user_text = st.chat_input(
        "Ask something like 'When is rent due for A-101?' or 'There's water leaking under the sink'."
    )
    if user_text:
        st.session_state.messages.append({"role": "user", "content": user_text})
        with st.chat_message("user"):
            st.write(user_text)

        bot_reply = _chatbot_reply(user_text)
        st.session_state.messages.append({"role": "assistant", "content": bot_reply})
        with st.chat_message("assistant"):
            st.write(bot_reply)

    st.caption("Step 1 = echo bot. Step 2 = RAG + citations. Step 3 = auto ticket creation.")

# --------------------------
# Knowledge Base tab
# --------------------------

def tab_kb():
    st.subheader("📚 Knowledge Base")

    left, right = st.columns([2, 1])

    # uploader / metadata entry
    with left:
        uploads = st.file_uploader(
            "Upload tenancy agreements, building rules, etc.",
            type=["pdf"],
            accept_multiple_files=True,
            help="Step 1 stores in memory only.",
        )

        unit_id = st.text_input("Unit ID for these docs", value="A-101")
        doc_type = st.selectbox(
            "Document type",
            ["lease", "house_rules", "notice", "other"],
            index=0,
        )
        effective_from = st.date_input("Effective from", value=date.today())

        if st.button("Add to Knowledge Base", type="primary"):
            if uploads:
                for f in uploads:
                    raw = f.read()
                    pages = _pdf_page_count(raw)
                    st.session_state.documents.append(
                        {
                            "id": _gen_id("doc"),
                            "name": f.name,
                            "unit_id": unit_id.strip(),
                            "doc_type": doc_type,
                            "effective_from": effective_from.isoformat(),
                            "pages": pages,
                            "size_kb": round(len(raw) / 1024, 1),
                            "uploaded_at": _now_str(),
                            "raw_bytes": raw,  # will move to vector DB later
                        }
                    )
                st.success(f"Uploaded {len(uploads)} document(s).")
                st.rerun()
            else:
                st.warning("No files selected.")

    # metrics summary
    with right:
        total_docs = len(st.session_state.documents)
        total_pages = sum([(d["pages"] or 0) for d in st.session_state.documents])
        st.metric("Documents", total_docs)
        st.metric("Total Pages", total_pages)
        st.metric(
            "Last Upload",
            st.session_state.documents[-1]["uploaded_at"] if total_docs else "—",
        )

    st.divider()

    # filters
    c1, c2, c3, c4 = st.columns([1.2, 1.2, 1, 1])
    with c1:
        f_unit = st.text_input("Filter: Unit contains", "")
    with c2:
        f_type = st.multiselect(
            "Filter: Doc Type",
            ["lease", "house_rules", "notice", "other"],
            [],
        )
    with c3:
        sort_by = st.selectbox(
            "Sort by",
            ["uploaded_at", "name", "unit_id", "doc_type"],
        )
    with c4:
        asc = st.toggle("Ascending", value=False)

    rows = st.session_state.documents
    if f_unit:
        rows = [d for d in rows if f_unit.lower() in d["unit_id"].lower()]
    if f_type:
        rows = [d for d in rows if d["doc_type"] in f_type]

    rows = sorted(rows, key=lambda x: x.get(sort_by) or "", reverse=not asc)

    if rows:
        st.dataframe(
            [
                {k: v for k, v in d.items() if k not in ("raw_bytes",)}
                for d in rows
            ],
            use_container_width=True,
            height=320,
        )
    else:
        st.info("No documents yet. Upload PDFs above.")

# --------------------------
# Service Desk tab
# --------------------------

def tab_service():
    st.subheader("🛠️ Service Desk")

    with st.expander("Create ticket", expanded=True):
        cols = st.columns([1, 1, 1, 1])
        with cols[0]:
            tenant_name = st.text_input("Tenant name", value="John Doe")
        with cols[1]:
            unit_id = st.text_input("Unit ID", value="A-101")
        with cols[2]:
            category = st.selectbox(
                "Category",
                ["plumbing", "electrical", "noise", "appliance", "other"],
            )
        with cols[3]:
            priority = st.selectbox(
                "Priority", ["low", "medium", "high"], index=1
            )

        cols2 = st.columns([1, 2])
        with cols2[0]:
            scheduled_at = st.date_input("Preferred date")
        with cols2[1]:
            notes = st.text_area(
                "Notes",
                placeholder="Describe the issue (e.g. 'Leaking under sink in kitchen')",
            )

        if st.button("Create ticket", type="primary"):
            ticket = {
                "id": _gen_id("tkt"),
                "tenant_name": tenant_name.strip(),
                "unit_id": unit_id.strip(),
                "category": category,
                "priority": priority,
                "status": "open",
                "scheduled_at": scheduled_at.isoformat() if scheduled_at else None,
                "created_at": _now_str(),
                "notes": notes.strip(),
            }
            st.session_state.tickets.append(ticket)
            st.success(f"Ticket created: {ticket['id']}")

    # KPIs / metrics
    open_cnt = sum(1 for t in st.session_state.tickets if t["status"] == "open")
    prog_cnt = sum(1 for t in st.session_state.tickets if t["status"] == "in_progress")
    done_cnt = sum(1 for t in st.session_state.tickets if t["status"] == "closed")
    m1, m2, m3 = st.columns(3)
    m1.metric("Open", open_cnt)
    m2.metric("In Progress", prog_cnt)
    m3.metric("Closed", done_cnt)

    st.divider()

    # filters for ticket list
    c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
    with c1:
        f_unit = st.text_input("Filter: Unit ID", "")
    with c2:
        f_status = st.multiselect(
            "Status",
            ["open", "in_progress", "closed"],
            default=["open", "in_progress", "closed"],
        )
    with c3:
        f_priority = st.multiselect(
            "Priority", ["low", "medium", "high"], []
        )
    with c4:
        sort_by = st.selectbox(
            "Sort by",
            ["created_at", "priority", "status", "unit_id", "category"],
        )

    tickets = st.session_state.tickets
    if f_unit:
        tickets = [t for t in tickets if f_unit.lower() in t["unit_id"].lower()]
    if f_status:
        tickets = [t for t in tickets if t["status"] in f_status]
    if f_priority:
        tickets = [t for t in tickets if t["priority"] in f_priority]

    tickets = sorted(
        tickets,
        key=lambda x: x.get(sort_by) or "",
        reverse=True,
    )

    if tickets:
        for t in tickets:
            with st.container(border=True):
                c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 1, 2])
                c1.write(f"**{t['id']}**")
                c2.write(t["unit_id"])
                c3.write(t["category"])
                c4.write(t["priority"].capitalize())
                c5.write(
                    f"Status: **{t['status']}** · Created: {t['created_at']} · "
                    f"Scheduled: {t['scheduled_at'] or '—'}"
                )

                b1, b2, b3, b4 = st.columns(4)
                if b1.button("Start", key=f"start_{t['id']}"):
                    t["status"] = "in_progress"
                    st.rerun()
                if b2.button("Close", key=f"close_{t['id']}"):
                    t["status"] = "closed"
                    st.rerun()
                if b3.button("Reopen", key=f"reopen_{t['id']}"):
                    t["status"] = "open"
                    st.rerun()
                if b4.button("Delete", key=f"del_{t['id']}"):
                    st.session_state.tickets = [
                        x for x in st.session_state.tickets if x["id"] != t["id"]
                    ]
                    st.rerun()
    else:
        st.info("No tickets yet. Create one above.")

# --------------------------
# Main
# --------------------------

def main():
    init_state()

    st.sidebar.title("Everrent Tenant Assistant")
    st.sidebar.caption(
        "Step 1 skeleton is running. Next we'll add RAG, DB, and auto-ticketing."
    )

    tabs = st.tabs(["💬 Chat", "📚 Knowledge Base", "🛠️ Service Desk"])
    with tabs[0]:
        tab_chat()
    with tabs[1]:
        tab_kb()
    with tabs[2]:
        tab_service()

    st.sidebar.divider()
    if st.sidebar.button("Reset app state", use_container_width=True):
        for k in ["messages", "documents", "tickets"]:
            if k in st.session_state:
                del st.session_state[k]
        st.toast("State cleared. Reloading…")
        st.rerun()


if __name__ == "__main__":
    main()