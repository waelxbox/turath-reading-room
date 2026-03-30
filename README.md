# 🏛️ Project TURATH: Selim Hassan Digital Archive

The **TURATH Reading Room** is a digital archive application for the Selim Hassan archaeological records. It features a SQLite + FTS5 full-text search backend and a modern, split-screen [Streamlit](https://streamlit.io) web interface designed for researchers.

---

## Features

- **Full-Text Search (FTS5)**: Natural language and keyword search across document summaries, English translations, and Arabic transcriptions.
- **Smart Filters**: Dynamically populated dropdowns for Excavation Site and Sender.
- **Split-Screen Viewer**:
  - **Left — The Artifact**: High-resolution original document scan.
  - **Right — The Decoded Data**: Formatted metadata, English translation, thematic tags, entities, and a collapsible Arabic transcription panel.
- **Auto-Bootstrap**: The database is built automatically on first launch — no manual setup needed on Streamlit Cloud.

---

## Project Structure

```
turath-reading-room/
├── app.py                          # Streamlit frontend
├── build_db.py                     # Database ingestion engine
├── requirements.txt                # Python dependencies
├── .streamlit/
│   └── config.toml                 # Streamlit theme and server config
└── data/
    ├── selim_transcriptions/       # ← Place your JSON files here
    ├── images/                     # ← Place your PNG scans here
    └── archive_database.db         # Auto-generated (git-ignored)
```

---

## Data Schema

Each JSON file in `data/selim_transcriptions/` should contain:

| Field | Type | Notes |
|---|---|---|
| `Reference_Number` | string | e.g. `IMG_7291` |
| `Document_Date` | string | e.g. `January 1930` |
| `Sender` | string | |
| `Recipient` | string | |
| `Excavation_Site` | string | e.g. `Abydos` |
| `Entities_Mentioned` | list | Converted to comma-separated string |
| `Thematic_Tags` | list | Converted to comma-separated string |
| `Brief_Summary` | string | |
| `English_Translation` | string | |
| `Stamps_and_Annotations` | list | Converted to comma-separated string |
| `Confidence_Notes` | string | |
| `Full_Transcription` | string | Raw Arabic text |

The image filename is derived from the JSON filename: `IMG_7291.json` → `data/images/IMG_7291.png`.

---

## Deploying to Streamlit Community Cloud

1. **Fork or clone** this repository to your own GitHub account.
2. Add your JSON files to `data/selim_transcriptions/` and PNG images to `data/images/`, then commit and push.
3. Go to [share.streamlit.io](https://share.streamlit.io) and click **New app**.
4. Select your repository, set the branch to `master`, and set the **Main file path** to `app.py`.
5. Click **Deploy**. The database will be built automatically on first launch.

---

## Running Locally

```bash
git clone https://github.com/waelxbox/turath-reading-room.git
cd turath-reading-room
pip install -r requirements.txt

# Place JSON files in data/selim_transcriptions/
# Place PNG images in data/images/

streamlit run app.py
```

The database is built automatically on first launch. To rebuild manually:

```bash
python build_db.py
```
