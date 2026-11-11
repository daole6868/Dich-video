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
