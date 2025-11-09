# app.py — Track B Demo (Chat + RAG + Auto Tickets + Service Desk)
# ---------------------------------------------------------------
from __future__ import annotations
import os
import uuid
import datetime as dt
from typing import List, Dict, Any

import streamlit as st
from dotenv import load_dotenv

# ==== project modules ====
from src.store.db import init_db, get_conn, execute, query
from src.rag.chunker import pdf_to_chunks
from src.rag.index import add_chunks, search
from src.rag.retrieval import answer_with_citations
from src.service.tickets import (
    create_ticket, list_tickets, update_status, delete_ticket, recent_duplicate_exists
)
from src.service.autoschema import AUTO_TICKET_TOOL, high_confidence

# ==== OpenAI client (supports base_url) ====
try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # 让应用能在未安装 openai 时仍然打开其它页面

# ========= bootstrap =========
load_dotenv()  # 读取本地 .env（OPENAI_API_KEY / OPENAI_BASE_URL / CHAT_MODEL / EMBED_MODEL）

st.set_page_config(page_title="Track B · RAG + Service Desk", layout="wide")

@st.cache_resource(show_spinner=False)
def _init_and_connect():
    init_db()
    return get_conn()

conn = _init_and_connect()

# ========= sidebar =========
st.sidebar.title("Settings")
default_unit = st.sidebar.text_input("Active Unit", value="A-101")
enable_rag = st.sidebar.checkbox("Enable citations (RAG)", value=True)
enable_ticket = st.sidebar.checkbox("Enable auto-ticket from chat", value=True)

# API key / base url from Secrets, then .env
api_key = None
base_url = None
try:
    if "OPENAI_API_KEY" in st.secrets:
        api_key = st.secrets["OPENAI_API_KEY"]
    if "OPENAI_BASE_URL" in st.secrets:
        base_url = st.secrets["OPENAI_BASE_URL"]
except Exception:
    pass
api_key = api_key or os.getenv("OPENAI_API_KEY")
base_url = base_url or os.getenv("OPENAI_BASE_URL")

model_chat = st.sidebar.text_input("Chat model", value=os.getenv("CHAT_MODEL", "gpt-4o-mini"))
model_embed = st.sidebar.text_input("Embedding model", value=os.getenv("EMBED_MODEL", "text-embedding-3-small"))

if not api_key:
    st.sidebar.error("OPENAI_API_KEY 未配置（.env 或 Secrets）。聊天、嵌入与工单抽取将不可用。")

# ========= tabs =========
tab_chat, tab_kb, tab_desk = st.tabs(["💬 Chat", "📚 Knowledge Base", "🛠 Service Desk"])

# ---------------------------------------------------------------------
# 💬 Chat
# ---------------------------------------------------------------------
with tab_chat:
    st.subheader("Assistant")

    if "messages" not in st.session_state:
        st.session_state.messages: List[tuple[str, str]] = []

    for role, content in st.session_state.messages:
        with st.chat_message(role):
            st.markdown(content)

    prompt = st.chat_input("Type your message…")
    if prompt:
        st.session_state.messages.append(("user", prompt))
        with st.chat_message("user"):
            st.markdown(prompt)

        # ---------- Auto-ticket (Responses API + Chat Completions 双通道) ----------
        draft: Dict[str, Any] | None = None
        tool_error: str | None = None

        def _to_cc_tool(t: Dict[str, Any]) -> Dict[str, Any]:
            """
            将 autoschema.AUTOTICKET_TOOL (Responses 版)
            转成 Chat Completions 版工具描述：
            {"type":"function","name":"create_ticket_draft","parameters":{...}}
            -> {"type":"function","function":{"name":"create_ticket_draft","parameters":{...}}}
            """
            if not t:
                return {}
            if "function" in t:  # 已是 CC 形状
                return t
            name = t.get("name", "create_ticket_draft")
            desc = t.get("description", "Create maintenance ticket draft")
            params = t.get("parameters", {})
            return {"type": "function", "function": {"name": name, "description": desc, "parameters": params}}

        if enable_ticket and OpenAI and api_key:
            try:
                client = OpenAI(api_key=api_key, base_url=base_url, timeout=30.0)

                # 1) 尝试 Responses API（out.type == "tool_use"）
                try:
                    rs = client.responses.create(
                        model=model_chat,
                        input=[{"role": "user", "content": prompt}],
                        tools=[AUTO_TICKET_TOOL],
                        tool_choice="auto",
                    )
                    for out in getattr(rs, "output", []) or []:
                        if getattr(out, "type", "") == "tool_use" and getattr(out, "name", "") == "create_ticket_draft":
                            draft = out.input  # dict: unit_id/category/priority/summary/access_window/confidence
                            break
                except Exception as e:
                    tool_error = f"responses.create failed: {e}"

                # 2) 兜底：Chat Completions（message.tool_calls）
                if not draft:
                    try:
                        cc_tool = _to_cc_tool(AUTO_TICKET_TOOL)
                        cc = client.chat.completions.create(
                            model=model_chat,
                            messages=[
                                {"role": "system", "content": "You are a helpful assistant that files maintenance tickets when appropriate."},
                                {"role": "user", "content": prompt},
                            ],
                            tools=[cc_tool],
                            tool_choice="auto",
                        )
                        tcalls = (cc.choices[0].message.tool_calls or [])
                        for call in tcalls:
                            fn = getattr(call, "function", None)
                            if not fn:
                                continue
                            if getattr(fn, "name", "") == "create_ticket_draft":
                                import json
                                try:
                                    draft = json.loads(fn.arguments or "{}")
                                except Exception:
                                    draft = {}
                                break
                    except Exception as e:
                        tool_error = (tool_error or "") + f" | chat.completions failed: {e}"

            except Exception as e:
                tool_error = (tool_error or "") + f" | OpenAI init error: {e}"

        # 展示草稿 & 创建
        if draft:
            with st.chat_message("assistant"):
                st.markdown("**Detected a maintenance request (draft):**")
                st.json(draft)

                is_dup = recent_duplicate_exists(conn, draft.get("unit_id", ""), draft.get("summary", ""))
                if is_dup:
                    st.warning("A similar ticket exists in the last 2 hours. Consider merging.")

                create_now = high_confidence(draft) and not is_dup
                if not create_now:
                    if st.button("Create ticket", key=f"btn_create_{uuid.uuid4()}"):
                        create_now = True

                if create_now:
                    # NOTE: 不再传 status 参数；建单后显式置为 open（确保可见）
                    tid = create_ticket(
                        conn,
                        unit_id=draft.get("unit_id", default_unit),
                        category=draft.get("category", "other"),
                        priority=draft.get("priority", "medium"),
                        summary=draft.get("summary", prompt[:140]),
                        access_window=draft.get("access_window", ""),
                    )
                    try:
                        update_status(conn, tid, "open")
                    except Exception:
                        pass
                    st.success(f"Ticket created: #{tid}")

        elif tool_error:
            with st.chat_message("assistant"):
                st.warning(f"Auto-ticket draft skipped ({tool_error}).")

        # ---------- RAG answer (with citations) or plain chat ----------
        answer_text = ""
        if enable_rag:
            hits = []
            try:
                hits = search(prompt, unit_id=default_unit, k=4)
            except Exception:
                hits = []
            if not hits:
                with st.chat_message("assistant"):
                    st.info("I couldn't find this in your documents. Please upload the relevant lease or rules.")
                    st.session_state.messages.append(("assistant", "I couldn't find this in your documents."))
            else:
                try:
                    if not (OpenAI and api_key):
                        raise RuntimeError("OpenAI key/base_url missing")
                    client = OpenAI(api_key=api_key, base_url=base_url, timeout=30.0)
                    answer_text = answer_with_citations(
                        client=client,
                        model=model_chat,
                        question=prompt,
                        hits=hits,
                        unit_id=default_unit,
                    )
                except Exception as e:
                    answer_text = f"RAG failed: {e}\n\nI can still chat without citations if you disable RAG."
                with st.chat_message("assistant"):
                    st.markdown(answer_text or "")
                st.session_state.messages.append(("assistant", answer_text or ""))
        else:
            # 非 RAG 模式：普通对话
            try:
                if not (OpenAI and api_key):
                    raise RuntimeError("OpenAI key/base_url missing")
                client = OpenAI(api_key=api_key, base_url=base_url, timeout=30.0)
                rs = client.chat.completions.create(
                    model=model_chat,
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant."},
                        {"role": "user", "content": prompt},
                    ],
                )
                text = rs.choices[0].message.content
            except Exception as e:
                text = f"Chat failed: {e}"
            with st.chat_message("assistant"):
                st.markdown(text)
            st.session_state.messages.append(("assistant", text))

# ---------------------------------------------------------------------
# 📚 Knowledge Base
# ---------------------------------------------------------------------
with tab_kb:
    st.subheader("Upload lease / rules PDFs")
    files = st.file_uploader(
        "Drag and drop files here",
        type=["pdf"],
        accept_multiple_files=True,
        label_visibility="collapsed",
    )
    if files:
        for f in files:
            name = f.name
            raw = f.read()
            doc_id = f"doc_{uuid.uuid4().hex[:8]}"

            # 记录 documents 元数据（pages 暂 0；size_kb 用文件大小）
            execute(
                conn,
                """
                INSERT INTO documents(id, name, unit_id, doc_type, version, effective_from, pages, size_kb, uploaded_at)
                VALUES (?, ?, ?, 'lease', 1, ?, 0, ?, ?)
                """,
                (
                    doc_id,
                    name,
                    default_unit,
                    dt.datetime.utcnow().isoformat(timespec="seconds"),
                    round(len(raw) / 1024, 1),
                    dt.datetime.utcnow().isoformat(timespec="seconds"),
                ),
            )

            # 抽取/切块/索引（带进度可视化）
            with st.status(f"Indexing {name} …", expanded=True) as s:
                try:
                    s.write("Extracting & chunking …")
                    chunks = pdf_to_chunks(doc_id, name, default_unit, raw)
                    s.write(f"Chunks: {len(chunks)}")
                    s.write("Embedding & writing to vector store …")
                    n = add_chunks(chunks)
                    s.update(label=f"Indexed {name} (chunks: {n})", state="complete", expanded=False)
                    st.toast(f"Indexed: {name} (chunks: {n})")
                except Exception as e:
                    s.update(label="Indexed metadata only (vector error or extract fail)", state="error", expanded=True)
                    st.warning(f"Index error: {e}")

    # 文档清单
    rows = query(
        conn,
        "SELECT id, name, unit_id, doc_type, version, effective_from, pages, size_kb, uploaded_at "
        "FROM documents ORDER BY uploaded_at DESC",
    )
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("No documents yet. Upload a PDF to build your knowledge base.")

    st.markdown("### Quick test (vector search only)")
    q = st.text_input("Search phrase (filtered by Active Unit):", "", label_visibility="collapsed")
    if q:
        hits = search(q, unit_id=default_unit, k=5)
        if not hits:
            st.warning("No hits. Try another keyword, or check if documents were indexed successfully.")
        for h in hits:
            st.markdown(
                f"- **{h.get('file','(unknown)')}** p.{h.get('page','?')}  \n"
                f"  {h.get('text','')[:240].replace(chr(10),' ')}"
            )

# ---------------------------------------------------------------------
# 🛠 Service Desk
# ---------------------------------------------------------------------
with tab_desk:
    st.subheader("Tickets")
    if st.button("Refresh list"):
        st.rerun()

    rows = list_tickets(conn)
    if not rows:
        st.info("No tickets yet. Create one from Chat or here.")
    else:
        for r in rows:
            with st.container(border=True):
                st.markdown(
                    f"**#{r['id']}** · Unit **{r['unit_id']}** · **{r['category']}** · Priority **{r['priority']}**"
                )
                st.write(r["summary"])
                cols = st.columns([1,1,1,1,2])
                with cols[0]:
                    new_status = st.selectbox(
                        "Status",
                        ["open", "in_progress", "closed"],
                        index=["open", "in_progress", "closed"].index(r["status"]),
                        key=f"status_{r['id']}",
                    )
                with cols[1]:
                    if st.button("Update", key=f"update_{r['id']}"):
                        update_status(conn, r["id"], new_status)
                        st.toast(f"Ticket #{r['id']} updated → {new_status}")
                        st.rerun()
                with cols[2]:
                    if st.button("Close", key=f"close_{r['id']}"):
                        update_status(conn, r["id"], "closed")
                        st.toast(f"Ticket #{r['id']} closed")
                        st.rerun()
                with cols[3]:
                    if st.button("Delete", type="primary", key=f"del_{r['id']}"):
                        delete_ticket(conn, r["id"])
                        st.toast(f"Ticket #{r['id']} deleted")
                        st.rerun()
                with cols[4]:
                    st.caption(f"Created at: {r['created_at']}  |  Access window: {r.get('access_window','')}")
