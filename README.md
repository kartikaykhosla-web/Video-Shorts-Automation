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

On Streamlit Cloud, `packages.txt` installs `ffmpeg` automatically during deployment.

Optional, for fetching YouTube/webpage videos:

```bash
pip install -U yt-dlp
```

## Run

```bash
streamlit run shorts_automation_app.py
```

## YouTube OAuth on Cloud Run

Enable the YouTube Data API v3 and create a Web application OAuth client. Add
the Cloud Run service URL as an authorized redirect URI, then expose these
Secret Manager values to the container:

```text
GOOGLE_OAUTH_CLIENT_ID
GOOGLE_OAUTH_CLIENT_SECRET
GOOGLE_OAUTH_REDIRECT_URI=https://jnm-short-video-automation-197804368906.asia-south1.run.app/
```

The app requests `youtube.force-ssl` and can download captions only when the
connected account has permission to edit the selected video.

## Apps Script transcript service

For organization-managed YouTube videos, Apps Script can retrieve captions with
the Google/CMS identity that authorized the script. Add
`apps_script_transcript_endpoint.gs` to the existing Apps Script project, set a
strong `TRANSCRIPT_API_SECRET` in **Project Settings > Script Properties**, and
deploy the project as a Web App with these settings:

- **Execute as:** Me
- **Who has access:** Anyone

The request body is protected with a five-minute HMAC signature and one-time
nonce. Do not put the secret in the Streamlit UI or in source control. After
adding or changing Apps Script code, create a new Web App deployment version.

Expose the deployment URL and the same secret to Cloud Run:

```text
APPS_SCRIPT_TRANSCRIPT_URL=https://script.google.com/macros/s/DEPLOYMENT_ID/exec
APPS_SCRIPT_TRANSCRIPT_SECRET=replace-with-a-long-random-secret
```

When configured, the app tries this organization service first and retains the
existing YouTube caption methods as fallbacks. The Apps Script account still
needs permission to access the video's caption track.

Generated uploads, transcripts, thumbnails, title cards, and exports are stored under `shorts_automation_work/` and ignored by Git.
