"""
build_db.py — TURATH Reading Room Database Ingestion Engine
============================================================
Reads JSON transcription files from data/selim_transcriptions/ and PNG images
from data/images/, then builds a SQLite database with FTS5 full-text search.

Run once before launching the app:
    python build_db.py
"""

import json
import sqlite3
from pathlib import Path

# ── Paths (relative to repo root, compatible with Streamlit Cloud) ──────────
JSON_FOLDER = Path("data/selim_transcriptions")
IMAGE_FOLDER = Path("data/images")
DB_FILE = Path("data/archive_database.db")


def create_schema(conn: sqlite3.Connection) -> None:
    """Create the documents table, FTS5 virtual table, and sync triggers."""
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            Reference_Number     TEXT,
            Document_Date        TEXT,
            Sender               TEXT,
            Recipient            TEXT,
            Excavation_Site      TEXT,
            Entities_Mentioned   TEXT,
            Thematic_Tags        TEXT,
            Brief_Summary        TEXT,
            English_Translation  TEXT,
            Stamps_and_Annotations TEXT,
            Confidence_Notes     TEXT,
            Full_Transcription   TEXT,
            filename             TEXT,
            image_path           TEXT
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
            Brief_Summary,
            English_Translation,
            Full_Transcription,
            content='documents',
            content_rowid='id'
        );

        CREATE TRIGGER IF NOT EXISTS docs_ai AFTER INSERT ON documents BEGIN
            INSERT INTO documents_fts(rowid, Brief_Summary, English_Translation, Full_Transcription)
            VALUES (new.id, new.Brief_Summary, new.English_Translation, new.Full_Transcription);
        END;

        CREATE TRIGGER IF NOT EXISTS docs_ad AFTER DELETE ON documents BEGIN
            INSERT INTO documents_fts(documents_fts, rowid, Brief_Summary, English_Translation, Full_Transcription)
            VALUES ('delete', old.id, old.Brief_Summary, old.English_Translation, old.Full_Transcription);
        END;

        CREATE TRIGGER IF NOT EXISTS docs_au AFTER UPDATE ON documents BEGIN
            INSERT INTO documents_fts(documents_fts, rowid, Brief_Summary, English_Translation, Full_Transcription)
            VALUES ('delete', old.id, old.Brief_Summary, old.English_Translation, old.Full_Transcription);
            INSERT INTO documents_fts(rowid, Brief_Summary, English_Translation, Full_Transcription)
            VALUES (new.id, new.Brief_Summary, new.English_Translation, new.Full_Transcription);
        END;
    """)
    conn.commit()


def _join_list(value) -> str:
    """Safely convert a list or string field to a comma-separated string."""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value) if value else ""


def ingest_json_files(conn: sqlite3.Connection) -> int:
    """Iterate over JSON folder, parse each file, and insert into the DB."""
    if not JSON_FOLDER.exists():
        print(f"⚠  JSON folder '{JSON_FOLDER}' not found — creating empty directory.")
        JSON_FOLDER.mkdir(parents=True, exist_ok=True)
        return 0

    cur = conn.cursor()
    inserted = 0

    for json_file in sorted(JSON_FOLDER.glob("*.json")):
        try:
            with open(json_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except json.JSONDecodeError as exc:
            print(f"  ✗ JSON error in {json_file.name}: {exc} — skipping.")
            continue
        except Exception as exc:
            print(f"  ✗ Could not read {json_file.name}: {exc} — skipping.")
            continue

        image_filename = json_file.stem + ".png"
        image_path = str(IMAGE_FOLDER / image_filename)

        cur.execute(
            """
            INSERT INTO documents (
                Reference_Number, Document_Date, Sender, Recipient, Excavation_Site,
                Entities_Mentioned, Thematic_Tags, Brief_Summary, English_Translation,
                Stamps_and_Annotations, Confidence_Notes, Full_Transcription,
                filename, image_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data.get("Reference_Number", ""),
                data.get("Document_Date", ""),
                data.get("Sender", ""),
                data.get("Recipient", ""),
                data.get("Excavation_Site", ""),
                _join_list(data.get("Entities_Mentioned", "")),
                _join_list(data.get("Thematic_Tags", "")),
                data.get("Brief_Summary", ""),
                data.get("English_Translation", ""),
                _join_list(data.get("Stamps_and_Annotations", "")),
                data.get("Confidence_Notes", ""),
                data.get("Full_Transcription", ""),
                json_file.name,
                image_path,
            ),
        )
        inserted += 1
        print(f"  ✓ Ingested {json_file.name}")

    conn.commit()
    return inserted


def main() -> None:
    print("=" * 55)
    print("  TURATH Reading Room — Database Build")
    print("=" * 55)

    DB_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Fresh build: remove existing DB so triggers and schema are clean
    if DB_FILE.exists():
        DB_FILE.unlink()
        print(f"Removed existing database at {DB_FILE}")

    conn = sqlite3.connect(DB_FILE)
    create_schema(conn)
    count = ingest_json_files(conn)
    conn.close()

    print("-" * 55)
    print(f"✅  Database ready: {DB_FILE}")
    print(f"    Total records ingested: {count}")
    print("=" * 55)


if __name__ == "__main__":
    main()
