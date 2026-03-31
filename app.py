"""
app.py — TURATH Reading Room & AI Archivist
============================================
Split-screen digital archive viewer + RAG-powered chatbot
for the Selim Hassan archaeological records.

Launch:  streamlit run app.py
"""

# ── Streamlit Cloud SQLite fix (must be first) ────────────────────────────────
import sys
__import__('pysqlite3')
sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')
# ─────────────────────────────────────────────────────────────────────────────

import io
import sqlite3
from pathlib import Path

import streamlit as st
from PIL import Image, ImageOps
from openai import OpenAI
import chromadb

def find_artifact_image(image_path_or_stem) -> str | None:
    """
    Resolve an image path from the database to a real file on disk.
    Handles three cases:
      1. Stored path is already correct (e.g. data/images/pngs_box_7/IMG_7279.png)
      2. Stored path is stale/flat (e.g. data/images/IMG_7279.png) — search by stem
      3. Only a stem is passed — search recursively
    """
    if not image_path_or_stem:
        return None
    p = Path(image_path_or_stem)
    # Case 1: exact path exists
    if p.exists():
        return str(p)
    # Case 2 & 3: search by stem across all subfolders
    stem = p.stem  # e.g. "IMG_7279"
    matches = list(Path("data/images").rglob(f"{stem}.png"))
    if matches:
        return str(matches[0])
    return None
# ── Paths ─────────────────────────────────────────────────────────────────────
DB_FILE    = Path("data/archive_database.db")
JSON_FOLDER = Path("data/selim_transcriptions")
IMAGE_FOLDER = Path("data/images")
CHROMA_DIR = Path("data/chroma_db")

# ── Chroma collection name — must match build_db.py ──────────────────────────
CHROMA_COLLECTION = "turath_archive"

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="🏛️ Project TURATH: Selim Hassan Digital Archive",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    [data-testid="stSidebar"] { background-color: #1a1a2e; }
    [data-testid="stSidebar"] * { color: #e0e0e0 !important; }
    [data-testid="stSidebar"] textarea { min-height: 100px !important; font-size: 1rem !important; }
    .main .block-container { padding-top: 1.5rem; }
    .badge {
        display: inline-block; background: #16213e; color: #e0c97f !important;
        border: 1px solid #e0c97f; border-radius: 6px; padding: 2px 10px;
        font-size: 0.82rem; font-weight: 600; margin-right: 6px; margin-bottom: 6px;
    }
    .tag-pill {
        display: inline-block; background: #0f3460; color: #a8d8ea !important;
        border-radius: 12px; padding: 2px 10px; font-size: 0.78rem; margin: 2px;
    }
    .translation-block {
        background: #f9f6ef; border-left: 4px solid #c8a951; padding: 1rem 1.2rem;
        border-radius: 4px; color: #1a1a1a; font-size: 0.97rem; line-height: 1.7;
    }
    div[data-testid="column"] button { width: 100%; font-size: 1.4rem; }
    hr { border-color: #333; }
</style>
""", unsafe_allow_html=True)


# ── Database check ────────────────────────────────────────────────────────────
def ensure_database() -> None:
    """Verify the pre-built database exists (built by GitHub Actions, not at runtime)."""
    if not DB_FILE.exists():
        st.error(
            "⚠️ Archive database not found. "
            "Please trigger the **Build Digital Archive Databases** GitHub Action "
            "to generate `data/archive_database.db`, then redeploy."
        )
        st.stop()


@st.cache_resource
def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@st.cache_data(show_spinner=False)
def has_column(_conn, table: str, column: str) -> bool:
    """Return True if the given column exists in the given table."""
    cur = _conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())


@st.cache_resource
def get_chroma_collection():
    """Return the persistent ChromaDB collection."""
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return client.get_or_create_collection(CHROMA_COLLECTION)


# ── Image helper ──────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def load_portrait_image(image_path: str) -> bytes | None:
    """Load PNG, apply EXIF rotation, ensure portrait orientation, return bytes."""
    try:
        target = Path(image_path)
        actual_path = None
        if target.exists():
            actual_path = target
        elif target.parent.exists():
            for f in target.parent.iterdir():
                if f.name.lower() == target.name.lower():
                    actual_path = f
                    break
        if not actual_path:
            return None
        img = Image.open(actual_path)
        img = ImageOps.exif_transpose(img)
        if img.width > img.height:
            img = img.rotate(-90, expand=True)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


# ── Query helpers ─────────────────────────────────────────────────────────────
def distinct_values(conn: sqlite3.Connection, column: str) -> list[str]:
    cur = conn.cursor()
    cur.execute(
        f"SELECT DISTINCT {column} FROM documents "
        f"WHERE {column} IS NOT NULL AND {column} != '' ORDER BY {column}"
    )
    return [row[0] for row in cur.fetchall()]


def search_documents(
    conn: sqlite3.Connection, query: str, site: str, sender: str
) -> list[sqlite3.Row]:
    cur = conn.cursor()
    # Gracefully handle databases that pre-date the box_label column
    box_col = "d.box_label" if has_column(conn, "documents", "box_label") else "NULL AS box_label"
    box_col_plain = "box_label" if has_column(conn, "documents", "box_label") else "NULL AS box_label"
    if query.strip():
        fts_query = " OR ".join(f'"{w}"' for w in query.split() if w)
        cur.execute(f"""
            SELECT d.id, d.Reference_Number, d.Document_Date,
                   d.Brief_Summary, d.English_Translation,
                   d.Excavation_Site, d.Sender, {box_col}
            FROM documents d
            JOIN documents_fts fts ON d.id = fts.rowid
            WHERE documents_fts MATCH ?
            ORDER BY rank
        """, (fts_query,))
    else:
        cur.execute(f"""
            SELECT id, Reference_Number, Document_Date,
                   Brief_Summary, English_Translation,
                   Excavation_Site, Sender, {box_col_plain}
            FROM documents ORDER BY Document_Date
        """)
    rows = cur.fetchall()
    return [
        row for row in rows
        if (site == "All Sites" or row["Excavation_Site"] == site)
        and (sender == "All Senders" or row["Sender"] == sender)
    ]


def get_document(conn: sqlite3.Connection, doc_id: int) -> sqlite3.Row | None:
    cur = conn.cursor()
    cur.execute("SELECT * FROM documents WHERE id = ?", (doc_id,))
    return cur.fetchone()


def render_pills(text: str, css_class: str = "tag-pill") -> None:
    if not text:
        st.caption("—")
        return
    pills = "".join(
        f'<span class="{css_class}">{item.strip()}</span>'
        for item in text.split(",") if item.strip()
    )
    st.markdown(pills, unsafe_allow_html=True)


# ── Main app ──────────────────────────────────────────────────────────────────
def main() -> None:
    ensure_database()
    conn = get_connection()

    st.markdown("## 🏛️ Project TURATH — Selim Hassan Digital Archive")
    st.divider()

    with st.sidebar:
        app_mode = st.radio("Navigation", ["📖 Reading Room", "🤖 AI Archivist Chat"])
        st.divider()

    # ══════════════════════════════════════════════════════════════════════════
    # MODE 1 — AI ARCHIVIST CHAT
    # ══════════════════════════════════════════════════════════════════════════
    if app_mode == "🤖 AI Archivist Chat":
        st.subheader("🤖 Chat with the Archive")
        st.caption("Semantic search over the Selim Hassan records, powered by Gemini.")

        if "OPENAI_API_KEY" not in st.secrets:
            st.error(
                "Missing API key. Add `OPENAI_API_KEY` to your Streamlit Secrets "
                "(Settings → Secrets) and redeploy."
            )
            return

        # OpenAI-compatible client pointed at Google's Gemini endpoint
        client = OpenAI(
            api_key=st.secrets["OPENAI_API_KEY"],
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )

        if "messages" not in st.session_state:
            st.session_state.messages = [{
                "role": "assistant",
                "content": (
                    "Welcome to the TURATH Reading Room. "
                    "How can I help you research the Selim Hassan collection today?"
                ),
            }]

        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        if prompt := st.chat_input("E.g., What were the main financial concerns at the Giza dig?"):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            # ── Semantic retrieval via ChromaDB ───────────────────────────────
            relevant_docs = []
            try:
                collection = get_chroma_collection()
                chroma_results = collection.query(
                    query_texts=[prompt],
                    n_results=min(4, collection.count()),
                )
                if chroma_results and chroma_results.get("ids"):
                    for doc_id in chroma_results["ids"][0]:
                        doc = get_document(conn, int(doc_id))
                        if doc:
                            relevant_docs.append(doc)
            except Exception as e:
                st.warning(f"⚠️ Semantic search error: {e}")

            # ── Build context for the LLM ─────────────────────────────────────
            if relevant_docs:
                context = "Most relevant historical documents retrieved via semantic search:\n\n"
                for i, doc in enumerate(relevant_docs):
                    context += (
                        f"--- Document {i+1} ---\n"
                        f"Date: {doc['Document_Date'] or 'Unknown'}\n"
                        f"From: {doc['Sender'] or 'Unknown'}\n"
                        f"Site: {doc['Excavation_Site'] or 'Unknown'}\n"
                        f"Summary: {doc['Brief_Summary'] or ''}\n"
                        f"Translation: {doc['English_Translation'] or ''}\n\n"
                    )
            else:
                context = "No specific documents were found in the archive for this query."

            system_prompt = (
                "You are the lead AI Archivist for Project TURATH, an expert in "
                "Egyptology and the Selim Hassan collection. "
                "Answer the user's question using ONLY the provided historical document context. "
                "If the answer is not in the context, politely say you cannot find it in the "
                "currently digitised records. "
                "Cite the Date or Sender of documents when you state facts."
            )

            # ── Stream the Gemini response ────────────────────────────────────
            with st.chat_message("assistant"):
                placeholder = st.empty()
                full_response = ""
                try:
                    stream = client.chat.completions.create(
                        model="gemini-2.5-flash",   # ← corrected model name
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {prompt}"},
                        ],
                        stream=True,
                    )
                    for chunk in stream:
                        delta = chunk.choices[0].delta.content
                        if delta:
                            full_response += delta
                            placeholder.markdown(full_response + "▌")
                    placeholder.markdown(full_response)
                except Exception as e:
                    full_response = f"⚠️ AI response error: {e}"
                    placeholder.markdown(full_response)

            st.session_state.messages.append({"role": "assistant", "content": full_response})

    # ══════════════════════════════════════════════════════════════════════════
    # MODE 2 — READING ROOM VIEWER
    # ══════════════════════════════════════════════════════════════════════════
    elif app_mode == "📖 Reading Room":
        with st.sidebar:
            st.markdown("### 🔍 Command Center")
            search_query = st.text_area(
                "Natural Language & Keyword Search",
                placeholder="e.g. excavation permit Saqqara\ne.g. salary budget",
                height=110,
            )

            sites   = ["All Sites"]   + distinct_values(conn, "Excavation_Site")
            senders = ["All Senders"] + distinct_values(conn, "Sender")
            site_filter   = st.selectbox("Excavation Site", sites)
            sender_filter = st.selectbox("Sender", senders)

            results = search_documents(conn, search_query, site_filter, sender_filter)
            st.markdown(f"#### 📋 Results — {len(results)} document(s)")

            if not results:
                st.info("No documents match your criteria.")
                st.session_state.doc_index = 0
                selected_id = None
            else:
                options = []
                for row in results:
                    date_str = row["Document_Date"] or "Undated"
                    ref_str  = row["Reference_Number"] or "—"
                    snippet  = (row["Brief_Summary"] or "")[:55]
                    box_str  = row["box_label"] if "box_label" in row.keys() else ""
                    label    = f"{box_str}  ·  {date_str}  ·  {ref_str}" if box_str else f"{date_str}  ·  {ref_str}"
                    if snippet:
                        label += f"\n{snippet}…"
                    options.append((row["id"], label))

                # Initialise / clamp session index
                if "doc_index" not in st.session_state:
                    st.session_state.doc_index = 0
                st.session_state.doc_index = max(
                    0, min(st.session_state.doc_index, len(options) - 1)
                )

                # Prev / Next arrows
                arrow_l, arrow_mid, arrow_r = st.columns([1, 3, 1])
                with arrow_l:
                    if st.button("◀", key="prev_btn",
                                 disabled=(st.session_state.doc_index == 0)):
                        st.session_state.doc_index -= 1
                        st.rerun()
                with arrow_mid:
                    st.caption(
                        f"Document {st.session_state.doc_index + 1} of {len(options)}"
                    )
                with arrow_r:
                    if st.button("▶", key="next_btn",
                                 disabled=(st.session_state.doc_index == len(options) - 1)):
                        st.session_state.doc_index += 1
                        st.rerun()

                # Dropdown selector (synced with arrow index)
                chosen_idx = st.selectbox(
                    "Jump to document",
                    range(len(options)),
                    index=st.session_state.doc_index,
                    format_func=lambda i: options[i][1],
                    key="doc_selector",
                )
                if chosen_idx != st.session_state.doc_index:
                    st.session_state.doc_index = chosen_idx
                    st.rerun()

                selected_id = options[st.session_state.doc_index][0]

        # ── Main stage ────────────────────────────────────────────────────────
        if not results or selected_id is None:
            st.markdown(
                "> 👈 Use the **Command Center** in the sidebar to search for documents."
            )
            return

        doc = get_document(conn, selected_id)
        if doc is None:
            return

        left, right = st.columns([1, 1], gap="large")

        with left:
            st.markdown("### 📜 The Artifact")
            img_path  = find_artifact_image(doc["image_path"]) if doc["image_path"] else None
            img_bytes = load_portrait_image(img_path) if img_path else None
            if img_bytes:
                st.image(img_bytes, use_container_width=True)
            else:
                st.warning(f"Image not found: `{doc['image_path']}`")
                st.markdown(
                    "<div style='height:300px;background:#1a1a2e;border-radius:8px;"
                    "display:flex;align-items:center;justify-content:center;"
                    "color:#555;font-size:3rem;'>🖼️</div>",
                    unsafe_allow_html=True,
                )

        with right:
            st.markdown("### 📖 The Decoded Data")

            badges = ""
            if doc["Reference_Number"]:
                badges += f'<span class="badge">📁 {doc["Reference_Number"]}</span>'
            if doc["Document_Date"]:
                badges += f'<span class="badge">📅 {doc["Document_Date"]}</span>'
            if doc["Excavation_Site"]:
                badges += f'<span class="badge">📍 {doc["Excavation_Site"]}</span>'
            if badges:
                st.markdown(badges, unsafe_allow_html=True)

            st.divider()
            c1, c2 = st.columns(2)
            with c1:
                st.caption("**From**")
                st.write(doc["Sender"] or "—")
            with c2:
                st.caption("**To**")
                st.write(doc["Recipient"] or "—")

            st.divider()
            st.markdown("**English Translation**")
            translation = doc["English_Translation"] or "_No translation available._"
            st.markdown(
                f'<div class="translation-block">{translation}</div>',
                unsafe_allow_html=True,
            )

            st.divider()
            st.markdown("**Thematic Tags**")
            render_pills(doc["Thematic_Tags"])
            st.markdown("**Entities Mentioned**")
            render_pills(doc["Entities_Mentioned"])

            st.divider()
            with st.expander("📄 View Original Arabic Transcription"):
                transcription = doc["Full_Transcription"]
                if transcription:
                    st.markdown(
                        f'<div dir="rtl" style="font-size:1rem;line-height:1.8;">'
                        f"{transcription}</div>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.write("No transcription available.")
                if doc["Confidence_Notes"]:
                    st.caption(f"**Confidence Notes:** {doc['Confidence_Notes']}")

            if doc["Stamps_and_Annotations"]:
                with st.expander("🔖 Stamps & Annotations"):
                    render_pills(doc["Stamps_and_Annotations"])


if __name__ == "__main__":
    main()
