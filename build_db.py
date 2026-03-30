import json
import sqlite3
import os
from pathlib import Path
import chromadb

# ── 1. PATH CONFIGURATION ───────────────────────────────────────────────────
DATA_DIR = Path("data")
JSON_FOLDER = DATA_DIR / "selim_transcriptions"
DB_FILE = DATA_DIR / "archive_database.db"
CHROMA_DIR = DATA_DIR / "chroma_db"

# Ensure the data directory exists
DATA_DIR.mkdir(exist_ok=True)

def sanitize_metadata(data_dict, filename):
    """
    Prevents 'MetadataValue' errors by forcing all values to strings.
    ChromaDB cannot handle None/null or complex Python objects.
    """
    return {
        "sender": str(data_dict.get("Sender") or "Unknown"),
        "date": str(data_dict.get("Document_Date") or "Unknown"),
        "site": str(data_dict.get("Excavation_Site") or "Unknown"),
        "source": str(filename)
    }

def create_database_schema(conn):
    """Sets up the SQLite tables for the Reading Room viewer."""
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS documents")
    cur.execute("""
        CREATE TABLE documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            Reference_Number TEXT,
            Document_Date TEXT,
            Sender TEXT,
            Recipient TEXT,
            Excavation_Site TEXT,
            English_Translation TEXT,
            Full_Transcription TEXT,
            image_path TEXT,
            Thematic_Tags TEXT,
            Entities_Mentioned TEXT,
            Stamps_and_Annotations TEXT,
            Confidence_Notes TEXT
        )
    """)
    # FTS5 enables high-speed keyword search in the sidebar
    cur.execute("CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(English_Translation, content='documents', content_rowid='id')")

def build_archive():
    print("🏗️ Initializing TURATH Build Process...")
    
    # Connect to SQLite
    conn = sqlite3.connect(DB_FILE)
    create_database_schema(conn)
    cur = conn.cursor()
    
    # Connect to ChromaDB
    chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = chroma_client.get_or_create_collection(name="turath_archive")

    # Find all JSON files
    files = list(JSON_FOLDER.glob("*.json"))
    if not files:
        print(f"⚠️ Warning: No JSON files found in {JSON_FOLDER}")
        return

    print(f"📄 Processing {len(files)} records...")

    for json_file in files:
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            translation_text = data.get("English_Translation") or ""
            
            # 1. Update SQLite (For the Viewer)
            cur.execute("""
                INSERT INTO documents (
                    Reference_Number, Document_Date, Sender, Recipient, 
                    Excavation_Site, English_Translation, Full_Transcription, 
                    image_path, Thematic_Tags, Entities_Mentioned, 
                    Stamps_and_Annotations, Confidence_Notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data.get("Reference_Number"), data.get("Document_Date"),
                data.get("Sender"), data.get("Recipient"),
                data.get("Excavation_Site"), translation_text,
                data.get("Full_Transcription"), data.get("image_path"),
                data.get("Thematic_Tags"), data.get("Entities_Mentioned"),
                data.get("Stamps_and_Annotations"), data.get("Confidence_Notes")
            ))
            row_id = cur.lastrowid
            
            # 2. Update ChromaDB (For the AI Chatbot)
            sanitized_meta = sanitize_metadata(data, json_file.name)
            collection.add(
                documents=[translation_text],
                ids=[str(row_id)],
                metadatas=[sanitized_meta]
            )
            print(f"  ✅ {json_file.name} indexed.")
            
        except Exception as e:
            print(f"  ❌ Error processing {json_file.name}: {e}")

    conn.commit()
    conn.close()
    print("\n✨ Archive build successful! SQLite and ChromaDB are ready.")

if __name__ == "__main__":
    build_archive()
