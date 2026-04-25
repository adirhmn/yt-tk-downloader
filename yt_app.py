import argparse
import json
import hashlib
import shutil
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

try:
    import msvcrt  # type: ignore
except Exception:  # pragma: no cover
    msvcrt = None  # type: ignore


def _json_dumps(obj: Any) -> str:
    # Use ASCII-safe JSON to avoid Windows default stdout encoding (cp1252) issues
    # when titles contain emojis or other non-encodable characters.
    return json.dumps(obj, ensure_ascii=True)


def _sanitize_custom_label(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    # Avoid characters invalid in Windows filenames and path separators.
    bad = '<>:"/\\|?*'
    for ch in bad:
        s = s.replace(ch, "-")
    # Keep it reasonably short.
    s = " ".join(s.split())
    return s[:80].strip() or None


def _detect_platform(url: str) -> str:
    u = url.lower()
    if "tiktok.com" in u:
        return "tiktok"
    if "youtube.com" in u or "youtu.be" in u:
        return "youtube"
    return "other"


def _archive_urls_path(output_dir: Path, platform: str) -> Path:
    safe = platform if platform in ("youtube", "tiktok", "other") else "other"
    return output_dir / f"archive.{safe}.urls.txt"


def _read_archive_urls(path: Path) -> Set[str]:
    if not path.exists():
        return set()
    urls: Set[str] = set()
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        if s:
            urls.add(s)
    return urls


def _append_archive_urls(path: Path, urls: List[str]) -> None:
    if not urls:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    # Use a separate lock file so we can safely append to the archive in multi-process mode.
    with lock_path.open("a+", encoding="utf-8") as lockf:
        if msvcrt is not None:
            try:
                msvcrt.locking(lockf.fileno(), msvcrt.LK_LOCK, 1)
            except Exception:
                pass
        try:
            existing = _read_archive_urls(path)
            with path.open("a", encoding="utf-8") as f:
                for u in urls:
                    if u in existing:
                        continue
                    f.write(u + "\n")
                    existing.add(u)
        finally:
            if msvcrt is not None:
                try:
                    msvcrt.locking(lockf.fileno(), msvcrt.LK_UNLCK, 1)
                except Exception:
                    pass


def _parse_date_iso(value: str) -> date:
    try:
        parts = value.split("-")
        if len(parts) != 3:
            raise ValueError
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except Exception as e:
        raise argparse.ArgumentTypeError("Format tanggal harus YYYY-MM-DD") from e


def _parse_duration_seconds(value: str) -> int:
    s = value.strip()
    if s.isdigit():
        return int(s)
    if ":" in s:
        parts = s.split(":")
        if len(parts) == 2:  # mm:ss
            m, sec = parts
            if m.isdigit() and sec.isdigit():
                return int(m) * 60 + int(sec)
        if len(parts) == 3:  # hh:mm:ss
            h, m, sec = parts
            if h.isdigit() and m.isdigit() and sec.isdigit():
                return int(h) * 3600 + int(m) * 60 + int(sec)
    raise argparse.ArgumentTypeError("Durasi harus detik atau format mm:ss / hh:mm:ss")


def _iso_from_yyyymmdd(value: Optional[str]) -> Optional[str]:
    if not value or not isinstance(value, str):
        return None
    if len(value) != 8 or not value.isdigit():
        return None
    return f"{value[0:4]}-{value[4:6]}-{value[6:8]}"


def _iso_from_timestamp(value: Any) -> Optional[str]:
    try:
        if isinstance(value, (int, float)):
            return datetime.utcfromtimestamp(float(value)).date().isoformat()
        return None
    except Exception:
        return None


def _require_deps() -> None:
    try:
        import yt_dlp  # type: ignore  # noqa: F401
    except Exception:
        raise RuntimeError(
            "Dependency belum terpasang. Jalankan:\n  py -m pip install -r requirements.txt"
        )


def _require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg tidak ditemukan di PATH. Pasang ffmpeg lalu pastikan `where ffmpeg` berhasil."
        )


def _entry_to_url(entry: Dict[str, Any]) -> Optional[str]:
    url = entry.get("webpage_url") or entry.get("url")
    if isinstance(url, str) and url.startswith("http"):
        return url
    video_id = entry.get("id")
    if isinstance(video_id, str) and video_id:
        return f"https://www.youtube.com/watch?v={video_id}"
    if isinstance(url, str) and url:
        return f"https://www.youtube.com/watch?v={url}"
    return None


def _pick_thumbnail(info: Dict[str, Any]) -> Optional[str]:
    thumb = info.get("thumbnail")
    if isinstance(thumb, str) and thumb:
        return thumb
    thumbs = info.get("thumbnails")
    if isinstance(thumbs, list) and thumbs:
        # Prefer the last (often highest res) that has a url.
        for t in reversed(thumbs):
            if isinstance(t, dict):
                u = t.get("url")
                if isinstance(u, str) and u:
                    return u
    return None


def _cache_dir() -> Path:
    return Path(__file__).resolve().parent / ".yt_cache"


def _cache_key(url: str, cookies: Optional[str]) -> str:
    seed = url
    if cookies:
        seed += "\nCOOKIES:" + str(Path(cookies).resolve())
    return hashlib.sha1(seed.encode("utf-8", errors="ignore")).hexdigest()


def _cache_paths(url: str, cookies: Optional[str]) -> Tuple[Path, Path]:
    d = _cache_dir()
    d.mkdir(parents=True, exist_ok=True)
    key = _cache_key(url, cookies)
    return d / f"{key}.jsonl", d / f"{key}.meta.json"


def _load_cache(url: str, cookies: Optional[str]) -> Tuple[Dict[int, Dict[str, Any]], Dict[str, Any]]:
    jsonl_path, meta_path = _cache_paths(url, cookies)
    cached: Dict[int, Dict[str, Any]] = {}
    if jsonl_path.exists():
        for line in jsonl_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                idx = int(row.get("index"))
                entry = row.get("entry")
                if isinstance(entry, dict):
                    cached[idx] = entry
            except Exception:
                continue

    meta: Dict[str, Any] = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            meta = {}
    meta.setdefault("url", url)
    if cookies:
        meta.setdefault("cookies", str(Path(cookies).resolve()))
    meta.setdefault("total_entries", None)
    return cached, meta


def _save_meta(url: str, cookies: Optional[str], meta: Dict[str, Any]) -> None:
    _, meta_path = _cache_paths(url, cookies)
    meta_path.write_text(_json_dumps(meta), encoding="utf-8")


def _append_cache_rows(url: str, cookies: Optional[str], rows: Iterable[Tuple[int, Dict[str, Any]]]) -> None:
    jsonl_path, _ = _cache_paths(url, cookies)
    with jsonl_path.open("a", encoding="utf-8") as f:
        for idx, entry in rows:
            f.write(_json_dumps({"index": idx, "entry": entry}) + "\n")


@dataclass
class ListFilters:
    query: Optional[str]
    exclude_shorts: bool
    min_duration: Optional[int]
    max_duration: Optional[int]
    date_from: Optional[date]
    date_to: Optional[date]


def _matches_filters(info: Dict[str, Any], filters: ListFilters) -> bool:
    title = info.get("title") if isinstance(info.get("title"), str) else ""
    if filters.query:
        if filters.query.lower() not in title.lower():
            return False

    duration = info.get("duration")
    if isinstance(duration, (int, float)):
        dur = int(duration)
    else:
        dur = None

    if filters.exclude_shorts and dur is not None and dur < 60:
        return False
    if filters.min_duration is not None and dur is not None and dur < filters.min_duration:
        return False
    if filters.max_duration is not None and dur is not None and dur > filters.max_duration:
        return False

    upload_iso = _iso_from_yyyymmdd(info.get("upload_date")) or _iso_from_timestamp(info.get("timestamp"))
    if upload_iso and (filters.date_from or filters.date_to):
        y, m, d = upload_iso.split("-")
        up = date(int(y), int(m), int(d))
        if filters.date_from and up < filters.date_from:
            return False
        if filters.date_to and up > filters.date_to:
            return False

    return True


def _build_common_ydl_opts() -> Dict[str, Any]:
    return {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "ignoreerrors": True,
        # Don't depend on yt-dlp cache dir behavior across environments.
        "cachedir": False,
    }


def _entry_slim(vinfo: Dict[str, Any], fallback_url: str) -> Dict[str, Any]:
    upload_iso = _iso_from_yyyymmdd(vinfo.get("upload_date")) or _iso_from_timestamp(vinfo.get("timestamp"))
    return {
        "id": vinfo.get("id"),
        "title": vinfo.get("title"),
        "duration": vinfo.get("duration"),
        "upload_date": upload_iso,
        "thumbnail": _pick_thumbnail(vinfo),
        "url": vinfo.get("webpage_url") or fallback_url,
        "timestamp": vinfo.get("timestamp"),
    }


def _fetch_chunk(
    url: str, start: int, end: int, cookies: Optional[str]
) -> Tuple[List[Tuple[int, Dict[str, Any]]], Optional[int]]:
    """
    Fetch playlist items [start..end] (1-based, inclusive) and return slim entries with their indexes.
    Returns (rows, total_entries_if_known).
    """
    import yt_dlp  # type: ignore

    opts = _build_common_ydl_opts()
    opts.update(
        {
            "skip_download": True,
            "extract_flat": False,
            "playlist_items": f"{start}:{end}",
            "lazy_playlist": True,
        }
    )
    if cookies:
        opts["cookiefile"] = str(Path(cookies).resolve())
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if not isinstance(info, dict):
        return [], None

    total_entries = info.get("playlist_count")
    if not isinstance(total_entries, int):
        total_entries = info.get("n_entries") if isinstance(info.get("n_entries"), int) else None

    entries = info.get("entries")
    if not isinstance(entries, list) or not entries:
        return [], total_entries

    rows: List[Tuple[int, Dict[str, Any]]] = []
    for offset, entry in enumerate(entries):
        idx = start + offset
        if not isinstance(entry, dict):
            continue
        fallback_url = _entry_to_url(entry) or ""
        rows.append((idx, _entry_slim(entry, fallback_url)))
    return rows, total_entries


def cmd_list(args: argparse.Namespace) -> int:
    _require_deps()

    filters = ListFilters(
        query=args.query.strip() if args.query else None,
        exclude_shorts=bool(args.exclude_shorts),
        min_duration=args.min_duration,
        max_duration=args.max_duration,
        date_from=args.date_from,
        date_to=args.date_to,
    )

    page = int(args.page)
    page_size = int(args.page_size)
    if page < 1:
        raise RuntimeError("--page minimal 1")
    if page_size < 1 or page_size > 100:
        raise RuntimeError("--page-size harus 1..100")

    start_index = (page - 1) * page_size
    end_index = start_index + page_size

    cookies = str(args.cookies).strip() if getattr(args, "cookies", None) else None
    cookies = cookies or None

    cached, meta = _load_cache(args.url, cookies)
    total_entries = meta.get("total_entries") if isinstance(meta.get("total_entries"), int) else None

    no_filters = (
        (not filters.query)
        and (not filters.exclude_shorts)
        and (filters.min_duration is None)
        and (filters.max_duration is None)
        and (filters.date_from is None)
        and (filters.date_to is None)
    )

    if no_filters:
        start_item = start_index + 1
        end_item = end_index

        missing = [i for i in range(start_item, end_item + 1) if i not in cached]
        if missing:
            rows, maybe_total = _fetch_chunk(args.url, start_item, end_item, cookies)
            if maybe_total is not None:
                total_entries = maybe_total
                meta["total_entries"] = maybe_total
                _save_meta(args.url, cookies, meta)
            for idx, entry in rows:
                cached[idx] = entry
            _append_cache_rows(args.url, cookies, rows)

        items: List[Dict[str, Any]] = []
        for i in range(start_item, end_item + 1):
            e = cached.get(i)
            if not e:
                continue
            items.append(
                {
                    "id": e.get("id"),
                    "title": e.get("title"),
                    "duration": e.get("duration"),
                    "upload_date": e.get("upload_date"),
                    "thumbnail": e.get("thumbnail"),
                    "url": e.get("url"),
                }
            )

        if total_entries is not None:
            has_more = end_item < total_entries
        else:
            probe_index = end_item + 1
            if probe_index not in cached:
                rows2, maybe_total2 = _fetch_chunk(args.url, probe_index, probe_index, cookies)
                if maybe_total2 is not None:
                    total_entries = maybe_total2
                    meta["total_entries"] = maybe_total2
                    _save_meta(args.url, cookies, meta)
                for idx, entry in rows2:
                    cached[idx] = entry
                _append_cache_rows(args.url, cookies, rows2)
            has_more = probe_index in cached

        payload = {
            "page": page,
            "page_size": page_size,
            "items": items,
            "has_more": bool(has_more),
        }
        print(_json_dumps(payload))
        return 0

    results: List[Dict[str, Any]] = []
    matched = 0
    has_more = False
    scanned = 0

    # With filters, we may need to scan more items; fetch metadata in chunks and cache it.
    chunk_size = 60
    idx = 1
    want_more_index = end_index + 1
    while True:
        if total_entries is not None and idx > total_entries:
            break
        if idx not in cached:
            rows, maybe_total = _fetch_chunk(args.url, idx, idx + chunk_size - 1, cookies)
            if maybe_total is not None and total_entries is None:
                total_entries = maybe_total
                meta["total_entries"] = maybe_total
                _save_meta(args.url, cookies, meta)
            if not rows:
                break
            for i, e in rows:
                cached[i] = e
            _append_cache_rows(args.url, cookies, rows)

        entry = cached.get(idx)
        idx += 1
        scanned += 1
        if not entry:
            continue

        if not _matches_filters(entry, filters):
            continue

        if matched >= want_more_index:
            has_more = True
            break

        if matched >= start_index and matched < end_index:
            results.append(
                {
                    "id": entry.get("id"),
                    "title": entry.get("title"),
                    "duration": entry.get("duration"),
                    "upload_date": entry.get("upload_date"),
                    "thumbnail": entry.get("thumbnail"),
                    "url": entry.get("url"),
                }
            )
        matched += 1

    payload = {
        "page": page,
        "page_size": page_size,
        "items": results,
        "has_more": has_more,
        "scanned_entries": scanned,
        "cached_entries": len(cached),
    }
    print(_json_dumps(payload))
    return 0


def _progress_hook(json_mode: bool):
    def hook(d: Dict[str, Any]) -> None:
        if not json_mode:
            return
        status = d.get("status")
        if status == "downloading":
            downloaded = d.get("downloaded_bytes") or 0
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            percent: Optional[float]
            if total:
                percent = float(downloaded) / float(total) * 100.0
            else:
                # Some formats (HLS/DASH/fragments) don't report total bytes.
                # Fall back to fragment progress if available.
                frag_idx = d.get("fragment_index")
                frag_count = d.get("fragment_count")
                if isinstance(frag_idx, int) and isinstance(frag_count, int) and frag_count > 0:
                    percent = float(frag_idx) / float(frag_count) * 100.0
                else:
                    percent = None
            info = d.get("info_dict") or {}
            evt = {
                "type": "progress",
                "id": info.get("id"),
                "title": info.get("title"),
                "percent": percent,
                "downloaded_bytes": downloaded,
                "total_bytes": total,
                "speed": d.get("speed"),
                "eta": d.get("eta"),
                "fragment_index": d.get("fragment_index"),
                "fragment_count": d.get("fragment_count"),
            }
            sys.stdout.write(_json_dumps(evt) + "\n")
            sys.stdout.flush()
        elif status == "finished":
            info = d.get("info_dict") or {}
            evt = {"type": "finished", "id": info.get("id"), "title": info.get("title")}
            sys.stdout.write(_json_dumps(evt) + "\n")
            sys.stdout.flush()

    return hook


def cmd_download(args: argparse.Namespace) -> int:
    _require_deps()
    _require_ffmpeg()
    import yt_dlp  # type: ignore

    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    custom_label = _sanitize_custom_label(getattr(args, "custom", None))
    if custom_label:
        filename_tmpl = f"%(upload_date)s_{custom_label}_%(title)s.%(ext)s"
    else:
        filename_tmpl = "%(upload_date)s - %(title)s [%(id)s].%(ext)s"

    outtmpl = {"default": str(output_dir / "%(uploader)s" / filename_tmpl)}

    json_mode = bool(args.json_progress)

    ydl_opts: Dict[str, Any] = {
        "outtmpl": outtmpl,
        "paths": {"home": str(output_dir)},
        "ignoreerrors": False,
        # When json_progress is enabled, suppress yt-dlp's own progress output
        # (it uses carriage-returns) so stdout stays JSON-only for Electron to parse.
        "quiet": json_mode,
        "no_warnings": json_mode,
        "noprogress": True if json_mode else False,
        "retries": 10,
        "fragment_retries": 10,
        "concurrent_fragment_downloads": 1,
        "continuedl": True,
        "overwrites": False,
        "sleep_interval": 1,
        "max_sleep_interval": 5,
        "progress_hooks": [_progress_hook(json_mode)],
    }
    if getattr(args, "cookies", None):
        ydl_opts["cookiefile"] = str(Path(args.cookies).resolve())

    if args.audio_only:
        ydl_opts["format"] = "bestaudio/best"
        ydl_opts["postprocessors"] = [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "0"}
        ]
    else:
        # Prefer MP4 + AAC/m4a for Windows player compatibility.
        ydl_opts["format"] = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
        ydl_opts["merge_output_format"] = "mp4"

    if args.subtitles:
        ydl_opts["writesubtitles"] = True
        ydl_opts["writeautomaticsub"] = True
        ydl_opts["subtitleslangs"] = ["id", "en.*"]
        ydl_opts["subtitlesformat"] = "vtt/best"

    urls: List[str] = list(args.urls)
    if not urls:
        return 0

    # Separate URL-based archives per platform (youtube/tiktok) as requested.
    # This is independent from yt-dlp's built-in download_archive (which stores ids).
    platform = _detect_platform(urls[0])
    archive_urls_file = _archive_urls_path(output_dir, platform)
    already = _read_archive_urls(archive_urls_file)
    todo = [u for u in urls if u not in already]

    if json_mode:
        sys.stdout.write(_json_dumps({"type": "start", "count": len(todo), "skipped": len(urls) - len(todo)}) + "\n")
        sys.stdout.flush()

    succeeded: List[str] = []
    code = 0
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for u in todo:
            try:
                rc = int(ydl.download([u]))
            except Exception as e:
                rc = 1
                code = 1
                if json_mode:
                    sys.stdout.write(_json_dumps({"type": "error", "url": u, "message": str(e)}) + "\n")
                    sys.stdout.flush()
            if rc == 0:
                succeeded.append(u)
            else:
                code = 1

    _append_archive_urls(archive_urls_file, succeeded)

    if json_mode:
        sys.stdout.write(_json_dumps({"type": "end", "code": code}) + "\n")
        sys.stdout.flush()
    return code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt_app",
        description="Backend helper untuk UI (list video + download) berbasis yt-dlp.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List video dengan filter + pagination (JSON).")
    p_list.add_argument("url", help="URL channel/playlist (mis. https://www.youtube.com/@NamaChannel/videos)")
    p_list.add_argument("--page", type=int, default=1, help="Halaman (1-based).")
    p_list.add_argument("--page-size", type=int, default=20, help="Jumlah item per halaman.")
    p_list.add_argument("--query", default=None, help="Filter judul (substring, case-insensitive).")
    p_list.add_argument("--exclude-shorts", action="store_true", help="Exclude Shorts (durasi < 60s).")
    p_list.add_argument("--min-duration", type=_parse_duration_seconds, default=None, help="Durasi minimum.")
    p_list.add_argument("--max-duration", type=_parse_duration_seconds, default=None, help="Durasi maksimum.")
    p_list.add_argument("--date-from", type=_parse_date_iso, default=None, help="Tanggal upload dari (YYYY-MM-DD).")
    p_list.add_argument("--date-to", type=_parse_date_iso, default=None, help="Tanggal upload sampai (YYYY-MM-DD).")
    p_list.add_argument("--cookies", default=None, help="Path cookies.txt (opsional).")
    p_list.set_defaults(func=cmd_list)

    p_dl = sub.add_parser("download", help="Download satu/lebih video (opsional JSON progress).")
    p_dl.add_argument("urls", nargs="+", help="Satu atau lebih URL video.")
    p_dl.add_argument("-o", "--output", default="downloads", help="Folder output utama.")
    p_dl.add_argument("--audio-only", action="store_true", help="Audio saja (mp3).")
    p_dl.add_argument("--subtitles", action="store_true", help="Subtitles (auto + manual) jika ada.")
    p_dl.add_argument(
        "--custom",
        default=None,
        help='Tambahkan label custom ke nama file: "(tanggal)_CUSTOM_(judul)". Jika kosong, pakai default.',
    )
    p_dl.add_argument("--cookies", default=None, help="Path cookies.txt (opsional).")
    p_dl.add_argument("--json-progress", action="store_true", help="Output progress sebagai JSON lines.")
    p_dl.set_defaults(func=cmd_download)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except Exception as e:
        sys.stderr.write(f"{e}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
