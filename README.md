# Video Shorts Automation

Local Streamlit prototype for converting owned horizontal videos into vertical short-video templates.

## Features

- Upload a local video or fetch a video from a link.
- Pull/import timestamped transcripts.
- Find keywords and create clips from transcript matches.
- Generate optional chapters and create clips from chapter rows.
- Export vertical MP4s using Jagran Shorts-style templates.
- Add custom title text and choose yellow-highlight words.
- Use bundled template assets and Teko title font.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Install FFmpeg separately:

```bash
brew install ffmpeg
```

Optional, for fetching YouTube/webpage videos:

```bash
pip install -U yt-dlp
```

## Run

```bash
streamlit run shorts_automation_app.py
```

Generated uploads, transcripts, thumbnails, title cards, and exports are stored under `shorts_automation_work/` and ignored by Git.
