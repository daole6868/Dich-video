"""Nhận dạng giọng nói.

* ``local``: Whisper chạy ngay trên máy bằng faster-whisper (miễn phí, không cần mạng
  sau khi đã tải mô hình).
* ``api``: dịch vụ nhận dạng tương thích OpenAI (OpenAI, Groq...) cho máy cấu hình yếu.

Cả hai đều trả về danh sách "từ" có mốc thời gian để ``segmenter`` cắt thành câu.
"""

from __future__ import annotations

import ctypes
import gc
import logging
import os
import re
import shutil
import sys
import threading
import time
import wave
from pathlib import Path
from typing import Callable

import requests

from . import config, ffmpeg, fileops, segmenter
from .ffmpeg import Cancelled

log = logging.getLogger(__name__)

# Mỗi mô hình có thể có vài kho dự phòng (kho trên Hugging Face đôi khi bị đổi tên).
WHISPER_REPOS = {
    "tiny": ["Systran/faster-whisper-tiny"],
    "base": ["Systran/faster-whisper-base"],
    "small": ["Systran/faster-whisper-small"],
    "medium": ["Systran/faster-whisper-medium"],
    "large-v3": ["Systran/faster-whisper-large-v3"],
    "large-v3-turbo": ["dropbox-dash/faster-whisper-large-v3-turbo",
                       "deepdml/faster-whisper-large-v3-turbo-ct2",
                       "mobiuslabsgmbh/faster-whisper-large-v3-turbo"],
}
MODEL_FILES = ["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"]

# Câu Whisper hay "bịa" ra khi gặp nhạc nền/khoảng lặng trong video tiếng Trung.
_HALLU_STRONG = re.compile(
    r"字幕由.{0,12}提供|字幕[組组]|字幕志愿者|由\s*Amara|Amara\.org|明[镜鏡]与点点|明鏡與點點|"
    r"不吝点赞|不吝點贊|打赏支持|打賞支持|优优独播剧场|優優獨播劇場|YoYo Television|"
    r"请订阅我的频道|請訂閱我的頻道|中文字幕\s*[:：]|翻译\s*[:：]|小編字幕由|字幕\s*by",
    re.I,
)
_HALLU_SOFT = re.compile(
    r"^(谢谢观看|謝謝觀看|感谢观看|感謝觀看|谢谢大家|謝謝大家|多谢观看|谢谢收看|謝謝收看|"
    r"下集再见|下期再见|请点赞订阅|thank you for watching|thanks for watching)[。！!.\s]*$",
    re.I,
)

# Không dùng câu nhắc mặc định: thử trên video thật cho thấy câu nhắc kiểu "以下是普通话的句子"
# khiến Whisper gộp cả video thành một đoạn và sinh dấu câu lạ (﹔). Người dùng vẫn có thể tự
# nhập câu nhắc (tên riêng, chủ đề) trong cài đặt dự án.
DEFAULT_PROMPTS: dict[str, str] = {}


def model_dir(name: str) -> Path:
    return config.MODELS_DIR / "whisper" / name


def model_ready(name: str) -> bool:
    d = model_dir(name)
    return (d / "model.bin").is_file() and (d / "config.json").is_file() and (d / "tokenizer.json").is_file()


def _dir_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def list_models() -> list[dict]:
    out = []
    for m in config.WHISPER_MODELS:
        ready = model_ready(m["id"])
        out.append({**m, "downloaded": ready,
                    "disk_mb": round(_dir_size(model_dir(m["id"])) / 1e6) if ready else 0})
    return out


def delete_model(name: str) -> None:
    if name in WHISPER_REPOS:
        shutil.rmtree(model_dir(name), ignore_errors=True)


def ensure_model(name: str, progress: Callable[[float, str], None] | None = None,
                 cancel: threading.Event | None = None) -> Path:
    """Tải mô hình Whisper về ``data/models/whisper/<tên>`` nếu chưa có."""
    if name not in WHISPER_REPOS:
        raise ValueError(f"Mô hình không hợp lệ: {name}")
    target = model_dir(name)
    if model_ready(name):
        return target
    repos = WHISPER_REPOS[name]
    target.mkdir(parents=True, exist_ok=True)
    expected = next((m["size_mb"] for m in config.WHISPER_MODELS if m["id"] == name), 500) * 1e6
    result: dict = {}

    def _download() -> None:
        from huggingface_hub import snapshot_download

        for repo in repos:
            try:
                snapshot_download(repo, local_dir=str(target), allow_patterns=MODEL_FILES)
                if model_ready(name):
                    result.pop("error", None)
                    return
            except Exception as e:  # noqa: BLE001 - thử kho dự phòng, cuối cùng báo nguyên nhân
                result["error"] = e
                log.warning("Không tải được %s: %s", repo, e)

    th = threading.Thread(target=_download, daemon=True, name=f"tai-mo-hinh-{name}")
    th.start()
    while th.is_alive():
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        if progress:
            done = _dir_size(target)
            progress(min(0.99, done / expected), f"Đang tải mô hình {name}: {done / 1e6:.0f}/{expected / 1e6:.0f} MB")
        th.join(0.7)
    if "error" in result or not model_ready(name):
        err = result.get("error")
        raise RuntimeError(
            f"Không tải được mô hình nhận dạng '{name}'. Hãy kiểm tra kết nối mạng "
            "(hoặc đặt máy chủ gương Hugging Face trong Cài đặt → Mạng) rồi chạy lại."
            + (f"\nChi tiết: {type(err).__name__}: {str(err)[:300]}" if err else "")
        )
    if progress:
        progress(1.0, f"Đã tải xong mô hình {name}")
    return target


def load_wav_float(path: str | os.PathLike):
    """Đọc WAV 16 kHz mono 16-bit thành mảng float32 trong khoảng [-1, 1]."""
    import numpy as np

    with wave.open(str(path), "rb") as w:
        if w.getframerate() != 16000 or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError("Tệp âm thanh phải là WAV 16 kHz mono 16-bit")
        data = w.readframes(w.getnframes())
    return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0


# --------------------------------------------------------------------------
# GPU NVIDIA (tuỳ chọn)
# --------------------------------------------------------------------------

_gpu_libs_registered = False


def _register_nvidia_libs() -> None:
    """Cho ctranslate2 thấy cuBLAS/cuDNN cài qua pip (gói nvidia-*-cu12)."""
    global _gpu_libs_registered
    if _gpu_libs_registered:
        return
    _gpu_libs_registered = True
    try:
        import site

        roots = [Path(p) / "nvidia" for p in site.getsitepackages()]
    except Exception:  # noqa: BLE001
        return
    for root in roots:
        if not root.is_dir():
            continue
        for sub in sorted(root.iterdir()):
            if sys.platform == "win32":
                d = sub / "bin"
                if d.is_dir():
                    try:
                        os.add_dll_directory(str(d))
                        os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
                    except OSError:
                        pass
            else:
                d = sub / "lib"
                if d.is_dir():
                    for lib in sorted(d.glob("lib*.so*")):
                        try:
                            ctypes.CDLL(str(lib), mode=ctypes.RTLD_GLOBAL)
                        except OSError:
                            pass


def gpu_available() -> bool:
    try:
        _register_nvidia_libs()
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:  # noqa: BLE001
        return False


def _cpu_threads() -> int:
    n = int(config.load_settings().get("advanced", {}).get("cpu_threads") or 0)
    if n > 0:
        return n
    return max(1, min(os.cpu_count() or 4, 8))


def _load_model(name: str, device: str):
    from faster_whisper import WhisperModel

    def load(path: str):
        if device == "cuda":
            import ctranslate2

            supported = ctranslate2.get_supported_compute_types("cuda")
            compute = next((c for c in ("float16", "int8_float16", "int8", "float32") if c in supported), "default")
            return WhisperModel(path, device="cuda", compute_type=compute)
        return WhisperModel(path, device="cpu", compute_type="int8", cpu_threads=_cpu_threads())

    path = str(model_dir(name))
    try:
        return load(path)
    except Exception:  # noqa: BLE001 - xem ghi chú dưới
        # Windows + thư mục có dấu: thư viện có thể không mở được tệp mô hình; thử lại bằng đường dẫn
        # thay thế chỉ gồm ký tự ASCII. Nếu đường dẫn vốn không có dấu thì đây là lỗi thật, báo nguyên.
        if os.name != "nt" or path.isascii():
            raise
        safe = fileops.native_path(path)
        log.info("Nạp mô hình qua đường dẫn thay thế %s", safe)
        return load(safe)


# --------------------------------------------------------------------------
# Whisper trên máy
# --------------------------------------------------------------------------

def snap_leading_word(words: list[dict], max_gap: float = 1.0) -> list[dict]:
    """Sửa lỗi quen thuộc của Whisper + VAD: từ đầu câu bị đặt sớm hơn phần còn lại vài giây.

    Khi bỏ khoảng lặng rồi khôi phục mốc thời gian, từ nằm đúng chỗ nối bị gán về cuối đoạn nói
    trước. Nếu từ đầu cách từ thứ hai quá ``max_gap`` giây thì kéo nó về sát từ thứ hai.
    """
    if len(words) >= 2:
        first, second = words[0], words[1]
        if second["start"] - first["end"] > max_gap:
            length = min(0.4, max(0.12, first["end"] - first["start"]))
            first["end"] = second["start"]
            first["start"] = max(0.0, second["start"] - length)
    return words


def is_hallucination(text: str, no_speech_prob: float = 0.0) -> bool:
    t = text.strip()
    if not t:
        return True
    if _HALLU_STRONG.search(t):
        return True
    return bool(_HALLU_SOFT.match(t)) and no_speech_prob > 0.5


def transcribe_local(wav_path: str | os.PathLike, *, language: str = "zh",
                     model: str = "large-v3-turbo", device: str = "auto", beam_size: int = 5,
                     vad: bool = True, prompt: str = "",
                     progress: Callable[[float, str], None] | None = None,
                     cancel: threading.Event | None = None) -> dict:
    """Trả về ``{"language", "words": [{"start","end","text"}], "device"}``."""
    if model not in WHISPER_REPOS:
        model = "large-v3-turbo"

    def report(p: float, msg: str) -> None:
        if progress:
            progress(p, msg)

    ensure_model(model, lambda p, m: report(p * 0.15, m), cancel)
    report(0.15, "Đang nạp mô hình nhận dạng…")
    audio = load_wav_float(wav_path)
    total = max(0.01, len(audio) / 16000.0)

    want_gpu = device in ("auto", "cuda") and gpu_available()
    attempts = (["cuda"] if want_gpu else []) + ["cpu"]
    last_err: Exception | None = None
    for dev in attempts:
        whisper = None
        try:
            whisper = _load_model(model, dev)
            lang = None if language == "auto" else language
            supported = getattr(whisper, "supported_languages", None) or []
            if lang and supported and lang not in supported:
                lang = "zh" if lang == "yue" else None
            kwargs = dict(
                language=lang, task="transcribe", beam_size=max(1, int(beam_size)),
                word_timestamps=True, condition_on_previous_text=False,
                initial_prompt=(prompt.strip() or DEFAULT_PROMPTS.get(lang or "", None)),
                vad_filter=bool(vad),
            )
            # Giữ nguyên thông số VAD mặc định của thư viện: thử trên video thật, việc rút ngắn
            # khoảng lặng tối thiểu làm từ đầu câu bị gán nhầm về cuối đoạn nói trước đó.
            seg_iter, info = whisper.transcribe(audio, **kwargs)
            words: list[dict] = []
            dropped = 0
            last_text, repeat = "", 0
            for seg in seg_iter:
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                report(0.15 + 0.85 * min(1.0, seg.end / total),
                       f"Đang nhận dạng… {seg.end:.0f}/{total:.0f} giây"
                       + (" (GPU)" if dev == "cuda" else ""))
                text = (seg.text or "").strip()
                if is_hallucination(text, float(getattr(seg, "no_speech_prob", 0.0) or 0.0)):
                    dropped += 1
                    continue
                # Vòng lặp "ảo giác": cùng một câu ngắn lặp lại liên tiếp nhiều lần.
                repeat = repeat + 1 if text == last_text else 0
                last_text = text
                if repeat >= 3:
                    dropped += 1
                    continue
                seg_words = snap_leading_word(
                    [{"start": float(w.start), "end": float(max(w.end, w.start + 0.02)), "text": w.word}
                     for w in (getattr(seg, "words", None) or []) if w.word and w.end > w.start - 1e-6])
                if seg_words:
                    words.extend(seg_words)
                    # Đánh dấu hết đoạn để không ghép nhầm hai đoạn Whisper vào một câu.
                    if words and not segmenter._ends_with(words[-1]["text"], segmenter.STRONG + segmenter.WEAK):
                        words[-1]["text"] += "，" if segmenter.is_cjk_text(text) else ""
                else:
                    words.append({"start": float(seg.start), "end": float(seg.end), "text": text, "whole": True})
            if dropped:
                log.info("Bỏ %d đoạn nghi là Whisper tự bịa", dropped)
            return {"language": getattr(info, "language", language) or language, "words": words,
                    "device": dev, "duration": total}
        except Cancelled:
            raise
        except Exception as e:  # noqa: BLE001 - thử lại bằng CPU nếu GPU lỗi
            last_err = e
            if dev == "cuda":
                log.warning("Chạy bằng GPU thất bại (%s). Chuyển sang CPU.", e)
                report(0.15, "GPU không dùng được, chuyển sang CPU…")
                continue
            raise
        finally:
            del whisper
            gc.collect()
    raise RuntimeError(f"Nhận dạng thất bại: {last_err}")


# --------------------------------------------------------------------------
# API tương thích OpenAI
# --------------------------------------------------------------------------

def _quiet_cut_points(wav_path: str, chunk_seconds: float, search: float = 20.0) -> list[float]:
    """Chọn các điểm cắt rơi vào chỗ yên lặng gần mốc ``chunk_seconds``."""
    import numpy as np

    with wave.open(str(wav_path), "rb") as w:
        sr = w.getframerate()
        n = w.getnframes()
        total = n / sr
        cuts = [0.0]
        t = chunk_seconds
        while t < total - 30:
            a = max(0.0, t - search)
            w.setpos(int(a * sr))
            block = np.frombuffer(w.readframes(int(2 * search * sr)), dtype=np.int16).astype(np.float32)
            frame = int(0.05 * sr)
            usable = len(block) // frame * frame
            if usable >= frame * 8:
                energy = (block[:usable].reshape(-1, frame) ** 2).mean(axis=1)
                win = 8
                smooth = np.convolve(energy, np.ones(win) / win, mode="valid")
                idx = int(smooth.argmin())
                cut = a + (idx + win / 2) * 0.05
            else:
                cut = t
            cuts.append(round(cut, 3))
            t = cut + chunk_seconds
        cuts.append(total)
    return cuts


def transcribe_api(wav_path: str | os.PathLike, *, language: str = "zh", api: dict | None = None,
                   prompt: str = "", progress: Callable[[float, str], None] | None = None,
                   cancel: threading.Event | None = None, chunk_seconds: float = 480.0) -> dict:
    api = api or config.load_settings()["asr_api"]
    base = (api.get("base_url") or "").rstrip("/")
    key = (api.get("api_key") or "").strip()
    model = (api.get("model") or "whisper-1").strip()
    if not base:
        raise RuntimeError("Chưa nhập địa chỉ API nhận dạng trong Cài đặt → Nhận dạng qua API.")
    if not key and not re.match(r"https?://(127\.0\.0\.1|localhost)", base):
        raise RuntimeError("Chưa nhập khoá API nhận dạng trong Cài đặt → Nhận dạng qua API.")
    cuts = _quiet_cut_points(str(wav_path), chunk_seconds)
    total = cuts[-1] or 0.01
    lang = None if language == "auto" else ("zh" if language == "yue" else language)
    words: list[dict] = []
    tmp_dir = Path(config.TMP_DIR)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    for i in range(len(cuts) - 1):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        a, b = cuts[i], cuts[i + 1]
        if b - a < 0.2:
            continue
        if progress:
            progress(a / total, f"Đang gửi âm thanh lên máy chủ nhận dạng… phần {i + 1}/{len(cuts) - 1}")
        chunk = tmp_dir / f"asr_{os.getpid()}_{time.time_ns()}.mp3"
        try:
            ffmpeg.run(["-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", str(wav_path), "-ac", "1",
                        "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "48k", str(chunk)])
            data = [("model", model), ("response_format", "verbose_json"),
                    ("timestamp_granularities[]", "word"), ("timestamp_granularities[]", "segment")]
            if lang:
                data.append(("language", lang))
            p = prompt.strip() or DEFAULT_PROMPTS.get(lang or "", "")
            if p:
                data.append(("prompt", p))
            resp = None
            for attempt in range(4):
                with open(chunk, "rb") as fh:
                    resp = requests.post(
                        base + "/audio/transcriptions",
                        headers={"Authorization": f"Bearer {key}"} if key else {},
                        data=data, files={"file": ("audio.mp3", fh, "audio/mpeg")}, timeout=600)
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < 3:
                    time.sleep(3 * (attempt + 1))
                    continue
                break
            assert resp is not None
            if resp.status_code != 200:
                raise RuntimeError(f"Máy chủ nhận dạng trả lỗi {resp.status_code}: {resp.text[:300]}")
            try:
                js = resp.json()
            except ValueError as e:
                raise RuntimeError("Máy chủ nhận dạng trả về dữ liệu không phải JSON.") from e
        finally:
            try:
                chunk.unlink()
            except OSError:
                pass
        got_words = js.get("words") or []
        if got_words:
            segs = js.get("segments") or []
            seg_ends = sorted(float(s.get("end", 0)) for s in segs)
            for w in got_words:
                txt = str(w.get("word", ""))
                if not txt.strip():
                    continue
                words.append({"start": a + float(w.get("start", 0)), "end": a + float(w.get("end", 0)), "text": txt})
            # API thường trả từ không kèm dấu câu: dùng ranh giới đoạn làm chỗ ngắt câu.
            if seg_ends and not any(segmenter._ends_with(w["text"], segmenter.STRONG + segmenter.WEAK) for w in words[-len(got_words):]):
                chunk_words = words[-len(got_words):]
                k = 0
                for w in chunk_words:
                    while k < len(seg_ends) and seg_ends[k] < w["end"] - a - 0.05:
                        k += 1
                    if k < len(seg_ends) and abs(seg_ends[k] - (w["end"] - a)) <= 0.05:
                        w["text"] += "。" if segmenter.is_cjk_text(w["text"]) else "."
        else:
            for s in js.get("segments") or []:
                txt = str(s.get("text", "")).strip()
                if txt and not is_hallucination(txt, float(s.get("no_speech_prob", 0) or 0)):
                    words.append({"start": a + float(s.get("start", 0)), "end": a + float(s.get("end", 0)),
                                  "text": txt, "whole": True})
            if not js.get("segments") and str(js.get("text", "")).strip():
                words.append({"start": a, "end": b, "text": str(js["text"]).strip(), "whole": True})
    if progress:
        progress(1.0, "Đã nhận dạng xong")
    return {"language": language, "words": words, "device": "api", "duration": total}


def words_to_segments(result: dict, *, max_chars: int = 22, max_duration: float = 7.0,
                      pause: float = 0.6) -> list[dict]:
    """Chuyển kết quả nhận dạng thành câu phụ đề."""
    words = result.get("words") or []
    if not words:
        return []
    cjk = segmenter.is_cjk_text("".join(w["text"] for w in words[:400]))
    segs: list[dict] = []
    run: list[dict] = []
    for w in words:
        if w.get("whole"):
            if run:
                segs += segmenter.resegment(run, max_chars=max_chars, max_duration=max_duration, pause=pause, cjk=cjk)
                run = []
            segs += segmenter.split_by_punctuation(w, max_chars=max_chars, cjk=cjk)
        else:
            run.append(w)
    if run:
        segs += segmenter.resegment(run, max_chars=max_chars, max_duration=max_duration, pause=pause, cjk=cjk)
    segs = [s for s in segs if not is_hallucination(s["text"])]
    return segmenter.polish_timing(segs)
