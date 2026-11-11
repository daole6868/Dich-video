"""Sinh THIRD_PARTY_NOTICES.md từ thông tin giấy phép thật của các gói đang cài.

Chạy bằng Python của môi trường ứng dụng: ``.venv/bin/python tools/gen_notices.py``
"""

from __future__ import annotations

import re
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def locked_names() -> list[str]:
    names = []
    for line in (ROOT / "requirements.lock.txt").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Za-z0-9_.\-]+)==", line)
        if m:
            names.append(m.group(1))
    return names


def license_of(dist: metadata.Distribution) -> str:
    md = dist.metadata
    expr = md.get("License-Expression")
    if expr:
        return expr.strip()
    classifiers = [c.split("::")[-1].strip() for c in md.get_all("Classifier") or [] if c.startswith("License ::")]
    if classifiers:
        return "; ".join(sorted(set(classifiers)))
    lic = (md.get("License") or "").strip()
    if lic and len(lic) < 80 and "\n" not in lic:
        return lic
    return "xem trang của gói"


def homepage(dist: metadata.Distribution) -> str:
    md = dist.metadata
    for entry in md.get_all("Project-URL") or []:
        label, _, url = entry.partition(",")
        if label.strip().lower() in ("homepage", "repository", "source", "source code", "github"):
            return url.strip()
    return (md.get("Home-page") or f"https://pypi.org/project/{md['Name']}/").strip()


def main() -> int:
    rows = []
    for name in locked_names():
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue  # gói chỉ dành cho nền tảng khác
        rows.append((dist.metadata["Name"], dist.version, license_of(dist), homepage(dist)))
    rows.sort(key=lambda r: r[0].lower())
    out = [
        "# Thành phần của bên thứ ba",
        "",
        "Dịch Video Studio dùng các thành phần mã nguồn mở dưới đây. Cảm ơn các tác giả.",
        "",
        "## Kèm sẵn trong gói",
        "",
        "| Thành phần | Giấy phép | Vị trí |",
        "|---|---|---|",
        "| Phông Be Vietnam Pro, Barlow Condensed, Kanit, Anton, Bangers, IBM Plex Serif, Philosopher, Pacifico, "
        "Patrick Hand, Mali (lấy nguyên bản từ kho Google Fonts) | SIL Open Font License 1.1 | `fonts/`, giấy phép từng phông trong `fonts/LICENSES/` |",
        "| Vue.js 3 (bản dựng cho trình duyệt) | MIT | `dichvideo/web/vendor/vue.global.prod.js`, `vue.LICENSE.txt` |",
        "| Bộ biểu tượng Lucide (một phần) | ISC | `dichvideo/web/js/icons.js`, `dichvideo/web/vendor/lucide.LICENSE.txt` |",
        "",
        "## Được tải về khi cài đặt (thư viện Python)",
        "",
        "Danh sách sinh tự động từ thông tin giấy phép do chính các gói khai báo "
        f"(Python {sys.version_info.major}.{sys.version_info.minor}, nền tảng dùng khi sinh: {sys.platform}).",
        "",
        "| Gói | Phiên bản | Giấy phép khai báo | Trang chủ |",
        "|---|---|---|---|",
    ]
    out += [f"| {n} | {v} | {lic} | {url} |" for n, v, lic, url in rows]
    out += [
        "",
        "## Được tải về khi dùng",
        "",
        "| Thành phần | Ghi chú |",
        "|---|---|",
        "| FFmpeg (đi kèm gói `imageio-ffmpeg`) | Bản dựng có bật các thành phần GPL; xem https://ffmpeg.org/legal.html |",
        "| Mô hình nhận dạng Whisper dạng CTranslate2 (tải từ Hugging Face khi dùng lần đầu) | Mô hình Whisper của OpenAI phát hành theo giấy phép MIT |",
        "| Mô hình OCR PP-OCR (đi kèm gói `rapidocr`) | Apache-2.0 |",
        "| Giọng đọc Piper tiếng Việt (tải từ kho `rhasspy/piper-voices` khi chọn dùng) | Mỗi giọng có giấy phép riêng, xem thẻ mô tả của giọng trong kho đó |",
        "| Công cụ `uv` và bản Python do `uv` tải (chỉ dùng để cài đặt) | uv: MIT hoặc Apache-2.0; CPython: PSF License |",
        "",
    ]
    (ROOT / "THIRD_PARTY_NOTICES.md").write_text("\n".join(out), encoding="utf-8")
    print(f"đã ghi THIRD_PARTY_NOTICES.md với {len(rows)} gói")
    return 0


if __name__ == "__main__":
    sys.exit(main())
