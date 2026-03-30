import os
import json
import sqlite3
from pathlib import Path

# Hardcoded paths
JSON_FOLDER = Path("data/selim_transcriptions")
IMAGE_FOLDER = Path("/Users/adamamin/Downloads/selim hassan collection/box 7/pngs")
DB_FILE = Path("data/archive_database.db")

def create_database():
    # Ensure data directory exists
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Create primary documents table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            Reference_Number TEXT,
            Document_Date TEXT,
            Sender TEXT,
            Recipient TEXT,
            Excavation_Site TEXT,
            Entities_Mentioned TEXT,
            Thematic_Tags TEXT,
            Brief_Summary TEXT,
            English_Translation TEXT,
            Stamps_and_Annotations TEXT,
            Confidence_Notes TEXT,
            Full_Transcription TEXT,
            filename TEXT,
            image_path TEXT
        )
    ''')
    
    # Create FTS5 virtual table
    cursor.execute('''
        CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
            Brief_Summary,
            English_Translation,
            Full_Transcription,
            content='documents',
            content_rowid='id'
        )
    ''')
    
    # Create triggers to keep FTS table in sync with documents table
    cursor.execute('''
        CREATE TRIGGER IF NOT EXISTS documents_ai AFTER INSERT ON documents BEGIN
            INSERT INTO documents_fts(rowid, Brief_Summary, English_Translation, Full_Transcription)
            VALUES (new.id, new.Brief_Summary, new.English_Translation, new.Full_Transcription);
        END;
    ''')
    
    cursor.execute('''
        CREATE TRIGGER IF NOT EXISTS documents_ad AFTER DELETE ON documents BEGIN
            INSERT INTO documents_fts(documents_fts, rowid, Brief_Summary, English_Translation, Full_Transcription)
            VALUES ('delete', old.id, old.Brief_Summary, old.English_Translation, old.Full_Transcription);
        END;
    ''')
    
    cursor.execute('''
        CREATE TRIGGER IF NOT EXISTS documents_au AFTER UPDATE ON documents BEGIN
            INSERT INTO documents_fts(documents_fts, rowid, Brief_Summary, English_Translation, Full_Transcription)
            VALUES ('delete', old.id, old.Brief_Summary, old.English_Translation, old.Full_Transcription);
            INSERT INTO documents_fts(rowid, Brief_Summary, English_Translation, Full_Transcription)
            VALUES (new.id, new.Brief_Summary, new.English_Translation, new.Full_Transcription);
        END;
    ''')
    
    conn.commit()
    return conn

def process_json_files(conn):
    if not JSON_FOLDER.exists():
        print(f"Warning: JSON folder '{JSON_FOLDER}' does not exist. Creating it.")
        JSON_FOLDER.mkdir(parents=True, exist_ok=True)
        return 0
        
    cursor = conn.cursor()
    inserted_count = 0
    
    for json_file in JSON_FOLDER.glob("*.json"):
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            # Convert list-based fields to comma-separated strings
            entities = ", ".join(data.get("Entities_Mentioned", [])) if isinstance(data.get("Entities_Mentioned"), list) else data.get("Entities_Mentioned", "")
            tags = ", ".join(data.get("Thematic_Tags", [])) if isinstance(data.get("Thematic_Tags"), list) else data.get("Thematic_Tags", "")
            stamps = ", ".join(data.get("Stamps_and_Annotations", [])) if isinstance(data.get("Stamps_and_Annotations"), list) else data.get("Stamps_and_Annotations", "")
            
            # Derive image path
            image_filename = json_file.stem + ".png"
            image_path = str(IMAGE_FOLDER / image_filename)
            
            cursor.execute('''
                INSERT INTO documents (
                    Reference_Number, Document_Date, Sender, Recipient, Excavation_Site,
                    Entities_Mentioned, Thematic_Tags, Brief_Summary, English_Translation,
                    Stamps_and_Annotations, Confidence_Notes, Full_Transcription, filename, image_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                data.get("Reference_Number", ""),
                data.get("Document_Date", ""),
                data.get("Sender", ""),
                data.get("Recipient", ""),
                data.get("Excavation_Site", ""),
                entities,
                tags,
                data.get("Brief_Summary", ""),
                data.get("English_Translation", ""),
                stamps,
                data.get("Confidence_Notes", ""),
                data.get("Full_Transcription", ""),
                json_file.name,
                image_path
            ))
            inserted_count += 1
            
        except json.JSONDecodeError:
            print(f"Error: Could not decode JSON in file {json_file.name}. Skipping.")
        except Exception as e:
            print(f"Error processing {json_file.name}: {e}")
            
    conn.commit()
    return inserted_count

def main():
    print("Initializing TURATH Reading Room Database...")
    conn = create_database()
    
    # Clear existing data for a fresh build
    cursor = conn.cursor()
    cursor.execute("DELETE FROM documents")
    cursor.execute("DELETE FROM documents_fts")
    conn.commit()
    
    count = process_json_files(conn)
    conn.close()
    
    print(f"✅ Success! Database built at {DB_FILE}")
    print(f"Total records ingested: {count}")

if __name__ == "__main__":
    main()
