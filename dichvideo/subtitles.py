"""Mô hình câu phụ đề và việc đọc/ghi các định dạng SRT, VTT, ASS, TXT.

Mỗi câu là một ``dict``: ``{"id", "start", "end", "text", "translation", ...}``
với thời gian tính bằng giây.
"""

from __future__ import annotations

import re
import sys
from typing import Iterable

Segment = dict


# --------------------------------------------------------------------------
# Thời gian
# --------------------------------------------------------------------------

def _split_time(t: float, digits: int) -> tuple[int, int, int, int]:
    unit = 10 ** digits
    total = max(0, int(round(t * unit)))
    frac = total % unit
    secs = total // unit
    return secs // 3600, secs % 3600 // 60, secs % 60, frac


def srt_time(t: float) -> str:
    h, m, s, ms = _split_time(t, 3)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def vtt_time(t: float) -> str:
    return srt_time(t).replace(",", ".")


def ass_time(t: float) -> str:
    h, m, s, cs = _split_time(t, 2)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


_TIME_RE = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{1,2})(?:[.,](\d{1,3}))?")


def parse_time(s: str) -> float | None:
    m = _TIME_RE.search(s)
    if not m:
        return None
    h = int(m.group(1) or 0)
    frac = (m.group(4) or "0").ljust(3, "0")[:3]
    return h * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(frac) / 1000.0


# --------------------------------------------------------------------------
# Chuẩn hoá danh sách câu
# --------------------------------------------------------------------------

def clean_text(s: str) -> str:
    s = (s or "").replace("\r", "")
    s = re.sub(r"[ \t　]+", " ", s)
    return "\n".join(part.strip() for part in s.split("\n") if part.strip())


def normalize(segments: Iterable[Segment], *, min_duration: float = 0.2) -> list[Segment]:
    """Sắp theo thời gian, bỏ câu rỗng, sửa mốc thời gian lỗi và đánh lại số thứ tự."""
    out: list[Segment] = []
    for seg in segments:
        try:
            start = float(seg.get("start", 0))
            end = float(seg.get("end", 0))
        except (TypeError, ValueError):
            continue
        text = clean_text(str(seg.get("text") or ""))
        translation = clean_text(str(seg.get("translation") or ""))
        if not text and not translation:
            continue
        start = max(0.0, start)
        if end < start + min_duration:
            end = start + min_duration
        item = dict(seg)
        item.update(start=round(start, 3), end=round(end, 3), text=text, translation=translation)
        out.append(item)
    out.sort(key=lambda s: (s["start"], s["end"]))
    for i, seg in enumerate(out, 1):
        seg["id"] = i
    return out


# --------------------------------------------------------------------------
# Đọc tệp phụ đề
# --------------------------------------------------------------------------

def decode_bytes(data: bytes) -> str:
    """Giải mã tệp phụ đề: UTF-8/UTF-16 có BOM, rồi GB18030 (tệp tiếng Trung cũ)."""
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", "replace")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", "replace")
    for enc in ("utf-8", "gb18030", "big5", "cp1258"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


_TAG_RE = re.compile(r"</?(?:i|b|u|s|font|c|v|ruby|rt|lang)[^>]*>", re.I)
_ASS_TAG_RE = re.compile(r"\{[^}]*\}")


def _strip_markup(s: str) -> str:
    return clean_text(_ASS_TAG_RE.sub("", _TAG_RE.sub("", s)))


def parse_srt(text: str) -> list[Segment]:
    """Đọc SRT và cả WebVTT (hai định dạng chỉ khác dấu phân cách mili-giây)."""
    segs: list[Segment] = []
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if "-->" in line:
            left, right = line.split("-->", 1)
            start, end = parse_time(left), parse_time(right)
            i += 1
            buf = []
            while i < n and lines[i].strip() != "":
                if "-->" in lines[i]:
                    break
                buf.append(lines[i])
                i += 1
            # Dòng số thứ tự của câu kế tiếp có thể dính vào cuối khi thiếu dòng trống.
            if i < n and "-->" in lines[i] and buf and buf[-1].strip().isdigit():
                buf.pop()
            body = _strip_markup("\n".join(buf))
            if start is not None and end is not None and body:
                segs.append({"start": start, "end": end, "text": body})
            continue
        i += 1
    return segs


def parse_ass(text: str) -> list[Segment]:
    segs: list[Segment] = []
    fmt: list[str] | None = None
    in_events = False
    for line in text.replace("\r\n", "\n").split("\n"):
        s = line.strip()
        if s.startswith("["):
            in_events = s.lower() == "[events]"
            continue
        if not in_events:
            continue
        if s.lower().startswith("format:"):
            fmt = [f.strip().lower() for f in s[7:].split(",")]
            continue
        if s.lower().startswith("dialogue:"):
            fields = fmt or ["layer", "start", "end", "style", "name", "marginl", "marginr",
                             "marginv", "effect", "text"]
            parts = s[9:].split(",", len(fields) - 1)
            if len(parts) < len(fields):
                continue
            row = dict(zip(fields, parts))
            start, end = parse_time(row.get("start", "")), parse_time(row.get("end", ""))
            body = row.get("text", "").replace("\\N", "\n").replace("\\n", "\n").replace("\\h", " ")
            body = _strip_markup(body)
            if start is not None and end is not None and body:
                segs.append({"start": start, "end": end, "text": body})
    return segs


def parse_subtitle_file(data: bytes, filename: str = "") -> list[Segment]:
    text = decode_bytes(data)
    name = filename.lower()
    if name.endswith((".ass", ".ssa")) or "[Events]" in text[:20000]:
        segs = parse_ass(text)
    else:
        segs = parse_srt(text)
    return normalize(segs)


# --------------------------------------------------------------------------
# Ghi tệp phụ đề
# --------------------------------------------------------------------------

def segment_lines(seg: Segment, mode: str) -> str:
    """Nội dung hiển thị của một câu theo chế độ: ``vi`` | ``zh`` | ``bilingual``."""
    vi = (seg.get("translation") or "").strip()
    zh = (seg.get("text") or "").strip()
    if mode == "zh":
        return zh
    if mode == "bilingual":
        return "\n".join(p for p in (vi, zh) if p)
    return vi


def to_srt(segments: Iterable[Segment], mode: str = "vi") -> str:
    out = []
    n = 0
    for seg in segments:
        body = segment_lines(seg, mode)
        if not body:
            continue
        n += 1
        out.append(f"{n}\n{srt_time(seg['start'])} --> {srt_time(seg['end'])}\n{body}\n")
    return "\n".join(out)


def to_vtt(segments: Iterable[Segment], mode: str = "vi") -> str:
    out = ["WEBVTT", ""]
    for seg in segments:
        body = segment_lines(seg, mode)
        if not body:
            continue
        out.append(f"{vtt_time(seg['start'])} --> {vtt_time(seg['end'])}\n{body}\n")
    return "\n".join(out)


def to_txt(segments: Iterable[Segment], mode: str = "vi") -> str:
    return "\n".join(b for b in (segment_lines(s, mode).replace("\n", " ") for s in segments) if b) + "\n"


# --------------------------------------------------------------------------
# ASS (dùng để gắn cứng phụ đề với libass)
# --------------------------------------------------------------------------

def ass_color(hex_color: str, opacity: float = 100.0) -> str:
    """``#RRGGBB`` + độ đậm (%) -> ``&HAABBGGRR`` của ASS (AA = độ trong suốt)."""
    h = (hex_color or "#FFFFFF").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if not re.fullmatch(r"[0-9a-fA-F]{6}", h):
        h = "FFFFFF"
    r, g, b = h[0:2], h[2:4], h[4:6]
    alpha = int(round(255 * (1 - max(0.0, min(100.0, opacity)) / 100.0)))
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def ass_escape(text: str) -> str:
    text = text.replace("\\", "/").replace("{", "(").replace("}", ")")
    return text.replace("\n", "\\N")


def default_cjk_font() -> str:
    if sys.platform == "win32":
        return "Microsoft YaHei"
    if sys.platform == "darwin":
        return "PingFang SC"
    return "Noto Sans CJK SC"


def build_ass(segments: Iterable[Segment], style: dict, width: int, height: int, *,
              mode: str = "vi", cjk_font: str | None = None, em_ratio: float = 0.7) -> str:
    """Tạo tệp ASS theo kiểu chữ người dùng chọn, đúng kích thước video đầu ra.

    ``style["size"]`` là cỡ chữ (em) tính bằng điểm ảnh trên video cao 1080. libass lại hiểu cỡ chữ
    là chiều cao dòng của phông, nên phải chia cho ``em_ratio`` (tỉ lệ em / chiều cao dòng của
    phông đó) để mọi phông hiện ra cùng một cỡ như người dùng chọn.
    """
    base = min(width, height) / 1080.0
    size = max(8.0, float(style.get("size", 46)) * base / max(0.3, min(1.2, em_ratio)))
    outline = max(0.0, float(style.get("outline", 3))) * base
    shadow = max(0.0, float(style.get("shadow", 1))) * base
    margin_v = int(round(height * float(style.get("margin_v", 6.0)) / 100.0))
    margin_h = int(round(width * float(style.get("margin_h", 5.0)) / 100.0))
    align = {"bottom": 2, "middle": 5, "top": 8}.get(style.get("align", "bottom"), 2)
    bold = -1 if style.get("bold", True) else 0
    italic = -1 if style.get("italic") else 0
    primary = ass_color(style.get("color", "#FFFFFF"))
    font = str(style.get("font") or "Arial").replace(",", " ")

    if style.get("box"):
        # BorderStyle=3: nền hộp tô bằng OutlineColour, "Outline" là phần đệm quanh chữ.
        border_style = 3
        outline_col = ass_color(style.get("box_color", "#000000"), float(style.get("box_opacity", 65)))
        back_col = ass_color("#000000", 0)
        outline_w = max(2.0, float(style.get("size", 46)) * base * 0.26)
        shadow_w = 0.0
    else:
        border_style = 1
        outline_col = ass_color(style.get("outline_color", "#000000"))
        back_col = ass_color("#000000", 55)
        outline_w = outline
        shadow_w = shadow

    # Dòng phụ (chữ Hán) dùng phông hệ thống; lấy tỉ lệ em phổ biến của phông CJK (~0,76).
    sec_size = float(style.get("size", 46)) * base / 0.76 * float(style.get("secondary_scale", 70)) / 100.0
    sec_color = ass_color(style.get("secondary_color", "#FFE27A"))
    sec_font = (cjk_font or default_cjk_font()).replace(",", " ")

    def style_line(name: str, fnt: str, sz: float, colour: str, b: int) -> str:
        return (f"Style: {name},{fnt},{sz:.1f},{colour},&H000000FF,{outline_col},{back_col},"
                f"{b},{italic},0,0,100,100,0,0,{border_style},{outline_w:.2f},{shadow_w:.2f},"
                f"{align},{margin_h},{margin_h},{margin_v},1")

    head = [
        "[Script Info]",
        "; Tạo bởi Dịch Video Studio",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: None",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        style_line("Chinh", font, size, primary, bold),
        style_line("Phu", sec_font, sec_size, sec_color, 0),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    events = []
    upper = bool(style.get("uppercase"))
    for seg in segments:
        vi = (seg.get("translation") or "").strip()
        zh = (seg.get("text") or "").strip()
        if upper:
            vi = vi.upper()
        if mode == "zh":
            text, st = ass_escape(zh), "Phu"
        elif mode == "bilingual" and vi and zh:
            text, st = ass_escape(vi) + "\\N{\\rPhu}" + ass_escape(zh), "Chinh"
        elif mode == "bilingual" and zh and not vi:
            text, st = ass_escape(zh), "Phu"
        else:
            text, st = ass_escape(vi), "Chinh"
        if not text:
            continue
        events.append(f"Dialogue: 0,{ass_time(seg['start'])},{ass_time(seg['end'])},{st},,0,0,0,,{text}")
    return "\n".join(head + events) + "\n"
