# Tenant Assistant (Track B) — Sprint 2 Prototype

## What this repo is
A minimal end-to-end prototype of the Track B tenant assistant.
It has:
- **Chat tab** (placeholder assistant)
- **Knowledge Base tab** (upload leases / house rules per unit)
- **Service Desk tab** (create & update maintenance tickets)

This matches the Sprint 2 goal of delivering a **working prototype** with a clear approach. Future steps will add retrieval-augmented answers and automatic ticket creation from chat.


## 1. Run locally
### 1. Install
```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. (Optional) set your OpenAI key for future RAG features
Create a `.env` file:
```bash
OPENAI_API_KEY="your-api-key-here"
```
Do **not** commit this file.

### 3. Launch the app
```bash
streamlit run app.py
```
Then open http://localhost:8501 in your browser.

You should see 3 tabs:
1. **💬 Chat** — right now it echoes and shows what it *would* do (answer contract questions, open tickets).
2. **📚 Knowledge Base** — upload PDFs, tag them with `unit_id`, and view stored metadata.
3. **🛠️ Service Desk** — log maintenance tickets, update status, filter, view KPIs.


## 2. Deploy to Streamlit Community Cloud
### Prep the repo
1. Commit all code to a public GitHub repo.
2. Make sure `.env` is **NOT** committed. The `.gitignore` here already excludes it.

### Deploy
1. Go to Streamlit Community Cloud (https://share.streamlit.io).
2. Connect your GitHub account and select this repo/branch.
3. Set **main file path** to `app.py`.
4. In **Advanced settings**, set Python version (e.g. 3.12) and add your secrets in TOML style under "Secrets", for example:
```toml
OPENAI_API_KEY = "your-api-key-here"
```
5. Click Deploy. The platform builds the app straight from your repo and gives you a public URL anyone can open.

### Why secrets?
- You should never push `.env` or API keys to GitHub.
- Streamlit Cloud lets you inject secrets at deploy time so they are available to your code via `st.secrets["OPENAI_API_KEY"]` (we'll start using that in the RAG step).

### Limitations of free hosting
- ~1 GB RAM and shared CPU.
- App will go to sleep after inactivity, and cold-start again when someone opens the link.
- No guaranteed persistent filesystem, so production data (vector store, tickets DB) should live in a real database later. For Sprint 2 we demo with in-memory state + small seeded examples.


## 3. Next steps (Sprint 2 ➜ Final)
**Planned upgrades:**
- Persist documents to a vector DB (Chroma / pgvector) with metadata (`unit_id`, `doc_type`, `effective_from`).
- Retrieval-Augmented answers in Chat, including quoted contract clauses + page refs.
- Automatically create/track Service Desk tickets from chat requests ("there is a leak in my bathroom").
- Replace in-memory lists with SQLite / Postgres tables and expose basic analytics.
- Add benchmark Q&A and include screenshots + README evidence for grading.

---
This repo, once pushed and deployed, already covers:
- public cloud demo of a tenant assistant UI,
- basic ticketing workflow,
- knowledge-base ingestion flow for leases & rules,
- and a clear path to retrieval + automation.