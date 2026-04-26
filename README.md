# Downloader UI (YouTube + TikTok) — Electron + yt-dlp

This project is a Windows desktop UI (Electron) for:

- Listing videos (thumbnail, title, duration, upload date) with filters + pagination
- Parallel downloads with Pause / Continue / Cancel (resumes from `.part` files when possible)
- YouTube and TikTok support (TikTok often needs `cookies.txt`)

The backend uses Python + `yt-dlp`.

> Note: only download content you own or have permission to download, and follow each platform’s Terms of Service.

## Requirements

- Windows (Electron UI)
- Python 3.9+ (recommended)
- Node.js + npm
- `ffmpeg` (required; needed to merge video+audio and/or extract audio)

Codec note: some Windows players can’t play `Opus` audio. With `ffmpeg`, the backend prefers `m4a/AAC` audio when producing MP4 for better compatibility.

## Install

```powershell
py -m pip install -r requirements.txt
npm install
```

## Run the UI (Electron)

```powershell
npm start
```

The UI has 2 tabs: **YouTube** and **TikTok**.

## UI Features

- **Filters**: search (title/caption), exclude < 60s, min/max duration, upload date range
- **Pagination**: 20 items per page
- **Parallel downloads**: configurable (runs multiple Python processes)
- **Custom label** (optional): file name becomes `(date)_CUSTOM_(title)`
- **Pause / Continue / Cancel**
  - Pause = stops processes (keeps `.part` files)
  - Continue = starts again and resumes (when possible)

## Backend CLI (used by the UI, can be used directly)

Backend file: `yt_app.py`

List + filters + pagination (JSON output):

```powershell
py .\yt_app.py list "<URL>" --page 1 --page-size 20 --query "keyword" --exclude-shorts --min-duration 60 --max-duration 1800 --date-from 2024-01-01 --date-to 2024-12-31
```

Download one or more URLs (JSON-line progress):

```powershell
py .\yt_app.py download "<URL_1>" "<URL_2>" --json-progress -o downloads
```

Cookies (optional, often required for TikTok):

```powershell
py .\yt_app.py list "<TIKTOK_PROFILE_URL>" --cookies "C:\\path\\cookies.txt"
py .\yt_app.py download "<TIKTOK_VIDEO_URL>" --cookies "C:\\path\\cookies.txt"
```

YouTube note: cookies can also help when YouTube shows “Sign in to confirm you’re not a bot”.

Custom label (optional):

```powershell
py .\yt_app.py download "<URL>" --custom "PROJECTA"
```

Performance note: large listings create a local cache in `.yt_cache/` to speed up subsequent pages.

## YouTube CLI (no UI)

`main.py` is still available for terminal-only YouTube channel/playlist downloads:

```powershell
py .\main.py "https://www.youtube.com/@ChannelName/videos" --parallel 3
```

## Output

- Default output goes to `downloads/` and is grouped by uploader.
- URL archives are split by platform:
  - `downloads/archive.youtube.urls.txt`
  - `downloads/archive.tiktok.urls.txt`
