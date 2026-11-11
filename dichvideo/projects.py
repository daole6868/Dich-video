"""Kho dự án: mỗi dự án là một thư mục trong ``data/projects/<id>/``.

    project.json   thông tin, cài đặt, trạng thái từng bước
    segments.json  danh sách câu phụ đề
    source.*       video gốc
    thumb.jpg      ảnh thu nhỏ
    work/          tệp trung gian (âm thanh tách ra, bộ đệm giọng đọc…)
    output/        kết quả cho người dùng tải về
    log.txt        nhật ký xử lý
"""

from __future__ import annotations

import copy
import datetime as dt
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Callable

from . import config, fileops, subtitles

STEPS = ["prepare", "transcribe", "translate", "dub", "render"]
STEP_NAMES = {
    "prepare": "Chuẩn bị", "transcribe": "Nhận dạng lời thoại", "translate": "Dịch",
    "dub": "Lồng tiếng", "render": "Xuất video",
}
ID_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")
VIDEO_EXT = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".m4v", ".ts", ".mpg", ".mpeg", ".3gp"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"}

_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


class ProjectError(Exception):
    """Lỗi có thông điệp hiển thị cho người dùng (kèm mã HTTP gợi ý)."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _lock(pid: str) -> threading.RLock:
    with _locks_guard:
        return _locks.setdefault(pid, threading.RLock())


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def check_id(pid: str) -> str:
    if not isinstance(pid, str) or not ID_RE.match(pid):
        raise ProjectError("Mã dự án không hợp lệ.", 404)
    return pid


def project_dir(pid: str) -> Path:
    return config.PROJECTS_DIR / check_id(pid)


def safe_name(name: str, fallback: str = "video") -> str:
    """Tên tệp an toàn trên mọi hệ điều hành, vẫn giữ được tiếng Việt và chữ Hán."""
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", name or "")
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:80].rstrip(" .") or fallback


def blank_steps() -> dict:
    return {s: {"status": "pending", "progress": 0.0, "message": "", "error": "", "info": {}} for s in STEPS}


def create(name: str, original_name: str, *, kind: str = "upload", url: str = "",
           settings: dict | None = None) -> dict:
    """Tạo khung dự án (chưa có tệp nguồn). Trả về dữ liệu dự án."""
    config.ensure_dirs()
    ext = Path(original_name).suffix.lower()
    if kind == "upload" and ext not in VIDEO_EXT | AUDIO_EXT:
        raise ProjectError(f"Định dạng '{ext or original_name}' không được hỗ trợ. "
                           "Hãy dùng tệp video (mp4, mkv, mov, avi, webm…) hoặc âm thanh (mp3, wav, m4a…).")
    for _ in range(20):
        pid = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)
        d = config.PROJECTS_DIR / pid
        if not d.exists():
            break
    d.mkdir(parents=True)
    (d / "work").mkdir()
    (d / "output").mkdir()
    base = config.new_project_settings()
    data = {
        "id": pid,
        "name": safe_name(name or Path(original_name).stem, "Dự án mới"),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "source": {"kind": kind, "file": f"source{ext or '.mp4'}", "original_name": original_name,
                   "url": url, "ready": False},
        "media": {},
        "settings": config.conform_project_settings(config.deep_merge(base, settings or {})),
        "steps": blank_steps(),
        "outputs": {},
        "counts": {"segments": 0, "translated": 0},
    }
    config.write_json_atomic(d / "project.json", data)
    config.write_json_atomic(d / "segments.json", [])
    return data


def load(pid: str) -> dict:
    d = project_dir(pid)
    with _lock(pid):
        data = config.read_json(d / "project.json")
    if not isinstance(data, dict):
        raise ProjectError("Không tìm thấy dự án.", 404)
    return data


def update(pid: str, fn: Callable[[dict], Any]) -> dict:
    """Đọc - sửa - ghi dự án trong một khoá để các luồng không ghi đè lên nhau."""
    d = project_dir(pid)
    with _lock(pid):
        data = config.read_json(d / "project.json")
        if not isinstance(data, dict):
            raise ProjectError("Không tìm thấy dự án.", 404)
        fn(data)
        data["updated_at"] = now_iso()
        config.write_json_atomic(d / "project.json", data)
        return copy.deepcopy(data)


def source_path(data: dict) -> Path:
    return project_dir(data["id"]) / Path(data["source"]["file"]).name


def list_all() -> list[dict]:
    config.ensure_dirs()
    out = []
    for d in config.PROJECTS_DIR.iterdir():
        if d.is_dir() and ID_RE.match(d.name):
            with _lock(d.name):  # không đọc trong lúc luồng xử lý đang ghi đè tệp (Windows không cho)
                data = config.read_json(d / "project.json")
            if isinstance(data, dict) and data.get("id") == d.name:
                out.append(summary(data))
    out.sort(key=lambda p: p["created_at"], reverse=True)
    return out


def summary(data: dict) -> dict:
    return {k: data.get(k) for k in ("id", "name", "created_at", "updated_at", "media", "steps",
                                     "counts", "outputs")} | {
        "source": {k: data["source"].get(k) for k in ("kind", "original_name", "ready")},
        "has_thumb": (project_dir(data["id"]) / "thumb.jpg").is_file(),
        "mode": {"dub": data["settings"]["dub"]["enabled"], "burn": data["settings"]["subtitle"]["burn"]},
    }


def delete(pid: str) -> None:
    d = project_dir(pid)
    with _lock(pid):
        if not d.is_dir():
            raise ProjectError("Không tìm thấy dự án.", 404)
        # Xoá project.json trước: dù còn tệp đang bị chương trình khác giữ (Windows) thì dự án vẫn
        # biến mất khỏi danh sách; phần sót lại được dọn ở lần khởi động sau (xem remove_leftovers).
        if not fileops.remove(d / "project.json", wait=2.0):
            raise ProjectError("Chưa xoá được dự án vì tệp đang được dùng. Hãy thử lại sau vài giây.", 409)
        fileops.remove_tree(d, wait=1.5)


def remove_leftovers() -> int:
    """Dọn thư mục dự án đã xoá nhưng còn sót tệp (lúc xoá có tệp đang bị giữ)."""
    config.ensure_dirs()
    n = 0
    for d in config.PROJECTS_DIR.iterdir():
        if d.is_dir() and ID_RE.match(d.name) and not (d / "project.json").exists():
            n += int(fileops.remove_tree(d, wait=0.0))
    return n


def disk_usage(pid: str) -> int:
    total = 0
    for p in project_dir(pid).rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total


# --------------------------------------------------------------------------
# Câu phụ đề
# --------------------------------------------------------------------------

def load_segments(pid: str) -> list[dict]:
    with _lock(pid):
        segs = config.read_json(project_dir(pid) / "segments.json", [])
    return segs if isinstance(segs, list) else []


def save_segments(pid: str, segments: list[dict], *, renumber: bool = True) -> list[dict]:
    clean = subtitles.normalize(segments) if renumber else segments
    with _lock(pid):
        config.write_json_atomic(project_dir(pid) / "segments.json", clean)

        def touch(data: dict) -> None:
            data["counts"] = {
                "segments": len(clean),
                "translated": sum(1 for s in clean if (s.get("translation") or "").strip()),
            }

        update(pid, touch)
    return clean


# --------------------------------------------------------------------------
# Trạng thái bước
# --------------------------------------------------------------------------

def set_step(pid: str, step: str, **fields: Any) -> None:
    def apply(data: dict) -> None:
        st = data["steps"].setdefault(step, {"status": "pending", "progress": 0.0, "message": "",
                                             "error": "", "info": {}})
        st.update(fields)

    update(pid, apply)


def mark_stale(pid: str, steps: list[str]) -> None:
    """Đánh dấu các bước đã xong là 'cần chạy lại' vì dữ liệu đầu vào đã đổi."""
    def apply(data: dict) -> None:
        for s in steps:
            st = data["steps"].get(s)
            if st and st.get("status") == "done":
                st["status"] = "stale"
                st["message"] = "Dữ liệu đã thay đổi, cần chạy lại"

    update(pid, apply)


def recover_interrupted() -> int:
    """Khi khởi động: bước nào còn ghi 'đang chạy' nghĩa là lần trước ứng dụng bị tắt giữa chừng."""
    n = 0
    config.ensure_dirs()
    for d in config.PROJECTS_DIR.iterdir():
        if not (d.is_dir() and ID_RE.match(d.name)):
            continue
        data = config.read_json(d / "project.json")
        if not isinstance(data, dict):
            continue
        dirty = [s for s, st in (data.get("steps") or {}).items() if st.get("status") in ("running", "queued")]
        if dirty:
            def apply(pd: dict) -> None:
                for s in dirty:
                    pd["steps"][s].update(status="error", progress=0.0, message="",
                                          error="Bị gián đoạn vì ứng dụng đã tắt giữa chừng. Hãy chạy lại bước này.")

            update(d.name, apply)
            n += 1
    return n


def log(pid: str, message: str) -> None:
    try:
        with open(project_dir(pid) / "log.txt", "a", encoding="utf-8") as f:
            f.write(f"[{dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message.rstrip()}\n")
    except OSError:
        pass


def read_log(pid: str, max_bytes: int = 200_000) -> str:
    p = project_dir(pid) / "log.txt"
    if not p.is_file():
        return ""
    with open(p, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - max_bytes))
        return f.read().decode("utf-8", "replace")
