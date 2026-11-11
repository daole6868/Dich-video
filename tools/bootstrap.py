"""Cài thư viện vào môi trường ảo của ứng dụng (được các tệp khởi động gọi).

Chỉ dùng thư viện chuẩn của Python. Thứ tự:
  1. Nếu các tệp requirements chưa đổi kể từ lần cài trước thì thoát ngay.
  2. Cài theo ``requirements.lock.txt`` (đúng phiên bản đã kiểm thử).
  3. Nếu thất bại (máy không có bản dựng sẵn cho phiên bản đó, ví dụ một số máy Mac)
     thì cài theo ``requirements.txt`` (cho phép phiên bản gần đó).

Dùng ``uv`` nếu có (nhanh hơn nhiều), không thì dùng pip.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "requirements.lock.txt"
LOOSE = ROOT / "requirements.txt"
MARKER = Path(sys.prefix) / ".dvs-deps"


def fingerprint() -> str:
    h = hashlib.sha256()
    for f in (LOCK, LOOSE):
        h.update(f.read_bytes() if f.is_file() else b"-")
    h.update(f"{sys.version_info[:2]}".encode())
    return h.hexdigest()


def find_uv(hint: str | None) -> str | None:
    for cand in (hint, str(ROOT / "runtime" / ("uv.exe" if os.name == "nt" else "uv"))):
        if cand and cand != "uv" and os.path.isfile(cand):
            return cand
    return shutil.which("uv")


def install(requirements: Path, uv: str | None) -> bool:
    if uv:
        cmd = [uv, "pip", "install", "--python", sys.executable, "-r", str(requirements)]
    else:
        cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-r", str(requirements)]
    print(f"  > Cài theo {requirements.name}…", flush=True)
    try:
        return subprocess.run(cmd, cwd=str(ROOT)).returncode == 0
    except OSError as e:
        print(f"  Không chạy được trình cài đặt: {e}")
        return False


def main() -> int:
    for stream in (sys.stdout, sys.stderr):  # cửa sổ dòng lệnh Windows: in được tiếng Việt có dấu
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--uv", default=None, help="đường dẫn tới uv (nếu có)")
    ap.add_argument("--force", action="store_true", help="cài lại dù không có gì thay đổi")
    args = ap.parse_args()

    if sys.version_info < (3, 10):
        print(f"Python {sys.version.split()[0]} quá cũ. Cần Python 3.10 trở lên (khuyên dùng 3.12).")
        return 1
    want = fingerprint()
    if not args.force and MARKER.is_file() and MARKER.read_text(encoding="utf-8").strip() == want:
        return 0

    print("Đang cài thư viện cho Dịch Video Studio (lần đầu mất vài phút, cần mạng)…", flush=True)
    uv = find_uv(args.uv)
    if not uv:
        # Không có uv: bảo đảm pip có sẵn trong môi trường ảo.
        subprocess.run([sys.executable, "-m", "ensurepip", "--upgrade"], capture_output=True)
    ok = LOCK.is_file() and install(LOCK, uv)
    if not ok:
        print("  Không cài được đúng bộ phiên bản đã kiểm thử; thử các phiên bản tương thích gần nhất…", flush=True)
        ok = install(LOOSE, uv)
    if not ok:
        print("\n[LỖI] Cài thư viện thất bại. Hãy kiểm tra kết nối mạng rồi chạy lại.\n"
              "Nếu vẫn lỗi, xem mục 'Gỡ rối' trong README.md.")
        return 1
    MARKER.write_text(want, encoding="utf-8")
    print("Đã cài xong thư viện.\n", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
