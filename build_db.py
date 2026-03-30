"""
build_db.py — TURATH Archive Database Builder (Incremental)
=============================================================
Reads JSON files from data/selim_transcriptions/ and builds:
  1. SQLite database  (data/archive_database.db)  — FTS5 full-text search
  2. ChromaDB store   (data/chroma_db/)            — semantic / AI chat search

INCREMENTAL: Only processes JSON files not already recorded in the database.
             Re-running this script on an existing database is safe and fast —
             it skips every file that has already been indexed.

Run manually:   python build_db.py
Auto-run by:    .github/workflows/update_archive.yml on every JSON push
"""

import json
import sqlite3
from pathlib import Path

import chromadb

# ── Paths ─────────────────────────────────────────────────────────────────────
DATA_DIR    = Path("data")
JSON_FOLDER = DATA_DIR / "selim_transcriptions"
DB_FILE     = DATA_DIR / "archive_database.db"
CHROMA_DIR  = DATA_DIR / "chroma_db"
IMAGE_DIR   = DATA_DIR / "images"

DATA_DIR.mkdir(exist_ok=True)

# ── Chroma collection name — must match app.py exactly ───────────────────────
CHROMA_COLLECTION = "turath_archive"


# ── Helpers ───────────────────────────────────────────────────────────────────

def list_to_str(value) -> str:
    """Convert a JSON list to a comma-separated string; pass strings through."""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if v)
    return str(value) if value is not None else ""


def sanitize_metadata(data: dict, filename: str) -> dict:
    """Coerce all Chroma metadata values to plain strings (no None, no lists)."""
    return {
        "sender":   str(data.get("Sender")          or "Unknown"),
        "date":     str(data.get("Document_Date")   or "Unknown"),
        "site":     str(data.get("Excavation_Site") or "Unknown"),
        "source":   str(filename),
    }


# ── Schema creation (only runs on a brand-new database) ──────────────────────

def create_schema_if_needed(conn: sqlite3.Connection) -> None:
    """
    Create the documents table and FTS5 virtual table if they don't exist yet.
    This is safe to call on an existing database — it is a no-op if the tables
    are already present.
    """
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            source_file            TEXT UNIQUE,   -- JSON filename, used for dedup
            Reference_Number       TEXT,
            Document_Date          TEXT,
            Sender                 TEXT,
            Recipient              TEXT,
            Excavation_Site        TEXT,
            Brief_Summary          TEXT,
            English_Translation    TEXT,
            Full_Transcription     TEXT,
            image_path             TEXT,
            Thematic_Tags          TEXT,
            Entities_Mentioned     TEXT,
            Stamps_and_Annotations TEXT,
            Confidence_Notes       TEXT
        )
    """)

    # FTS5 virtual table — content= keeps it in sync via triggers
    cur.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
            Brief_Summary,
            English_Translation,
            Full_Transcription,
            content='documents',
            content_rowid='id'
        )
    """)

    # Triggers to keep FTS5 in sync with the documents table
    cur.execute("""
        CREATE TRIGGER IF NOT EXISTS docs_ai AFTER INSERT ON documents BEGIN
            INSERT INTO documents_fts(
                rowid, Brief_Summary, English_Translation, Full_Transcription
            ) VALUES (
                new.id, new.Brief_Summary, new.English_Translation, new.Full_Transcription
            );
        END
    """)
    cur.execute("""
        CREATE TRIGGER IF NOT EXISTS docs_ad AFTER DELETE ON documents BEGIN
            INSERT INTO documents_fts(
                documents_fts, rowid, Brief_Summary, English_Translation, Full_Transcription
            ) VALUES (
                'delete', old.id, old.Brief_Summary, old.English_Translation, old.Full_Transcription
            );
        END
    """)
    cur.execute("""
        CREATE TRIGGER IF NOT EXISTS docs_au AFTER UPDATE ON documents BEGIN
            INSERT INTO documents_fts(
                documents_fts, rowid, Brief_Summary, English_Translation, Full_Transcription
            ) VALUES (
                'delete', old.id, old.Brief_Summary, old.English_Translation, old.Full_Transcription
            );
            INSERT INTO documents_fts(
                rowid, Brief_Summary, English_Translation, Full_Transcription
            ) VALUES (
                new.id, new.Brief_Summary, new.English_Translation, new.Full_Transcription
            );
        END
    """)

    conn.commit()


# ── Main build logic ──────────────────────────────────────────────────────────

def build_archive() -> None:
    print("🏗️  TURATH Incremental Build…")

    # ── SQLite ────────────────────────────────────────────────────────────────
    conn = sqlite3.connect(DB_FILE)
    create_schema_if_needed(conn)
    cur = conn.cursor()

    # Find which source files are already indexed (dedup by filename)
    cur.execute("SELECT source_file FROM documents WHERE source_file IS NOT NULL")
    already_indexed = {row[0] for row in cur.fetchall()}

    # ── ChromaDB ──────────────────────────────────────────────────────────────
    chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = chroma_client.get_or_create_collection(CHROMA_COLLECTION)

    # ── Find new JSON files ───────────────────────────────────────────────────
    all_files = sorted(JSON_FOLDER.rglob("*.json"))
    new_files  = [f for f in all_files if f.name not in already_indexed]

    if not new_files:
        print(f"✅  Nothing to do — all {len(all_files)} file(s) already indexed.")
        conn.close()
        return

    print(f"📄  {len(already_indexed)} already indexed, "
          f"{len(new_files)} new file(s) to process…")

    added = 0
    for json_file in new_files:
        try:
            with open(json_file, encoding="utf-8") as f:
                data = json.load(f)

            # Synthesise image_path from the JSON filename
            stem       = json_file.stem                        # e.g. "IMG_7291"
            image_path = str(IMAGE_DIR / f"{stem}.png")       # "data/images/IMG_7291.png"

            # Serialise list fields to comma-separated strings for SQLite
            thematic_tags      = list_to_str(data.get("Thematic_Tags"))
            entities_mentioned = list_to_str(data.get("Entities_Mentioned"))
            stamps_annotations = list_to_str(data.get("Stamps_and_Annotations"))

            translation_text   = data.get("English_Translation") or ""
            brief_summary      = data.get("Brief_Summary")       or ""

            # 1. Insert into SQLite (FTS5 triggers fire automatically)
            cur.execute("""
                INSERT INTO documents (
                    source_file,
                    Reference_Number, Document_Date, Sender, Recipient,
                    Excavation_Site, Brief_Summary, English_Translation,
                    Full_Transcription, image_path,
                    Thematic_Tags, Entities_Mentioned,
                    Stamps_and_Annotations, Confidence_Notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                json_file.name,
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

            print(f"  ✅  {json_file.name}  →  id={row_id}")
            added += 1

        except Exception as e:
            print(f"  ❌  Error processing {json_file.name}: {e}")

    conn.commit()
    conn.close()
    print(f"\n✨  Done — {added} new record(s) added. "
          f"Total: {len(already_indexed) + added} document(s) in archive.")


if __name__ == "__main__":
    build_archive()
