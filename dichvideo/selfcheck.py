"""Tự kiểm tra bản cài: ``python run.py --check``.

Không cần mạng và không tải mô hình. Kiểm tra thư viện, ffmpeg (bộ lọc phụ đề, bộ mã hoá),
phông chữ tiếng Việt, bộ đọc chữ OCR, rồi dựng thử một video ngắn có phụ đề và vùng che.
"""

from __future__ import annotations

import importlib
import platform
import shutil
import sys
import tempfile
import time
from pathlib import Path

MODULES = [
    ("starlette", "máy chủ giao diện"), ("uvicorn", "máy chủ giao diện"), ("requests", "kết nối mạng"),
    ("numpy", "xử lý âm thanh"), ("PIL", "xử lý ảnh"), ("faster_whisper", "nhận dạng giọng nói"),
    ("ctranslate2", "nhận dạng giọng nói"), ("onnxruntime", "nhận dạng / OCR"), ("rapidocr", "đọc phụ đề cứng"),
    ("edge_tts", "giọng đọc Edge"), ("piper", "giọng đọc ngoại tuyến"), ("anthropic", "bộ dịch Claude"),
    ("imageio_ffmpeg", "ffmpeg kèm theo"), ("yt_dlp", "tải video từ liên kết"),
]


def run() -> int:
    ok = True

    def report(good: bool, name: str, detail: str = "") -> None:
        nonlocal ok
        ok = ok and good
        print(f"  [{'OK ' if good else 'LỖI'}] {name}" + (f" — {detail}" if detail else ""), flush=True)

    print(f"Dịch Video Studio — tự kiểm tra ({platform.system()} {platform.machine()}, Python {platform.python_version()})")
    print("Thư viện:")
    for mod, purpose in MODULES:
        try:
            m = importlib.import_module(mod)
            report(True, mod, getattr(m, "__version__", ""))
        except Exception as e:  # noqa: BLE001
            report(False, mod, f"{purpose}: {type(e).__name__}: {e}")

    from . import config, ffmpeg, fonts, render

    config.ensure_dirs()
    print("Xử lý video:")
    try:
        caps = ffmpeg.capabilities()
        report(True, "ffmpeg", f"{caps['version']} ({caps['path']})")
        report(bool(caps["subtitles"]), "bộ lọc gắn phụ đề (libass)")
        report(bool(caps["libx264"]), "bộ mã hoá H.264 (libx264)")
        hw = ffmpeg.pick_encoder("auto")
        print(f"  [i  ] mã hoá bằng: {'CPU (libx264)' if hw == 'libx264' else hw}")
    except Exception as e:  # noqa: BLE001
        report(False, "ffmpeg", str(e))
        return 1

    print("Phông chữ:")
    fams = fonts.catalog(refresh=True)["families"]
    report(len(fams) >= 10 and all(f["vietnamese"] for f in fams if f["origin"] == "kem-theo"),
           "phông phụ đề tiếng Việt", f"{len(fams)} họ phông")

    print("Đọc phụ đề cứng (OCR):")
    try:
        import numpy as np
        from PIL import Image, ImageDraw, ImageFont

        from . import ocr

        font_file = next(f["path"] for f in fonts.catalog()["faces"] if f["family"] == fonts.DEFAULT_FONT and f["bold"])
        img = Image.new("RGB", (640, 120), (20, 30, 40))
        ImageDraw.Draw(img).text((40, 30), "Subtitle 2024", font=ImageFont.truetype(font_file, 52), fill=(255, 255, 255))
        t = time.time()
        items = ocr.read_frame_texts(ocr._make_engine(), np.asarray(img)[:, :, ::-1].copy(), False)
        text = " ".join(i["text"] for i in items)
        report("ubtitle" in text and "2024" in text, "nhận dạng chữ", f"đọc được {text!r} sau {time.time() - t:.1f} giây")
    except Exception as e:  # noqa: BLE001
        report(False, "nhận dạng chữ", f"{type(e).__name__}: {e}")

    print("Dựng thử video:")
    tmp = Path(tempfile.mkdtemp(prefix="dvs-kiemtra-"))
    try:
        src = tmp / "nguon.mp4"
        ffmpeg.run(["-f", "lavfi", "-i", "testsrc2=s=640x360:r=25:d=2", "-f", "lavfi", "-i", "sine=f=440:d=2",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(src)])
        media = ffmpeg.probe(src)
        st = config.new_project_settings()
        st["cover"] = [{"x": 0.1, "y": 0.75, "w": 0.8, "h": 0.2, "mode": "blur", "strength": 60}]
        st["cover_when"] = "subtitle"
        segs = [{"id": 1, "start": 0.2, "end": 1.8, "text": "你好", "translation": "Xin chào, đây là phụ đề thử nghiệm"}]
        info = render.render(src, tmp / "ra.mp4", project_dir=tmp, segments=segs, settings=st, media=media)
        out = ffmpeg.probe(tmp / "ra.mp4")
        report(out["has_video"] and out["has_audio"] and info["burned"], "xuất MP4 có phụ đề + vùng che",
               f"{out['width']}x{out['height']}, {out['duration']:.1f} giây")
    except Exception as e:  # noqa: BLE001
        report(False, "xuất MP4 có phụ đề + vùng che", f"{type(e).__name__}: {e}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nKẾT QUẢ: " + ("mọi thứ sẵn sàng." if ok else "CÓ LỖI — xem các dòng [LỖI] ở trên."))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run())
