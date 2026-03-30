"""
app.py — TURATH Reading Room & AI Archivist (ChromaDB Version)
====================================================
A split-screen digital archive viewer and RAG-powered 
chatbot for the Selim Hassan archaeological records.
"""

# --- STREAMLIT CLOUD SQLITE FIX ---
import sys
__import__('pysqlite3')
sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')
# ----------------------------------

import io
import sqlite3
from pathlib import Path
import streamlit as st
from PIL import Image, ImageOps
from openai import OpenAI
import chromadb

# ── Paths ────────────────────────────────────────────────────────────────────
DB_FILE = Path("data/archive_database.db")
JSON_FOLDER = Path("data/selim_transcriptions")
IMAGE_FOLDER = Path("data/images")
CHROMA_DIR = Path("data/chroma_db")

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="🏛️ Project TURATH: Selim Hassan Digital Archive",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown(
    """
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
    """,
    unsafe_allow_html=True,
)

@st.cache_resource
def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

@st.cache_data(show_spinner=False)
def load_portrait_image(image_path: str) -> bytes | None:
    try:
        target = Path(image_path)
        actual_path = None
        if target.exists(): actual_path = target
        elif target.parent.exists():
            for f in target.parent.iterdir():
                if f.name.lower() == target.name.lower():
                    actual_path = f
                    break
        if not actual_path: return None
        img = Image.open(actual_path)
        img = ImageOps.exif_transpose(img)
        if img.width > img.height: img = img.rotate(-90, expand=True)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None

def distinct_values(conn: sqlite3.Connection, column: str) -> list[str]:
    cur = conn.cursor()
    cur.execute(f"SELECT DISTINCT {column} FROM documents WHERE {column} IS NOT NULL AND {column} != '' ORDER BY {column}")
    return [row[0] for row in cur.fetchall()]

def search_documents(conn: sqlite3.Connection, query: str, site: str, sender: str) -> list[sqlite3.Row]:
    cur = conn.cursor()
    if query.strip():
        fts_query = " AND ".join(f'"{w}"' for w in query.split() if w)
        cur.execute(
            """
            SELECT d.id, d.Reference_Number, d.Document_Date, d.Brief_Summary, d.English_Translation, d.Excavation_Site, d.Sender
            FROM documents d JOIN documents_fts fts ON d.id = fts.rowid
            WHERE documents_fts MATCH ? ORDER BY rank
            """, (fts_query,)
        )
    else:
        cur.execute("SELECT id, Reference_Number, Document_Date, Brief_Summary, English_Translation, Excavation_Site, Sender FROM documents ORDER BY Document_Date")
    rows = cur.fetchall()
    return [row for row in rows if (site == "All Sites" or row["Excavation_Site"] == site) and (sender == "All Senders" or row["Sender"] == sender)]

def get_document(conn: sqlite3.Connection, doc_id: int) -> sqlite3.Row | None:
    cur = conn.cursor()
    cur.execute("SELECT * FROM documents WHERE id = ?", (doc_id,))
    return cur.fetchone()

def render_pills(text: str, css_class: str = "tag-pill") -> None:
    if not text:
        st.caption("—")
        return
    pills = "".join(f'<span class="{css_class}">{item.strip()}</span>' for item in text.split(",") if item.strip())
    st.markdown(pills, unsafe_allow_html=True)


# ── Main app ──────────────────────────────────────────────────────────────────
def main() -> None:
    conn = get_connection()

    st.markdown("## 🏛️ Project TURATH — Selim Hassan Digital Archive")
    st.divider()

    with st.sidebar:
        app_mode = st.radio("Navigation", ["📖 Reading Room", "🤖 AI Archivist Chat"])
        st.divider()

    # ==========================================
    # MODE 1: THE AI ARCHIVIST CHAT (CHROMADB)
    # ==========================================
    if app_mode == "🤖 AI Archivist Chat":
        st.subheader("🤖 Chat with the Archive")
        st.caption("Using Semantic Search to analyze the Selim Hassan records.")

        if "OPENAI_API_KEY" not in st.secrets:
            st.error("Missing OpenAI API Key. Please add it to your Streamlit Secrets.")
            return
        
        client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

        if "messages" not in st.session_state:
            st.session_state.messages = [{"role": "assistant", "content": "Welcome to the TURATH Reading Room. How can I help you research the collection today?"}]

        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        if prompt := st.chat_input("E.g., What were the main financial concerns at the Giza dig?"):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            # --- CHROMA DB SEMANTIC RETRIEVAL ---
            relevant_docs = []
            try:
                chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
                # Attempt to grab the first available collection, commonly "documents"
                collections = chroma_client.list_collections()
                if not collections:
                    st.error("No ChromaDB collections found. Did the GitHub Action build them?")
                else:
                    collection = collections[0] 
                    
                    # Query ChromaDB for the closest semantic matches
                    chroma_results = collection.query(
                        query_texts=[prompt],
                        n_results=4
                    )
                    
                    # Grab the SQLite row IDs from Chroma's results
                    if chroma_results and "ids" in chroma_results and len(chroma_results["ids"]) > 0:
                        doc_ids = chroma_results["ids"][0]
                        for doc_id in doc_ids:
                            doc = get_document(conn, int(doc_id))
                            if doc:
                                relevant_docs.append(doc)
            except Exception as e:
                st.error(f"⚠️ ChromaDB Semantic Search failed: {e}. (The server might be out of memory).")
            # ------------------------------------
            
            context = ""
            if relevant_docs:
                context += "Here are the most relevant historical documents retrieved via Semantic Search:\n\n"
                for i, doc in enumerate(relevant_docs):
                    context += f"--- Document {i+1} ---\nDate: {doc['Document_Date']}\nFrom: {doc['Sender']}\nSite: {doc['Excavation_Site']}\nTranslation: {doc['English_Translation']}\n\n"
            else:
                context += "No specific documents were found."

            # Build the AI Prompt
            system_prompt = (
                "You are the lead AI Archivist for Project TURATH, an expert in Egyptology and the Selim Hassan collection. "
                "Answer the user's question using ONLY the provided historical document context. "
                "If the answer is not in the context, politely say you cannot find it in the currently digitized records. "
                "Cite the Date or Sender of the documents when you provide facts."
            )

            with st.chat_message("assistant"):
                message_placeholder = st.empty()
                full_response = ""
                
                responses = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"Context: {context}\n\nQuestion: {prompt}"}
                    ],
                    stream=True,
                )
                
                for chunk in responses:
                    if chunk.choices[0].delta.content is not None:
                        full_response += chunk.choices[0].delta.content
                        message_placeholder.markdown(full_response + "▌")
                
                message_placeholder.markdown(full_response)
            
            st.session_state.messages.append({"role": "assistant", "content": full_response})


    # ==========================================
    # MODE 2: THE READING ROOM VIEWER
    # ==========================================
    elif app_mode == "📖 Reading Room":
        with st.sidebar:
            st.markdown("### 🔍 Command Center")
            search_query = st.text_area("Keyword Search", height=110)
            
            sites = ["All Sites"] + distinct_values(conn, "Excavation_Site")
            senders = ["All Senders"] + distinct_values(conn, "Sender")
            site_filter = st.selectbox("Excavation Site", sites)
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
                    ref_str = row["Reference_Number"] or "—"
                    snippet = (row["Brief_Summary"] or "")[:55]
                    label = f"{date_str}  ·  {ref_str}"
                    if snippet: label += f"\n{snippet}…"
                    options.append((row["id"], label))

                if "doc_index" not in st.session_state: st.session_state.doc_index = 0
                st.session_state.doc_index = max(0, min(st.session_state.doc_index, len(options) - 1))

                arrow_l, arrow_mid, arrow_r = st.columns([1, 3, 1])
                with arrow_l:
                    if st.button("◀", key="prev_btn", disabled=(st.session_state.doc_index == 0)):
                        st.session_state.doc_index -= 1
                        st.rerun()
                with arrow_mid:
                    st.caption(f"Document {st.session_state.doc_index + 1} of {len(options)}")
                with arrow_r:
                    if st.button("▶", key="next_btn", disabled=(st.session_state.doc_index == len(options) - 1)):
                        st.session_state.doc_index += 1
                        st.rerun()

                chosen_idx = st.selectbox("Jump to document", range(len(options)), index=st.session_state.doc_index, format_func=lambda i: options[i][1], key="doc_selector")
                if chosen_idx != st.session_state.doc_index:
                    st.session_state.doc_index = chosen_idx
                    st.rerun()

                selected_id = options[st.session_state.doc_index][0]

        if not results or selected_id is None:
            st.markdown("> 👈 Use the **Command Center** in the sidebar to search for documents.")
            return

        doc = get_document(conn, selected_id)
        if doc is None: return

        left, right = st.columns([1, 1], gap="large")

        with left:
            st.markdown("### 📜 The Artifact")
            img_path = doc["image_path"]
            img_bytes = load_portrait_image(img_path) if img_path else None
            if img_bytes:
                st.image(img_bytes, use_container_width=True)
            else:
                st.warning(f"Image not found: `{img_path}`")

        with right:
            st.markdown("### 📖 The Decoded Data")
            badges = ""
            if doc["Reference_Number"]: badges += f'<span class="badge">📁 {doc["Reference_Number"]}</span>'
            if doc["Document_Date"]: badges += f'<span class="badge">📅 {doc["Document_Date"]}</span>'
            if doc["Excavation_Site"]: badges += f'<span class="badge">📍 {doc["Excavation_Site"]}</span>'
            if badges: st.markdown(badges, unsafe_allow_html=True)
            
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
            st.markdown(f'<div class="translation-block">{translation}</div>', unsafe_allow_html=True)
            
            st.divider()
            st.markdown("**Thematic Tags**")
            render_pills(doc["Thematic_Tags"])
            st.markdown("**Entities Mentioned**")
            render_pills(doc["Entities_Mentioned"])
            
            st.divider()
            with st.expander("📄 View Original Arabic Transcription"):
                transcription = doc["Full_Transcription"]
                if transcription: st.markdown(f'<div dir="rtl" style="font-size:1rem;line-height:1.8;">{transcription}</div>', unsafe_allow_html=True)
                else: st.write("No transcription available.")
                if doc["Confidence_Notes"]: st.caption(f"**Confidence Notes:** {doc['Confidence_Notes']}")

            if doc["Stamps_and_Annotations"]:
                with st.expander("🔖 Stamps & Annotations"):
                    render_pills(doc["Stamps_and_Annotations"])

if __name__ == "__main__":
    main()
