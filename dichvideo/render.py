"""Xuất video: gắn cứng phụ đề, che phụ đề gốc, chèn logo, ghép âm thanh, mã hoá MP4."""

from __future__ import annotations

import logging
import os
import shutil
import threading
from pathlib import Path
from typing import Callable

from . import ffmpeg, fileops, fonts, subtitles
from .ffmpeg import Cancelled, FFmpegError

log = logging.getLogger(__name__)

CRF = {"high": 19, "medium": 23, "small": 27}
COPYABLE_VIDEO = {"h264", "hevc"}
COVER_PAD = 0.3  # giây che dư trước/sau mỗi câu (mốc phụ đề cứng chỉ chính xác tới ~1/4 giây)
COVER_MERGE = 0.6  # hai lần che cách nhau dưới ngần này thì nối liền cho khỏi nháy


def even(n: float) -> int:
    """Số chẵn gần nhất (bộ mã hoá H.264 với màu 4:2:0 không nhận kích thước lẻ)."""
    return max(2, int(n / 2 + 0.5) * 2)


def output_size(media: dict, output: dict) -> tuple[int, int]:
    """Kích thước video đầu ra: giữ nguyên, hoặc thu nhỏ để cạnh ngắn bằng độ phân giải chọn."""
    w, h = int(media.get("width") or 0), int(media.get("height") or 0)
    if w <= 0 or h <= 0:
        return 1280, 720
    res = str(output.get("resolution", "source"))
    if res.isdigit():
        target = int(res)
        short = min(w, h)
        if short > target:
            scale = target / short
            return even(w * scale), even(h * scale)
    return even(w), even(h)


def source_frame_size(media: dict) -> tuple[int, int]:
    """Kích thước khung hình thật của nguồn. Trả ``(0, 0)`` khi điểm ảnh không vuông để luôn phải co lại."""
    if abs(float(media.get("sar") or 1.0) - 1.0) > 0.002:
        return 0, 0
    return (int(media.get("frame_width") or media.get("width") or 0),
            int(media.get("frame_height") or media.get("height") or 0))


def subtitle_mode(sub: dict) -> str:
    return "bilingual" if sub.get("bilingual") else "vi"


def region_px(region: dict, width: int, height: int) -> tuple[int, int, int, int] | None:
    """Vùng che theo tỉ lệ 0..1 -> toạ độ điểm ảnh chẵn nằm trong khung hình."""
    try:
        x = float(region["x"]) * width
        y = float(region["y"]) * height
        w = float(region["w"]) * width
        h = float(region["h"]) * height
    except (KeyError, TypeError, ValueError):
        return None
    x0, y0 = max(0, int(x) // 2 * 2), max(0, int(y) // 2 * 2)
    x1, y1 = min(width, even(x + w)), min(height, even(y + h))
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    return x0, y0, x1 - x0, y1 - y0


def _hex(color: str, default: str = "000000") -> str:
    c = (color or "").lstrip("#")
    return c.upper() if len(c) == 6 and all(ch in "0123456789abcdefABCDEF" for ch in c) else default


def auto_cover_region(region: list[float]) -> dict:
    """Vùng che gợi ý từ vùng chữ mà OCR tìm thấy: nới ngang một chút để phủ cả câu dài hơn mẫu."""
    x, y, w, h = (float(v) for v in region)
    x0, x1 = max(0.0, x - 0.04), min(1.0, x + w + 0.04)
    return {"x": round(x0, 4), "y": round(y, 4), "w": round(x1 - x0, 4), "h": round(h, 4),
            "mode": "blur", "strength": 60, "auto": True}


def margin_for_region(region: dict, style: dict, width: int, height: int) -> float:
    """Lề dưới (% chiều cao) để dòng phụ đề Việt nằm giữa vùng che."""
    base = min(width, height) / 1080.0
    half_line = 0.62 * float(style.get("size", 46)) * base
    center_from_bottom = height * (1.0 - (float(region["y"]) + float(region["h"]) / 2))
    return round(max(0.0, min(60.0, (center_from_bottom - half_line) / height * 100.0)), 1)


def cover_timed(settings: dict, source: str | None) -> bool:
    """Vùng che chỉ bật lúc có câu thoại (``True``) hay bật suốt video (``False``)."""
    when = settings.get("cover_when", "auto")
    if when == "subtitle":
        return True
    if when == "always":
        return False
    # Tự động: mốc thời gian lấy từ chính phụ đề cứng thì biết chắc lúc nào có chữ để che.
    return source == "ocr"


def cover_intervals(segments: list[dict], duration: float | None = None) -> list[tuple[float, float]]:
    """Các khoảng thời gian cần che phụ đề gốc: mỗi câu nới thêm một chút, khoảng sát nhau thì nối."""
    spans = sorted((max(0.0, float(s["start"]) - COVER_PAD), float(s["end"]) + COVER_PAD)
                   for s in segments if (s.get("text") or s.get("translation") or "").strip())
    merged: list[list[float]] = []
    for a, b in spans:
        if merged and a - merged[-1][1] <= COVER_MERGE:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    if duration:
        merged = [[a, min(b, duration)] for a, b in merged if a < duration]
    return [(round(a, 3), round(b, 3)) for a, b in merged]


def build_video_chain(width: int, height: int, src_size: tuple[int, int], settings: dict, *,
                      ass_name: str | None, logo_input: int | None,
                      cover_times: list[tuple[float, float]] | None = None,
                      cover_on: bool = True) -> tuple[str, str, str] | None:
    """Trả về ``(filter_complex, nhãn đầu ra, nội dung tệp lệnh sendcmd)`` hoặc ``None``.

    ``cover_times``: nếu có, vùng che chỉ bật trong các khoảng đó (điều khiển bằng bộ lọc sendcmd
    đọc tệp ``cover.cmd`` trong thư mục làm việc). ``cover_on=False`` bỏ hẳn vùng che (dùng khi
    dựng một khung hình xem trước rơi vào lúc không có câu thoại).
    """
    steps: list[str] = []
    label = "0:v"
    n = 0
    targets: list[str] = []

    def nxt() -> str:
        nonlocal n
        n += 1
        return f"v{n}"

    if (width, height) != src_size:
        out = nxt()
        steps.append(f"[{label}]scale={width}:{height}:flags=lanczos,setsar=1[{out}]")
        label = out

    regions = [px for px in (region_px(r, width, height) for r in (settings.get("cover") or [])) if px]
    raw_regions = [r for r in (settings.get("cover") or []) if region_px(r, width, height)]
    timed = cover_times is not None and bool(regions) and cover_on
    if timed:
        out = nxt()
        steps.append(f"[{label}]sendcmd=f=cover.cmd[{out}]")
        label = out
    if cover_on:
        for i, (region, (x, y, w, h)) in enumerate(zip(raw_regions, regions), 1):
            out = nxt()
            if region.get("mode") == "box":
                opacity = max(0.0, min(100.0, float(region.get("opacity", 100)))) / 100.0
                name = f"drawbox@cv{i}"
                steps.append(f"[{label}]{name if timed else 'drawbox'}=x={x}:y={y}:w={w}:h={h}:"
                             f"color=0x{_hex(region.get('color', '#000000'))}@{opacity:.2f}:t=fill"
                             f"{':enable=0' if timed else ''}[{out}]")
            else:
                strength = max(5.0, min(100.0, float(region.get("strength", 60))))
                # Làm nhoè vừa đủ để chữ không đọc được; nhoè mạnh quá sẽ thành một dải phẳng lộ liễu.
                sigma = max(4.0, h * 0.18 * strength / 60.0)
                a, b, c = nxt(), nxt(), nxt()
                name = f"overlay@cv{i}"
                steps.append(f"[{label}]split[{a}][{b}]")
                steps.append(f"[{b}]crop={w}:{h}:{x}:{y},gblur=sigma={sigma:.1f}[{c}]")
                steps.append(f"[{a}][{c}]{name if timed else 'overlay'}={x}:{y}{':enable=0' if timed else ''}[{out}]")
            targets.append(name)
            label = out

    logo = settings.get("logo") or {}
    if logo_input is not None:
        lw = even(width * max(2.0, min(60.0, float(logo.get("scale", 14)))) / 100.0)
        margin = int(min(width, height) * max(0.0, min(20.0, float(logo.get("margin", 3)))) / 100.0)
        opacity = max(0.0, min(100.0, float(logo.get("opacity", 100)))) / 100.0
        pos = logo.get("position", "top-right")
        ox = str(margin) if "left" in pos else f"W-w-{margin}"
        oy = str(margin) if "top" in pos else f"H-h-{margin}"
        lg, out = nxt(), nxt()
        steps.append(f"[{logo_input}:v]scale={lw}:-1,format=rgba,colorchannelmixer=aa={opacity:.2f}[{lg}]")
        steps.append(f"[{label}][{lg}]overlay={ox}:{oy}[{out}]")
        label = out

    if ass_name:
        out = nxt()
        steps.append(f"[{label}]ass={ass_name}:fontsdir=fonts[{out}]")
        label = out

    if not steps:
        return None
    commands = ""
    if timed:
        lines = []
        for a, b in cover_times or []:
            lines.append(f"{a:.3f} " + ", ".join(f"{t} enable 1" for t in targets) + ";")
            lines.append(f"{b:.3f} " + ", ".join(f"{t} enable 0" for t in targets) + ";")
        commands = "\n".join(lines) + "\n"
    return ";".join(steps), label, commands


def encoder_args(encoder: str, quality: str, speed: str) -> list[str]:
    crf = CRF.get(quality, 23)
    if encoder == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", {"fast": "p3", "medium": "p5", "slow": "p7"}.get(speed, "p5"),
                "-rc", "vbr", "-cq", str(crf + 2), "-b:v", "0"]
    if encoder == "h264_qsv":
        return ["-c:v", "h264_qsv", "-global_quality", str(crf + 2),
                "-preset", {"fast": "veryfast", "medium": "medium", "slow": "slow"}.get(speed, "medium")]
    if encoder == "h264_amf":
        return ["-c:v", "h264_amf", "-rc", "cqp", "-qp_i", str(crf), "-qp_p", str(crf + 2),
                "-quality", {"fast": "speed", "medium": "balanced", "slow": "quality"}.get(speed, "balanced")]
    if encoder == "h264_videotoolbox":
        return ["-c:v", "h264_videotoolbox", "-q:v", str({"high": 65, "medium": 55, "small": 45}.get(quality, 55))]
    return ["-c:v", "libx264", "-preset", {"fast": "veryfast", "medium": "fast", "slow": "medium"}.get(speed, "fast"),
            "-crf", str(crf)]


def _prepare_workdir(work: Path, segments: list[dict], sub: dict, width: int, height: int,
                     burn: bool) -> str | None:
    """Ghi tệp ASS và chép phông vào thư mục làm việc; trả về tên tệp ASS (tương đối)."""
    work.mkdir(parents=True, exist_ok=True)
    if not burn:
        return None
    style = dict(sub)
    style["font"] = fonts.resolve_family(str(sub.get("font") or fonts.DEFAULT_FONT))
    ass = subtitles.build_ass(segments, style, width, height, mode=subtitle_mode(sub),
                              em_ratio=fonts.em_ratio(style["font"]))
    (work / "subs.ass").write_text(ass, encoding="utf-8")
    fonts.copy_fonts_to(work / "fonts", style["font"])
    return "subs.ass"


def _logo_path(settings: dict, project_dir: Path) -> Path | None:
    logo = settings.get("logo") or {}
    if not logo.get("enabled") or not logo.get("file"):
        return None
    p = project_dir / Path(str(logo["file"])).name
    return p if p.is_file() else None


def render(src: str | os.PathLike, out_path: str | os.PathLike, *, project_dir: str | os.PathLike,
           segments: list[dict], settings: dict, media: dict, audio: str | os.PathLike | None = None,
           source: str | None = None,
           progress: Callable[[float, str], None] | None = None,
           cancel: threading.Event | None = None) -> dict:
    """Xuất video hoàn chỉnh.

    ``audio``: tệp WAV đã trộn tiếng lồng (``None`` = dùng tiếng gốc).
    ``source``: lời thoại lấy từ đâu (``"ocr"``/``"asr"``), để quyết định che phụ đề gốc theo thời điểm.
    """
    project_dir = Path(project_dir)
    sub, output = settings.get("subtitle") or {}, settings.get("output") or {}
    has_text = any((s.get("translation") or "").strip() for s in segments)
    burn = bool(sub.get("burn")) and has_text and bool(media.get("has_video"))
    if not media.get("has_video"):
        raise FFmpegError("Tệp nguồn không có hình ảnh nên không thể xuất video.")
    width, height = output_size(media, output)
    src_size = source_frame_size(media)
    work = project_dir / "work" / "render"
    shutil.rmtree(work / "fonts", ignore_errors=True)
    ass_name = _prepare_workdir(work, segments, sub, width, height, burn)
    logo = _logo_path(settings, project_dir)
    duration = float(media.get("duration") or 0) or None

    inputs: list[str] = ["-i", str(src)]
    idx = 1
    logo_input = audio_input = srt_input = None
    if logo:
        inputs += ["-i", str(logo)]
        logo_input, idx = idx, idx + 1
    if audio:
        inputs += ["-i", str(audio)]
        audio_input, idx = idx, idx + 1
    soft = bool(output.get("soft_subs")) and has_text
    if soft:
        (work / "soft.srt").write_text(subtitles.to_srt(segments, "vi"), encoding="utf-8")
        inputs += ["-i", str(work / "soft.srt")]
        srt_input, idx = idx, idx + 1

    timed = cover_timed(settings, source)
    chain = build_video_chain(width, height, src_size, settings, ass_name=ass_name, logo_input=logo_input,
                              cover_times=cover_intervals(segments, duration) if timed else None)
    if chain and chain[2]:
        (work / "cover.cmd").write_text(chain[2], encoding="utf-8")
    codec = (media.get("video_codec") or "").lower()
    out_path = Path(out_path)
    tmp_out = out_path.with_name(out_path.stem + ".dang-xuat.mp4")

    def build(encoder: str) -> list[str]:
        args = list(inputs)
        if chain:
            args += ["-filter_complex", chain[0], "-map", f"[{chain[1]}]"]
            args += encoder_args(encoder, output.get("quality", "medium"), output.get("speed", "medium"))
            args += ["-pix_fmt", "yuv420p"]
        else:
            args += ["-map", "0:v:0"]
            if codec in COPYABLE_VIDEO:
                args += ["-c:v", "copy"]  # không đổi hình ảnh: chép nguyên luồng video, rất nhanh
            else:
                args += encoder_args(encoder, output.get("quality", "medium"), output.get("speed", "medium"))
                args += ["-pix_fmt", "yuv420p"]
        if audio_input is not None:
            args += ["-map", f"{audio_input}:a:0"]
        elif media.get("has_audio"):
            args += ["-map", "0:a:0"]
        if audio_input is not None or media.get("has_audio"):
            args += ["-c:a", "aac", "-b:a", f"{int(output.get('audio_bitrate') or 192)}k", "-ac", "2"]
        if srt_input is not None:
            args += ["-map", f"{srt_input}:s:0", "-c:s", "mov_text",
                     "-metadata:s:s:0", "language=vie", "-metadata:s:s:0", "title=Tiếng Việt"]
        if duration:
            args += ["-t", f"{duration:.3f}"]
        args += ["-movflags", "+faststart", "-f", "mp4", str(tmp_out)]
        return args

    def report(p: float) -> None:
        if progress:
            progress(p, f"Đang xuất video… {p * 100:.0f}%")

    will_encode = bool(chain) or codec not in COPYABLE_VIDEO
    encoder = "libx264"
    if will_encode:
        preferred = ffmpeg.pick_encoder(str(output.get("encoder", "auto")))
        if preferred != "libx264" and ffmpeg.encoder_usable(
                preferred, encoder_args(preferred, output.get("quality", "medium"), output.get("speed", "medium"))):
            encoder = preferred
    try:
        try:
            ffmpeg.run(build(encoder), duration=duration, progress=report, cancel=cancel, cwd=str(work))
        except FFmpegError:
            if encoder == "libx264":
                raise
            log.warning("Mã hoá bằng %s thất bại, chuyển sang CPU (libx264).", encoder)
            encoder = "libx264"
            ffmpeg.run(build(encoder), duration=duration, progress=report, cancel=cancel, cwd=str(work))
        try:
            fileops.replace(tmp_out, out_path, wait=15.0)
        except PermissionError as e:
            raise FFmpegError(
                f"Đã dựng xong nhưng không ghi đè được tệp kết quả cũ “{Path(out_path).name}” vì tệp đang được "
                "mở trong chương trình khác (trình phát video?). Hãy đóng chương trình đó rồi xuất lại.") from e
    finally:
        fileops.remove(tmp_out)
    return {"width": width, "height": height, "encoder": encoder if will_encode else "copy",
            "burned": burn, "soft_subs": soft, "size": out_path.stat().st_size,
            "cover": ("subtitle" if timed else "always") if (settings.get("cover") or []) else "none"}


def preview_frame(src: str | os.PathLike, t: float, out_jpg: str | os.PathLike, *,
                  project_dir: str | os.PathLike, segments: list[dict], settings: dict, media: dict,
                  source: str | None = None,
                  sample_text: str = "Đây là dòng phụ đề mẫu để xem thử kiểu chữ") -> None:
    """Dựng đúng một khung hình với mọi hiệu ứng (che, logo, phụ đề) để xem trước chính xác."""
    project_dir = Path(project_dir)
    sub, output = settings.get("subtitle") or {}, settings.get("output") or {}
    width, height = output_size(media, output)
    src_size = source_frame_size(media)
    work = project_dir / "work" / "preview"
    active = next((s for s in segments if s["start"] <= t <= s["end"] and (s.get("translation") or "").strip()), None)
    shown = dict(active) if active else {"text": "这是示例字幕", "translation": sample_text}
    shown.update(start=0.0, end=3600.0)
    ass_name = _prepare_workdir(work, [shown], sub, width, height, bool(sub.get("burn")))
    logo = _logo_path(settings, project_dir)
    # Vùng che theo thời điểm: khung xem trước chỉ có vùng che nếu rơi đúng lúc có câu thoại.
    cover_on = True
    if cover_timed(settings, source) and segments:
        cover_on = any(a <= t <= b for a, b in cover_intervals(segments))
    args = ["-ss", f"{max(0.0, t):.3f}", "-i", str(src)]
    if logo:
        args += ["-i", str(logo)]
    chain = build_video_chain(width, height, src_size, settings, ass_name=ass_name,
                              logo_input=1 if logo else None, cover_on=cover_on)
    if chain:
        args += ["-filter_complex", chain[0], "-map", f"[{chain[1]}]"]
    else:
        args += ["-map", "0:v:0"]
    args += ["-frames:v", "1", "-q:v", "3", "-update", "1", str(out_jpg)]
    ffmpeg.run(args, cwd=str(work))
    if not os.path.isfile(out_jpg) or os.path.getsize(out_jpg) == 0:
        raise FFmpegError("Không dựng được khung hình xem trước tại thời điểm này.")


__all__ = ["render", "preview_frame", "output_size", "build_video_chain", "encoder_args",
           "cover_intervals", "cover_timed", "Cancelled"]
