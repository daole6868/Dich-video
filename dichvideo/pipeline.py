"""Các bước xử lý của một dự án: chuẩn bị → nhận dạng → dịch → lồng tiếng → xuất video."""

from __future__ import annotations

import logging
import shutil
import threading
import time
import traceback
from pathlib import Path
from typing import Callable

from . import asr, dubbing, ffmpeg, fileops, projects, render, subtitles, translate, tts
from .ffmpeg import Cancelled

log = logging.getLogger(__name__)

Progress = Callable[[float, str], None]


class StepError(RuntimeError):
    """Lỗi có thông điệp tiếng Việt, hiển thị nguyên văn cho người dùng."""


def _paths(pid: str) -> dict[str, Path]:
    d = projects.project_dir(pid)
    return {"dir": d, "work": d / "work", "out": d / "output", "audio": d / "work" / "audio16k.wav",
            "tts": d / "work" / "tts", "dub": d / "work" / "dub.wav", "mix": d / "work" / "mix.wav",
            "thumb": d / "thumb.jpg"}


# --------------------------------------------------------------------------
# Từng bước
# --------------------------------------------------------------------------

def step_prepare(pid: str, progress: Progress, cancel: threading.Event) -> dict:
    data = projects.load(pid)
    p = _paths(pid)
    src = projects.source_path(data)
    if not src.is_file():
        raise StepError("Chưa có tệp video nguồn. Hãy tải video lên lại.")
    progress(0.05, "Đang đọc thông tin video…")
    media = ffmpeg.probe(src)
    if media["duration"] <= 0:
        raise StepError("Không xác định được thời lượng video. Tệp có thể bị hỏng.")
    projects.update(pid, lambda d: d.update(media=media))
    if media["has_video"]:
        progress(0.15, "Đang tạo ảnh thu nhỏ…")
        try:
            ffmpeg.extract_frame(src, min(media["duration"] * 0.15, 8.0), p["thumb"], max_width=640)
        except ffmpeg.FFmpegError as e:
            log.warning("Không tạo được ảnh thu nhỏ: %s", e)
    if media["has_audio"]:
        ffmpeg.extract_audio(src, p["audio"], duration=media["duration"], cancel=cancel,
                             progress=lambda x: progress(0.2 + 0.4 * x, "Đang tách âm thanh…"))
    proxy = p["work"] / "preview.mp4"
    if media["has_video"] and needs_proxy(src, media):
        make_proxy(src, proxy, media, cancel=cancel,
                   progress=lambda x: progress(0.6 + 0.3 * x, "Đang tạo bản xem trước nhẹ cho trình duyệt…"))
    else:
        fileops.remove(proxy)
    hardsub = {"found": False, "hits": 0, "samples": 0, "region": None}
    if media["has_video"]:
        progress(0.92, "Đang kiểm tra video có phụ đề cứng không…")
        try:
            from . import ocr  # nạp muộn: thư viện OCR khá nặng

            hardsub = ocr.detect_hardsub(src, media, lang=data["settings"]["source_lang"], cancel=cancel)
        except Cancelled:
            raise
        except Exception as e:  # noqa: BLE001 - chỉ là gợi ý, lỗi ở đây không được làm hỏng bước chuẩn bị
            log.warning("Không kiểm tra được phụ đề cứng: %s", e)
    projects.update(pid, lambda d: d.__setitem__("hardsub", hardsub))
    return {"duration": media["duration"], "size": f"{media['width']}x{media['height']}" if media["has_video"] else "",
            "has_audio": media["has_audio"], "proxy": proxy.is_file(), "hardsub": hardsub["found"]}


def resolve_source(data: dict) -> str:
    """Cách lấy lời thoại: ``asr`` (nghe giọng nói), ``ocr`` (đọc phụ đề cứng) hay ``both``.

    Chế độ tự động: nếu bước chuẩn bị thấy video có phụ đề cứng thì chạy cả hai rồi chọn kết quả
    đầy đủ hơn (``both``); video không có tiếng thì chỉ còn cách đọc phụ đề cứng.
    """
    choice = data["settings"].get("subtitle_source", "auto")
    media = data.get("media") or {}
    if choice in ("asr", "ocr"):
        return choice
    if not media.get("has_video"):
        return "asr"
    if not media.get("has_audio"):
        return "ocr"
    return "both" if (data.get("hardsub") or {}).get("found") else "asr"


def text_amount(segs: list[dict]) -> int:
    """Tổng số ký tự lời thoại (bỏ dấu câu, khoảng trắng) của một danh sách câu."""
    import re

    return sum(len(re.sub(r"[\s\W_]+", "", s.get("text") or "")) for s in segs)


def choose_source(ocr_segs: list[dict], asr_segs: list[dict]) -> str:
    """Chọn giữa kết quả OCR và kết quả nghe giọng nói khi đã có cả hai.

    Phụ đề cứng đúng chữ hơn (tên riêng, từ đồng âm) nên được ưu tiên, miễn là nó phủ được phần
    lớn lời thoại nghe thấy. Nếu OCR chỉ ra vài chữ lẻ (video không thật sự có phụ đề, hoặc chỉ
    có tiêu đề) thì dùng kết quả nghe giọng nói.
    """
    if not ocr_segs:
        return "asr"
    if not asr_segs:
        return "ocr"
    return "ocr" if text_amount(ocr_segs) >= 0.6 * text_amount(asr_segs) else "asr"


def needs_proxy(src: Path, media: dict) -> bool:
    """Trình duyệt chỉ phát mượt MP4/H.264: định dạng khác hoặc video quá lớn cần bản xem trước riêng."""
    ok_container = src.suffix.lower() in (".mp4", ".m4v", ".mov")
    ok_video = (media.get("video_codec") or "").lower() == "h264"
    ok_audio = not media.get("has_audio") or (media.get("audio_codec") or "").lower() in ("aac", "mp3")
    small = min(int(media.get("width") or 0), int(media.get("height") or 0)) <= 1080
    return not (ok_container and ok_video and ok_audio and small)


def make_proxy(src: Path, dest: Path, media: dict, *, progress: Callable[[float], None] | None = None,
               cancel: threading.Event | None = None) -> None:
    w, h = render.output_size(media, {"resolution": "480"})
    tmp = dest.with_name("preview.part.mp4")
    args = ["-i", str(src), "-map", "0:v:0", "-vf", f"scale={w}:{h}:flags=bilinear,setsar=1",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p", "-g", "48"]
    if media.get("has_audio"):
        args += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "96k", "-ac", "2"]
    args += ["-movflags", "+faststart", "-f", "mp4", str(tmp)]
    try:
        ffmpeg.run(args, duration=float(media.get("duration") or 0) or None, progress=progress, cancel=cancel)
        fileops.replace(tmp, dest, wait=10.0)
    finally:
        fileops.remove(tmp)


def step_transcribe(pid: str, progress: Progress, cancel: threading.Event) -> dict:
    data = projects.load(pid)
    st = data["settings"]
    p = _paths(pid)
    seg_cfg = st["segment"]
    source = resolve_source(data)
    media = data["media"]
    a = st["asr"]

    def run_ocr(prog: Progress) -> dict:
        from . import ocr  # nạp muộn: thư viện OCR khá nặng

        if not media.get("has_video"):
            raise StepError("Tệp nguồn không có hình ảnh nên không thể đọc phụ đề cứng (OCR).")
        return ocr.extract_subtitles(projects.source_path(data), media, st["ocr"], lang=st["source_lang"],
                                     progress=prog, cancel=cancel)

    def run_asr(prog: Progress) -> tuple[list[dict], dict]:
        if not media.get("has_audio") or not p["audio"].is_file():
            raise StepError("Video không có âm thanh để nhận dạng. Hãy chọn nguồn lời thoại "
                            "'Đọc phụ đề cứng (OCR)' hoặc nhập tệp phụ đề có sẵn.")
        if a.get("engine") == "api":
            result = asr.transcribe_api(p["audio"], language=st["source_lang"], prompt=a.get("prompt", ""),
                                        progress=prog, cancel=cancel)
        else:
            result = asr.transcribe_local(p["audio"], language=st["source_lang"],
                                          model=a.get("model", "large-v3-turbo"), device=a.get("device", "auto"),
                                          beam_size=a.get("beam_size", 5), vad=a.get("vad", True),
                                          prompt=a.get("prompt", ""), progress=prog, cancel=cancel)
        found = asr.words_to_segments(result, max_chars=seg_cfg["max_chars"],
                                      max_duration=seg_cfg["max_duration"], pause=seg_cfg["pause"])
        return found, {"device": result.get("device"), "language": result.get("language")}

    def remember_region(result: dict) -> None:
        if result.get("region"):
            projects.update(pid, lambda d: d.__setitem__("ocr_region", result["region"]))

    def apply_auto_cover(region: list[float] | None) -> bool:
        """Lời thoại lấy từ phụ đề cứng: tự che phụ đề gốc và đặt phụ đề Việt đè lên đúng chỗ đó."""
        if not region or not st.get("auto_cover", True) or st.get("cover"):
            return False
        cover = render.auto_cover_region(region)
        w, h = render.output_size(media, st["output"])

        def apply(d: dict) -> None:
            d["settings"]["cover"] = [cover]
            d["settings"]["subtitle"]["margin_v"] = render.margin_for_region(cover, d["settings"]["subtitle"], w, h)
            d["settings"]["subtitle"]["align"] = "bottom"

        projects.update(pid, apply)
        return True

    if source == "ocr":
        result = run_ocr(progress)
        segs = result["segments"]
        info = {"source": "ocr", "frames": result.get("frames", 0)}
        remember_region(result)
        if not segs:
            raise StepError("Không đọc được phụ đề cứng nào trong vùng quét. Hãy khoanh lại vùng phụ đề ở thẻ "
                            "'Nhận dạng & Dịch', hoặc đổi nguồn lời thoại sang 'Nghe giọng nói'.")
        info["auto_cover"] = apply_auto_cover(result.get("region"))
    elif source == "both":
        result = run_ocr(lambda x, m: progress(0.7 * x, m))
        remember_region(result)
        try:
            asr_segs, asr_info = run_asr(lambda x, m: progress(0.7 + 0.3 * x, m))
        except Cancelled:
            raise
        except Exception as e:  # noqa: BLE001 - nghe giọng nói lỗi thì vẫn còn kết quả OCR
            if not result["segments"]:
                raise
            log.warning("Nhận dạng giọng nói lỗi, dùng kết quả OCR: %s", e)
            asr_segs, asr_info = [], {}
        chosen = choose_source(result["segments"], asr_segs)
        segs = result["segments"] if chosen == "ocr" else asr_segs
        info = {"source": chosen, "auto": True, "ocr_lines": len(result["segments"]), "asr_lines": len(asr_segs),
                **(asr_info if chosen == "asr" else {})}
        if chosen == "ocr":
            info["auto_cover"] = apply_auto_cover(result.get("region"))
    else:
        segs, info = run_asr(progress)
        info["source"] = "asr"
    if not segs:
        raise StepError("Không tìm thấy lời thoại nào trong video. Hãy kiểm tra ngôn ngữ nguồn, "
                        "hoặc thử nguồn phụ đề khác.")
    saved = projects.save_segments(pid, [{"start": s["start"], "end": s["end"], "text": s["text"],
                                          "translation": ""} for s in segs])
    info["segments"] = len(saved)
    return info


def step_translate(pid: str, progress: Progress, cancel: threading.Event, *, keep_existing: bool = False) -> dict:
    """Dịch các câu phụ đề. ``keep_existing``: chỉ dịch những câu còn trống.

    Khi người dùng bấm "chạy tiếp" (không chỉ đích danh bước Dịch), các câu đã có bản dịch được giữ
    nguyên: đó có thể là câu họ tự gõ, hoặc phần đã dịch xong trước khi bộ dịch báo lỗi giữa chừng.
    Muốn dịch lại tất cả thì dùng nút "Dịch lại toàn bộ".
    """
    data = projects.load(pid)
    segs = projects.load_segments(pid)
    if not segs:
        raise StepError("Chưa có câu phụ đề nào để dịch. Hãy chạy bước Nhận dạng trước.")
    kept = sum(1 for s in segs if (s.get("translation") or "").strip()) if keep_existing else 0
    try:
        result = translate.translate_segments(segs, data["settings"], progress=progress, cancel=cancel,
                                              only_empty=keep_existing)
    finally:
        projects.save_segments(pid, segs)  # giữ lại phần đã dịch dù bị lỗi/huỷ giữa chừng
    if kept:
        result["kept"] = kept
    return result


def step_dub(pid: str, progress: Progress, cancel: threading.Event) -> dict:
    data = projects.load(pid)
    st, media = data["settings"], data["media"]
    dub = st["dub"]
    p = _paths(pid)
    segs = projects.load_segments(pid)
    if not any((s.get("translation") or "").strip() for s in segs):
        raise StepError("Chưa có bản dịch để lồng tiếng. Hãy chạy bước Dịch trước.")
    try:
        valid = {v["id"] for v in tts.list_voices(dub.get("engine", "edge"))}
    except Exception:  # noqa: BLE001 - không lấy được danh sách thì không lọc giọng gán riêng
        valid = None
    clips = dubbing.prepare_clips(segs, dub, p["tts"], cancel=cancel, valid_voices=valid,
                                  progress=lambda x, m: progress(0.75 * x, m))
    if not clips:
        raise StepError("Không tạo được giọng đọc cho câu nào. Hãy kiểm tra bản dịch và cấu hình giọng đọc.")
    total = float(media["duration"])
    plan = dubbing.schedule(segs, clips, total, dub.get("max_speed", 1.5))
    dubbing.build_track(plan, p["dub"], total, cancel=cancel,
                        progress=lambda x, m: progress(0.75 + 0.1 * x, m))
    background = None
    if dub.get("background", "original") != "mute" and media.get("has_audio"):
        background = projects.source_path(data)
    dubbing.mix(background, p["dub"], p["mix"], plan, total,
                background_volume=max(0.0, min(100.0, float(dub.get("original_volume", 15)))) / 100.0,
                dub_volume=max(0.0, min(200.0, float(dub.get("dub_volume", 100)))) / 100.0,
                ducking=bool(dub.get("ducking", True)), cancel=cancel,
                progress=lambda x, m: progress(0.85 + 0.12 * x, m))
    # Ghi lại thông tin khớp thời lượng vào từng câu để trình sửa phụ đề cảnh báo câu bị đọc nhanh.
    by_id = {item["id"]: item for item in plan}
    for s in segs:
        item = by_id.get(s["id"])
        if item:
            s["dub"] = {"start": item["start"], "duration": item["duration"], "speed": item["speed"],
                        "late": item["late"]}
        else:
            s.pop("dub", None)
    projects.save_segments(pid, segs, renumber=False)
    progress(0.98, "Đang lưu rãnh tiếng lồng…")
    name = projects.safe_name(data["name"])
    out = p["out"] / f"{name}.longtieng.m4a"
    p["out"].mkdir(exist_ok=True)
    ffmpeg.run(["-i", str(p["dub"]), "-c:a", "aac", "-b:a", "128k", str(out)], cancel=cancel)
    projects.update(pid, lambda d: d["outputs"].__setitem__("dub_audio", out.name))
    return dubbing.summarize(plan)


def export_subtitles(pid: str) -> dict[str, str]:
    """Ghi các tệp phụ đề (Việt, gốc, song ngữ) vào thư mục kết quả."""
    data = projects.load(pid)
    segs = projects.load_segments(pid)
    p = _paths(pid)
    p["out"].mkdir(exist_ok=True)
    name = projects.safe_name(data["name"])
    outputs: dict[str, str] = {}
    has_vi = any((s.get("translation") or "").strip() for s in segs)
    has_zh = any((s.get("text") or "").strip() for s in segs)
    targets = []
    if has_vi:
        targets.append(("srt_vi", f"{name}.vi.srt", "vi"))
    if has_zh:
        targets.append(("srt_source", f"{name}.goc.srt", "zh"))
    if has_vi and has_zh:
        targets.append(("srt_bilingual", f"{name}.songngu.srt", "bilingual"))
    for key, filename, mode in targets:
        (p["out"] / filename).write_text(subtitles.to_srt(segs, mode), encoding="utf-8-sig")
        outputs[key] = filename
    projects.update(pid, lambda d: d["outputs"].update(outputs))
    return outputs


def step_render(pid: str, progress: Progress, cancel: threading.Event) -> dict:
    data = projects.load(pid)
    st, media = data["settings"], data["media"]
    p = _paths(pid)
    segs = projects.load_segments(pid)
    export_subtitles(pid)
    if not media.get("has_video"):
        # Tệp chỉ có âm thanh: kết quả là âm thanh lồng tiếng và các tệp phụ đề.
        return {"video": False}
    use_dub = st["dub"]["enabled"] and data["steps"]["dub"]["status"] in ("done", "stale") and p["mix"].is_file()
    name = projects.safe_name(data["name"])
    out = p["out"] / f"{name}.vi.mp4"
    info = render.render(projects.source_path(data), out, project_dir=p["dir"], segments=segs, settings=st,
                         media=media, audio=p["mix"] if use_dub else None, source=transcribe_source(data),
                         progress=progress, cancel=cancel)
    projects.update(pid, lambda d: d["outputs"].__setitem__("video", out.name))
    info["dubbed"] = bool(use_dub)
    return info


def transcribe_source(data: dict) -> str | None:
    """Lời thoại của dự án lấy từ đâu: ``"ocr"``, ``"asr"``, ``"import"`` hoặc ``None`` nếu chưa có."""
    return ((data.get("steps") or {}).get("transcribe") or {}).get("info", {}).get("source")


STEP_FUNCS = {"prepare": step_prepare, "transcribe": step_transcribe, "translate": step_translate,
              "dub": step_dub, "render": step_render}


# --------------------------------------------------------------------------
# Chạy một chuỗi bước
# --------------------------------------------------------------------------

def plan_steps(data: dict, requested: list[str] | None) -> list[str]:
    """Danh sách bước sẽ chạy, theo đúng thứ tự, bỏ bước không áp dụng."""
    if requested:
        steps = [s for s in projects.STEPS if s in requested]
    else:
        # Chạy tự động: bắt đầu từ bước đầu tiên chưa xong.
        first = next((i for i, s in enumerate(projects.STEPS)
                      if data["steps"].get(s, {}).get("status") not in ("done", "skipped")), len(projects.STEPS))
        steps = projects.STEPS[first:]
    if not data["settings"]["dub"]["enabled"]:
        steps = [s for s in steps if s != "dub"]
    return steps


def run_steps(pid: str, steps: list[str], cancel: threading.Event, *, auto: bool = False) -> str:
    """Chạy lần lượt các bước. Trả về ``"done"`` | ``"review"`` | ``"error"`` | ``"cancelled"``."""
    for i, step in enumerate(steps):
        if cancel.is_set():
            _reset_queued(pid, steps[i:])
            return "cancelled"
        started = time.time()
        last_write = [0.0]
        projects.set_step(pid, step, status="running", progress=0.0, message="Đang bắt đầu…", error="", info={})
        projects.log(pid, f"▶ {projects.STEP_NAMES[step]}")

        def progress(value: float, message: str = "", _step: str = step) -> None:
            now = time.time()
            if now - last_write[0] < 0.4 and value < 1.0:  # không ghi đĩa quá dày
                return
            last_write[0] = now
            projects.set_step(pid, _step, progress=round(max(0.0, min(1.0, value)), 4), message=message)

        try:
            if step == "translate":
                info = step_translate(pid, progress, cancel, keep_existing=auto) or {}
            else:
                info = STEP_FUNCS[step](pid, progress, cancel) or {}
        except Cancelled:
            projects.set_step(pid, step, status="pending", progress=0.0, message="Đã huỷ", error="")
            projects.log(pid, f"■ Đã huỷ ở bước {projects.STEP_NAMES[step]}")
            _reset_queued(pid, steps[i + 1:])
            return "cancelled"
        except Exception as e:  # noqa: BLE001 - mọi lỗi đều được ghi lại và báo cho người dùng
            friendly = isinstance(e, (StepError, translate.TranslateError, ffmpeg.FFmpegError,
                                      projects.ProjectError, RuntimeError, ValueError))
            message = str(e) if friendly and str(e) else f"Lỗi không mong đợi: {type(e).__name__}: {e}"
            projects.set_step(pid, step, status="error", progress=0.0, message="", error=message)
            projects.log(pid, f"✖ {projects.STEP_NAMES[step]} lỗi: {message}\n{traceback.format_exc()}")
            log.exception("Bước %s của dự án %s lỗi", step, pid)
            _reset_queued(pid, steps[i + 1:])
            return "error"
        took = time.time() - started
        info["seconds"] = round(took, 1)
        projects.set_step(pid, step, status="done", progress=1.0, message="Hoàn tất", error="", info=info)
        projects.log(pid, f"✔ {projects.STEP_NAMES[step]} xong sau {took:.1f} giây: {info}")
        # Bước phía sau đã làm từ trước giờ dùng dữ liệu cũ.
        later = [s for s in projects.STEPS[projects.STEPS.index(step) + 1:] if s not in steps[i + 1:]]
        projects.mark_stale(pid, later)
        if (auto and step == "translate" and projects.load(pid)["settings"].get("stop_for_review")
                and i + 1 < len(steps)):
            _reset_queued(pid, steps[i + 1:])
            projects.log(pid, "⏸ Dừng lại để duyệt phụ đề trước khi lồng tiếng / xuất video.")
            return "review"
    return "done"


def _reset_queued(pid: str, steps: list[str]) -> None:
    def apply(data: dict) -> None:
        for s in steps:
            st = data["steps"].get(s)
            if st and st.get("status") == "queued":
                st.update(status=st.get("prev_status") or "pending", message="", progress=0.0)
            if st:
                st.pop("prev_status", None)

    projects.update(pid, apply)


def clear_outputs(pid: str, steps: list[str]) -> None:
    """Xoá tệp trung gian của các bước sắp chạy lại (để không dùng nhầm kết quả cũ)."""
    p = _paths(pid)
    if "dub" in steps:
        for f in (p["dub"], p["mix"]):
            fileops.remove(f)
    if "transcribe" in steps:
        shutil.rmtree(p["work"] / "ocr", ignore_errors=True)
