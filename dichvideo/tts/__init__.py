"""Chuyển văn bản thành giọng nói: chọn engine, làm sạch văn bản, chạy song song có kiểm soát."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from .. import config, fileops
from ..ffmpeg import Cancelled
from . import api_engines, edge, piper_engine
from .edge import NothingToSay

log = logging.getLogger(__name__)

ENGINES = [
    {"id": "edge", "name": "Microsoft Edge", "desc": "Miễn phí, giọng tự nhiên, cần mạng.", "ext": "mp3"},
    {"id": "piper", "name": "Piper (ngoại tuyến)", "desc": "Miễn phí, chạy trên máy, không cần mạng sau khi tải giọng.", "ext": "wav"},
    {"id": "openai", "name": "API tương thích OpenAI", "desc": "Cần khoá API trong Cài đặt.", "ext": "mp3"},
    {"id": "elevenlabs", "name": "ElevenLabs", "desc": "Cần khoá API trong Cài đặt.", "ext": "mp3"},
]
_SYNTH = {
    "edge": edge.synthesize,
    "piper": piper_engine.synthesize,
    "openai": api_engines.openai_synthesize,
    "elevenlabs": api_engines.elevenlabs_synthesize,
}
_SPEAKABLE_RE = re.compile(r"[0-9A-Za-zÀ-ỹ]")
_DROP_RE = re.compile(r"[\"“”‘’«»\[\]{}<>*_#~^|\\]+")


def engine_ext(engine: str) -> str:
    return next((e["ext"] for e in ENGINES if e["id"] == engine), "mp3")


def list_voices(engine: str, refresh: bool = False) -> list[dict]:
    if engine == "edge":
        return edge.list_voices(refresh)
    if engine == "piper":
        return piper_engine.list_voices()
    if engine == "openai":
        return api_engines.openai_voices()
    if engine == "elevenlabs":
        return api_engines.elevenlabs_voices()
    raise ValueError(f"Engine giọng đọc không hợp lệ: {engine}")


def clean_text(text: str) -> str:
    """Bỏ ký hiệu mà máy đọc sẽ phát âm thành tiếng lạ; trả chuỗi rỗng nếu không còn gì để đọc."""
    t = _DROP_RE.sub(" ", (text or "").replace("\n", ", "))
    t = t.replace("…", ", ").replace("&", " và ").replace("%", " phần trăm")
    t = re.sub(r"\s+", " ", t).strip(" ,;:-")
    return t if _SPEAKABLE_RE.search(t) else ""


def cache_key(text: str, engine: str, voice: str, rate: int, pitch: int) -> str:
    raw = "\x1f".join([engine, voice or "", str(int(rate)), str(int(pitch)), clean_text(text)])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def synthesize(text: str, out_path: str, *, engine: str = "edge", voice: str = "", rate: int = 0,
               pitch: int = 0) -> bool:
    """Tạo tệp giọng đọc. Trả ``False`` nếu văn bản không có gì để đọc."""
    fn = _SYNTH.get(engine)
    if fn is None:
        raise ValueError(f"Engine giọng đọc không hợp lệ: {engine}")
    cleaned = clean_text(text)
    if not cleaned:
        return False
    tmp = f"{out_path}.part"
    try:
        fn(cleaned, tmp, voice=voice, rate=rate, pitch=pitch)
    except NothingToSay:
        return False
    finally:
        if os.path.isfile(tmp) and os.path.getsize(tmp) == 0:
            os.remove(tmp)
    if not os.path.isfile(tmp):
        return False
    fileops.replace(tmp, out_path)
    return True


def synthesize_batch(jobs: list[dict], *, progress: Callable[[int, int], None] | None = None,
                     cancel: threading.Event | None = None) -> dict[str, bool]:
    """``jobs``: [{"key", "text", "out_path", "engine", "voice", "rate", "pitch"}].

    Bỏ qua các mục đã có tệp (bộ đệm). Trả về ``{key: có_âm_thanh}``.
    """
    results: dict[str, bool] = {}
    todo = []
    for job in jobs:
        if os.path.isfile(job["out_path"]) and os.path.getsize(job["out_path"]) > 200:
            results[job["key"]] = True
        else:
            todo.append(job)
    total = len(jobs)
    done = total - len(todo)
    if progress:
        progress(done, total)
    if not todo:
        return results
    engine = todo[0]["engine"]
    # Piper chạy tuần tự (khoá nội bộ); dịch vụ mạng chạy vài luồng để nhanh mà không dồn dập.
    workers = 1 if engine == "piper" else max(1, min(8, int(
        config.load_settings().get("advanced", {}).get("tts_concurrency") or 4)))

    def run(job: dict) -> tuple[str, bool]:
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        ok = synthesize(job["text"], job["out_path"], engine=job["engine"], voice=job.get("voice", ""),
                        rate=job.get("rate", 0), pitch=job.get("pitch", 0))
        return job["key"], ok

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="tts") as pool:
        futures = [pool.submit(run, job) for job in todo]
        try:
            for fut in as_completed(futures):
                key, ok = fut.result()
                results[key] = ok
                done += 1
                if progress:
                    progress(done, total)
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
        except BaseException:
            for f in futures:
                f.cancel()
            raise
    return results
