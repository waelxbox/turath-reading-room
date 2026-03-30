"""
app.py — TURATH Reading Room Streamlit Application
====================================================
A split-screen digital archive viewer for the Selim Hassan archaeological
records. Connects to a local SQLite database (built by build_db.py) and
serves a clean, academic research interface.
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

# ── Paths ────────────────────────────────────────────────────────────────────
DB_FILE = Path("data/archive_database.db")
JSON_FOLDER = Path("data/selim_transcriptions")
IMAGE_FOLDER = Path("data/images")

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
        /* Sidebar */
        [data-testid="stSidebar"] { background-color: #1a1a2e; }
        [data-testid="stSidebar"] * { color: #e0e0e0 !important; }

        /* Bigger search textarea */
        [data-testid="stSidebar"] textarea {
            min-height: 100px !important;
            font-size: 1rem !important;
        }

        /* Main area padding */
        .main .block-container { padding-top: 1.5rem; }

        /* Header badges */
        .badge {
            display: inline-block;
            background: #16213e;
            color: #e0c97f !important;
            border: 1px solid #e0c97f;
            border-radius: 6px;
            padding: 2px 10px;
            font-size: 0.82rem;
            font-weight: 600;
            margin-right: 6px;
            margin-bottom: 6px;
        }

        /* Tag pills */
        .tag-pill {
            display: inline-block;
            background: #0f3460;
            color: #a8d8ea !important;
            border-radius: 12px;
            padding: 2px 10px;
            font-size: 0.78rem;
            margin: 2px;
        }

        /* Translation block */
        .translation-block {
            background: #f9f6ef;
            border-left: 4px solid #c8a951;
            padding: 1rem 1.2rem;
            border-radius: 4px;
            color: #1a1a1a;
            font-size: 0.97rem;
            line-height: 1.7;
        }

        /* Nav arrow buttons */
        div[data-testid="column"] button {
            width: 100%;
            font-size: 1.4rem;
        }

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


# ── Image helper: respect EXIF orientation & ignore case-sensitivity ──────────
@st.cache_data(show_spinner=False)
def load_portrait_image(image_path: str) -> bytes | None:
    """Load a PNG, apply EXIF rotation, and handle Linux case-insensitivity."""
    try:
        target = Path(image_path)
        actual_path = None
        
        # 1. Try the exact match first
        if target.exists():
            actual_path = target
        # 2. If not found, scan the folder and ignore all uppercase/lowercase rules
        elif target.parent.exists():
            for f in target.parent.iterdir():
                if f.name.lower() == target.name.lower():
                    actual_path = f
                    break
                    
        if not actual_path:
            return None
            
        img = Image.open(actual_path)
        img = ImageOps.exif_transpose(img)   # applies EXIF orientation tag
        # If still landscape after EXIF correction, rotate 90° CW to portrait
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
    conn: sqlite3.Connection,
    query: str,
    site: str,
    sender: str,
) -> list[sqlite3.Row]:
    cur = conn.cursor()

    if query.strip():
        fts_query = " OR ".join(f'"{w}"' for w in query.split() if w)
        cur.execute(
            """
            SELECT d.id, d.Reference_Number, d.Document_Date,
                   d.Brief_Summary, d.Excavation_Site, d.Sender
            FROM documents d
            JOIN documents_fts fts ON d.id = fts.rowid
            WHERE documents_fts MATCH ?
            ORDER BY rank
            """,
            (fts_query,),
        )
    else:
        cur.execute(
            """
            SELECT id, Reference_Number, Document_Date,
                   Brief_Summary, Excavation_Site, Sender
            FROM documents
            ORDER BY Document_Date
            """
        )

    rows = cur.fetchall()
    filtered = []
    for row in rows:
        if site != "All Sites" and row["Excavation_Site"] != site:
            continue
        if sender != "All Senders" and row["Sender"] != sender:
            continue
        filtered.append(row)
    return filtered


def get_document(conn: sqlite3.Connection, doc_id: int) -> sqlite3.Row | None:
    cur = conn.cursor()
    cur.execute("SELECT * FROM documents WHERE id = ?", (doc_id,))
    return cur.fetchone()


# ── Tag/entity rendering ──────────────────────────────────────────────────────
def render_pills(text: str, css_class: str = "tag-pill") -> None:
    if not text:
        st.caption("—")
        return
    pills = "".join(
        f'<span class="{css_class}">{item.strip()}</span>'
        for item in text.split(",")
        if item.strip()
    )
    st.markdown(pills, unsafe_allow_html=True)


# ── Main app ──────────────────────────────────────────────────────────────────
def main() -> None:
    conn = get_connection()

    # ── Header ────────────────────────────────────────────────────────────────
    st.markdown("## 🏛️ Project TURATH — Selim Hassan Digital Archive")
    st.caption(
        "A digital reading room for the Selim Hassan archaeological correspondence "
        "and administrative records."
    )
    st.divider()

    # ── Sidebar (Command Center) ───────────────────────────────────────────────
    with st.sidebar:
        st.markdown("### 🔍 Command Center")

        # Taller search box via text_area
        search_query = st.text_area(
            "Natural Language & Keyword Search",
            placeholder="e.g. letters about budget or salary\ne.g. excavation permit Saqqara",
            height=110,
            help="Searches across summaries, translations, and Arabic transcriptions via FTS5.",
        )

        st.markdown("#### Smart Filters")
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
            # Build option labels
            options = []
            for row in results:
                date_str = row["Document_Date"] or "Undated"
                ref_str = row["Reference_Number"] or "—"
                snippet = (row["Brief_Summary"] or "")[:55]
                label = f"{date_str}  ·  {ref_str}"
                if snippet:
                    label += f"\n{snippet}…"
                options.append((row["id"], label))

            # Initialise / clamp session index
            if "doc_index" not in st.session_state:
                st.session_state.doc_index = 0
