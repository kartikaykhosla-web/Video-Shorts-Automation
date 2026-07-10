import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageChops, ImageDraw, ImageFont
import streamlit as st


APP_DIR = Path(__file__).resolve().parent
WORK_DIR = APP_DIR / "shorts_automation_work"
UPLOAD_DIR = WORK_DIR / "uploads"
EXPORT_DIR = WORK_DIR / "exports"
MANIFEST_PATH = WORK_DIR / "manifest.json"
TITLE_CARD_DIR = WORK_DIR / "title_cards"
LOGO_DIR = WORK_DIR / "logos"
TEMPLATE_DIR = WORK_DIR / "templates"
TRANSCRIPT_DIR = WORK_DIR / "transcripts"
THUMBNAIL_DIR = WORK_DIR / "thumbnails"
FONT_DIR = WORK_DIR / "fonts"
DEFAULT_TITLE_TEMPLATE = TEMPLATE_DIR / "reference_title_template.png"
DEFAULT_BACKGROUND_MARK = TEMPLATE_DIR / "jagran-background-mark.png"
DEFAULT_BACKGROUND_WATERMARK_SOURCE = TEMPLATE_DIR / "jagran-logo-bg-source.png"
DEFAULT_BACKGROUND_PATTERN = TEMPLATE_DIR / "jagran-background-pattern.png"
DEFAULT_SHORTS_LOGO = TEMPLATE_DIR / "jagran-shorts-logo.png"
DEFAULT_SHORTS_RED_BACKGROUND = TEMPLATE_DIR / "jagran-shorts-red-bg.png"
DEFAULT_PLAY_ICON = TEMPLATE_DIR / "youtube-play-icon.png"
TEKO_FONT = FONT_DIR / "Teko-SemiBold.ttf"
CANVAS_WIDTH = 1080
CANVAS_HEIGHT = 1920
TEKO_TITLE_SIZE = 63
NEWS_VIDEO_HEIGHT = 1120
NEWS_PANEL_HEIGHT = CANVAS_HEIGHT - NEWS_VIDEO_HEIGHT
TITLE_CARD_OVERLAP = 80
TITLE_CARD_HEIGHT = NEWS_PANEL_HEIGHT + TITLE_CARD_OVERLAP
NEWS_HORIZONTAL_CONTENT_HEIGHT = int(CANVAS_WIDTH * 9 / 16)
NEWS_FOREGROUND_TOP_TRIM = 34
MAX_CREATED_CLIPS = 10
SHORTS_TEMPLATE_LABELS = {
    "template_3": "Template 3",
}
@dataclass
class ClipCandidate:
    index: int
    start: float
    end: float
    title: str
    caption: str
    reason: str
    score: int

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class TranscriptSegment:
    start: float
    end: Optional[float]
    text: str


def ensure_dirs() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    TITLE_CARD_DIR.mkdir(parents=True, exist_ok=True)
    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
    FONT_DIR.mkdir(parents=True, exist_ok=True)


def ensure_default_template() -> None:
    ensure_dirs()
    if DEFAULT_TITLE_TEMPLATE.exists():
        return
    local_sources = [
        TEMPLATE_DIR / "jagran-shorts.png",
        TEMPLATE_DIR / "jagran-shorts_1_.png",
        Path.home() / "Downloads" / "jagran-shorts (1).png",
    ]
    for source in local_sources:
        if source.exists():
            shutil.copyfile(source, DEFAULT_TITLE_TEMPLATE)
            return


def ensure_default_shorts_logo() -> None:
    ensure_dirs()
    if DEFAULT_SHORTS_LOGO.exists():
        return
    local_sources = [
        Path("/var/folders/fg/b8wcmqxd233_lwd6zf5lpl_w0000gn/T/codex-clipboard-1be102c4-b0a8-425b-94b3-2ccfbff6e410.png"),
        TEMPLATE_DIR / "jagran-shorts-logo.png",
        Path.home() / "Downloads" / "jagran-shorts-logo.png",
    ]
    for source in local_sources:
        if source.exists() and source != DEFAULT_SHORTS_LOGO:
            shutil.copyfile(source, DEFAULT_SHORTS_LOGO)
            return


def ensure_default_play_icon() -> None:
    ensure_dirs()
    if DEFAULT_PLAY_ICON.exists():
        return
    icon = Image.new("RGBA", (170, 120), (0, 0, 0, 0))
    draw = ImageDraw.Draw(icon)
    draw.rounded_rectangle((15, 18, 155, 102), radius=24, fill="#ff0000")
    draw.polygon([(70, 42), (70, 78), (104, 60)], fill="#ffffff")
    icon.save(DEFAULT_PLAY_ICON)


def ensure_default_background_mark() -> None:
    ensure_dirs()
    ensure_default_background_watermark_source()
    if DEFAULT_BACKGROUND_WATERMARK_SOURCE.exists():
        ensure_default_background_pattern()
        return
    if DEFAULT_BACKGROUND_MARK.exists():
        remove_light_matte(DEFAULT_BACKGROUND_MARK)
        ensure_default_background_pattern()
        return
    local_sources = [
        Path("/var/folders/fg/b8wcmqxd233_lwd6zf5lpl_w0000gn/T/codex-clipboard-eaffa5a2-5e9f-4678-8c69-fd2c6c61d37f.png"),
        TEMPLATE_DIR / "jagran-background-mark.png",
    ]
    for source in local_sources:
        if source.exists() and source != DEFAULT_BACKGROUND_MARK:
            shutil.copyfile(source, DEFAULT_BACKGROUND_MARK)
            remove_light_matte(DEFAULT_BACKGROUND_MARK)
            ensure_default_background_pattern()
            return


def ensure_default_background_watermark_source() -> None:
    if DEFAULT_BACKGROUND_WATERMARK_SOURCE.exists():
        return
    source = Path.home() / "Downloads" / "Jagran logo Bg.png"
    if source.exists():
        shutil.copyfile(source, DEFAULT_BACKGROUND_WATERMARK_SOURCE)


def ensure_default_background_pattern() -> None:
    source_path = DEFAULT_BACKGROUND_WATERMARK_SOURCE if DEFAULT_BACKGROUND_WATERMARK_SOURCE.exists() else DEFAULT_BACKGROUND_MARK
    if DEFAULT_BACKGROUND_PATTERN.exists() and source_path.exists() and DEFAULT_BACKGROUND_PATTERN.stat().st_mtime >= source_path.stat().st_mtime:
        return
    try:
        source_image = Image.open(source_path).convert("RGBA")
    except Exception:
        return
    pattern = resize_cover(source_image, (CANVAS_WIDTH, CANVAS_HEIGHT))
    pattern.save(DEFAULT_BACKGROUND_PATTERN)


def remove_light_matte(path: Path) -> None:
    try:
        image = Image.open(path).convert("RGBA")
    except Exception:
        return
    pixels = image.load()
    changed = False
    for y in range(image.height):
        for x in range(image.width):
            r, g, b, a = pixels[x, y]
            if a and r > 238 and g > 238 and b > 238:
                pixels[x, y] = (r, g, b, 0)
                changed = True
    if changed:
        image.save(path)


def tool_path(name: str) -> Optional[str]:
    found = shutil.which(name)
    if found:
        return found
    local_candidates = [
        APP_DIR / ".venv-shorts" / "bin" / name,
        APP_DIR / ".venv" / "bin" / name,
        Path.home() / ".local" / "bin" / name,
        Path("/opt/homebrew/bin") / name,
        Path("/usr/local/bin") / name,
    ]
    for candidate in local_candidates:
        if candidate.exists():
            return str(candidate)
    return None


def run_command(args: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, check=False)


def running_on_streamlit_cloud() -> bool:
    return bool(os.environ.get("STREAMLIT_SHARING_MODE") or os.environ.get("STREAMLIT_SERVER_PORT"))


def browser_cookie_args(browser_cookie_source: str = "") -> List[str]:
    if running_on_streamlit_cloud():
        return []
    browser = browser_cookie_source.strip().lower()
    if not browser:
        return []
    home = Path.home()
    cookie_locations = {
        "chrome": [home / ".config" / "google-chrome", home / "Library" / "Application Support" / "Google" / "Chrome"],
        "chromium": [home / ".config" / "chromium", home / "Library" / "Application Support" / "Chromium"],
        "brave": [home / ".config" / "BraveSoftware" / "Brave-Browser", home / "Library" / "Application Support" / "BraveSoftware" / "Brave-Browser"],
        "edge": [home / ".config" / "microsoft-edge", home / "Library" / "Application Support" / "Microsoft Edge"],
        "firefox": [home / ".mozilla" / "firefox", home / "Library" / "Application Support" / "Firefox"],
        "opera": [home / ".config" / "opera", home / "Library" / "Application Support" / "com.operasoftware.Opera"],
        "vivaldi": [home / ".config" / "vivaldi", home / "Library" / "Application Support" / "Vivaldi"],
    }
    if browser in cookie_locations and not any(path.exists() for path in cookie_locations[browser]):
        return []
    return ["--cookies-from-browser", browser]


def whisper_available() -> bool:
    try:
        import whisper  # noqa: F401

        return True
    except Exception:
        return tool_path("whisper") is not None


def whisper_dependency_fix_message(details: str = "") -> str:
    message = (
        "Whisper is installed, but one of its compiled dependencies is incompatible with NumPy 2.x. "
        "In this environment, downgrade NumPy and reinstall numba with: "
        "`pip install 'numpy<2' --force-reinstall` and then `pip install -U numba openai-whisper`. "
        "Restart Streamlit after that."
    )
    if details:
        message += f" Details: {details[-600:]}"
    return message


@lru_cache(maxsize=1)
def available_ffmpeg_filters() -> set:
    ffmpeg = tool_path("ffmpeg")
    if not ffmpeg:
        return set()
    result = run_command([ffmpeg, "-hide_banner", "-filters"])
    if result.returncode != 0:
        return set()
    filters = set()
    for line in result.stdout.splitlines():
        match = re.match(r"^\s*[.A-Z|]+\s+([A-Za-z0-9_]+)\s+", line)
        if match:
            filters.add(match.group(1))
    return filters


def seconds_to_timecode(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    whole = int(seconds)
    ms = int(round((seconds - whole) * 1000))
    if ms == 1000:
        whole += 1
        ms = 0
    td = timedelta(seconds=whole)
    hours = whole // 3600
    minutes = (whole % 3600) // 60
    secs = whole % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"


def compact_time(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def parse_timecode(value: str) -> Optional[float]:
    value = value.strip().replace(",", ".")
    match = re.match(r"^(?:(\d+):)?(\d{1,2}):(\d{1,2})(?:\.(\d{1,3}))?$", value)
    if not match:
        return None
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    millis = int((match.group(4) or "0").ljust(3, "0")[:3])
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


def probe_video(path: Path) -> Dict[str, float]:
    ffprobe = tool_path("ffprobe")
    if not ffprobe:
        return {}
    args = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,r_frame_rate:format=duration",
        "-of",
        "json",
        str(path),
    ]
    result = run_command(args)
    if result.returncode != 0:
        return {}
    try:
        payload = json.loads(result.stdout)
        stream = (payload.get("streams") or [{}])[0]
        duration = float((payload.get("format") or {}).get("duration") or 0)
        fps_raw = str(stream.get("r_frame_rate") or "0/1")
        numerator, denominator = fps_raw.split("/")
        fps = float(numerator) / max(float(denominator), 1.0)
        return {
            "width": int(stream.get("width") or 0),
            "height": int(stream.get("height") or 0),
            "duration": duration,
            "fps": fps,
        }
    except Exception:
        return {}


def extract_audio_for_transcript(source: Path) -> Tuple[Optional[Path], str]:
    ffmpeg = tool_path("ffmpeg")
    if not ffmpeg:
        return None, "ffmpeg is not installed or not available on PATH."
    ensure_dirs()
    audio_path = TRANSCRIPT_DIR / f"{source.stem}_transcript_audio.wav"
    result = run_command(
        [
            ffmpeg,
            "-y",
            "-i",
            str(source),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            str(audio_path),
        ]
    )
    if result.returncode != 0:
        return None, result.stderr[-1800:] or "Audio extraction failed."
    return audio_path, "Audio extracted."


def transcribe_video_to_srt(source: Path, model_name: str = "base") -> Tuple[Optional[str], str]:
    audio_path, audio_message = extract_audio_for_transcript(source)
    if not audio_path:
        return None, audio_message

    ensure_dirs()
    srt_path = TRANSCRIPT_DIR / f"{source.stem}_{model_name}.srt"

    try:
        import whisper

        model = whisper.load_model(model_name)
        result = model.transcribe(str(audio_path), fp16=False, verbose=False)
        blocks: List[str] = []
        for idx, segment in enumerate(result.get("segments", []), start=1):
            text = str(segment.get("text") or "").strip()
            if not text:
                continue
            blocks.append(
                f"{idx}\n"
                f"{seconds_to_srt(float(segment.get('start') or 0))} --> {seconds_to_srt(float(segment.get('end') or 0))}\n"
                f"{text}\n"
            )
        if blocks:
            srt_text = "\n".join(blocks)
            srt_path.write_text(srt_text, encoding="utf-8")
            return srt_text, f"Transcript generated: {srt_path.name}"
    except Exception as python_error:
        python_error_text = str(python_error)
        if "numpy.core.multiarray failed to import" in python_error_text or "NumPy 1.x" in python_error_text:
            return None, whisper_dependency_fix_message(python_error_text)
        cli = tool_path("whisper")
        if not cli:
            return None, (
                "Whisper is not installed. Install it with `pip install -U openai-whisper`, "
                "then rerun transcript generation."
            )
        result = run_command(
            [
                cli,
                str(audio_path),
                "--model",
                model_name,
                "--output_format",
                "srt",
                "--output_dir",
                str(TRANSCRIPT_DIR),
            ]
        )
        if result.returncode != 0:
            cli_error_text = result.stderr or result.stdout or str(python_error)
            if "numpy.core.multiarray failed to import" in cli_error_text or "NumPy 1.x" in cli_error_text:
                return None, whisper_dependency_fix_message(cli_error_text)
            return None, cli_error_text[-2200:] or str(python_error)
        cli_srt = TRANSCRIPT_DIR / f"{audio_path.stem}.srt"
        if cli_srt.exists():
            srt_text = cli_srt.read_text(encoding="utf-8", errors="ignore")
            srt_path.write_text(srt_text, encoding="utf-8")
            return srt_text, f"Transcript generated: {srt_path.name}"

    return None, "Whisper did not return any timestamped transcript segments."


def pull_timestamped_transcript_from_url(url: str, browser_cookie_source: str = "") -> Tuple[Optional[str], str]:
    ytdlp = tool_path("yt-dlp")
    if not ytdlp:
        return None, "Install `yt-dlp` to pull captions from video links: `./.venv-shorts/bin/pip install -U yt-dlp`."
    if not url.strip():
        return None, "Paste a video link first."
    ensure_dirs()
    started_at = time.time()
    before = {path.resolve() for path in TRANSCRIPT_DIR.glob("*")}

    node = tool_path("node")
    common_args = [
        ytdlp,
        "--skip-download",
        "--no-playlist",
        "--sub-format",
        "srt/vtt/best",
        "--retries",
        "3",
        "--fragment-retries",
        "3",
        "--force-overwrites",
        "-o",
        str(TRANSCRIPT_DIR / "%(title).80s_%(id)s.%(ext)s"),
    ]
    if node:
        common_args.extend(["--js-runtimes", f"node:{node}"])
    common_args.extend(["--remote-components", "ejs:github"])
    common_args.extend(browser_cookie_args(browser_cookie_source))

    def friendly_caption_error(text: str) -> str:
        if "HTTP Error 429" in text or "Too Many Requests" in text:
            return (
                "YouTube is rate-limiting subtitle downloads right now (HTTP 429). "
                "Import an SRT/VTT transcript file manually, or upload the owned MP4 and transcript."
            )
        if "Please sign in" in text or "Sign in" in text and "cookies" in text.lower():
            return (
                "YouTube requires a signed-in session for this video. A deployed Streamlit app cannot access an end user's "
                "Chrome login, so upload the owned MP4 and import/paste the transcript instead."
            )
        if "could not copy Chrome cookie database" in text or "Permission" in text and "cookies" in text.lower():
            return (
                "Browser cookies are only available when running the app locally on the same computer as the browser. "
                "On Streamlit Cloud, upload the owned MP4 or import an SRT/VTT transcript."
            )
        if "No video subtitles" in text or "There are no subtitles" in text:
            return "No timestamped captions were found for this video link. Import an SRT/VTT file or paste timestamped text."
        if "No supported JavaScript runtime" in text:
            return (
                "yt-dlp needs a JavaScript runtime for this YouTube link. Install Node with `brew install node`, "
                "restart Streamlit, then try again."
            )
        if "Remote component challenge solver" in text or "n challenge solving failed" in text:
            return (
                "YouTube's JavaScript challenge blocked yt-dlp. The app now enables yt-dlp remote JS components; "
                "try again once, or import an SRT/VTT transcript if YouTube still blocks it."
            )
        return text[-2200:] or "yt-dlp could not pull subtitles for this link."

    def new_caption_files() -> List[Path]:
        return [
            path
            for path in TRANSCRIPT_DIR.glob("*")
            if path.suffix.lower() in {".srt", ".vtt"}
            and (path.resolve() not in before or path.stat().st_mtime >= started_at)
        ]

    last_result = None
    rate_limited_errors: List[str] = []
    for sub_langs in ["en-orig", "en", "hi", "en.*,en,hi.*,hi"]:
        manual_result = run_command(common_args + ["--sub-langs", sub_langs, "--write-subs", url.strip()])
        last_result = manual_result
        candidates = new_caption_files()
        if candidates:
            break
        auto_result = run_command(common_args + ["--sub-langs", sub_langs, "--write-auto-subs", url.strip()])
        last_result = auto_result
        candidates = new_caption_files()
        if candidates:
            break
        error_text = auto_result.stderr or auto_result.stdout or manual_result.stderr or manual_result.stdout
        if "HTTP Error 429" in error_text or "Too Many Requests" in error_text:
            rate_limited_errors.append(error_text)
            continue

    if not candidates:
        error_text = ""
        if last_result is not None:
            error_text = last_result.stderr or last_result.stdout
        if rate_limited_errors:
            error_text = "\n".join(rate_limited_errors[-2:])
        if error_text:
            return None, friendly_caption_error(error_text)
        return None, "No English or Hindi timestamped captions were found for this video link. Import an SRT/VTT file or paste timestamped text."
    transcript_path = sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)[0]
    return transcript_path.read_text(encoding="utf-8", errors="ignore"), f"Loaded captions: {transcript_path.name}"


def store_transcript_text(transcript: str) -> None:
    st.session_state["transcript_text"] = transcript


def reset_video_working_state() -> None:
    st.session_state["transcript_text"] = ""
    st.session_state["created_clips"] = []
    st.session_state["rendered_clip_outputs"] = {}
    st.session_state["next_clip_index"] = 1
    st.session_state.pop("thumbnail_path", None)
    st.session_state.pop("loaded_transcript_name", None)
    st.session_state.pop("clip_limit_message", None)
    st.session_state.pop("saved_upload_signature", None)
    st.session_state.pop("source_kind", None)
    st.session_state.pop("last_upload_transcript_attempt", None)


def save_upload(uploaded_file) -> Path:
    ensure_dirs()
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", uploaded_file.name).strip("_")
    target = UPLOAD_DIR / safe_name
    suffix = target.suffix
    stem = target.stem
    counter = 1
    while target.exists():
        target = UPLOAD_DIR / f"{stem}_{counter}{suffix}"
        counter += 1
    target.write_bytes(uploaded_file.getbuffer())
    return target


def safe_filename_from_url(url: str, default_name: str = "linked_video.mp4") -> str:
    parsed = urllib.parse.urlparse(url)
    name = Path(urllib.parse.unquote(parsed.path)).name
    if not name or "." not in name:
        name = default_name
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_") or default_name


def youtube_video_id(url: str) -> Optional[str]:
    parsed = urllib.parse.urlparse(url.strip())
    host = parsed.netloc.lower().replace("www.", "")
    if host in {"youtu.be"}:
        video_id = parsed.path.strip("/").split("/")[0]
        return video_id or None
    if "youtube.com" in host:
        query_id = urllib.parse.parse_qs(parsed.query).get("v", [""])[0]
        if query_id:
            return query_id
        parts = [part for part in parsed.path.split("/") if part]
        for marker in ("shorts", "embed", "live"):
            if marker in parts and parts.index(marker) + 1 < len(parts):
                return parts[parts.index(marker) + 1]
    return None


def fetch_youtube_thumbnail(url: str) -> Tuple[Optional[Path], str]:
    video_id = youtube_video_id(url)
    if not video_id:
        return None, "No YouTube video ID found for thumbnail."
    ensure_dirs()
    target = THUMBNAIL_DIR / f"{video_id}.jpg"
    thumbnail_urls = [
        f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
        f"https://i.ytimg.com/vi/{video_id}/sddefault.jpg",
        f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
    ]
    for thumb_url in thumbnail_urls:
        try:
            request = urllib.request.Request(thumb_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=30) as response:
                data = response.read()
            if len(data) < 1024:
                continue
            target.write_bytes(data)
            return target, f"Thumbnail loaded: {target.name}"
        except Exception:
            continue
    return None, "Could not fetch YouTube thumbnail."


def unique_upload_path(filename: str) -> Path:
    ensure_dirs()
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("_")
    if not safe_name:
        safe_name = "linked_video.mp4"
    target = UPLOAD_DIR / safe_name
    suffix = target.suffix or ".mp4"
    stem = target.stem
    counter = 1
    while target.exists():
        target = UPLOAD_DIR / f"{stem}_{counter}{suffix}"
        counter += 1
    return target


def download_direct_video_url(url: str) -> Tuple[Optional[Path], str]:
    target = unique_upload_path(safe_filename_from_url(url))
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=120) as response:
            content_type = response.headers.get("Content-Type", "")
            if "text/html" in content_type.lower():
                return None, "That link looks like a webpage. Install `yt-dlp` to fetch video-page links."
            target.write_bytes(response.read())
        return target, f"Downloaded linked video: {target.name}"
    except Exception as error:
        return None, f"Could not download direct video link: {error}"


def normalize_youtube_po_token(token: str) -> str:
    token = token.strip()
    if not token:
        return ""
    if ".gvs+" in token:
        return token
    return f"web.gvs+{token}"


def youtube_extractor_args(po_token: str = "", player_client: str = "web") -> List[str]:
    parts = [f"player_client={player_client}"]
    normalized_token = normalize_youtube_po_token(po_token)
    if normalized_token:
        parts.append(f"po_token={normalized_token}")
    return ["--extractor-args", "youtube:" + ";".join(parts)]


def download_video_link(url: str, browser_cookie_source: str = "", youtube_po_token: str = "") -> Tuple[Optional[Path], str]:
    url = url.strip()
    if not url:
        return None, "Paste a video link first."
    ensure_dirs()

    ytdlp = tool_path("yt-dlp")
    if ytdlp:
        node = tool_path("node")
        target_template = str(UPLOAD_DIR / "%(title).80s_%(id)s.%(ext)s")
        base_args = [ytdlp, "--no-playlist", "--remote-components", "ejs:github"]
        if node:
            base_args.extend(["--js-runtimes", f"node:{node}"])
        base_args.extend(browser_cookie_args(browser_cookie_source))
        download_attempts = [
            youtube_extractor_args(youtube_po_token, "web") + ["--merge-output-format", "mp4"],
            youtube_extractor_args(youtube_po_token, "web_creator") + ["--merge-output-format", "mp4"],
        ]
        result = None
        for attempt in download_attempts:
            result = run_command(base_args + attempt + ["-o", target_template, url])
            if result.returncode == 0:
                break
        if result.returncode != 0:
            error_text = result.stderr or result.stdout or "yt-dlp failed to download this video link."
            if "HTTP Error 429" in error_text or "Too Many Requests" in error_text:
                return None, (
                    "YouTube is rate-limiting this download right now (HTTP 429). "
                    "Download the video from your owned source and upload it here."
                )
            if "Please sign in" in error_text or "Sign in" in error_text and "cookies" in error_text.lower():
                return None, (
                    "YouTube requires a signed-in session for this video. A deployed Streamlit app cannot access an end user's "
                    "Chrome login, even if they are logged in on their own computer. Please upload the owned MP4 instead."
                )
            if "could not copy Chrome cookie database" in error_text or "Permission" in error_text and "cookies" in error_text.lower():
                return None, (
                    "Browser cookies are only available when running the app locally on the same computer as the browser. "
                    "On Streamlit Cloud, upload the owned MP4 instead."
                )
            if "No supported JavaScript runtime" in error_text:
                return None, "Install Node with `brew install node`, restart Streamlit, then try the video link again."
            if "HTTP Error 403" in error_text or "PO Token" in error_text or "po_token" in error_text:
                return None, (
                    "YouTube blocked this video download with HTTP 403. On Streamlit Cloud, browser cookies are not available, "
                    "so upload the MP4 from YouTube Studio / your source system. A PO token may help some public videos, "
                    "but signed-in videos still need upload."
                )
            if (
                "Remote component challenge solver" in error_text
                or "n challenge solving failed" in error_text
                or "Only images are available" in error_text
                or "Requested format is not available" in error_text
            ):
                return None, (
                    "YouTube blocked the video formats behind a JS/SABR challenge. The app tried yt-dlp remote JS components "
                    "and web YouTube clients. Add a PO token in Advanced YouTube options, or download the video from YouTube Studio "
                    "or your source system and upload the local MP4."
                )
            return None, error_text[-2200:] or "yt-dlp failed to download this video link."
        recent_files = sorted(UPLOAD_DIR.glob("*"), key=lambda path: path.stat().st_mtime, reverse=True)
        for path in recent_files:
            if path.suffix.lower() in {".mp4", ".mov", ".m4v", ".webm", ".mkv"}:
                return path, f"Downloaded linked video: {path.name}"
        return None, "yt-dlp completed, but no video file was found in the uploads folder."

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme in {"http", "https"} and Path(parsed.path).suffix.lower() in {".mp4", ".mov", ".m4v", ".webm", ".mkv"}:
        return download_direct_video_url(url)

    return None, "Install `yt-dlp` to fetch YouTube or webpage video links: `pip install -U yt-dlp`."


def parse_transcript_segments(transcript: str) -> List[TranscriptSegment]:
    segments: List[TranscriptSegment] = []
    lines = transcript.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue

        if line.isdigit() and index + 1 < len(lines):
            next_line = lines[index + 1].strip()
            if "-->" in next_line:
                index += 1
                line = next_line

        srt_match = re.match(
            r"^(\d{1,2}:\d{2}(?::\d{2})?(?:[,.]\d{1,3})?)\s*-->\s*(\d{1,2}:\d{2}(?::\d{2})?(?:[,.]\d{1,3})?)",
            line,
        )
        if srt_match:
            start = parse_timecode(srt_match.group(1))
            end = parse_timecode(srt_match.group(2))
            index += 1
            text_lines: List[str] = []
            while index < len(lines) and lines[index].strip():
                text_lines.append(lines[index].strip())
                index += 1
            if start is not None:
                segments.append(TranscriptSegment(start=start, end=end, text=" ".join(text_lines).strip()))
            continue

        timestamp_match = re.match(r"^\[?(\d{1,2}:\d{2}(?::\d{2})?(?:[,.]\d{1,3})?)\]?\s+(.+)$", line)
        if timestamp_match:
            start = parse_timecode(timestamp_match.group(1))
            if start is not None:
                segments.append(TranscriptSegment(start=start, end=None, text=timestamp_match.group(2).strip()))
        index += 1
    return segments


def extract_timestamped_lines(transcript: str) -> List[Tuple[float, str]]:
    return [(segment.start, segment.text) for segment in parse_transcript_segments(transcript)]


def split_keywords(value: str) -> List[str]:
    return [item.strip() for item in re.split(r"[,;\n]+", value) if item.strip()]


def find_keyword_hits(transcript: str, keywords: str) -> List[Dict[str, str]]:
    terms = split_keywords(keywords)
    if not terms:
        return []
    hits: List[Dict[str, str]] = []
    for segment in parse_transcript_segments(transcript):
        text = segment.text.strip()
        if not text:
            continue
        matched = [term for term in terms if re.search(re.escape(term), text, flags=re.IGNORECASE)]
        if matched:
            hits.append(
                {
                    "Time": compact_time(segment.start),
                    "Start seconds": f"{segment.start:.2f}",
                    "Matched keyword": ", ".join(matched),
                    "Transcript text": text,
                }
            )
    return hits


def create_clip_candidate_from_moment(
    start: float,
    text: str,
    clip_length: int,
    duration: float,
    reason: str,
    index: int = 1,
) -> ClipCandidate:
    clip_start = max(0.0, start - 2)
    clip_end = clip_start + clip_length
    if duration:
        clip_end = min(duration, clip_end)
        clip_start = max(0.0, clip_end - clip_length)
    clean_text = re.sub(r"\s+", " ", text).strip()
    return ClipCandidate(
        index=index,
        start=clip_start,
        end=clip_end,
        title=make_title(clean_text, index),
        caption=clean_text[:160],
        reason=reason,
        score=max(score_text(clean_text), 80),
    )


def generate_keyword_candidates(
    duration: float,
    clip_length: int,
    count: int,
    transcript: str,
    keywords: str,
) -> List[ClipCandidate]:
    terms = split_keywords(keywords)
    if not terms:
        return []
    candidates: List[ClipCandidate] = []
    for segment in parse_transcript_segments(transcript):
        text = segment.text.strip()
        matched = [term for term in terms if text and re.search(re.escape(term), text, flags=re.IGNORECASE)]
        if not matched:
            continue
        clip_start = max(0.0, segment.start - 2)
        clip_end = clip_start + clip_length
        if duration:
            clip_end = min(duration, clip_end)
            clip_start = max(0.0, clip_end - clip_length)
        candidates.append(
            ClipCandidate(
                index=len(candidates) + 1,
                start=clip_start,
                end=clip_end,
                title=make_title(text, len(candidates) + 1),
                caption=text[:160],
                reason=f"Keyword match: {', '.join(matched)} at {compact_time(segment.start)}",
                score=max(score_text(text), 82),
            )
        )
        if len(candidates) >= count:
            break
    return candidates


def chapter_title_from_text(text: str, fallback: str) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    clean = re.sub(r"<[^>]+>", "", clean)
    if not clean:
        return fallback
    words = clean.split()
    title = " ".join(words[:8]).strip(" -:,.")
    return title[:80] or fallback


def suggest_chapters(transcript: str, duration: float = 0) -> List[Dict[str, str]]:
    segments = [segment for segment in parse_transcript_segments(transcript) if segment.text.strip()]
    if not segments:
        return []
    is_short_video = (duration and duration < 20 * 60) or len(transcript) < 12000
    max_chapters = 5 if is_short_video else 12
    min_gap = 120 if is_short_video else 300

    chapters: List[Tuple[float, str]] = [(0.0, "Introduction")]
    last_start = 0.0
    for segment in segments:
        if len(chapters) >= max_chapters:
            break
        if segment.start < 15:
            continue
        if segment.start - last_start < min_gap:
            continue
        chapters.append((segment.start, chapter_title_from_text(segment.text, f"Chapter {len(chapters) + 1}")))
        last_start = segment.start

    return [
        {
            "Time": seconds_to_timecode(start).split(".")[0],
            "Start seconds": f"{start:.2f}",
            "Chapter": title,
            "YouTube format": f"{seconds_to_timecode(start).split('.')[0]} - {title}",
        }
        for start, title in chapters
    ]


def score_text(text: str) -> int:
    lowered = text.lower()
    score = 35
    hooks = [
        "why",
        "how",
        "what",
        "secret",
        "mistake",
        "biggest",
        "first",
        "breaking",
        "important",
        "watch",
        "remember",
        "problem",
        "solution",
        "because",
        "?",
    ]
    score += sum(7 for hook in hooks if hook in lowered)
    word_count = len(re.findall(r"\w+", text))
    if 18 <= word_count <= 90:
        score += 20
    elif word_count < 8:
        score -= 12
    if re.search(r"\b(1|2|3|4|5|one|two|three|four|five)\b", lowered):
        score += 8
    return max(1, min(score, 99))


def generate_candidates(
    duration: float,
    clip_length: int,
    count: int,
    transcript: str,
    min_gap: int,
) -> List[ClipCandidate]:
    candidates: List[ClipCandidate] = []
    timestamped = extract_timestamped_lines(transcript)

    if timestamped:
        for idx, (start, text) in enumerate(timestamped[: count * 3], start=1):
            clip_start = max(0.0, start - 2)
            clip_end = clip_start + clip_length
            if duration:
                clip_end = min(duration, clip_end)
                clip_start = max(0.0, clip_end - clip_length)
            caption = text[:120] if text else "Selected timestamped moment"
            candidates.append(
                ClipCandidate(
                    index=idx,
                    start=clip_start,
                    end=clip_end,
                    title=make_title(caption, idx),
                    caption=caption,
                    reason="Timestamp found in transcript",
                    score=score_text(caption),
                )
            )
    else:
        usable_duration = duration or (clip_length * count)
        if usable_duration <= clip_length:
            starts = [0.0]
        else:
            step = max(min_gap, math.floor((usable_duration - clip_length) / max(count, 1)))
            starts = [float(i * step) for i in range(count)]
        for idx, start in enumerate(starts, start=1):
            end = min(start + clip_length, usable_duration)
            candidates.append(
                ClipCandidate(
                    index=idx,
                    start=start,
                    end=end,
                    title=f"Short candidate {idx}",
                    caption="Add a hook caption for this clip",
                    reason="Evenly sampled from the video",
                    score=max(45, 78 - idx * 4),
                )
            )

    deduped: List[ClipCandidate] = []
    for candidate in sorted(candidates, key=lambda item: (-item.score, item.start)):
        if all(abs(candidate.start - existing.start) >= min_gap for existing in deduped):
            deduped.append(candidate)
        if len(deduped) >= count:
            break

    return sorted(deduped, key=lambda item: item.start)


def make_title(text: str, idx: int) -> str:
    words = re.findall(r"[^\s,.;:!?।]+", text, flags=re.UNICODE)
    if not words:
        return f"Short candidate {idx}"
    title = " ".join(words[:8]).strip()
    return title if re.search(r"[^\x00-\x7F]", title) else title.title()


def escape_drawtext(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("%", "\\%")
        .replace("\n", " ")
    )


def escape_filter_value(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace(",", "\\,")
        .replace(" ", "\\ ")
    )


def focal_crop_x(focus: str) -> str:
    if focus == "Left":
        return "0"
    if focus == "Right":
        return "iw-ow"
    return "(iw-ow)/2"


def focal_crop_y(focus: str) -> str:
    if focus == "Top":
        return "0"
    if focus == "Bottom":
        return "ih-oh"
    return "(ih-oh)/2"


def find_title_font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        "/System/Library/Fonts/Kohinoor.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def contains_devanagari(text: str) -> bool:
    return any("\u0900" <= char <= "\u097f" for char in text)


def find_shorts_headline_font(size: int, text: str = "") -> ImageFont.FreeTypeFont:
    teko_candidates = [
        TEKO_FONT,
        Path.home() / "Downloads" / "Teko" / "static" / "Teko-SemiBold.ttf",
        Path.home() / "Downloads" / "Teko" / "Teko-VariableFont_wght.ttf",
    ]
    for candidate in teko_candidates:
        if candidate.exists():
            try:
                return ImageFont.truetype(str(candidate), size=size)
            except Exception:
                continue
    if contains_devanagari(text):
        candidates = [
            "/System/Library/Fonts/Supplemental/ITFDevanagari.ttc",
            "/System/Library/Fonts/Supplemental/Devanagari Sangam MN.ttc",
            "/System/Library/Fonts/Supplemental/DevanagariMT.ttc",
            "/System/Library/Fonts/Kohinoor.ttc",
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            "/Library/Fonts/Arial Unicode.ttf",
        ]
    else:
        candidates = [
            "/System/Library/Fonts/Supplemental/Impact.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            "/Library/Fonts/Arial Unicode.ttf",
        ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size=size)
            except Exception:
                continue
    return find_title_font(size)


def text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def wrap_title_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> List[str]:
    words = [word for word in re.split(r"\s+", text.strip()) if word]
    if not words:
        return ["Shorts headline"]
    lines: List[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if current and text_width(draw, trial, font) > max_width:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines[:3]


def split_balanced_two_line_title(text: str) -> List[str]:
    words = [word for word in re.split(r"\s+", text.strip()) if word]
    if len(words) <= 1:
        return [text.strip()]
    best_index = 1
    best_delta = math.inf
    for index in range(1, len(words)):
        first = " ".join(words[:index])
        second = " ".join(words[index:])
        delta = abs(len(first) - len(second))
        if delta < best_delta:
            best_delta = delta
            best_index = index
    return [" ".join(words[:best_index]), " ".join(words[best_index:])]


def format_title_text(text: str, mode: str) -> str:
    cleaned = re.sub(r"\s+", " ", text.strip())
    if mode == "clean":
        return cleaned
    if mode == "title_case":
        if contains_devanagari(cleaned):
            return cleaned
        keep_upper = {"AI", "PM", "US", "UK", "UN", "G20", "BJP"}
        words = []
        for word in cleaned.split():
            stripped = re.sub(r"[^A-Za-z0-9]", "", word)
            if stripped.upper() in keep_upper:
                words.append(word.upper())
            else:
                words.append(word[:1].upper() + word[1:].lower())
        return " ".join(words)
    if mode == "upper":
        return cleaned.upper()
    if mode == "two_lines":
        return "\n".join(split_balanced_two_line_title(cleaned))
    return text


def fit_title_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    max_lines: int = 2,
    start_size: int = 98,
    min_size: int = 58,
) -> Tuple[ImageFont.ImageFont, List[str]]:
    manual_lines = [line.strip() for line in text.splitlines() if line.strip()]
    if manual_lines:
        manual_lines = manual_lines[:max_lines]
        for size in range(start_size, min_size - 1, -4):
            font = find_title_font(size)
            if all(text_width(draw, line, font) <= max_width for line in manual_lines):
                return font, manual_lines
        return find_title_font(min_size), manual_lines

    for size in range(start_size, min_size - 1, -4):
        font = find_title_font(size)
        lines = wrap_title_text(draw, text, font, max_width)
        if len(lines) <= max_lines and all(text_width(draw, line, font) <= max_width for line in lines):
            return font, lines
    font = find_title_font(min_size)
    return font, wrap_title_text(draw, text, font, max_width)[:max_lines]


def save_logo_upload(uploaded_file) -> Path:
    ensure_dirs()
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", uploaded_file.name).strip("_")
    target = LOGO_DIR / safe_name
    target.write_bytes(uploaded_file.getbuffer())
    return target


def save_template_upload(uploaded_file) -> Path:
    ensure_dirs()
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", uploaded_file.name).strip("_")
    target = TEMPLATE_DIR / safe_name
    target.write_bytes(uploaded_file.getbuffer())
    return target


def resize_cover(image: Image.Image, size: Tuple[int, int]) -> Image.Image:
    target_w, target_h = size
    src_w, src_h = image.size
    scale = max(target_w / src_w, target_h / src_h)
    resized = image.resize((int(src_w * scale), int(src_h * scale)), Image.Resampling.LANCZOS)
    left = max(0, (resized.width - target_w) // 2)
    top = max(0, (resized.height - target_h) // 2)
    return resized.crop((left, top, left + target_w, top + target_h))


def resize_contain_top(image: Image.Image, size: Tuple[int, int], fill: str = "#a80000") -> Image.Image:
    target_w, target_h = size
    src_w, src_h = image.size
    scale = min(target_w / src_w, target_h / src_h)
    resized = image.resize((int(src_w * scale), int(src_h * scale)), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (target_w, target_h), fill)
    left = (target_w - resized.width) // 2
    canvas.alpha_composite(resized, (left, 0))
    return canvas


def trim_template_edges(image: Image.Image) -> Image.Image:
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    alpha_bbox = image.getchannel("A").getbbox()
    if alpha_bbox:
        image = image.crop(alpha_bbox)

    # Also trim near-black gutters around otherwise opaque screenshots.
    rgb = image.convert("RGB")
    bg = Image.new("RGB", rgb.size, (13, 17, 23))
    diff = Image.eval(ImageChops.difference(rgb, bg), lambda px: 255 if px > 10 else 0)
    bbox = diff.getbbox()
    if bbox:
        image = image.crop(bbox)
    return image


def make_header_neutral_matte_transparent(image: Image.Image) -> Image.Image:
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    pixels = image.load()
    header_limit = max(1, int(image.height * 0.18))
    for y in range(header_limit):
        for x in range(image.width):
            r, g, b, a = pixels[x, y]
            max_channel = max(r, g, b)
            min_channel = min(r, g, b)
            is_neutral_matte = max_channel - min_channel < 34 and max_channel < 232
            if a and is_neutral_matte:
                pixels[x, y] = (r, g, b, 0)
    return image


def crop_template_left_edge(image: Image.Image) -> Image.Image:
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    crop_px = max(1, int(round(image.width * 0.018)))
    return image.crop((crop_px, 0, image.width, image.height))


def paste_logo(image: Image.Image, logo_path: Optional[Path], xy: Tuple[int, int], max_size: Tuple[int, int]) -> bool:
    if not logo_path or not logo_path.exists():
        return False
    try:
        logo = Image.open(logo_path).convert("RGBA")
        logo.thumbnail(max_size)
        x = xy[0] + (max_size[0] - logo.width) // 2
        y = xy[1] + (max_size[1] - logo.height) // 2
        image.paste(logo, (x, y), logo)
        return True
    except Exception:
        return False


def draw_reference_jagran_mark(draw: ImageDraw.ImageDraw, x: int, y: int, size: int) -> None:
    draw.pieslice((x, y, x + size, y + size), 180, 360, fill="#e31b23")
    inset = int(size * 0.15)
    draw.pieslice((x + inset, y + inset, x + size - inset, y + size - inset), 185, 355, fill="#ff9e18")
    inner = int(size * 0.34)
    draw.pieslice((x + inner, y + inner, x + size - inner // 2, y + size - inner // 2), 185, 355, fill="#ffe45d")
    draw.rectangle((x, y + int(size * 0.58), x + size, y + size), fill="#ffffff")


def draw_reference_brand_strip(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    logo_path: Optional[Path],
) -> None:
    strip_h = 64
    notch_start = 470
    notch_peak = 540
    rail_end = CANVAS_WIDTH

    # Thin reference-style seam: most of the strip remains the card color.
    draw.rectangle((0, 0, CANVAS_WIDTH, strip_h), fill="#5d0000")
    draw.rectangle((notch_peak, 0, CANVAS_WIDTH, strip_h), fill="#5a0000")

    draw.line((0, 7, notch_start + 8, 7), fill="#ffffff", width=5)
    draw.line((0, strip_h - 8, notch_start, strip_h - 8), fill="#ffffff", width=5)
    draw.line((notch_start, strip_h - 8, notch_peak, 7), fill="#ffffff", width=5)
    draw.line((notch_peak, 7, rail_end, 7), fill="#ffffff", width=5)
    draw.line((0, strip_h - 1, notch_start - 8, strip_h - 1), fill="#f1f1f1", width=2)
    draw.line((0, strip_h - 19, notch_start - 20, strip_h - 19), fill="#b80000", width=4)

    logo_box = (58, 21)
    if not paste_logo(image, logo_path, logo_box, (58, 34)):
        draw_reference_jagran_mark(draw, 62, 22, 48)

    brand_font = find_title_font(29)
    draw.text((118, 24), "जागरण SHORTS", font=brand_font, fill="#ffffff")


def shorts_template_layout(template_key: str) -> Dict[str, object]:
    layouts: Dict[str, Dict[str, object]] = {
        "template_3": {"logo": (250, 105), "title": (95, 1580, 985, 1835), "panels": [("video", 75, 260, 930, 610), ("image", 75, 925, 930, 610)]},
    }
    return layouts["template_3"]


def draw_shorts_background(draw: ImageDraw.ImageDraw) -> None:
    draw.rectangle((0, 0, CANVAS_WIDTH, CANVAS_HEIGHT), fill="#8d0008")
    draw.rectangle((0, 0, CANVAS_WIDTH, 145), fill="#6e0008")
    draw.rectangle((0, CANVAS_HEIGHT - 190, CANVAS_WIDTH, CANVAS_HEIGHT), fill="#a40008")
    for x in range(-40, CANVAS_WIDTH, 34):
        draw.rectangle((x, CANVAS_HEIGHT - 120, x + 8, CANVAS_HEIGHT - 112), fill="#bd1a20")
    for idx in range(14):
        x = CANVAS_WIDTH - 260 + idx * 24
        y = 230 + idx * 105
        draw.rectangle((x, y, x + 68, y + 92), fill="#c40012")
    for idx in range(10):
        x = 70 + idx * 48
        y = 1545 + idx * 22
        draw.rectangle((x, y, x + 18, y + 18), fill="#b81219")


def load_shorts_background() -> Image.Image:
    if DEFAULT_SHORTS_RED_BACKGROUND.exists():
        try:
            source = Image.open(DEFAULT_SHORTS_RED_BACKGROUND).convert("RGBA")
            scale = max(CANVAS_WIDTH / source.width, CANVAS_HEIGHT / source.height)
            resized = source.resize(
                (math.ceil(source.width * scale), math.ceil(source.height * scale)),
                Image.Resampling.LANCZOS,
            )
            left = max(0, (resized.width - CANVAS_WIDTH) // 2)
            top = max(0, (resized.height - CANVAS_HEIGHT) // 2)
            return resized.crop((left, top, left + CANVAS_WIDTH, top + CANVAS_HEIGHT))
        except Exception:
            pass
    fallback = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), "#8d0008")
    draw_shorts_background(ImageDraw.Draw(fallback))
    return fallback


def draw_logo_asset(image: Image.Image, xy: Tuple[int, int], max_size: Tuple[int, int]) -> None:
    logo_path = DEFAULT_SHORTS_LOGO if DEFAULT_SHORTS_LOGO.exists() else None
    if logo_path:
        try:
            logo = Image.open(logo_path).convert("RGBA")
            logo.thumbnail(max_size)
            image.alpha_composite(logo, xy)
            return
        except Exception:
            pass
    draw = ImageDraw.Draw(image)
    draw_reference_jagran_mark(draw, xy[0], xy[1] + 3, 58)
    brand_font = find_title_font(34)
    draw.text((xy[0] + 70, xy[1] + 10), "जागरण SHORTS", font=brand_font, fill="#ffffff")


def parse_highlight_terms(highlight_text: str) -> List[str]:
    terms = [term.strip() for term in re.split(r"[,\\n]+", highlight_text or "") if term.strip()]
    return sorted(set(terms), key=len, reverse=True)


def highlight_pattern(highlight_terms: List[str]) -> Optional[re.Pattern]:
    defaults = ["PM", "Modi", "मोदी", "AI"]
    terms = highlight_terms or defaults
    escaped = [re.escape(term) for term in terms if term.strip()]
    if not escaped:
        return None
    return re.compile("(" + "|".join(escaped) + ")", flags=re.IGNORECASE)


def draw_template_headline(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: Tuple[int, int, int, int],
    highlight_text: str = "",
) -> None:
    x1, y1, x2, y2 = box
    title = text.strip() or "Shorts headline"
    raw_lines = title.splitlines()
    manual_lines = [line.strip() for line in raw_lines if line.strip()] if len(raw_lines) > 1 else []
    max_lines = 2
    title_words = [word for word in re.split(r"\s+", title) if word]
    if not manual_lines and not contains_devanagari(title) and len(title_words) > 5:
        manual_lines = split_balanced_two_line_title(title)
    width_ratio = 0.36 if not contains_devanagari(title) and len(title_words) > 5 else 0.68
    max_text_width = int((x2 - x1) * width_ratio)
    for size in range(TEKO_TITLE_SIZE, 35, -2):
        font = find_shorts_headline_font(size, title)
        allowed_width = x2 - x1
        if manual_lines:
            lines = manual_lines[:max_lines]
        elif not contains_devanagari(title) and len(title_words) > 5:
            lines = split_balanced_two_line_title(title)
        else:
            lines = wrap_title_text(draw, title, font, max_text_width)[:max_lines]
            allowed_width = max_text_width
        line_height = int(size * 1.02)
        if lines and all(text_width(draw, line, font) <= allowed_width for line in lines) and len(lines) * line_height <= y2 - y1:
            break
    else:
        font = find_shorts_headline_font(35, title)
        if manual_lines:
            lines = manual_lines[:max_lines]
        elif not contains_devanagari(title) and len(title_words) > 5:
            lines = split_balanced_two_line_title(title)
        else:
            lines = wrap_title_text(draw, title, font, max_text_width)[:max_lines]
        line_height = 35
    total_height = len(lines) * line_height
    y = y1 + max(0, (y2 - y1 - total_height) // 2)
    pattern = highlight_pattern(parse_highlight_terms(highlight_text))
    for idx, line in enumerate(lines):
        segments = pattern.split(line) if pattern else [line]
        segment_fonts = [
            find_shorts_headline_font(size if "size" in locals() else 42, segment)
            for segment in segments
        ]
        width = sum(text_width(draw, segment, segment_font) for segment, segment_font in zip(segments, segment_fonts) if segment)
        cursor = x1 + max(0, (x2 - x1 - width) // 2)
        for segment, segment_font in zip(segments, segment_fonts):
            if not segment:
                continue
            fill = "#f5ed3a" if pattern and pattern.fullmatch(segment) else "#fff1f1"
            draw.text((cursor + 3, y + 3), segment, font=segment_font, fill="#330004")
            draw.text((cursor, y), segment, font=segment_font, fill=fill, stroke_width=2, stroke_fill="#6c0008")
            cursor += text_width(draw, segment, segment_font)
        y += line_height


def create_shorts_layout_background(
    text: str,
    template_key: str,
    output_path: Path,
    highlight_text: str = "",
) -> Tuple[Path, List[Tuple[str, int, int, int, int]]]:
    ensure_dirs()
    ensure_default_shorts_logo()
    layout = shorts_template_layout(template_key)
    image = load_shorts_background()
    draw = ImageDraw.Draw(image)
    logo_xy = layout.get("logo", (240, 110))
    draw_logo_asset(image, logo_xy, (500, 58))
    for panel in layout.get("panels", []):
        _, x, y, w, h = panel
        draw.rounded_rectangle((x, y, x + w, y + h), radius=18, fill="#f8f8f8")
        draw.rounded_rectangle((x + 7, y + 7, x + w - 7, y + h - 7), radius=12, fill="#280006")
    draw_template_headline(draw, text, layout.get("title", (100, 240, 980, 500)), highlight_text)
    image.save(output_path)
    return output_path, list(layout.get("panels", []))


def create_news_title_card(
    text: str,
    output_path: Path,
    logo_path: Optional[Path] = None,
    template_path: Optional[Path] = None,
) -> Path:
    ensure_dirs()
    if template_path and template_path.exists():
        image = Image.open(template_path).convert("RGBA")
        image = crop_template_left_edge(image)
        draw = ImageDraw.Draw(image)
        title = text.strip()
        if title:
            title_top = int(image.height * 0.14)
            title_bottom = int(image.height * 0.50)
            max_width = int(image.width * 0.86)
            title_font, lines = fit_title_lines(
                draw,
                title,
                max_width=max_width,
                max_lines=2,
                start_size=max(32, int(image.height * 0.14)),
                min_size=max(22, int(image.height * 0.08)),
            )
            line_height = int(title_font.size * 1.18) if hasattr(title_font, "size") else 48
            title_area_height = int((title_bottom - title_top) * 0.92)
            while hasattr(title_font, "size") and len(lines) * line_height > title_area_height and title_font.size > max(22, int(image.height * 0.08)):
                title_font = find_title_font(title_font.size - 2)
                line_height = int(title_font.size * 1.18)
            total_height = len(lines) * line_height
            y = title_top + max(0, ((title_bottom - title_top) - total_height) // 2)
            for idx, line in enumerate(lines):
                fill = "#ffe95c" if idx == 0 else "#ffffff"
                width = text_width(draw, line, title_font)
                draw.text(((image.width - width) // 2, y), line, font=title_font, fill=fill)
                y += line_height
        image.save(output_path)
        return output_path
    else:
        image = Image.new("RGB", (CANVAS_WIDTH, TITLE_CARD_HEIGHT), "#a80000")
        draw = ImageDraw.Draw(image)

        title_top = 64
        title_bottom = 455
        draw.rectangle((0, 0, CANVAS_WIDTH, TITLE_CARD_HEIGHT), fill="#a60000")
        draw.rectangle((0, title_top, CANVAS_WIDTH, title_bottom), fill="#410000")
        draw.rectangle((0, title_bottom, CANVAS_WIDTH, TITLE_CARD_HEIGHT), fill="#b00000")

        draw_reference_brand_strip(image, draw, logo_path)

        draw.line((0, title_bottom, CANVAS_WIDTH, title_bottom), fill="#ffffff", width=5)
        draw.line((0, title_bottom + 9, CANVAS_WIDTH, title_bottom + 9), fill="#d61f26", width=8)
        draw.rectangle((0, title_bottom + 22, CANVAS_WIDTH, title_bottom + 54), fill="#8e0000")
        draw.rounded_rectangle((CANVAS_WIDTH - 210, title_bottom - 28, CANVAS_WIDTH - 38, title_bottom + 23), radius=26, fill="#b7520a")
        draw.ellipse((CANVAS_WIDTH - 166, title_bottom - 17, CANVAS_WIDTH - 82, title_bottom + 12), fill="#ffad2f")
        draw.ellipse((CANVAS_WIDTH - 136, title_bottom - 9, CANVAS_WIDTH - 106, title_bottom + 2), fill="#fff4ba")

        draw = ImageDraw.Draw(image)

        title = text.strip() or "Shorts headline"
        title_font, lines = fit_title_lines(draw, title, max_width=890, max_lines=2, start_size=94, min_size=54)
        line_height = int(title_font.size * 1.18) if hasattr(title_font, "size") else 96
        total_height = len(lines) * line_height
        y = title_top + max(0, ((title_bottom - title_top) - total_height) // 2) - 6
        for idx, line in enumerate(lines):
            fill = "#ffe95c" if idx == 0 else "#ffffff"
            width = text_width(draw, line, title_font)
            draw.text(((CANVAS_WIDTH - width) // 2, y), line, font=title_font, fill=fill)
            y += line_height

        draw.line((70, TITLE_CARD_HEIGHT - 74, CANVAS_WIDTH - 70, TITLE_CARD_HEIGHT - 74), fill="#ca1d1d", width=3)

        image.save(output_path)
        return output_path


def build_video_filter(
    mode: str,
    headline: str,
    subtitle_file: Optional[Path],
    include_safe_guides: bool,
    focus_x: str = "Center",
    focus_y: str = "Center",
    title_card_path: Optional[Path] = None,
    background_mark_path: Optional[Path] = None,
    title_position: str = "Bottom",
) -> str:
    filters = available_ffmpeg_filters()
    safe_width = 960
    safe_height = 1500
    safe_x = 60
    safe_y = 210
    overlays: List[str] = []
    if include_safe_guides and "drawbox" in filters:
        overlays.append(f"drawbox=x={safe_x}:y={safe_y}:w={safe_width}:h={safe_height}:color=white@0.18:t=2")

    if headline.strip() and "drawtext" in filters:
        text = escape_drawtext(headline.strip()[:90])
        overlays.append(
            "drawtext="
            f"text='{text}':x=(w-text_w)/2:y=130:"
            "fontcolor=white:fontsize=54:"
            "box=1:boxcolor=black@0.55:boxborderw=24"
        )

    if subtitle_file and "subtitles" in filters:
        escaped_path = escape_filter_value(str(subtitle_file))
        overlays.append(f"subtitles=filename='{escaped_path}'")

    overlays.append("format=yuv420p")
    overlays.append("setsar=1")
    suffix = "," + ",".join(overlays) if overlays else ""

    if mode == "News template: video + headline":
        x_expr = focal_crop_x(focus_x)
        y_expr = focal_crop_y(focus_y)
        if title_card_path:
            background_input = 2 if background_mark_path else None
            panel_height = TITLE_CARD_HEIGHT
            try:
                with Image.open(title_card_path) as panel_image:
                    panel_height = int(round(panel_image.height * CANVAS_WIDTH / panel_image.width))
            except Exception:
                pass
            panel_scale = f"scale={CANVAS_WIDTH}:-1"
            if title_position == "Top":
                video_y = TITLE_CARD_HEIGHT - TITLE_CARD_OVERLAP
                panel_y = 0
                video_height = NEWS_VIDEO_HEIGHT
                foreground_y = "0"
            else:
                video_y = 0
                panel_y = CANVAS_HEIGHT - panel_height
                video_height = panel_y + TITLE_CARD_OVERLAP
                foreground_y = "H-h"
            if background_input is not None:
                fg_overlay_y = video_y if title_position == "Top" else f"{video_height}-h"
                return (
                    "[0:v]setsar=1[fgsrc];"
                    f"[{background_input}:v]format=rgba,scale={CANVAS_WIDTH}:{CANVAS_HEIGHT}:force_original_aspect_ratio=increase,"
                    f"crop={CANVAS_WIDTH}:{CANVAS_HEIGHT},setsar=1[basebg];"
                    f"[fgsrc]scale={CANVAS_WIDTH}:{video_height}:force_original_aspect_ratio=decrease,"
                    f"crop=iw:ih-{NEWS_FOREGROUND_TOP_TRIM}:0:{NEWS_FOREGROUND_TOP_TRIM}[fg];"
                    f"[basebg][fg]overlay=(W-w)/2:{fg_overlay_y},setsar=1[base];"
                    f"[1:v]format=rgba,{panel_scale},format=rgba,setsar=1[panel];"
                    f"[base][panel]overlay=0:{panel_y},format=yuv420p,setsar=1[vout]"
                )
            return (
                "[0:v]setsar=1,split=2[bgsrc][fgsrc];"
                f"[bgsrc]scale={CANVAS_WIDTH}:{video_height}:force_original_aspect_ratio=increase,"
                f"crop={CANVAS_WIDTH}:{video_height},boxblur=20:2[bg];"
                f"[fgsrc]scale={CANVAS_WIDTH}:{video_height}:force_original_aspect_ratio=decrease,"
                f"crop=iw:ih-{NEWS_FOREGROUND_TOP_TRIM}:0:{NEWS_FOREGROUND_TOP_TRIM}[fg];"
                f"[bg][fg]overlay=(W-w)/2:{foreground_y},setsar=1[vclip];"
                f"[vclip]pad={CANVAS_WIDTH}:{CANVAS_HEIGHT}:0:{video_y}:color=#a80000[base];"
                f"[1:v]format=rgba,{panel_scale},format=rgba,setsar=1[panel];"
                f"[base][panel]overlay=0:{panel_y},format=yuv420p,setsar=1[vout]"
            )
        return (
            f"[0:v]setsar=1,scale={CANVAS_WIDTH}:{CANVAS_HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={CANVAS_WIDTH}:{CANVAS_HEIGHT}:{x_expr}:{y_expr}{suffix}[vout]"
        )

    if mode in {"Fit full video + blur", "Blurred background"}:
        return (
            "[0:v]split=2[bgsrc][fgsrc];"
            "[bgsrc]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,boxblur=24:2[bg];"
            "[fgsrc]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2{suffix}[vout]"
        )

    if mode == "Fit inside safe area + blur":
        return (
            "[0:v]split=2[bgsrc][fgsrc];"
            "[bgsrc]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,boxblur=24:2[bg];"
            f"[fgsrc]scale={safe_width}:{safe_height}:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2{suffix}[vout]"
        )

    if mode == "Fit full video + black bars":
        return (
            "[0:v]scale=1080:1920:force_original_aspect_ratio=decrease,"
            f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black{suffix}[vout]"
        )

    if mode == "Fit inside safe area + black bars":
        return (
            f"[0:v]scale={safe_width}:{safe_height}:force_original_aspect_ratio=decrease,"
            f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black{suffix}[vout]"
        )

    return (
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
        f"crop=1080:1920{suffix}[vout]"
    )


def build_shorts_template_filter(
    panels: List[Tuple[str, int, int, int, int]],
    include_safe_guides: bool,
    thumbnail_input: Optional[int],
    play_icon_input: Optional[int],
) -> str:
    if not panels:
        return "[1:v]scale=1080:1920,format=yuv420p,setsar=1[vout]"
    video_panels = [panel for panel in panels if panel[0] == "video"]
    image_panels = [panel for panel in panels if panel[0] == "image"]
    fallback_image_panels = 0 if thumbnail_input is not None else len(image_panels)
    split_count = max(1, len(video_panels) + fallback_image_panels)
    split_labels = "".join(f"[p{idx}src]" for idx in range(split_count))
    parts = [f"[1:v]scale={CANVAS_WIDTH}:{CANVAS_HEIGHT},format=rgba,setsar=1[base];"]
    parts.append(f"[0:v]setsar=1,split={split_count}{split_labels};")
    previous = "base"
    overlay_count = 0
    video_idx = 0
    play_targets: List[Tuple[int, int, int, int]] = []

    for kind, x, y, width, height in panels:
        inner_x = x + 7
        inner_y = y + 7
        inner_w = width - 14
        inner_h = height - 14
        output_label = f"tmp{overlay_count}"
        if kind == "image" and thumbnail_input is not None:
            parts.append(
                f"[{thumbnail_input}:v]scale={inner_w}:{inner_h}:force_original_aspect_ratio=increase,"
                f"crop={inner_w}:{inner_h},setsar=1[img{overlay_count}];"
                f"[{previous}][img{overlay_count}]overlay={inner_x}:{inner_y},setsar=1[{output_label}];"
            )
        else:
            source_label = f"p{video_idx}src"
            video_idx += 1
            if kind == "video":
                parts.append(
                    f"[{source_label}]scale={inner_w}:{inner_h}:force_original_aspect_ratio=decrease,"
                    f"pad={inner_w}:{inner_h}:(ow-iw)/2:(oh-ih)/2:color=0x280006,setsar=1[p{overlay_count}];"
                    f"[{previous}][p{overlay_count}]overlay={inner_x}:{inner_y},setsar=1[{output_label}];"
                )
            else:
                parts.append(
                    f"[{source_label}]scale={inner_w}:{inner_h}:force_original_aspect_ratio=increase,"
                    f"crop={inner_w}:{inner_h},setsar=1[p{overlay_count}];"
                    f"[{previous}][p{overlay_count}]overlay={inner_x}:{inner_y},setsar=1[{output_label}];"
                )
            if kind == "video":
                play_targets.append((inner_x, inner_y, inner_w, inner_h))
        previous = output_label
        overlay_count += 1

    if play_icon_input is not None:
        for play_idx, (inner_x, inner_y, inner_w, inner_h) in enumerate(play_targets):
            play_w = max(96, min(150, inner_w // 5))
            play_h = int(play_w * 120 / 170)
            output_label = f"playtmp{play_idx}"
            parts.append(
                f"[{play_icon_input}:v]scale={play_w}:{play_h},format=rgba[play{play_idx}];"
                f"[{previous}][play{play_idx}]overlay={inner_x + (inner_w - play_w) // 2}:{inner_y + (inner_h - play_h) // 2},setsar=1[{output_label}];"
            )
            previous = output_label
    suffix = ""
    if include_safe_guides and "drawbox" in available_ffmpeg_filters():
        suffix = ",drawbox=x=60:y=210:w=960:h=1500:color=white@0.18:t=2"
    return "".join(parts) + f"[{previous}]format=yuv420p{suffix},setsar=1[vout]"


def create_simple_srt(text: str, duration: float, output_path: Path) -> Optional[Path]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    duration = max(duration, 1.0)
    chunk_duration = duration / len(lines)
    blocks = []
    for idx, line in enumerate(lines, start=1):
        start = (idx - 1) * chunk_duration
        end = min(duration, idx * chunk_duration)
        blocks.append(
            f"{idx}\n"
            f"{seconds_to_srt(start)} --> {seconds_to_srt(end)}\n"
            f"{line[:180]}\n"
        )
    output_path.write_text("\n".join(blocks), encoding="utf-8")
    return output_path


def seconds_to_srt(seconds: float) -> str:
    timecode = seconds_to_timecode(seconds).replace(".", ",")
    return timecode


def export_clip(
    source: Path,
    candidate: ClipCandidate,
    mode: str,
    headline: str,
    captions: str,
    include_safe_guides: bool,
    focus_x: str = "Center",
    focus_y: str = "Center",
    title_position: str = "Bottom",
    logo_path: Optional[Path] = None,
    template_path: Optional[Path] = None,
    shorts_template: str = "reference",
    thumbnail_path: Optional[Path] = None,
    title_highlight_text: str = "",
    overlay_play_icon: bool = False,
) -> Tuple[Optional[Path], str]:
    ffmpeg = tool_path("ffmpeg")
    if not ffmpeg:
        return None, "ffmpeg is not installed or not available on PATH."

    ensure_dirs()
    ensure_default_background_mark()
    safe_title = re.sub(r"[^A-Za-z0-9._-]+", "_", candidate.title).strip("_")[:48]
    if not safe_title:
        safe_title = "news_template"
    position_suffix = f"_{shorts_template}_{title_position.lower()}" if mode == "News template: video + headline" else ""
    output_path = EXPORT_DIR / f"{source.stem}_short_{candidate.index}_{safe_title}{position_suffix}.mp4"
    counter = 1
    while output_path.exists():
        output_path = EXPORT_DIR / f"{source.stem}_short_{candidate.index}_{safe_title}{position_suffix}_{counter}.mp4"
        counter += 1
    subtitle_file = create_simple_srt(
        captions,
        candidate.duration,
        EXPORT_DIR / f"{source.stem}_short_{candidate.index}.srt",
    )
    title_card_path = None
    background_mark_path = DEFAULT_BACKGROUND_PATTERN if DEFAULT_BACKGROUND_PATTERN.exists() else None
    template_panels: List[Tuple[str, int, int, int, int]] = []
    if mode == "News template: video + headline":
        if shorts_template == "reference":
            title_card_path = create_news_title_card(
                headline or candidate.title,
                TITLE_CARD_DIR / f"{source.stem}_short_{candidate.index}_title.png",
                logo_path=logo_path,
                template_path=template_path,
            )
        else:
            title_card_path, template_panels = create_shorts_layout_background(
                headline or candidate.title,
                shorts_template,
                TITLE_CARD_DIR / f"{source.stem}_short_{candidate.index}_{shorts_template}.png",
                title_highlight_text,
            )
        subtitle_file = None
    if mode == "News template: video + headline" and shorts_template != "reference":
        thumbnail_input = 2 if thumbnail_path and thumbnail_path.exists() else None
        play_icon_input = (3 if thumbnail_input is not None else 2) if overlay_play_icon else None
        video_filter = build_shorts_template_filter(template_panels, include_safe_guides, thumbnail_input, play_icon_input)
    else:
        video_filter = build_video_filter(
            mode,
            headline,
            subtitle_file,
            include_safe_guides,
            focus_x=focus_x,
            focus_y=focus_y,
            title_card_path=title_card_path,
            background_mark_path=background_mark_path if title_card_path else None,
            title_position=title_position,
        )
    filter_warnings = []
    filters = available_ffmpeg_filters()
    if headline.strip() and "drawtext" not in filters and mode != "News template: video + headline":
        filter_warnings.append("headline overlay skipped because this FFmpeg build lacks the drawtext filter")
    if subtitle_file and "subtitles" not in filters:
        filter_warnings.append("burned captions skipped because this FFmpeg build lacks the subtitles filter")
    if include_safe_guides and "drawbox" not in filters:
        filter_warnings.append("safe-area guide skipped because this FFmpeg build lacks the drawbox filter")

    args = [
        ffmpeg,
        "-y",
        "-ss",
        f"{candidate.start:.3f}",
        "-i",
        str(source),
    ]
    if title_card_path:
        args.extend(["-loop", "1", "-i", str(title_card_path)])
    if title_card_path and background_mark_path and shorts_template == "reference":
        args.extend(["-loop", "1", "-i", str(background_mark_path)])
    if title_card_path and shorts_template != "reference":
        if thumbnail_path and thumbnail_path.exists():
            args.extend(["-loop", "1", "-i", str(thumbnail_path)])
        if overlay_play_icon:
            ensure_default_play_icon()
            args.extend(["-loop", "1", "-i", str(DEFAULT_PLAY_ICON)])
    args.extend([
        "-t",
        f"{candidate.duration:.3f}",
        "-filter_complex",
        video_filter,
        "-map",
        "[vout]",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "22",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-shortest",
        "-movflags",
        "+faststart",
        str(output_path),
    ])
    result = run_command(args)
    if result.returncode != 0:
        return None, result.stderr[-2500:] or "ffmpeg export failed."
    save_manifest(source, output_path, candidate, mode, headline)
    message = "Export complete."
    if filter_warnings:
        message += " Note: " + "; ".join(filter_warnings) + "."
    return output_path, message


def save_manifest(source: Path, output: Path, candidate: ClipCandidate, mode: str, headline: str) -> None:
    ensure_dirs()
    existing = []
    if MANIFEST_PATH.exists():
        try:
            existing = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        except Exception:
            existing = []
    existing.append(
        {
            "source": str(source),
            "output": str(output),
            "start": candidate.start,
            "end": candidate.end,
            "duration": candidate.duration,
            "title": candidate.title,
            "caption": candidate.caption,
            "mode": mode,
            "headline": headline,
        }
    )
    MANIFEST_PATH.write_text(json.dumps(existing, indent=2), encoding="utf-8")


def render_candidate_card(candidate: ClipCandidate) -> None:
    st.markdown(f"**{candidate.title}**")
    col_a, col_b = st.columns(2)
    col_a.metric("Start", compact_time(candidate.start))
    col_b.metric("Length", f"{int(candidate.duration)}s")
    st.caption(candidate.reason)
    if candidate.caption:
        st.write(candidate.caption)


def load_created_clips() -> List[ClipCandidate]:
    payload = st.session_state.get("created_clips", [])
    if not isinstance(payload, list):
        return []
    clips: List[ClipCandidate] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            clips.append(ClipCandidate(**item))
        except TypeError:
            continue
    return clips


def save_created_clips(clips: List[ClipCandidate]) -> None:
    st.session_state["created_clips"] = [clip.__dict__ for clip in clips]


def add_created_clip(candidate: ClipCandidate, title_text: str = "") -> bool:
    clips = load_created_clips()
    if len(clips) >= MAX_CREATED_CLIPS:
        st.session_state["clip_limit_message"] = f"Maximum {MAX_CREATED_CLIPS} clips can be open at once. Remove one to add another."
        return False
    next_index = int(st.session_state.get("next_clip_index", 1))
    candidate.index = next_index
    st.session_state["next_clip_index"] = next_index + 1
    clips.append(candidate)
    save_created_clips(clips)
    if title_text:
        st.session_state[f"title_card_text_{candidate.index}"] = title_text
    return True


def remove_created_clip(index: int) -> None:
    clips = [clip for clip in load_created_clips() if clip.index != index]
    save_created_clips(clips)
    rendered = st.session_state.get("rendered_clip_outputs", {})
    if isinstance(rendered, dict):
        rendered.pop(str(index), None)
        st.session_state["rendered_clip_outputs"] = rendered


def remember_rendered_clip(index: int, output: Path, label: str) -> None:
    rendered = st.session_state.get("rendered_clip_outputs", {})
    if not isinstance(rendered, dict):
        rendered = {}
    key = str(index)
    rendered[key] = [{"path": str(output), "label": label}]
    st.session_state["rendered_clip_outputs"] = rendered


def render_saved_outputs(index: int) -> None:
    rendered = st.session_state.get("rendered_clip_outputs", {})
    if not isinstance(rendered, dict):
        return
    items = rendered.get(str(index), [])
    if not isinstance(items, list) or not items:
        return
    st.markdown("**Rendered videos**")
    for item_idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        path = Path(str(item.get("path", "")))
        if not path.exists():
            continue
        st.caption(item.get("label") or path.name)
        st.video(str(path))
        with path.open("rb") as file_obj:
            st.download_button(
                "Download MP4",
                file_obj,
                file_name=path.name,
                mime="video/mp4",
                key=f"download_rendered_{index}_{item_idx}",
            )


def render_chapter_clip_actions(chapter_rows: List[Dict[str, str]], clip_length: int, duration: float) -> None:
    for idx, row in enumerate(chapter_rows, start=1):
        start = float(row.get("Start seconds") or 0)
        cols = st.columns([0.12, 0.70, 0.18])
        cols[0].write(row.get("Time", compact_time(start)))
        cols[1].write(row.get("Chapter", "Chapter"))
        if cols[2].button("Create", key=f"chapter_clip_{idx}", use_container_width=True):
            candidate = create_clip_candidate_from_moment(
                start=start,
                text=row.get("Chapter", ""),
                clip_length=clip_length,
                duration=duration,
                reason=f"Selected chapter at {row.get('Time', compact_time(start))}",
            )
            add_created_clip(candidate, row.get("Chapter", ""))
            st.rerun()


def render_keyword_clip_actions(keyword_hits: List[Dict[str, str]], clip_length: int, duration: float) -> None:
    for idx, row in enumerate(keyword_hits, start=1):
        start = float(row.get("Start seconds") or 0)
        text = row.get("Transcript text", "")
        matched = row.get("Matched keyword", "")
        cols = st.columns([0.10, 0.72, 0.18])
        cols[0].write(row.get("Time", compact_time(start)))
        cols[1].write(f"{matched} - {text}" if matched else text)
        if cols[2].button("Create", key=f"keyword_clip_{idx}", use_container_width=True):
            candidate = create_clip_candidate_from_moment(
                start=start,
                text=text,
                clip_length=clip_length,
                duration=duration,
                reason=f"Selected keyword match: {row.get('Matched keyword', '')} at {row.get('Time', compact_time(start))}",
            )
            add_created_clip(candidate, text)
            st.rerun()


def visible_chapter_rows(chapter_rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    return [
        {
            "Time": row.get("Time", ""),
            "Chapter": row.get("Chapter", ""),
            "YouTube format": row.get("YouTube format", ""),
        }
        for row in chapter_rows
    ]


def main() -> None:
    st.set_page_config(page_title="Shorts Automation Prototype", page_icon="▶", layout="wide")
    ensure_default_template()
    ensure_default_background_mark()

    st.title("Shorts Automation Prototype")
    st.caption("Convert owned horizontal videos into vertical YouTube Shorts candidates.")
    st.markdown(
        """
        <style>
        div[data-testid="stFileUploader"] section {
            padding: 0.35rem 0.55rem;
            min-height: 44px;
        }
        div[data-testid="stFileUploader"] section > div {
            gap: 0.35rem;
        }
        div[data-testid="stFileUploader"] small {
            display: none;
        }
        div[data-testid="stFileUploader"] button {
            padding: 0.35rem 0.65rem;
        }
        div[data-testid="stTextArea"] textarea {
            min-height: 96px !important;
        }
        div[data-testid="stVerticalBlock"] {
            gap: 0.55rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    ffmpeg_ok = tool_path("ffmpeg") is not None
    ffprobe_ok = tool_path("ffprobe") is not None
    if not ffmpeg_ok or not ffprobe_ok:
        st.warning(
            "Install ffmpeg to enable video inspection and export. On macOS: `brew install ffmpeg`. "
            "On Ubuntu/Streamlit Cloud: add `ffmpeg` to packages.txt."
        )
    if "transcript_text" not in st.session_state:
        st.session_state["transcript_text"] = ""

    clip_length = 45
    crop_mode = "News template: video + headline"
    focus_x = "Center"
    focus_y = "Center"
    title_position = "Bottom"
    overlay_play_icon = False
    include_safe_guides = False
    template_path = DEFAULT_TITLE_TEMPLATE if DEFAULT_TITLE_TEMPLATE.exists() else None
    logo_path = None

    st.markdown("**Source**")
    input_cols = st.columns([0.30, 0.55, 0.15])
    uploaded = input_cols[0].file_uploader(
        "Upload video",
        type=["mp4", "mov", "m4v", "webm", "mkv"],
        label_visibility="collapsed",
    )

    source_path: Optional[Path] = Path(st.session_state["source_path"]) if "source_path" in st.session_state else None
    if uploaded:
        upload_signature = f"{uploaded.name}:{uploaded.size}"
        if st.session_state.get("saved_upload_signature") != upload_signature:
            saved_path = save_upload(uploaded)
            if str(saved_path) != st.session_state.get("source_path"):
                reset_video_working_state()
            st.session_state["source_path"] = str(saved_path)
            st.session_state["source_kind"] = "upload"
            st.session_state["saved_upload_signature"] = upload_signature
            source_path = saved_path
            st.success(f"Uploaded video saved: {saved_path.name}")
        else:
            source_path = Path(st.session_state["source_path"])
            st.session_state["source_kind"] = st.session_state.get("source_kind", "upload")
            st.success(f"Uploaded video ready: {source_path.name}")

    video_url = input_cols[1].text_input(
        "Video link",
        placeholder="https://www.youtube.com/watch?v=... or https://example.com/video.mp4",
        label_visibility="collapsed",
    )
    browser_cookie_source = ""
    youtube_po_token = ""
    fetch_clicked = input_cols[2].button("Fetch", disabled=not video_url.strip(), use_container_width=True)
    if fetch_clicked:
        thumbnail_path, thumbnail_message = fetch_youtube_thumbnail(video_url)
        if thumbnail_path:
            st.session_state["thumbnail_path"] = str(thumbnail_path)
            st.success(thumbnail_message)
        else:
            st.session_state.pop("thumbnail_path", None)
            st.warning(thumbnail_message)
        with st.spinner("Pulling timestamped transcript from video link..."):
            pulled_transcript, pull_message = pull_timestamped_transcript_from_url(video_url, browser_cookie_source)
        if pulled_transcript:
            store_transcript_text(pulled_transcript)
            st.success(pull_message)
        else:
            st.warning(pull_message)

        with st.spinner("Fetching video from link..."):
            linked_path, link_message = download_video_link(video_url, browser_cookie_source, youtube_po_token)
        if linked_path:
            if str(linked_path) != st.session_state.get("source_path"):
                reset_video_working_state()
            st.session_state["source_path"] = str(linked_path)
            st.session_state["source_kind"] = "link"
            if thumbnail_path:
                st.session_state["thumbnail_path"] = str(thumbnail_path)
            if pulled_transcript:
                store_transcript_text(pulled_transcript)
            source_path = linked_path
            st.success(link_message)
            st.session_state["last_upload_transcript_attempt"] = f"{source_path}:{video_url.strip()}"
        else:
            st.error(link_message)

    if (
        source_path
        and st.session_state.get("source_kind") == "upload"
        and video_url.strip()
        and not st.session_state.get("transcript_text", "").strip()
    ):
        transcript_attempt_key = f"{source_path}:{video_url.strip()}"
        if st.session_state.get("last_upload_transcript_attempt") != transcript_attempt_key:
            st.session_state["last_upload_transcript_attempt"] = transcript_attempt_key
            thumbnail_path, thumbnail_message = fetch_youtube_thumbnail(video_url)
            if thumbnail_path:
                st.session_state["thumbnail_path"] = str(thumbnail_path)
            with st.spinner("Pulling timestamped transcript from video link for the uploaded video..."):
                pulled_transcript, pull_message = pull_timestamped_transcript_from_url(video_url, browser_cookie_source)
            if pulled_transcript:
                store_transcript_text(pulled_transcript)
                st.success(pull_message)
            else:
                st.warning(pull_message)

    if not source_path:
        if st.session_state.get("transcript_text", "").strip():
            st.markdown("**Transcript / Keywords**")
            transcript_preview = st.text_area(
                "Timestamped transcript",
                height=130,
                key="transcript_text",
            )
            keyword_query = st.text_input(
                "Find keywords in transcript",
                placeholder="Example: Supreme Court, AI, फैसला",
            )
            keyword_hits = find_keyword_hits(transcript_preview, keyword_query)
            if keyword_query.strip():
                if keyword_hits:
                    st.dataframe(keyword_hits, use_container_width=True, hide_index=True)
                    st.caption(f"Found {len(keyword_hits)} timestamped match(es).")
                else:
                    st.info("No timestamped matches found for those keywords.")
            chapter_rows = suggest_chapters(transcript_preview, 0)
            if chapter_rows:
                with st.expander("Optional suggested chapters"):
                    st.dataframe(visible_chapter_rows(chapter_rows), use_container_width=True, hide_index=True)
                    chapter_text = "\n".join(row["YouTube format"] for row in chapter_rows)
                    st.text_area("Chapters copy block", value=chapter_text, height=150)
            st.info("Transcript is loaded. Fetch/upload the video file when you are ready to create Shorts.")
        else:
            st.info("Start by uploading a video or fetching a video link.")
        return

    metadata = probe_video(source_path)
    thumbnail_path = Path(st.session_state["thumbnail_path"]) if st.session_state.get("thumbnail_path") else None
    duration = float(metadata.get("duration") or 0)

    st.markdown("**Transcript / Keywords**")
    transcript_col, keyword_col = st.columns([0.68, 0.32])
    transcript = transcript_col.text_area(
        "Transcript",
        height=130,
        placeholder="[00:01:12] The strongest hook from the video...\n[00:04:30] Another useful moment...",
        key="transcript_text",
        label_visibility="collapsed",
    )
    keyword_query = keyword_col.text_input(
        "Keywords",
        placeholder="Keywords: Supreme Court, AI, फैसला",
        label_visibility="collapsed",
    )
    keyword_hits = find_keyword_hits(transcript, keyword_query)
    if keyword_query.strip():
        if keyword_hits:
            with st.expander(f"Keyword matches ({len(keyword_hits)})", expanded=False):
                render_keyword_clip_actions(keyword_hits, clip_length, duration)
        else:
            st.info("No timestamped matches found for those keywords.")

    chapter_rows = suggest_chapters(transcript, duration)
    if chapter_rows:
        with st.expander(f"Suggested chapters ({len(chapter_rows)})", expanded=False):
            render_chapter_clip_actions(chapter_rows, clip_length, duration)
            chapter_text = "\n".join(row["YouTube format"] for row in chapter_rows)
            st.text_area("YouTube chapters", value=chapter_text, height=90)

    created_clips = load_created_clips()
    st.subheader("Created Clips")
    if st.session_state.pop("clip_limit_message", ""):
        st.warning(f"Maximum {MAX_CREATED_CLIPS} clips can be open at once. Remove one to add another.")
    if not created_clips:
        st.info("No clips created yet. Click **Create** on a chapter or keyword match.")
        return

    st.caption(f"{len(created_clips)} of {MAX_CREATED_CLIPS} clips created.")
    tabs = st.tabs([f"Clip {clip.index}" for clip in created_clips])
    for tab, candidate in zip(tabs, created_clips):
        with tab:
            remove_col, spacer_col = st.columns([0.18, 0.82])
            if remove_col.button("Remove clip", key=f"remove_clip_{candidate.index}"):
                remove_created_clip(candidate.index)
                st.rerun()

            top, controls = st.columns([0.44, 0.56])
            with top:
                render_candidate_card(candidate)
            with controls:
                start = st.number_input(
                    "Start seconds",
                    min_value=0.0,
                    max_value=max(duration, candidate.end, 1.0),
                    value=float(candidate.start),
                    step=1.0,
                    key=f"start_{candidate.index}",
                )
                length = st.number_input(
                    "Duration seconds",
                    min_value=5.0,
                    max_value=180.0,
                    value=float(candidate.duration),
                    step=1.0,
                    key=f"duration_{candidate.index}",
                )
                selected_template = "template_3"
                title_key = f"title_card_text_{candidate.index}"
                title_card_text = st.text_area(
                    "Title card text",
                    value=st.session_state.get(title_key, ""),
                    placeholder="Example: गोत्र की शुरुआत\nआखिर कैसे हुई?",
                    height=90,
                    key=title_key,
                )
                title_highlight_text = st.text_input(
                    "Yellow highlight text",
                    placeholder="Example: PM मोदी, AI",
                    key=f"title_highlight_text_{candidate.index}",
                    help="Enter one phrase or comma-separated words from the title to highlight in yellow.",
                )
                headline = title_card_text.strip() or candidate.title
                captions = st.text_area(
                    "Burned captions",
                    value=candidate.caption,
                    height=110,
                    key=f"captions_{candidate.index}",
                )

                edited = ClipCandidate(
                    index=candidate.index,
                    start=float(start),
                    end=float(start + length),
                    title=headline,
                    caption=captions,
                    reason=candidate.reason,
                    score=candidate.score,
                )
                if st.button("Export vertical MP4", key=f"export_{candidate.index}", type="primary"):
                    with st.spinner("Rendering vertical Short..."):
                        output, message = export_clip(
                            source_path,
                            edited,
                            crop_mode,
                            headline,
                            captions,
                            include_safe_guides,
                            focus_x,
                            focus_y,
                            title_position,
                            logo_path,
                            template_path,
                            selected_template,
                            thumbnail_path,
                            title_highlight_text,
                            overlay_play_icon,
                        )
                    if output:
                        remember_rendered_clip(
                            candidate.index,
                            output,
                            f"{SHORTS_TEMPLATE_LABELS.get(selected_template, selected_template)} · {output.name}",
                        )
                        st.success(message)
                    else:
                        st.error(message)
                render_saved_outputs(candidate.index)

    if MANIFEST_PATH.exists():
        with st.expander("Export manifest"):
            st.json(json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))


if __name__ == "__main__":
    main()
