import json
import sqlite3
from pathlib import Path
import chromadb

# ── Paths ────────────────────────────────────────────────────────────────────
JSON_FOLDER = Path("data/selim_transcriptions")
DB_FILE = Path("data/archive_database.db")
CHROMA_DIR = Path("data/chroma_db")

def create_schema(conn):
    cur = conn.cursor()
    # Your original high-detail schema
    cur.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            Reference_Number TEXT,
            Document_Date TEXT,
            Sender TEXT,
            Recipient TEXT,
            Excavation_Site TEXT,
            English_Translation TEXT,
            Full_Transcription TEXT,
            image_path TEXT
        )
    """)
    # FTS5 search index
    cur.execute("CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(English_Translation, content='documents', content_rowid='id')")

def build():
    # 1. Clean start
    if DB_FILE.exists(): DB_FILE.unlink()
    conn = sqlite3.connect(DB_FILE)
    create_schema(conn)
    
    # 2. Setup AI Vector DB
    chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = chroma_client.get_or_create_collection(name="turath_archive")

    # 3. Ingest
    for json_file in JSON_FOLDER.glob("*.json"):
        with open(json_file, "r") as f:
            data = json.load(f)
            
        # SQL Insert
        cur = conn.cursor()
        cur.execute("INSERT INTO documents (Reference_Number, Document_Date, Sender, English_Translation) VALUES (?, ?, ?, ?)",
                    (data.get("Reference_Number"), data.get("Document_Date"), data.get("Sender"), data.get("English_Translation")))
        row_id = cur.lastrowid
        
        # AI Vector Insert
        collection.add(
            documents=[data.get("English_Translation", "")],
            ids=[str(row_id)],
            metadatas=[{"sender": data.get("Sender", "Unknown")}]
        )
        print(f"✓ Indexed: {json_file.name}")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    build()
