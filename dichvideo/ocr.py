"""Trích phụ đề cứng (chữ in sẵn trên hình) bằng OCR.

Video Trung Quốc thường có sẵn phụ đề cứng, đọc bằng OCR nhiều khi chính xác hơn nghe
giọng nói (tên riêng, từ đồng âm). Cách làm: lấy mẫu vài khung hình mỗi giây trong vùng
phụ đề, nhận dạng chữ, rồi gộp các khung liên tiếp cùng nội dung thành một câu có mốc thời gian.
"""

from __future__ import annotations

import difflib
import logging
import os
import re
import subprocess
import threading
from collections import Counter
from typing import Callable

import numpy as np

from . import ffmpeg
from .ffmpeg import Cancelled

log = logging.getLogger(__name__)

MAX_WIDTH = 1280  # thu nhỏ vùng cắt rộng hơn mức này cho nhanh
MIN_SCORE = 0.6
SAME_TEXT = 0.72  # độ giống tối thiểu để coi hai khung là cùng một câu
_CJK_RE = re.compile(r"[㐀-鿿぀-ヿ가-힯]")
_NORM_RE = re.compile(r"[\s\W_]+", re.UNICODE)


def default_region(media: dict) -> list[float]:
    """Vùng phụ đề mặc định: dải dưới khung hình (video dọc thì phụ đề nằm cao hơn)."""
    if int(media.get("height") or 0) > int(media.get("width") or 0):
        return [0.04, 0.50, 0.92, 0.42]
    return [0.04, 0.68, 0.92, 0.30]


def valid_region(region, media: dict) -> list[float]:
    try:
        x, y, w, h = (float(v) for v in region)
        x, y = max(0.0, min(0.98, x)), max(0.0, min(0.98, y))
        w, h = max(0.02, min(1.0 - x, w)), max(0.02, min(1.0 - y, h))
        return [x, y, w, h]
    except (TypeError, ValueError):
        return default_region(media)


def norm(text: str) -> str:
    return _NORM_RE.sub("", text or "").lower()


def similar(a: str, b: str) -> float:
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:  # phụ đề hiện dần từng chữ: chuỗi ngắn nằm trong chuỗi dài
        return max(SAME_TEXT, min(len(a), len(b)) / max(len(a), len(b)))
    return difflib.SequenceMatcher(None, a, b).ratio()


def frame_signature(frame: np.ndarray) -> np.ndarray:
    """Chữ ký của một khung: mật độ điểm sáng (chữ phụ đề thường sáng) trên lưới ô 8x8."""
    gray = frame.astype(np.uint16).sum(axis=2) // 3
    mask = (gray > 190).astype(np.float32)
    h, w = mask.shape
    bh, bw = h // 8 * 8, w // 8 * 8
    return mask[:bh, :bw].reshape(bh // 8, 8, bw // 8, 8).mean(axis=(1, 3))


def same_signature(a: np.ndarray, b: np.ndarray) -> bool:
    """Hai khung có cùng lớp chữ sáng hay không. Ngưỡng chặt: nghi ngờ thì coi là khác (đọc lại)."""
    if a.shape != b.shape:
        return False
    diff = float(np.abs(a - b).sum())
    mass = max(float(a.sum()), float(b.sum()))
    return diff <= 0.05 * mass + 0.0015 * a.size


def _make_engine():
    try:
        from rapidocr import RapidOCR
    except ImportError as e:
        raise RuntimeError("Chưa cài thư viện OCR (rapidocr). Hãy chạy lại tệp khởi động để cài đủ thư viện.") from e
    return RapidOCR(params={
        # Mặc định thư viện phóng cạnh ngắn lên 736 px: với dải phụ đề dẹt thì ảnh thành khổng lồ
        # và chậm gấp 10 lần. Giới hạn cạnh dài là đủ cho chữ phụ đề.
        "Det.limit_side_len": 960, "Det.limit_type": "max",
        "Global.use_cls": False, "Global.log_level": "error",
    })


def read_frame_texts(engine, frame: np.ndarray, need_cjk: bool) -> list[dict]:
    """Chữ đọc được trong một khung: [{"text", "score", "box": (x0, y0, x1, y1)}], từ trên xuống."""
    result = engine(frame)
    txts = getattr(result, "txts", None)
    if not txts:
        return []
    boxes = np.asarray(result.boxes, dtype=np.float32)
    scores = result.scores or [1.0] * len(txts)
    items = []
    for text, score, box in zip(txts, scores, boxes):
        text = (text or "").strip()
        if not text or float(score) < MIN_SCORE:
            continue
        if need_cjk and not _CJK_RE.search(text):
            continue  # nguồn tiếng Trung/Nhật/Hàn: bỏ mẩu chỉ có chữ Latin/số (logo, đồng hồ…)
        items.append({"text": text, "score": float(score),
                      "box": (float(box[:, 0].min()), float(box[:, 1].min()),
                              float(box[:, 0].max()), float(box[:, 1].max()))})
    items.sort(key=lambda it: (round(it["box"][1] / 12), it["box"][0]))
    return items


def _square(media: dict) -> str:
    """Bộ lọc đưa khung hình về điểm ảnh vuông (để toạ độ vùng cắt khớp với kích thước hiển thị)."""
    if abs(float(media.get("sar") or 1.0) - 1.0) > 0.002:
        return f"scale={int(media['width'])}:{int(media['height'])},setsar=1,"
    return ""


def _iter_frames(src: str, crop_px: tuple[int, int, int, int], out_size: tuple[int, int], fps: float,
                 cancel: threading.Event | None, prefix: str = ""):
    x, y, w, h = crop_px
    ow, oh = out_size
    vf = f"fps={fps:g},{prefix}crop={w}:{h}:{x}:{y}"
    if (ow, oh) != (w, h):
        vf += f",scale={ow}:{oh}:flags=bilinear"
    cmd = [ffmpeg.ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error", "-i", str(src),
           "-map", "0:v:0", "-an", "-vf", vf, "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"]
    proc = ffmpeg.spawn(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    size = ow * oh * 3
    try:
        index = 0
        while True:
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            buf = proc.stdout.read(size)  # type: ignore[union-attr]
            if len(buf) < size:
                break
            yield index, np.frombuffer(buf, dtype=np.uint8).reshape(oh, ow, 3)
            index += 1
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        if proc.stdout:
            proc.stdout.close()


def dominant_line(items: list[dict]) -> tuple[float, float] | None:
    """Dòng phụ đề chính của video: ``(tâm theo chiều dọc, chiều cao dòng)``.

    Tính theo số ký tự đọc được ở từng độ cao. Trả ``None`` khi quá ít dữ liệu hoặc chữ rải rác
    (không dòng nào chiếm quá nửa), lúc đó không lọc gì.
    """
    if len(items) < 8:
        return None
    yc = np.array([(it["box"][1] + it["box"][3]) / 2 for it in items], dtype=np.float32)
    ht = np.array([it["box"][3] - it["box"][1] for it in items], dtype=np.float32)
    wt = np.array([max(1, len(norm(it["text"]))) for it in items], dtype=np.float32)
    step = max(4.0, float(np.median(ht)) * 0.5)
    bins = np.floor(yc / step).astype(int)
    weight: Counter = Counter()
    for b, w in zip(bins, wt):
        weight[int(b)] += float(w)
    # Xét từng cặp ô liền nhau để dòng nằm vắt giữa hai ô không bị chia đôi.
    best = max(weight, key=lambda b: weight[b] + weight.get(b + 1, 0.0))
    near = (bins == best) | (bins == best + 1)
    if float(wt[near].sum()) < 0.5 * float(wt.sum()):
        return None
    return float(np.average(yc[near], weights=wt[near])), float(np.median(ht[near]))


def on_subtitle_line(item: dict, line: tuple[float, float]) -> bool:
    center, line_h = line
    y0, y1 = item["box"][1], item["box"][3]
    height = y1 - y0
    # Cho phép lệch hơn một dòng để giữ được phụ đề hai dòng.
    return abs((y0 + y1) / 2 - center) <= 1.35 * line_h and 0.45 * line_h <= height <= 2.4 * line_h


def _pick_text(votes: Counter, scores: dict[str, float]) -> str:
    """Chọn nội dung đại diện cho một câu: bản xuất hiện nhiều, ưu tiên bản dài (chữ hiện dần)."""
    top = max(votes.values())
    strong = [t for t, c in votes.items() if c >= max(1, top * 0.34)]
    return max(strong, key=lambda t: (len(norm(t)), votes[t], scores.get(t, 0.0)))


def merge_frames(frames: list[tuple[float, str, float]], interval: float, *,
                 min_frames: int = 2) -> list[dict]:
    """``frames``: [(thời điểm, nội dung, điểm tin cậy)] theo thứ tự -> danh sách câu."""
    events: list[dict] = []
    cur: dict | None = None

    def close() -> None:
        nonlocal cur
        if cur and cur["count"] >= min_frames:
            events.append({"start": max(0.0, cur["start"] - interval / 2), "end": cur["last"] + interval / 2,
                           "text": _pick_text(cur["votes"], cur["scores"])})
        cur = None

    for t, text, score in frames:
        if not text:
            # Cho phép hụt đúng một khung giữa câu (chuyển cảnh, chớp sáng làm OCR trượt).
            if cur and t - cur["last"] > interval * 1.6:
                close()
            continue
        if cur and similar(text, cur["rep"]) >= SAME_TEXT and t - cur["last"] <= interval * 2.6:
            cur["last"] = t
            cur["count"] += 1
            cur["votes"][text] += 1
            cur["scores"][text] = max(cur["scores"].get(text, 0.0), score)
            cur["rep"] = _pick_text(cur["votes"], cur["scores"])
        else:
            close()
            cur = {"start": t, "last": t, "count": 1, "rep": text, "votes": Counter({text: 1}),
                   "scores": {text: score}}
    close()
    # Hai câu liền nhau trùng nội dung (bị tách do một khung đọc sai) thì nhập lại.
    merged: list[dict] = []
    for ev in events:
        if merged and similar(ev["text"], merged[-1]["text"]) >= 0.9 and ev["start"] - merged[-1]["end"] <= interval * 2:
            merged[-1]["end"] = ev["end"]
        else:
            merged.append(ev)
    for i in range(len(merged) - 1):
        if merged[i]["end"] > merged[i + 1]["start"]:
            merged[i]["end"] = merged[i + 1]["start"]
    return merged


def extract_subtitles(src: str | os.PathLike, media: dict, cfg: dict, *, lang: str = "zh",
                      progress: Callable[[float, str], None] | None = None,
                      cancel: threading.Event | None = None) -> dict:
    """Trả về ``{"segments", "frames", "region"}``; ``region`` là vùng chữ thực tế tìm thấy."""
    width, height = int(media["width"]), int(media["height"])
    duration = float(media["duration"])
    region = valid_region(cfg.get("region"), media) if cfg.get("region") else default_region(media)
    fps = max(1.0, min(10.0, float(cfg.get("fps") or 4)))
    interval = 1.0 / fps
    x = int(region[0] * width) // 2 * 2
    y = int(region[1] * height) // 2 * 2
    w = max(16, int(region[2] * width) // 2 * 2)
    h = max(16, int(region[3] * height) // 2 * 2)
    w, h = min(w, width - x), min(h, height - y)
    scale = min(1.0, MAX_WIDTH / w)
    ow, oh = max(16, int(w * scale) // 2 * 2), max(16, int(h * scale) // 2 * 2)

    if progress:
        progress(0.0, "Đang nạp bộ nhận dạng chữ (OCR)…")
    engine = _make_engine()
    need_cjk = lang in ("zh", "yue", "ja", "ko")
    per_frame: list[tuple[float, list[dict]]] = []
    last_sig: np.ndarray | None = None
    last_items: list[dict] = []
    reused = 0
    max_reuse = max(1, int(round(2.0 * fps)))  # tối đa 2 giây liên tiếp dùng lại kết quả cũ
    skipped = 0
    for index, frame in _iter_frames(str(src), (x, y, w, h), (ow, oh), fps, cancel, _square(media)):
        t = index * interval
        sig = frame_signature(frame)
        if last_sig is not None and reused < max_reuse and same_signature(sig, last_sig):
            items = last_items  # dải phụ đề không đổi so với khung vừa đọc: khỏi nhận dạng lại
            reused += 1
            skipped += 1
        else:
            items = read_frame_texts(engine, frame, need_cjk)
            last_sig, last_items, reused = sig, items, 0
        per_frame.append((t, items))
        if progress and index % 4 == 0:
            progress(min(0.97, t / max(duration, 0.1)), f"Đang đọc phụ đề cứng… {t:.0f}/{duration:.0f} giây")

    total = len(per_frame)
    # Chữ đứng yên suốt video (logo, tên kênh) không phải phụ đề: bỏ mẩu xuất hiện ở phần lớn số khung.
    seen = Counter()
    for _t, items in per_frame:
        for key in {norm(it["text"]) for it in items}:
            seen[key] += 1
    static = {k for k, c in seen.items() if total >= 40 and c > total * 0.4}

    per_frame = [(t, [it for it in items if norm(it["text"]) not in static]) for t, items in per_frame]
    # Phụ đề luôn nằm trên cùng một dòng; chữ ở chỗ khác trong vùng quét là chữ của cảnh quay
    # (biển hiệu, hoạ tiết bị đọc nhầm thành chữ) nên bị loại.
    line = dominant_line([it for _t, items in per_frame for it in items])
    off_line = 0
    frames: list[tuple[float, str, float]] = []
    kept_boxes: list[tuple[float, float, float, float]] = []
    for t, items in per_frame:
        if line:
            on_line = [it for it in items if on_subtitle_line(it, line)]
            off_line += len(items) - len(on_line)
            items = on_line
        text = " ".join(it["text"] for it in items)
        score = min((it["score"] for it in items), default=0.0)
        frames.append((t, text, score))
        kept_boxes += [it["box"] for it in items]

    events = merge_frames(frames, interval, min_frames=2 if fps >= 3 else 1)
    found = None
    if kept_boxes:
        b = np.asarray(kept_boxes, dtype=np.float32) / scale
        x0, y0 = float(np.percentile(b[:, 0], 3)), float(np.percentile(b[:, 1], 3))
        x1, y1 = float(np.percentile(b[:, 2], 97)), float(np.percentile(b[:, 3], 97))
        pad_y, pad_x = (y1 - y0) * 0.18 + 4, (x1 - x0) * 0.03 + 8
        fx0, fy0 = max(0.0, (x + x0 - pad_x) / width), max(0.0, (y + y0 - pad_y) / height)
        fx1, fy1 = min(1.0, (x + x1 + pad_x) / width), min(1.0, (y + y1 + pad_y) / height)
        found = [round(fx0, 4), round(fy0, 4), round(fx1 - fx0, 4), round(fy1 - fy0, 4)]
    if progress:
        progress(1.0, f"Đã đọc xong phụ đề cứng: {len(events)} câu")
    return {"segments": events, "frames": total, "region": found, "static_removed": len(static),
            "skipped": skipped, "off_line": off_line}


def detect_hardsub(src: str | os.PathLike, media: dict, *, lang: str = "zh", samples: int = 60,
                   cancel: threading.Event | None = None) -> dict:
    """Lấy mẫu các khung hình rải đều để đoán video có phụ đề cứng hay không.

    Coi là có khi ít nhất 4 khung mẫu có chữ nằm trên cùng một dòng và nội dung thay đổi
    (chữ giống hệt nhau ở mọi khung là logo/tiêu đề đứng yên, không phải phụ đề). Phụ đề chỉ hiện
    khi có lời thoại nên phải lấy khá nhiều mẫu: video thật dùng để thử chỉ có chữ ở 1/4 thời lượng.
    """
    width, height = int(media["width"]), int(media["height"])
    duration = float(media["duration"])
    region = default_region(media)
    x, y = int(region[0] * width) // 2 * 2, int(region[1] * height) // 2 * 2
    w = min(width - x, max(16, int(region[2] * width) // 2 * 2))
    h = min(height - y, max(16, int(region[3] * height) // 2 * 2))
    scale = min(1.0, MAX_WIDTH / w)
    ow, oh = max(16, int(w * scale) // 2 * 2), max(16, int(h * scale) // 2 * 2)
    engine = _make_engine()
    need_cjk = lang in ("zh", "yue", "ja", "ko")
    samples = max(12, min(120, samples))
    per_frame: list[list[dict]] = []
    for i in range(samples):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        t = duration * (0.04 + 0.92 * (i + 0.5) / samples)
        vf = _square(media) + f"crop={w}:{h}:{x}:{y}" + (f",scale={ow}:{oh}:flags=bilinear" if (ow, oh) != (w, h) else "")
        try:
            raw = ffmpeg.run_pipe(["-ss", f"{t:.3f}", "-i", str(src), "-map", "0:v:0", "-frames:v", "1",
                                   "-vf", vf, "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"], timeout=60)
        except ffmpeg.FFmpegError:
            continue
        if len(raw) < ow * oh * 3:
            continue
        frame = np.frombuffer(raw[:ow * oh * 3], dtype=np.uint8).reshape(oh, ow, 3)
        per_frame.append(read_frame_texts(engine, frame, need_cjk))
    seen: Counter = Counter()
    for items in per_frame:
        for key in {norm(it["text"]) for it in items}:
            seen[key] += 1
    static = {k for k, c in seen.items() if c >= max(3, 0.5 * len(per_frame))}
    per_frame = [[it for it in items if norm(it["text"]) not in static] for items in per_frame]
    all_items = [it for items in per_frame for it in items]
    hits, found_region = 0, None
    if len(all_items) >= 4:
        line = dominant_line(all_items)
        if line is None:  # ít dữ liệu: lấy trung vị làm dòng chuẩn
            yc = np.array([(it["box"][1] + it["box"][3]) / 2 for it in all_items], dtype=np.float32)
            ht = np.array([it["box"][3] - it["box"][1] for it in all_items], dtype=np.float32)
            line = (float(np.median(yc)), float(np.median(ht)))
        on = [[it for it in items if abs((it["box"][1] + it["box"][3]) / 2 - line[0]) <= 0.7 * line[1]
               and 0.5 * line[1] <= it["box"][3] - it["box"][1] <= 2.0 * line[1]] for items in per_frame]
        # Chỉ tính khung có chữ rõ ràng: phụ đề thật cho điểm tin cậy >= 0,95 và thường dài từ 2 chữ;
        # hoạ tiết bị đọc nhầm thì chỉ ra một chữ lẻ với điểm 0,7-0,85.
        on = [[it for it in items if it["score"] >= 0.85] for items in on]
        on = [items if sum(len(norm(it["text"])) for it in items) >= 2 else [] for items in on]
        hits = sum(1 for items in on if items)
        if len({norm(" ".join(it["text"] for it in items)) for items in on if items}) < 3:
            hits = 0  # phụ đề thì phải đổi nội dung theo thời gian
        boxes = [it["box"] for items in on for it in items]
        if boxes:
            b = np.asarray(boxes, dtype=np.float32) / scale
            pad_y = (float(b[:, 3].max()) - float(b[:, 1].min())) * 0.2 + 4
            fx0 = max(0.0, (x + float(b[:, 0].min()) - 12) / width)
            fx1 = min(1.0, (x + float(b[:, 2].max()) + 12) / width)
            fy0 = max(0.0, (y + float(b[:, 1].min()) - pad_y) / height)
            fy1 = min(1.0, (y + float(b[:, 3].max()) + pad_y) / height)
            found_region = [round(fx0, 4), round(fy0, 4), round(fx1 - fx0, 4), round(fy1 - fy0, 4)]
    return {"found": hits >= 4, "hits": hits, "samples": len(per_frame), "region": found_region if hits >= 4 else None}
