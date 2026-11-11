"""Thao tác tệp chịu được kiểu khoá tệp của Windows.

Trên Linux/macOS, ghi đè hay xoá một tệp đang mở luôn thành công. Trên Windows thì không: tệp đang
được một chương trình khác mở (phần mềm diệt virus đang quét, trình phát video đang đọc…) sẽ làm
``os.replace`` / ``os.remove`` ném ``PermissionError``. Phần lớn các lần giữ tệp như vậy chỉ kéo dài
vài phần nghìn giây, nên các hàm ở đây thử lại trong chốc lát rồi mới báo lỗi.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path


def _retry(action, wait: float) -> None:
    end = time.monotonic() + max(0.0, wait)
    delay = 0.02
    while True:
        try:
            action()
            return
        except PermissionError:
            if time.monotonic() >= end:
                raise
            time.sleep(delay)
            delay = min(0.25, delay * 2)


def replace(src: str | os.PathLike, dst: str | os.PathLike, wait: float = 3.0) -> None:
    """Như ``os.replace`` nhưng thử lại tối đa ``wait`` giây khi tệp đích đang bị giữ."""
    _retry(lambda: os.replace(src, dst), wait)


def remove(path: str | os.PathLike, wait: float = 0.5) -> bool:
    """Xoá tệp nếu có. Trả ``False`` (không ném lỗi) khi không xoá được."""
    def action() -> None:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass

    try:
        _retry(action, wait)
        return True
    except OSError:
        return False


def remove_tree(path: str | os.PathLike, wait: float = 2.0) -> bool:
    """Xoá cả thư mục; thử lại khi còn tệp bị giữ. Trả ``True`` nếu thư mục đã biến mất."""
    path = Path(path)
    end = time.monotonic() + max(0.0, wait)
    while True:
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            return True
        if time.monotonic() >= end:
            return False
        time.sleep(0.2)


# --------------------------------------------------------------------------
# Đường dẫn có dấu trên Windows
# --------------------------------------------------------------------------

def _short_path(path: str) -> str | None:
    """Tên ngắn kiểu 8.3 của Windows (``C:\\NGIDNG~1\\...``), nếu ổ đĩa có tạo tên ngắn."""
    import ctypes
    from ctypes import wintypes

    fn = ctypes.windll.kernel32.GetShortPathNameW  # type: ignore[attr-defined]
    fn.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    fn.restype = wintypes.DWORD
    buf = ctypes.create_unicode_buffer(32768)
    n = fn(path, buf, len(buf))
    return buf.value if 0 < n < len(buf) else None


def _alias_roots() -> list[Path]:
    roots = []
    for var in ("ProgramData", "PUBLIC"):
        base = os.environ.get(var, "")
        if base and base.isascii() and os.path.isdir(base):
            roots.append(Path(base) / "DichVideoStudio" / "lien-ket")
    return roots


def _make_junction(target: str, link: str) -> None:
    try:
        import _winapi

        _winapi.CreateJunction(target, link)  # type: ignore[attr-defined]
    except (ImportError, AttributeError, OSError):
        import subprocess

        done = subprocess.run(["cmd", "/d", "/c", "mklink", "/J", link, target], capture_output=True,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if done.returncode != 0:
            raise OSError("không tạo được lối tắt thư mục (mklink /J)") from None


def _junction_alias(target: str) -> str | None:
    """Tạo (hoặc dùng lại) một lối tắt thư mục có tên toàn ký tự ASCII trỏ tới ``target``."""
    import hashlib

    name = hashlib.sha1(os.path.normcase(target).encode("utf-8")).hexdigest()[:16]
    for root in _alias_roots():
        link = root / name
        try:
            root.mkdir(parents=True, exist_ok=True)
            if os.path.lexists(link):
                try:
                    if os.path.samefile(link, target):
                        return str(link)
                except OSError:
                    pass
                os.rmdir(link)  # chỉ gỡ lối tắt cũ, không đụng tới thư mục đích
            _make_junction(target, str(link))
            if os.path.samefile(link, target):
                return str(link)
        except OSError:
            continue
    return None


def native_path(path: str | os.PathLike) -> str:
    """Đường dẫn tương đương mà thư viện gốc chỉ hiểu chuỗi ANSI trên Windows mở được.

    Vài thư viện C (espeak trong Piper, có phiên bản CTranslate2) mở tệp bằng hàm không hỗ trợ Unicode
    trên Windows, nên thư mục có dấu tiếng Việt làm chúng không tìm thấy tệp. Hàm này trả về một đường
    dẫn chỉ gồm ký tự ASCII trỏ tới cùng chỗ: tên ngắn 8.3 nếu ổ đĩa có, không thì một lối tắt thư mục
    (junction) đặt trong ``C:\\ProgramData\\DichVideoStudio``. Trên Linux/macOS, hoặc khi đường dẫn vốn
    không có dấu, trả lại nguyên đường dẫn.
    """
    full = os.path.abspath(os.fspath(path))
    if os.name != "nt" or full.isascii():
        return full
    try:
        short = _short_path(full)
    except OSError:
        short = None
    if short and short.isascii() and os.path.exists(short):
        return short
    is_dir = os.path.isdir(full)
    target, tail = (full, "") if is_dir else os.path.split(full)
    if tail.isascii():
        alias = _junction_alias(target)
        if alias:
            return os.path.join(alias, tail) if tail else alias
    raise RuntimeError(
        f"Thư mục “{target}” có ký tự có dấu mà một thư viện xử lý không đọc được trên Windows, và ứng dụng "
        "không tạo được đường dẫn thay thế. Hãy chuyển thư mục ứng dụng tới một đường dẫn không dấu, "
        "ví dụ C:\\DichVideoStudio, rồi chạy lại.")
