"""Tải video từ liên kết bằng yt-dlp (YouTube, Bilibili, Douyin, liên kết tệp trực tiếp…).

Chỉ tải những video bạn có quyền sử dụng.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from pathlib import Path
from typing import Callable

from . import config, ffmpeg, projects

log = logging.getLogger(__name__)

URL_RE = re.compile(r"^https?://[^\s]+$", re.I)


class DownloadError(RuntimeError):
    pass


class _Stop(Exception):
    pass


class _Quiet:
    """yt-dlp tự in lỗi ra màn hình; gom về nhật ký của ứng dụng cho gọn."""

    def debug(self, msg: str) -> None:
        pass

    def info(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        log.info("yt-dlp: %s", msg)

    def error(self, msg: str) -> None:
        log.warning("yt-dlp: %s", msg)


def check_url(url: str) -> str:
    url = (url or "").strip()
    if not URL_RE.match(url):
        raise DownloadError("Liên kết không hợp lệ. Hãy dán địa chỉ bắt đầu bằng http:// hoặc https://")
    return url


def download(url: str, dest_dir: str | os.PathLike, *,
             progress: Callable[[float, str], None] | None = None,
             cancel: threading.Event | None = None, max_height: int = 1080) -> dict:
    """Tải video về ``dest_dir/source.<đuôi>``. Trả về ``{"path", "title"}``."""
    url = check_url(url)
    try:
        import yt_dlp
    except ImportError as e:
        raise DownloadError("Chưa cài thư viện yt-dlp. Hãy chạy lại tệp khởi động để cài đủ thư viện.") from e
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    def hook(d: dict) -> None:
        if cancel is not None and cancel.is_set():
            raise _Stop()
        if progress and d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            if total:
                progress(min(0.98, done / total), f"Đang tải video… {done / 1e6:.0f}/{total / 1e6:.0f} MB")
            else:
                progress(0.0, f"Đang tải video… {done / 1e6:.0f} MB")

    opts = {
        "outtmpl": str(dest / "source.%(ext)s"),
        "format": f"bv*[height<={max_height}]+ba/b[height<={max_height}]/bv*+ba/b",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "retries": 3,
        "fragment_retries": 3,
        "overwrites": True,
        "progress_hooks": [hook],
        "logger": _Quiet(),
        "ffmpeg_location": ffmpeg.ffmpeg_path(),
        "cachedir": str(config.DATA_DIR / "cache" / "yt-dlp"),  # mặc định là ~/.cache/yt-dlp
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except _Stop as e:
        raise ffmpeg.Cancelled() from e
    except Exception as e:  # noqa: BLE001 - yt-dlp ném nhiều loại lỗi khác nhau
        if cancel is not None and cancel.is_set():
            raise ffmpeg.Cancelled() from e
        msg = re.sub(r"\x1b\[[0-9;]*m", "", str(e)).replace("ERROR: ", "").strip()
        raise DownloadError(
            "Không tải được video từ liên kết này. Một số trang cần đăng nhập hoặc chặn tải tự động; "
            f"bạn có thể tải video về máy rồi dùng nút 'Chọn tệp'. Chi tiết: {msg[:300]}") from e
    files = [p for p in dest.glob("source.*") if p.suffix.lower() in projects.VIDEO_EXT | projects.AUDIO_EXT]
    if not files:
        raise DownloadError("Tải xong nhưng không thấy tệp video. Liên kết có thể không chứa video.")
    path = max(files, key=lambda p: p.stat().st_size)
    title = ""
    if isinstance(info, dict):
        title = str(info.get("title") or "")
    if progress:
        progress(1.0, "Đã tải xong video")
    return {"path": path, "title": title}
