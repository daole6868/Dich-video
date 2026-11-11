"""Đóng gói bản phát hành: ``python tools/build_zip.py`` -> ``dist/DichVideoStudio-<phiên bản>.zip``.

Chỉ lấy mã nguồn, phông chữ, tài liệu và các tệp khởi động. Không lấy dữ liệu chạy
(``data/``), môi trường ảo (``.venv/``), công cụ tải về (``runtime/``) hay tệp tạm.
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOP = "DichVideoStudio"
INCLUDE = ["dichvideo", "fonts", "tests", "tools", "run.py", "requirements.txt", "requirements.lock.txt",
           "Chay_Windows.bat", "Chay_macOS.command", "chay_linux.sh", "README.md", "LICENSE",
           "THIRD_PARTY_NOTICES.md"]
SKIP_DIRS = {"__pycache__", ".pytest_cache", ".git", ".venv", "data", "dist", "runtime", "node_modules"}
SKIP_SUFFIXES = {".pyc", ".pyo", ".log", ".part", ".tmp"}
EXECUTABLE = {"chay_linux.sh", "Chay_macOS.command"}


def version() -> str:
    text = (ROOT / "dichvideo" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__\s*=\s*"([^"]+)"', text).group(1)


def files() -> list[Path]:
    out: list[Path] = []
    for name in INCLUDE:
        p = ROOT / name
        if p.is_file():
            out.append(p)
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                rel = f.relative_to(ROOT)
                if f.is_file() and not (set(rel.parts) & SKIP_DIRS) and f.suffix not in SKIP_SUFFIXES \
                        and f.name not in (".DS_Store", "Thumbs.db"):
                    out.append(f)
        else:
            raise SystemExit(f"Thiếu tệp/thư mục cần đóng gói: {name}")
    return out


def main() -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows: in được tiếng Việt có dấu
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    target = dist / f"{TOP}-{version()}.zip"
    listed = files()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in listed:
            rel = f.relative_to(ROOT).as_posix()
            data = f.read_bytes()
            if f.suffix.lower() in (".bat", ".cmd"):
                # Tệp lệnh Windows bắt buộc xuống dòng kiểu CRLF và chỉ chứa ký tự ASCII.
                data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
                if any(b > 127 for b in data):
                    raise SystemExit(f"{rel} chứa ký tự không phải ASCII")
            info = zipfile.ZipInfo(f"{TOP}/{rel}", date_time=(2026, 11, 11, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if f.name in EXECUTABLE else 0o644) << 16
            z.writestr(info, data)
    with zipfile.ZipFile(target) as z:
        bad = z.testzip()
        if bad:
            raise SystemExit(f"Tệp zip lỗi tại {bad}")
        count = len(z.namelist())
    print(f"{target}  ({count} tệp, {target.stat().st_size / 1e6:.2f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
