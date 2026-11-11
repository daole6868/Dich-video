"""Google Dịch qua cổng công khai miễn phí (không cần khoá API).

Đây là cổng không chính thức và có giới hạn tần suất. Mô-đun gọi thưa, gom nhiều câu
vào một yêu cầu, và khi máy chủ báo quá tải (429) thì chờ đúng thời gian được yêu cầu
rồi mới thử lại; hết số lần thử thì báo lỗi rõ ràng thay vì cố vượt giới hạn.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

import requests

from ..ffmpeg import Cancelled
from .errors import TranslateError

log = logging.getLogger(__name__)

ENDPOINT = "https://translate.googleapis.com/translate_a/single"
LANG_CODES = {"zh": "zh-CN", "yue": "yue", "auto": "auto", "en": "en", "ja": "ja", "ko": "ko"}
MAX_CHARS = 420  # mỗi yêu cầu GET: chữ Hán mã hoá URL dài gấp 9 lần nên giữ lô nhỏ
PAUSE = 0.4  # giây nghỉ giữa hai yêu cầu
MAX_ATTEMPTS = 5

_session = requests.Session()
_pace_lock = threading.Lock()
_last_call = 0.0


def _wait(seconds: float, cancel: threading.Event | None) -> None:
    if cancel is not None:
        if cancel.wait(seconds):
            raise Cancelled()
    else:
        time.sleep(seconds)


def _request(text: str, source: str, target: str, cancel: threading.Event | None,
             notify: Callable[[str], None] | None = None) -> str:
    global _last_call
    params = {"client": "gtx", "sl": LANG_CODES.get(source, source), "tl": target, "dt": "t", "q": text}
    last = ""
    for attempt in range(MAX_ATTEMPTS):
        with _pace_lock:
            gap = PAUSE - (time.monotonic() - _last_call)
            if gap > 0:
                _wait(gap, cancel)
            _last_call = time.monotonic()
        try:
            r = _session.get(ENDPOINT, params=params, timeout=30)
        except requests.RequestException as e:
            last = f"lỗi mạng: {type(e).__name__}"
            _wait(min(30, 3 * (attempt + 1)), cancel)
            continue
        if r.status_code == 200:
            try:
                data = r.json()
                return "".join(part[0] for part in data[0] if part and part[0])
            except (ValueError, TypeError, IndexError):
                last = "phản hồi không đọc được"
                _wait(2, cancel)
                continue
        if r.status_code in (429, 500, 502, 503, 504):
            try:
                delay = float(r.headers.get("Retry-After", ""))
            except ValueError:
                delay = 8.0 * (2 ** attempt)
            delay = max(2.0, min(delay, 180.0))
            last = f"máy chủ báo {r.status_code}"
            if attempt < MAX_ATTEMPTS - 1:
                if notify:
                    notify(f"Google Dịch đang giới hạn tần suất, chờ {delay:.0f} giây…")
                log.warning("Google Dịch trả %s, chờ %.0f giây", r.status_code, delay)
                _wait(delay, cancel)
            continue
        raise TranslateError(f"Google Dịch trả lỗi {r.status_code}: {r.text[:200]}")
    raise TranslateError(
        "Google Dịch miễn phí đang giới hạn tần suất hoặc không truy cập được (" + last + "). "
        "Hãy thử lại sau ít phút, hoặc chọn một bộ dịch AI (cần khoá API) trong phần Dịch."
    )


def translate_lines(lines: list[str], source: str = "zh", target: str = "vi", *,
                    cancel: threading.Event | None = None,
                    progress: Callable[[int], None] | None = None,
                    notify: Callable[[str], None] | None = None) -> list[str]:
    """Dịch danh sách câu, giữ đúng thứ tự và số lượng."""
    out: list[str] = [""] * len(lines)
    batch: list[int] = []
    size = 0

    def flush() -> None:
        nonlocal batch, size
        if not batch:
            return
        texts = [" ".join(lines[i].split()) for i in batch]
        result = None
        if len(batch) > 1:
            joined = _request("\n".join(texts), source, target, cancel, notify)
            parts = [p.strip() for p in joined.split("\n")]
            if len(parts) == len(batch) and all(parts):
                result = parts
        if result is None:  # số dòng trả về lệch: dịch từng câu để không ghép nhầm
            result = [_request(t, source, target, cancel, notify).strip() for t in texts]
        for i, vi in zip(batch, result):
            out[i] = vi
        if progress:
            progress(len(batch))
        batch, size = [], 0

    for i, line in enumerate(lines):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        text = " ".join((line or "").split())
        if not text:
            if progress:
                progress(1)
            continue
        if batch and size + len(text) + 1 > MAX_CHARS:
            flush()
        batch.append(i)
        size += len(text) + 1
    flush()
    return out
