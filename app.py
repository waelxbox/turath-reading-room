"""
app.py — TURATH Reading Room Streamlit Application
====================================================
A split-screen digital archive viewer for the Selim Hassan archaeological
records. Connects to a local SQLite database (built by build_db.py) and
serves a clean, academic research interface.

Launch with:
    streamlit run app.py
"""

import sqlite3
import subprocess
import sys
from pathlib import Path

import streamlit as st

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

# ── Custom CSS for a polished, academic look ─────────────────────────────────
st.markdown(
    """
    <style>
        /* Sidebar background */
        [data-testid="stSidebar"] { background-color: #1a1a2e; }
        [data-testid="stSidebar"] * { color: #e0e0e0 !important; }

        /* Main area */
        .main .block-container { padding-top: 1.5rem; }

        /* Document header badges */
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

        /* Section dividers */
        hr { border-color: #333; }

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
    </style>
    """,
    unsafe_allow_html=True,
)


# ── Database bootstrap ────────────────────────────────────────────────────────
def ensure_database() -> None:
    """Auto-build the database on first launch if it doesn't exist."""
    if not DB_FILE.exists():
        with st.spinner("Building archive database for the first time — please wait…"):
            result = subprocess.run(
                [sys.executable, "build_db.py"],
                capture_output=True,
                text=True,
            )
        if result.returncode != 0:
            st.error(f"Database build failed:\n{result.stderr}")
            st.stop()
        st.success("Database built successfully. Welcome to the Reading Room.")
        st.rerun()


@st.cache_resource
def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


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
        # Build FTS5 query: each word is OR-joined for broad matching
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

    # Apply sidebar filters
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
    ensure_database()
    conn = get_connection()

    # ── Header ────────────────────────────────────────────────────────────────
    st.markdown(
        "## 🏛️ Project TURATH — Selim Hassan Digital Archive",
    )
    st.caption(
        "A digital reading room for the Selim Hassan archaeological correspondence "
        "and administrative records."
    )
    st.divider()

    # ── Sidebar (Command Center) ───────────────────────────────────────────────
    with st.sidebar:
        st.markdown("### 🔍 Command Center")

        search_query = st.text_input(
            "Natural Language & Keyword Search",
            placeholder="e.g. letters about budget or salary",
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
            selected_id = None
        else:
            options = []
            for row in results:
                date_str = row["Document_Date"] or "Undated"
                ref_str = row["Reference_Number"] or "—"
                summary_snippet = (row["Brief_Summary"] or "")[:60]
                label = f"{date_str}  ·  {ref_str}"
                if summary_snippet:
                    label += f"\n{summary_snippet}…"
                options.append((row["id"], label))

            idx = st.selectbox(
                "Select a document",
                range(len(options)),
                format_func=lambda i: options[i][1],
            )
            selected_id = options[idx][0]

    # ── Main Stage (Split-Screen Viewer) ──────────────────────────────────────
    if selected_id is None:
        st.markdown(
            "> 👈 Use the **Command Center** in the sidebar to search for documents "
            "and select one to begin exploring the archive."
        )
        return

    doc = get_document(conn, selected_id)
    if doc is None:
        st.error("Document not found in the database.")
        return

    left, right = st.columns([1, 1], gap="large")

    # ── Left: The Artifact ────────────────────────────────────────────────────
    with left:
        st.markdown("### 📜 The Artifact")
        img_path = Path(doc["image_path"]) if doc["image_path"] else None

        if img_path and img_path.exists():
            st.image(str(img_path), use_container_width=True)
        else:
            st.warning(
                f"Image not found: `{img_path}`\n\n"
                "Place the corresponding PNG in `data/images/` and rebuild the database."
            )
            st.markdown(
                "<div style='height:300px;background:#1a1a2e;border-radius:8px;"
                "display:flex;align-items:center;justify-content:center;"
                "color:#555;font-size:3rem;'>🖼️</div>",
                unsafe_allow_html=True,
            )

    # ── Right: The Decoded Data ───────────────────────────────────────────────
    with right:
        st.markdown("### 📖 The Decoded Data")

        # Header badges
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

        # Sender / Recipient
        c1, c2 = st.columns(2)
        with c1:
            st.caption("**From**")
            st.write(doc["Sender"] or "—")
        with c2:
            st.caption("**To**")
            st.write(doc["Recipient"] or "—")

        st.divider()

        # English Translation
        st.markdown("**English Translation**")
        translation = doc["English_Translation"] or "_No translation available._"
        st.markdown(
            f'<div class="translation-block">{translation}</div>',
            unsafe_allow_html=True,
        )

        st.divider()

        # Thematic Tags
        st.markdown("**Thematic Tags**")
        render_pills(doc["Thematic_Tags"])

        # Entities Mentioned
        st.markdown("**Entities Mentioned**")
        render_pills(doc["Entities_Mentioned"])

        st.divider()

        # Original Arabic Transcription (collapsed)
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

        # Stamps & Annotations (collapsed)
        if doc["Stamps_and_Annotations"]:
            with st.expander("🔖 Stamps & Annotations"):
                render_pills(doc["Stamps_and_Annotations"])


if __name__ == "__main__":
    main()
