# 🏛️ Project TURATH: Selim Hassan Digital Archive

The TURATH Reading Room is a robust Digital Archive application designed for the Selim Hassan archaeological records. It features a lightweight SQLite backend with Full-Text Search (FTS5) capabilities and a modern, split-screen Streamlit web interface for researchers to easily search, view, and analyze historical documents.

## Features

- **The Brain (SQLite + FTS5)**: A single-file database that stores document metadata, translations, and transcriptions, enabling ultra-fast semantic and keyword searches.
- **The Command Center**: A clean sidebar featuring a natural language search bar and smart filters for excavation sites and senders.
- **The Split-Screen Viewer**: 
  - **Left Half (The Artifact)**: Displays high-resolution original document scans.
  - **Right Half (The Decoded Data)**: Presents cleanly formatted metadata, English translations, thematic tags, and a collapsible section for original Arabic transcriptions.

## Project Structure

- `build_db.py`: The database ingestion engine. Reads JSON metadata and creates the SQLite database with FTS5 virtual tables.
- `app.py`: The Streamlit frontend application.
- `data/`: Directory containing the SQLite database and JSON transcription files.

## Setup Instructions

### Prerequisites

- Python 3.8+
- The original document images (PNGs) located at the hardcoded path (or update the path in `build_db.py` and `app.py`).

### Installation

1. Clone this repository:
   ```bash
   git clone <repository-url>
   cd turath-reading-room
   ```

2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Ensure your data folders are set up correctly:
   - Place JSON transcription files in `data/selim_transcriptions/`
   - Ensure images are available at the path specified in `build_db.py`

### Usage

1. **Build the Database**
   Run the ingestion script to create and populate the SQLite database:
   ```bash
   python build_db.py
   ```

2. **Launch the Reading Room**
   Start the Streamlit application:
   ```bash
   streamlit run app.py
   ```

## Data Schema

The application expects JSON files with the following structure:
- `Reference_Number`
- `Document_Date`
- `Sender`
- `Recipient`
- `Excavation_Site`
- `Entities_Mentioned` (list)
- `Thematic_Tags` (list)
- `Brief_Summary`
- `English_Translation`
- `Stamps_and_Annotations` (list)
- `Confidence_Notes`
- `Full_Transcription` (raw Arabic text)
