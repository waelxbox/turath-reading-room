"""
build_db.py — TURATH Archive Database Builder
===============================================
Reads all JSON files from data/selim_transcriptions/, builds:
  1. SQLite database (data/archive_database.db) with FTS5 full-text search
  2. ChromaDB vector store (data/chroma_db/) for semantic / AI chat search

Run manually:   python build_db.py
Auto-run by:    .github/workflows/update_archive.yml on every JSON push
"""

import json
import sqlite3
from pathlib import Path

import chromadb

# ── Path configuration ────────────────────────────────────────────────────────
DATA_DIR    = Path("data")
JSON_FOLDER = DATA_DIR / "selim_transcriptions"
DB_FILE     = DATA_DIR / "archive_database.db"
CHROMA_DIR  = DATA_DIR / "chroma_db"
IMAGE_DIR   = DATA_DIR / "images"

DATA_DIR.mkdir(exist_ok=True)

# ── Collection name — must match app.py exactly ───────────────────────────────
CHROMA_COLLECTION = "turath_archive"


def list_to_str(value) -> str:
    """Convert a JSON list to a comma-separated string; pass strings through."""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if v)
    return str(value) if value is not None else ""


def sanitize_metadata(data: dict, filename: str) -> dict:
    """
    Coerce all Chroma metadata values to plain strings.
    ChromaDB rejects None, lists, or any non-scalar type.
    """
    return {
        "sender":   str(data.get("Sender")          or "Unknown"),
        "date":     str(data.get("Document_Date")   or "Unknown"),
        "site":     str(data.get("Excavation_Site") or "Unknown"),
        "source":   str(filename),
    }


def create_schema(conn: sqlite3.Connection) -> None:
    """Drop and recreate the documents table and FTS5 virtual table."""
    cur = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS documents_fts")
    cur.execute("DROP TABLE IF EXISTS documents")

    cur.execute("""
        CREATE TABLE documents (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            Reference_Number     TEXT,
            Document_Date        TEXT,
            Sender               TEXT,
            Recipient            TEXT,
            Excavation_Site      TEXT,
            Brief_Summary        TEXT,
            English_Translation  TEXT,
            Full_Transcription   TEXT,
            image_path           TEXT,
            Thematic_Tags        TEXT,
            Entities_Mentioned   TEXT,
            Stamps_and_Annotations TEXT,
            Confidence_Notes     TEXT
        )
    """)

    # FTS5 virtual table — indexes the three most search-relevant text columns.
    # content= keeps it in sync with the documents table automatically via triggers.
    cur.execute("""
        CREATE VIRTUAL TABLE documents_fts USING fts5(
            Brief_Summary,
            English_Translation,
            Full_Transcription,
            content='documents',
            content_rowid='id'
        )
    """)

    # Triggers to keep FTS5 in sync whenever documents rows change
    cur.execute("""
        CREATE TRIGGER docs_ai AFTER INSERT ON documents BEGIN
            INSERT INTO documents_fts(rowid, Brief_Summary, English_Translation, Full_Transcription)
            VALUES (new.id, new.Brief_Summary, new.English_Translation, new.Full_Transcription);
        END
    """)
    cur.execute("""
        CREATE TRIGGER docs_ad AFTER DELETE ON documents BEGIN
            INSERT INTO documents_fts(documents_fts, rowid, Brief_Summary, English_Translation, Full_Transcription)
            VALUES ('delete', old.id, old.Brief_Summary, old.English_Translation, old.Full_Transcription);
        END
    """)
    cur.execute("""
        CREATE TRIGGER docs_au AFTER UPDATE ON documents BEGIN
            INSERT INTO documents_fts(documents_fts, rowid, Brief_Summary, English_Translation, Full_Transcription)
            VALUES ('delete', old.id, old.Brief_Summary, old.English_Translation, old.Full_Transcription);
            INSERT INTO documents_fts(rowid, Brief_Summary, English_Translation, Full_Transcription)
            VALUES (new.id, new.Brief_Summary, new.English_Translation, new.Full_Transcription);
        END
    """)

    conn.commit()


def build_archive() -> None:
    print("🏗️  Initialising TURATH Build Process…")

    # ── SQLite ────────────────────────────────────────────────────────────────
    conn = sqlite3.connect(DB_FILE)
    create_schema(conn)
    cur = conn.cursor()

    # ── ChromaDB — delete existing collection so IDs don't collide on rebuild ─
    chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    try:
        chroma_client.delete_collection(CHROMA_COLLECTION)
        print(f"🗑️  Deleted existing ChromaDB collection '{CHROMA_COLLECTION}'")
    except Exception:
        pass  # Collection didn't exist yet — that's fine
    collection = chroma_client.create_collection(CHROMA_COLLECTION)

    # ── Process JSON files ────────────────────────────────────────────────────
    files = sorted(JSON_FOLDER.glob("*.json"))
    if not files:
        print(f"⚠️  No JSON files found in {JSON_FOLDER}")
        conn.close()
        return

    print(f"📄  Processing {len(files)} records…")

    for json_file in files:
        try:
            with open(json_file, encoding="utf-8") as f:
                data = json.load(f)

            # Synthesise image_path from the JSON filename (no image_path in JSON)
            stem = json_file.stem                          # e.g. "IMG_7291"
            image_path = str(IMAGE_DIR / f"{stem}.png")   # "data/images/IMG_7291.png"

            # Serialise list fields to comma-separated strings for SQLite
            thematic_tags        = list_to_str(data.get("Thematic_Tags"))
            entities_mentioned   = list_to_str(data.get("Entities_Mentioned"))
            stamps_annotations   = list_to_str(data.get("Stamps_and_Annotations"))

            translation_text     = data.get("English_Translation") or ""
            brief_summary        = data.get("Brief_Summary") or ""

            # 1. Insert into SQLite (triggers auto-populate FTS5)
            cur.execute("""
                INSERT INTO documents (
                    Reference_Number, Document_Date, Sender, Recipient,
                    Excavation_Site, Brief_Summary, English_Translation,
                    Full_Transcription, image_path,
                    Thematic_Tags, Entities_Mentioned,
                    Stamps_and_Annotations, Confidence_Notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data.get("Reference_Number"),
                data.get("Document_Date"),
                data.get("Sender"),
                data.get("Recipient"),
                data.get("Excavation_Site"),
                brief_summary,
                translation_text,
                data.get("Full_Transcription"),
                image_path,
                thematic_tags,
                entities_mentioned,
                stamps_annotations,
                data.get("Confidence_Notes"),
            ))
            row_id = cur.lastrowid

            # 2. Add to ChromaDB for semantic / AI chat search
            embed_text = f"{brief_summary}\n\n{translation_text}".strip() or stem
            collection.add(
                documents=[embed_text],
                ids=[str(row_id)],
                metadatas=[sanitize_metadata(data, json_file.name)],
            )

            print(f"  ✅  {json_file.name}  →  SQLite id={row_id}")

        except Exception as e:
            print(f"  ❌  Error processing {json_file.name}: {e}")

    conn.commit()
    conn.close()
    print("\n✨  Archive build complete — SQLite + FTS5 + ChromaDB are ready.")


if __name__ == "__main__":
    build_archive()
