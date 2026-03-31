"""
build_db.py — TURATH Archive Database Builder (Incremental)
=============================================================
Reads JSON files from data/selim_transcriptions/ (any depth of subfolders) and builds:
  1. SQLite database  (data/archive_database.db)  — FTS5 full-text search
  2. ChromaDB store   (data/chroma_db/)            — semantic / AI chat search

INCREMENTAL: Only processes JSON files not already recorded in the database.
             Re-running this script on an existing database is safe and fast —
             it skips every file that has already been indexed.

FOLDER STRUCTURE: Works with any subfolder layout, e.g.:
  data/selim_transcriptions/transcriptions_box_7/IMG_7279.json
  data/selim_transcriptions/transcriptions_box_8/IMG_7603.json
  data/images/pngs_box_7/IMG_7279.png
  data/images/pngs_box_8/IMG_7603.png

  The dedup key is the relative path from JSON_FOLDER (e.g. "transcriptions_box_7/IMG_7279.json")
  so files with the same name in different boxes are treated as distinct records.
  Images are found by recursively searching IMAGE_DIR for a matching stem + .png.

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


def find_image(stem: str) -> str:
    """
    Recursively search IMAGE_DIR for a PNG whose stem matches the JSON stem.
    Returns the relative path string, or empty string if not found.
    e.g. stem="IMG_7279" -> "data/images/pngs_box_7/IMG_7279.png"
    """
    matches = list(IMAGE_DIR.rglob(f"{stem}.png"))
    if matches:
        return str(matches[0])
    return ""


def sanitize_metadata(data: dict, rel_path: str) -> dict:
    """Coerce all Chroma metadata values to plain strings (no None, no lists)."""
    return {
        "sender":   str(data.get("Sender")          or "Unknown"),
        "date":     str(data.get("Document_Date")   or "Unknown"),
        "site":     str(data.get("Excavation_Site") or "Unknown"),
        "source":   str(rel_path),
    }


# ── Schema creation (only runs on a brand-new database) ──────────────────────

def migrate_schema(conn: sqlite3.Connection) -> None:
    """
    Apply any schema migrations needed for existing databases.
    Safe to run on any version — each migration is idempotent.
    """
    cur = conn.cursor()
    # Migration 1: add box_label column if missing (added in v2)
    cur.execute("PRAGMA table_info(documents)")
    columns = {row[1] for row in cur.fetchall()}
    if "box_label" not in columns:
        print("  🔧  Migrating schema: adding box_label column…")
        cur.execute("ALTER TABLE documents ADD COLUMN box_label TEXT")
        conn.commit()
        print("  ✅  Migration complete.")


def create_schema_if_needed(conn: sqlite3.Connection) -> None:
    """
    Create the documents table and FTS5 virtual table if they don't exist yet.
    Safe to call on an existing database — no-op if tables already present.
    """
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            source_file            TEXT UNIQUE,   -- relative path from JSON_FOLDER, used for dedup
            box_label              TEXT,          -- e.g. "Box 7", derived from parent folder name
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


def derive_box_label(json_file: Path) -> str:
    """
    Derive a human-readable box label from the parent folder name.
    e.g. "transcriptions_box_7" -> "Box 7"
         "transcriptions_box_8" -> "Box 8"
         "selim_transcriptions" -> "Box 1"  (files at root level)
    """
    parent = json_file.parent.name
    # Try to extract a number from the folder name
    import re
    match = re.search(r'(\d+)', parent)
    if match:
        return f"Box {match.group(1)}"
    # If the file is directly in JSON_FOLDER (no subfolder), label it "Uncategorised"
    if json_file.parent == JSON_FOLDER:
        return "Uncategorised"
    return parent.replace("_", " ").title()


# ── Main build logic ──────────────────────────────────────────────────────────

def build_archive() -> None:
    print("🏗️  TURATH Incremental Build…")

    # ── SQLite ────────────────────────────────────────────────────────────────
    conn = sqlite3.connect(DB_FILE)
    create_schema_if_needed(conn)
    migrate_schema(conn)
    cur = conn.cursor()

    # Dedup key = relative path from JSON_FOLDER (handles same filename in different boxes)
    cur.execute("SELECT source_file FROM documents WHERE source_file IS NOT NULL")
    already_indexed = {row[0] for row in cur.fetchall()}

    # ── ChromaDB ──────────────────────────────────────────────────────────────
    chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = chroma_client.get_or_create_collection(CHROMA_COLLECTION)

    # ── Find all JSON files recursively ───────────────────────────────────────
    all_files = sorted(JSON_FOLDER.rglob("*.json"))
    # Use relative path as the dedup key so box_7/IMG_7279.json ≠ box_8/IMG_7279.json
    new_files = [
        f for f in all_files
        if str(f.relative_to(JSON_FOLDER)) not in already_indexed
    ]

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

            stem      = json_file.stem                          # e.g. "IMG_7291"
            rel_path  = str(json_file.relative_to(JSON_FOLDER)) # e.g. "transcriptions_box_7/IMG_7291.json"
            box_label = derive_box_label(json_file)             # e.g. "Box 7"
            image_path = find_image(stem)                       # e.g. "data/images/pngs_box_7/IMG_7291.png"

            # Serialise ALL fields that could be lists in some JSONs
            thematic_tags      = list_to_str(data.get("Thematic_Tags"))
            entities_mentioned = list_to_str(data.get("Entities_Mentioned"))
            stamps_annotations = list_to_str(data.get("Stamps_and_Annotations"))
            excavation_site    = list_to_str(data.get("Excavation_Site"))

            translation_text = data.get("English_Translation") or ""
            brief_summary    = data.get("Brief_Summary")       or ""

            # 1. Insert into SQLite (FTS5 triggers fire automatically)
            cur.execute("""
                INSERT INTO documents (
                    source_file, box_label,
                    Reference_Number, Document_Date, Sender, Recipient,
                    Excavation_Site, Brief_Summary, English_Translation,
                    Full_Transcription, image_path,
                    Thematic_Tags, Entities_Mentioned,
                    Stamps_and_Annotations, Confidence_Notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                rel_path,
                box_label,
                data.get("Reference_Number"),
                data.get("Document_Date"),
                data.get("Sender"),
                data.get("Recipient"),
                excavation_site,
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
                metadatas=[sanitize_metadata(data, rel_path)],
            )

            print(f"  ✅  [{box_label}] {json_file.name}  →  id={row_id}  img={image_path or 'NOT FOUND'}")
            added += 1

        except Exception as e:
            print(f"  ❌  Error processing {json_file.name}: {e}")

    conn.commit()
    conn.close()
    print(f"\n✨  Done — {added} new record(s) added. "
          f"Total: {len(already_indexed) + added} document(s) in archive.")


if __name__ == "__main__":
    build_archive()
