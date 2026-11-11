"""Lồng tiếng: tạo giọng đọc cho từng câu, khớp thời lượng, ghép thành rãnh tiếng và trộn nền.

Quy trình:
1. ``prepare_clips``  - gọi TTS (có bộ đệm), giải mã, cắt khoảng lặng, cân âm lượng.
2. ``schedule``       - xếp lịch phát: câu nào dài hơn khoảng trống thì tăng tốc vừa đủ.
3. ``build_track``    - ghi rãnh tiếng lồng (mono) theo lịch.
4. ``mix``            - trộn với âm thanh gốc (tự hạ âm gốc khi có tiếng lồng).
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

import numpy as np

from . import ffmpeg, fileops, tts
from .ffmpeg import Cancelled

log = logging.getLogger(__name__)

SR = 44100
MIN_GAP = 0.06  # giây nghỉ tối thiểu giữa hai câu lồng tiếng
TARGET_RMS = 0.085  # mức âm lượng chuẩn của giọng đọc (khoảng -21 dBFS)


# --------------------------------------------------------------------------
# Xử lý từng đoạn giọng đọc
# --------------------------------------------------------------------------

def trim_silence(pcm: np.ndarray, sr: int = SR, pad: float = 0.02) -> np.ndarray:
    """Cắt khoảng lặng đầu/cuối (TTS thường thừa 0,1-0,3 giây) để khớp thời lượng tốt hơn."""
    if len(pcm) == 0:
        return pcm
    win = max(1, int(sr * 0.01))
    usable = len(pcm) // win * win
    if usable == 0:
        return pcm
    energy = np.abs(pcm[:usable].astype(np.float32)).reshape(-1, win).mean(axis=1)
    threshold = max(90.0, float(energy.max()) * 0.035)
    loud = np.nonzero(energy > threshold)[0]
    if len(loud) == 0:
        return pcm[:0]
    start = max(0, loud[0] * win - int(sr * pad))
    end = min(len(pcm), (loud[-1] + 1) * win + int(sr * pad))
    return pcm[start:end]


def normalize_level(pcm: np.ndarray) -> np.ndarray:
    """Đưa các câu về cùng mức âm lượng để giọng không lúc to lúc nhỏ."""
    if len(pcm) == 0:
        return pcm
    x = pcm.astype(np.float32) / 32768.0
    win = SR // 20
    usable = len(x) // win * win
    if usable:
        frames = np.sqrt((x[:usable].reshape(-1, win) ** 2).mean(axis=1))
        voiced = frames[frames > max(0.004, frames.max() * 0.1)]
        rms = float(np.sqrt((voiced ** 2).mean())) if len(voiced) else 0.0
    else:
        rms = float(np.sqrt((x ** 2).mean()))
    if rms < 1e-4:
        return pcm
    gain = min(4.0, TARGET_RMS / rms)
    peak = float(np.abs(x).max()) * gain
    if peak > 0.97:
        gain *= 0.97 / peak
    return np.clip(x * gain * 32768.0, -32768, 32767).astype(np.int16)


def fade_edges(pcm: np.ndarray, ms: float = 6.0) -> np.ndarray:
    n = min(len(pcm) // 2, int(SR * ms / 1000))
    if n <= 1:
        return pcm
    out = pcm.astype(np.float32)
    ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
    out[:n] *= ramp
    out[-n:] *= ramp[::-1]
    return out.astype(np.int16)


def change_tempo(pcm: np.ndarray, speed: float) -> np.ndarray:
    """Đổi tốc độ nhưng giữ cao độ (bộ lọc atempo của ffmpeg)."""
    if len(pcm) == 0 or abs(speed - 1.0) < 0.01:
        return pcm
    speed = max(0.5, min(2.0, speed))
    out = ffmpeg.run_pipe(["-f", "s16le", "-ar", str(SR), "-ac", "1", "-i", "pipe:0",
                           "-filter:a", f"atempo={speed:.4f}", "-f", "s16le", "-ar", str(SR), "-ac", "1", "pipe:1"],
                          input_bytes=pcm.tobytes())
    return np.frombuffer(out, dtype=np.int16)


def shift_pitch(pcm: np.ndarray, semitones: float) -> np.ndarray:
    """Đổi cao độ, giữ nguyên thời lượng (cho engine không tự chỉnh được cao độ)."""
    if len(pcm) == 0 or abs(semitones) < 0.05:
        return pcm
    ratio = 2.0 ** (max(-6.0, min(6.0, semitones)) / 12.0)
    out = ffmpeg.run_pipe(["-f", "s16le", "-ar", str(SR), "-ac", "1", "-i", "pipe:0", "-filter:a",
                           f"asetrate={SR * ratio:.1f},aresample={SR},atempo={1.0 / ratio:.5f}",
                           "-f", "s16le", "-ar", str(SR), "-ac", "1", "pipe:1"], input_bytes=pcm.tobytes())
    return np.frombuffer(out, dtype=np.int16)


def voice_for(seg: dict, dub: dict, valid: set[str] | None = None) -> str:
    """Giọng của một câu: giọng gán riêng (nếu hợp lệ với engine) hoặc giọng mặc định của dự án."""
    v = (seg.get("voice") or "").strip()
    if v and (valid is None or v in valid):
        return v
    return dub.get("voice") or ""


def prepare_clips(segments: list[dict], dub: dict, cache_dir: str | os.PathLike, *,
                  progress: Callable[[float, str], None] | None = None,
                  cancel: threading.Event | None = None,
                  valid_voices: set[str] | None = None) -> dict[int, dict]:
    """Tạo giọng đọc cho mọi câu có bản dịch. Trả về ``{id câu: {"pcm": đường dẫn, "duration": giây}}``."""
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    engine = dub.get("engine", "edge")
    ext = tts.engine_ext(engine)
    rate, pitch = int(dub.get("rate", 0)), int(dub.get("pitch", 0))
    # Edge tự chỉnh cao độ; engine khác được chỉnh sau khi tạo (pitch tính theo nửa cung x 0,5).
    native_pitch = pitch * 5 if engine == "edge" else 0
    post_pitch = 0.0 if engine == "edge" else pitch * 0.5

    jobs, by_key = [], {}
    for seg in segments:
        text = (seg.get("translation") or "").strip()
        if not tts.clean_text(text):
            continue
        voice = voice_for(seg, dub, valid_voices)
        key = tts.cache_key(text, engine, voice, rate, pitch)
        if key not in by_key:
            by_key[key] = []
            jobs.append({"key": key, "text": text, "out_path": str(cache / f"{key}.{ext}"),
                         "engine": engine, "voice": voice, "rate": rate, "pitch": native_pitch})
        by_key[key].append(seg["id"])

    def tts_progress(done: int, total: int) -> None:
        if progress and total:
            progress(0.8 * done / total, f"Đang tạo giọng đọc… {done}/{total} câu")

    spoken = tts.synthesize_batch(jobs, progress=tts_progress, cancel=cancel)

    def decode(job: dict) -> tuple[str, float]:
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        pcm_path = cache / f"{job['key']}.pcm"
        if pcm_path.is_file() and pcm_path.stat().st_size > 0:
            return job["key"], pcm_path.stat().st_size / 2 / SR
        pcm = ffmpeg.read_pcm(job["out_path"], SR)
        pcm = normalize_level(trim_silence(shift_pitch(pcm, post_pitch)))
        tmp = pcm_path.with_suffix(".pcm.part")
        tmp.write_bytes(pcm.tobytes())
        fileops.replace(tmp, pcm_path)
        return job["key"], len(pcm) / SR

    clips: dict[int, dict] = {}
    ready = [j for j in jobs if spoken.get(j["key"])]
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="giai-ma") as pool:
        for n, (key, duration) in enumerate(pool.map(decode, ready), 1):
            if duration > 0.05:
                for seg_id in by_key[key]:
                    clips[seg_id] = {"pcm": str(cache / f"{key}.pcm"), "duration": duration, "key": key}
            if progress and n % 10 == 0:
                progress(0.8 + 0.2 * n / max(1, len(ready)), f"Đang xử lý giọng đọc… {n}/{len(ready)}")
    if progress:
        progress(1.0, "Đã tạo xong giọng đọc")
    return clips


# --------------------------------------------------------------------------
# Xếp lịch phát
# --------------------------------------------------------------------------

def schedule(segments: list[dict], clips: dict[int, dict], total_duration: float,
             max_speed: float = 1.5) -> list[dict]:
    """Xếp từng câu lồng tiếng vào trục thời gian.

    Mỗi câu bắt đầu đúng lúc câu gốc bắt đầu (hoặc ngay sau câu trước nếu câu trước lấn sang),
    được phép dùng cả khoảng lặng trước câu kế tiếp. Nếu vẫn không vừa thì tăng tốc, nhưng
    không quá ``max_speed``; phần còn dư sẽ đẩy lùi câu sau.
    """
    max_speed = max(1.0, min(2.0, float(max_speed)))
    order = sorted((s for s in segments if s["id"] in clips), key=lambda s: s["start"])
    plan: list[dict] = []
    cursor = 0.0
    for i, seg in enumerate(order):
        clip = clips[seg["id"]]
        start = max(float(seg["start"]), cursor + MIN_GAP if plan else 0.0)
        next_start = float(order[i + 1]["start"]) if i + 1 < len(order) else max(total_duration, float(seg["end"]))
        slot_end = max(float(seg["end"]), next_start - MIN_GAP)
        available = max(0.25, slot_end - start)
        speed = 1.0
        if clip["duration"] > available:
            speed = min(max_speed, clip["duration"] / available)
        duration = clip["duration"] / speed
        plan.append({"id": seg["id"], "start": round(start, 3), "duration": round(duration, 3),
                     "speed": round(speed, 3), "pcm": clip["pcm"],
                     "late": round(start - float(seg["start"]), 3),
                     "overflow": round(max(0.0, start + duration - slot_end), 3)})
        cursor = start + duration
    return plan


def summarize(plan: list[dict]) -> dict:
    if not plan:
        return {"clips": 0, "sped_up": 0, "max_speed": 1.0, "late": 0, "max_late": 0.0, "overflow": 0}
    return {
        "clips": len(plan),
        "sped_up": sum(1 for p in plan if p["speed"] > 1.05),
        "max_speed": max(p["speed"] for p in plan),
        "late": sum(1 for p in plan if p["late"] > 0.3),
        "max_late": max(p["late"] for p in plan),
        "overflow": sum(1 for p in plan if p["overflow"] > 0.05),
    }


# --------------------------------------------------------------------------
# Ghi rãnh tiếng lồng và trộn
# --------------------------------------------------------------------------

def build_track(plan: list[dict], out_wav: str | os.PathLike, total_duration: float, *,
                progress: Callable[[float, str], None] | None = None,
                cancel: threading.Event | None = None) -> float:
    """Ghi rãnh tiếng lồng mono 44,1 kHz. Trả về thời lượng thực của rãnh."""
    written = 0
    silence = np.zeros(SR, dtype=np.int16)

    def pad_to(frame: int, wf: wave.Wave_write) -> None:
        nonlocal written
        while written < frame:
            n = min(len(silence), frame - written)
            wf.writeframes(silence[:n].tobytes())
            written += n

    with wave.open(str(out_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        for n, item in enumerate(plan, 1):
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            pcm = np.fromfile(item["pcm"], dtype=np.int16)
            pcm = fade_edges(change_tempo(pcm, item["speed"]))
            # Không ghi lùi: nếu câu trước dài hơn dự tính vài mili-giây thì câu này nối ngay sau.
            pad_to(max(written, int(round(item["start"] * SR))), wf)
            item["start"] = round(written / SR, 3)
            item["duration"] = round(len(pcm) / SR, 3)
            wf.writeframes(pcm.tobytes())
            written += len(pcm)
            if progress and n % 20 == 0:
                progress(n / len(plan), f"Đang ghép tiếng lồng… {n}/{len(plan)}")
        pad_to(max(written, int(round(total_duration * SR))), wf)
    if progress:
        progress(1.0, "Đã ghép xong rãnh tiếng lồng")
    return written / SR


def duck_envelope(plan: list[dict], total_duration: float, base: float, ducked: float,
                  ramp: float = 0.25, step: float = 0.01) -> np.ndarray:
    """Đường âm lượng của tiếng gốc (mỗi ``step`` giây một giá trị): hạ xuống khi có tiếng lồng."""
    n = int(total_duration / step) + 2
    env = np.full(n, base, dtype=np.float32)
    # Nới mỗi câu thêm ``ramp`` hai phía rồi làm mượt: tới lúc câu lồng tiếng cất lên thì nền
    # đã hạ xong; các câu sát nhau không làm nền phập phồng.
    for item in plan:
        a = max(0, int((item["start"] - ramp) / step))
        b = min(n, int((item["start"] + item["duration"] + ramp) / step) + 1)
        env[a:b] = ducked
    k = max(1, int(ramp / step))
    if k > 1 and base != ducked:
        padded = np.pad(env, (k, k), mode="edge")
        env = np.convolve(padded, np.ones(k, dtype=np.float32) / k, mode="same")[k:-k]
    return env


def _soft_limit(x: np.ndarray, knee: float = 0.9) -> np.ndarray:
    over = np.abs(x) > knee
    if over.any():
        x = x.copy()
        x[over] = np.sign(x[over]) * (knee + (1 - knee) * np.tanh((np.abs(x[over]) - knee) / (1 - knee)))
    return x


def mix(background: str | os.PathLike | None, dub_wav: str | os.PathLike, out_wav: str | os.PathLike,
        plan: list[dict], total_duration: float, *, background_volume: float = 0.15,
        dub_volume: float = 1.0, ducking: bool = True,
        progress: Callable[[float, str], None] | None = None,
        cancel: threading.Event | None = None) -> None:
    """Trộn tiếng lồng với âm thanh nền thành WAV stereo.

    ``ducking`` bật: nền giữ nguyên âm lượng ở chỗ không có lời, hạ xuống ``background_volume``
    khi có tiếng lồng. Tắt: nền luôn ở mức ``background_volume``.
    """
    chunk = SR  # xử lý từng giây để tốn ít bộ nhớ dù video dài
    total_frames = int(round(total_duration * SR))
    base = 1.0 if ducking else background_volume
    env = duck_envelope(plan, total_duration, base, background_volume) if background else None
    proc = None
    if background:
        cmd = [ffmpeg.ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error", "-i", str(background),
               "-map", "0:a:0", "-vn", "-ac", "2", "-ar", str(SR), "-f", "s16le", "pipe:1"]
        proc = ffmpeg.spawn(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        with wave.open(str(dub_wav), "rb") as dub, wave.open(str(out_wav), "wb") as out:
            out.setnchannels(2)
            out.setsampwidth(2)
            out.setframerate(SR)
            pos = 0
            while pos < total_frames:
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                n = min(chunk, total_frames - pos)
                voice = np.frombuffer(dub.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
                if len(voice) < n:
                    voice = np.pad(voice, (0, n - len(voice)))
                frame = np.repeat((voice * dub_volume)[:, None], 2, axis=1)
                if proc is not None and proc.stdout is not None:
                    raw = proc.stdout.read(n * 4)
                    bg = np.frombuffer(raw[:len(raw) // 4 * 4], dtype=np.int16).astype(np.float32) / 32768.0
                    bg = bg.reshape(-1, 2)
                    if len(bg) < n:
                        bg = np.pad(bg, ((0, n - len(bg)), (0, 0)))
                    times = (pos + np.arange(n, dtype=np.float32)) / SR
                    gain = np.interp(times, np.arange(len(env), dtype=np.float32) * 0.01, env)
                    frame += bg * gain[:, None]
                out.writeframes((_soft_limit(frame) * 32767.0).astype(np.int16).tobytes())
                pos += n
                if progress and (pos // chunk) % 5 == 0:
                    progress(pos / total_frames, "Đang trộn âm thanh…")
    finally:
        if proc is not None:
            if proc.poll() is None:
                proc.kill()
            proc.wait()
            if proc.stdout:
                proc.stdout.close()
    if progress:
        progress(1.0, "Đã trộn xong âm thanh")
