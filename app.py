import streamlit as st
import sqlite3
from pathlib import Path
import pandas as pd

# Page configuration
st.set_page_config(
    page_title="🏛️ Project TURATH: Selim Hassan Digital Archive",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Database path
DB_FILE = Path("data/archive_database.db")

@st.cache_resource
def get_db_connection():
    """Create and cache database connection"""
    if not DB_FILE.exists():
        st.error(f"Database not found at {DB_FILE}. Please run build_db.py first.")
        st.stop()
    return sqlite3.connect(DB_FILE)

def get_distinct_values(conn, column):
    """Get distinct values from a column"""
    cursor = conn.cursor()
    cursor.execute(f"SELECT DISTINCT {column} FROM documents WHERE {column} IS NOT NULL AND {column} != '' ORDER BY {column}")
    return [row[0] for row in cursor.fetchall()]

def search_documents(conn, query, site_filter=None, sender_filter=None):
    """Search documents using FTS5 and apply filters"""
    cursor = conn.cursor()
    
    if query.strip():
        # Use FTS5 for semantic search
        fts_query = " OR ".join(query.split())
        cursor.execute('''
            SELECT d.id, d.Reference_Number, d.Document_Date, d.Brief_Summary, 
                   d.Excavation_Site, d.Sender
            FROM documents d
            INNER JOIN documents_fts fts ON d.id = fts.rowid
            WHERE documents_fts MATCH ?
        ''', (fts_query,))
    else:
        # No search query, get all documents
        cursor.execute('''
            SELECT id, Reference_Number, Document_Date, Brief_Summary, 
                   Excavation_Site, Sender
            FROM documents
        ''')
    
    results = cursor.fetchall()
    
    # Apply filters
    filtered_results = []
    for row in results:
        doc_id, ref_num, date, summary, site, sender = row
        
        if site_filter and site_filter != "All Sites" and site != site_filter:
            continue
        if sender_filter and sender_filter != "All Senders" and sender != sender_filter:
            continue
            
        filtered_results.append(row)
    
    return filtered_results

def get_document_details(conn, doc_id):
    """Get full details of a document"""
    cursor = conn.cursor()
    cursor.execute('''
        SELECT Reference_Number, Document_Date, Sender, Recipient, Excavation_Site,
               Entities_Mentioned, Thematic_Tags, Brief_Summary, English_Translation,
               Stamps_and_Annotations, Confidence_Notes, Full_Transcription, image_path
        FROM documents
        WHERE id = ?
    ''', (doc_id,))
    return cursor.fetchone()

def main():
    conn = get_db_connection()
    
    # Title
    st.title("🏛️ Project TURATH: Selim Hassan Digital Archive")
    st.markdown("A comprehensive digital reading room for Selim Hassan archaeological records.")
    
    # Left Sidebar (Command Center)
    with st.sidebar:
        st.header("🔍 Command Center")
        
        # Natural Language Search Bar
        search_query = st.text_input(
            "Natural Language & Keyword Search",
            placeholder="e.g., 'Find letters about budgets and money'",
            help="Search across document summaries, translations, and transcriptions"
        )
        
        # Get filter options
        sites = ["All Sites"] + get_distinct_values(conn, "Excavation_Site")
        senders = ["All Senders"] + get_distinct_values(conn, "Sender")
        
        # Smart Filters
        st.subheader("Smart Filters")
        site_filter = st.selectbox("Excavation Site", sites)
        sender_filter = st.selectbox("Sender", senders)
        
        # Perform search
        results = search_documents(conn, search_query, site_filter, sender_filter)
        
        # Hit List
        st.subheader(f"📋 Results ({len(results)} documents)")
        
        if results:
            # Create options for selectbox
            options = []
            for doc_id, ref_num, date, summary, site, sender in results:
                label = f"{date} | {ref_num}"
                if summary:
                    label += f" | {summary[:50]}..."
                options.append((doc_id, label))
            
            # Select document
            if options:
                selected_idx = st.selectbox(
                    "Select a document to view",
                    range(len(options)),
                    format_func=lambda i: options[i][1],
                    key="doc_selector"
                )
                selected_doc_id = options[selected_idx][0]
            else:
                selected_doc_id = None
        else:
            st.info("No documents match your search criteria.")
            selected_doc_id = None
    
    # Main Stage (Split-Screen Viewer)
    if selected_doc_id:
        doc_details = get_document_details(conn, selected_doc_id)
        
        if doc_details:
            ref_num, date, sender, recipient, site, entities, tags, summary, translation, stamps, confidence, transcription, image_path = doc_details
            
            # Create two columns for split-screen
            left_col, right_col = st.columns([1, 1], gap="large")
            
            # Left Column (The Artifact)
            with left_col:
                st.subheader("📜 The Artifact")
                
                # Display image
                image_file = Path(image_path)
                if image_file.exists():
                    st.image(str(image_file), use_container_width=True)
                else:
                    st.warning(f"Image not found at {image_path}")
            
            # Right Column (The Decoded Data)
            with right_col:
                st.subheader("📖 The Decoded Data")
                
                # Header badges
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Reference", ref_num or "N/A")
                with col2:
                    st.metric("Date", date or "N/A")
                with col3:
                    st.metric("Site", site or "N/A")
                
                st.divider()
                
                # Translation
                st.subheader("Translation")
                st.write(translation or "No translation available")
                
                st.divider()
                
                # Sender and Recipient
                col1, col2 = st.columns(2)
                with col1:
                    st.caption("**Sender**")
                    st.write(sender or "Unknown")
                with col2:
                    st.caption("**Recipient**")
                    st.write(recipient or "Unknown")
                
                st.divider()
                
                # Thematic Tags
                if tags:
                    st.subheader("Thematic Tags")
                    tag_list = [tag.strip() for tag in tags.split(",")]
                    st.write(", ".join([f"🏷️ {tag}" for tag in tag_list if tag]))
                
                # Entities Mentioned
                if entities:
                    st.subheader("Entities Mentioned")
                    entity_list = [entity.strip() for entity in entities.split(",")]
                    st.write(", ".join([f"👤 {entity}" for entity in entity_list if entity]))
                
                st.divider()
                
                # Original Arabic Transcription (collapsed)
                with st.expander("View Original Arabic Transcription"):
                    if transcription:
                        st.write(transcription)
                    else:
                        st.write("No transcription available")
                    
                    if confidence:
                        st.caption(f"**Confidence Notes:** {confidence}")
                
                # Stamps and Annotations
                if stamps:
                    with st.expander("View Stamps & Annotations"):
                        stamp_list = [stamp.strip() for stamp in stamps.split(",")]
                        st.write(", ".join([f"🔖 {stamp}" for stamp in stamp_list if stamp]))
    else:
        st.info("👈 Use the sidebar to search and select a document to begin exploring the archive.")
    
    conn.close()

if __name__ == "__main__":
    main()
