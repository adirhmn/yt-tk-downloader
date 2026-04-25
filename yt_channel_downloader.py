import argparse
import os
import shutil
import sys
import threading
from typing import Optional
from queue import Queue
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt_channel_downloader",
        description=(
            "Download video dari sebuah channel/playlist menggunakan yt-dlp.\n"
            "Gunakan hanya untuk konten yang kamu miliki atau punya izin untuk diunduh."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "url",
        help=(
            "URL channel (atau tab /videos), playlist, atau user handle.\n"
            "Contoh: https://www.youtube.com/@NamaChannel/videos"
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        default="downloads",
        help="Folder output utama.",
    )
    parser.add_argument(
        "--format",
        default="bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        help="Format selector yt-dlp.",
    )
    parser.add_argument(
        "--audio-only",
        action="store_true",
        help="Download audio saja (extract ke mp3).",
    )
    parser.add_argument(
        "--subtitles",
        action="store_true",
        help="Download subtitles (auto + manual) jika tersedia.",
    )
    parser.add_argument(
        "--sub-lang",
        default="id,en.*",
        help="Bahasa subtitle (yt-dlp --sub-langs).",
    )
    parser.add_argument(
        "--cookies",
        default=None,
        help="Path ke cookies.txt (opsional, untuk konten yang butuh login).",
    )
    parser.add_argument(
        "--archive",
        default=None,
        help="File download archive (untuk skip yang sudah pernah diunduh). Default dibuat di folder output.",
    )
    parser.add_argument(
        "--custom",
        default=None,
        help='Tambahkan label custom ke nama file: "(tanggal)_CUSTOM_(judul)". Jika kosong, pakai default.',
    )
    parser.add_argument(
        "--playlist-start",
        type=int,
        default=1,
        help="Mulai dari item ke-N (1-based).",
    )
    parser.add_argument(
        "--playlist-end",
        type=int,
        default=None,
        help="Berhenti di item ke-N (1-based).",
    )
    parser.add_argument(
        "--max-downloads",
        type=int,
        default=None,
        help="Batasi jumlah video yang diunduh pada run ini.",
    )
    parser.add_argument(
        "--rate-limit",
        default=None,
        help="Batasi kecepatan download, mis. 2M, 500K.",
    )
    parser.add_argument(
        "--sleep-interval",
        type=int,
        default=1,
        help="Jeda minimal antar download (detik).",
    )
    parser.add_argument(
        "--max-sleep-interval",
        type=int,
        default=5,
        help="Jeda maksimal antar download (detik).",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=10,
        help="Jumlah retry.",
    )
    parser.add_argument(
        "--concurrent-fragments",
        type=int,
        default=1,
        help="Jumlah fragmen paralel (lebih kecil biasanya lebih ramah jaringan).",
    )
    parser.add_argument(
        "--parallel",
        type=int,
        default=1,
        help="Jumlah video yang diunduh paralel (default 1).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Cek daftar video tanpa download.",
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        import yt_dlp  # type: ignore
    except Exception:
        print(
            "Dependency belum terpasang. Jalankan:\n"
            "  py -m pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 2

    has_ffmpeg = shutil.which("ffmpeg") is not None
    if not has_ffmpeg:
        print(
            "Error: ffmpeg tidak ditemukan di PATH. Script ini membutuhkan ffmpeg.\n"
            "Pasang ffmpeg lalu pastikan perintah ini jalan:\n"
            "  where ffmpeg",
            file=sys.stderr,
        )
        return 3
    if args.parallel < 1:
        print("Error: --parallel minimal 1", file=sys.stderr)
        return 2

    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    archive_file = Path(args.archive).resolve() if args.archive else output_dir / "archive.txt"

    custom_label = None
    if args.custom is not None:
        s = str(args.custom).strip()
        if s:
            bad = '<>:"/\\|?*'
            for ch in bad:
                s = s.replace(ch, "-")
            s = " ".join(s.split())
            custom_label = (s[:80].strip() or None)

    if custom_label:
        filename_tmpl = f"%(upload_date)s_{custom_label}_%(title)s.%(ext)s"
    else:
        filename_tmpl = "%(upload_date)s - %(title)s [%(id)s].%(ext)s"

    outtmpl = {
        "default": str(
            output_dir
            / "%(uploader)s"
            / filename_tmpl
        )
    }

    ydl_opts: dict = {
        "outtmpl": outtmpl,
        "paths": {"home": str(output_dir)},
        "ignoreerrors": True,
        "noprogress": False,
        "retries": args.retries,
        "fragment_retries": args.retries,
        "concurrent_fragment_downloads": args.concurrent_fragments,
        "download_archive": str(archive_file),
        "continuedl": True,
        "overwrites": False,
        "playliststart": args.playlist_start,
        "sleep_interval": args.sleep_interval,
        "max_sleep_interval": args.max_sleep_interval,
        "ratelimit": args.rate_limit,
    }

    if args.playlist_end is not None:
        ydl_opts["playlistend"] = args.playlist_end

    if args.max_downloads is not None:
        ydl_opts["max_downloads"] = args.max_downloads

    if args.cookies:
        ydl_opts["cookiefile"] = str(Path(args.cookies).resolve())

    if args.audio_only:
        ydl_opts["format"] = "bestaudio/best"
        ydl_opts["postprocessors"] = [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "0"}
        ]
    else:
        ydl_opts["format"] = args.format
        ydl_opts["merge_output_format"] = "mp4"

    if args.subtitles:
        ydl_opts["writesubtitles"] = True
        ydl_opts["writeautomaticsub"] = True
        ydl_opts["subtitleslangs"] = [lang.strip() for lang in args.sub_lang.split(",") if lang.strip()]
        ydl_opts["subtitlesformat"] = "vtt/best"

    if args.dry_run:
        ydl_opts["skip_download"] = True

    # Make Windows console a bit more robust for non-ascii titles.
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        except Exception:
            pass

    def _entry_to_url(entry: dict) -> Optional[str]:
        url = entry.get("webpage_url") or entry.get("url")
        if isinstance(url, str) and url.startswith("http"):
            return url
        video_id = entry.get("id")
        if isinstance(video_id, str) and video_id:
            return f"https://www.youtube.com/watch?v={video_id}"
        if isinstance(url, str) and url:
            # Best effort: treat as id-ish value
            return f"https://www.youtube.com/watch?v={url}"
        return None

    if args.parallel == 1:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.download([args.url])
            return int(result)

    # Parallel download: ambil daftar video dulu, lalu unduh beberapa URL sekaligus.
    list_opts = dict(ydl_opts)
    list_opts.update(
        {
            "skip_download": True,
            "extract_flat": "in_playlist",
            "quiet": True,
            "noprogress": True,
        }
    )
    with yt_dlp.YoutubeDL(list_opts) as ydl:
        info = ydl.extract_info(args.url, download=False)

    entries: list = []
    if isinstance(info, dict) and "entries" in info:
        entries = list(info.get("entries") or [])
    elif isinstance(info, dict):
        entries = [info]
    else:
        print("Error: tidak bisa membaca daftar video dari URL tersebut.", file=sys.stderr)
        return 1

    video_urls: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        u = _entry_to_url(entry)
        if u:
            video_urls.append(u)

    if args.max_downloads is not None:
        video_urls = video_urls[: args.max_downloads]

    if not video_urls:
        print("Tidak ada video untuk diunduh.", file=sys.stderr)
        return 0

    # Seed archive per worker untuk menghindari race saat menulis archive.
    archive_file.parent.mkdir(parents=True, exist_ok=True)
    if archive_file.exists():
        seed_text = archive_file.read_text(encoding="utf-8", errors="ignore")
    else:
        seed_text = ""
        archive_file.write_text("", encoding="utf-8")

    worker_archives: list[Path] = []
    for i in range(args.parallel):
        worker_archive = archive_file.parent / f"{archive_file.stem}.worker{i}{archive_file.suffix}"
        worker_archive.write_text(seed_text, encoding="utf-8")
        worker_archives.append(worker_archive)

    jobs: list[Queue[Optional[str]]] = [Queue() for _ in range(args.parallel)]
    for idx, url in enumerate(video_urls):
        jobs[idx % args.parallel].put(url)
    for q in jobs:
        q.put(None)

    results_lock = threading.Lock()
    any_failures = False
    completed = 0
    total = len(video_urls)

    def worker(worker_idx: int) -> None:
        nonlocal any_failures, completed
        worker_opts = dict(ydl_opts)
        worker_opts["download_archive"] = str(worker_archives[worker_idx])
        # Progress output paralel cenderung berantakan; matikan progress bar.
        worker_opts["noprogress"] = True

        with yt_dlp.YoutubeDL(worker_opts) as ydl:
            while True:
                item = jobs[worker_idx].get()
                if item is None:
                    return
                url = item
                try:
                    print(f"[{worker_idx+1}/{args.parallel}] Download: {url}")
                    code = int(ydl.download([url]))
                except Exception:
                    code = 1
                with results_lock:
                    completed += 1
                    if code != 0:
                        any_failures = True
                    print(f"Progress: {completed}/{total}")

    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(args.parallel)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Merge archive: gabungkan entri unik dari seluruh worker, lalu bersihkan file worker.
    base_lines: list[str] = []
    base_set: set[str] = set()
    if archive_file.exists():
        for line in archive_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            s = line.strip()
            if not s:
                continue
            base_lines.append(s)
            base_set.add(s)

    for wa in worker_archives:
        if not wa.exists():
            continue
        for line in wa.read_text(encoding="utf-8", errors="ignore").splitlines():
            s = line.strip()
            if not s or s in base_set:
                continue
            base_lines.append(s)
            base_set.add(s)
        try:
            wa.unlink(missing_ok=True)
        except Exception:
            pass

    archive_file.write_text("\n".join(base_lines) + ("\n" if base_lines else ""), encoding="utf-8")

    return 1 if any_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
