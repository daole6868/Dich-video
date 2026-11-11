"""Giọng đọc Piper: chạy hoàn toàn trên máy, không cần mạng sau khi tải giọng."""

from __future__ import annotations

import logging
import threading
import wave
from pathlib import Path

from .. import config

log = logging.getLogger(__name__)
# Piper in một dòng cảnh báo cho mỗi âm vị không có trong giọng (bị bỏ qua khi đọc), làm ngập
# nhật ký. Giọng nào gặp nhiều thì đã ghi "chất lượng thấp hơn" ở danh sách bên dưới.
logging.getLogger("piper.phoneme_ids").setLevel(logging.ERROR)

REPO = "rhasspy/piper-voices"
VOICES = [
    # Giới tính và độ rõ ghi theo kết quả đo thực tế (cao độ giọng, nhận dạng lại bằng Whisper).
    {"id": "vi_VN-vais1000-medium", "name": "VAIS 1000 (rõ nhất)", "gender": "female", "lang": "vi-VN",
     "path": "vi/vi_VN/vais1000/medium", "size_mb": 63},
    {"id": "vi_VN-25hours_single-low", "name": "25 giờ (chất lượng thấp hơn)", "gender": "female", "lang": "vi-VN",
     "path": "vi/vi_VN/25hours_single/low", "size_mb": 63},
]
_lock = threading.Lock()  # bộ phiên âm espeak của Piper không an toàn đa luồng
_loaded: dict[str, object] = {}


def voices_dir() -> Path:
    return config.MODELS_DIR / "piper"


def list_voices() -> list[dict]:
    return [{k: v[k] for k in ("id", "name", "gender", "lang", "size_mb")} | {"downloaded": voice_ready(v["id"])}
            for v in VOICES]


def _meta(voice: str) -> dict:
    return next((v for v in VOICES if v["id"] == voice), VOICES[0])


def _paths(voice: str) -> tuple[Path, Path]:
    meta = _meta(voice)
    base = voices_dir() / meta["path"]
    return base / f"{meta['id']}.onnx", base / f"{meta['id']}.onnx.json"


def voice_ready(voice: str) -> bool:
    onnx, cfg = _paths(voice)
    return onnx.is_file() and cfg.is_file() and onnx.stat().st_size > 1_000_000


def ensure_voice(voice: str) -> tuple[Path, Path]:
    onnx, cfg = _paths(voice)
    if voice_ready(voice):
        return onnx, cfg
    meta = _meta(voice)
    try:
        from huggingface_hub import hf_hub_download

        for name in (f"{meta['id']}.onnx.json", f"{meta['id']}.onnx"):
            hf_hub_download(REPO, f"{meta['path']}/{name}", local_dir=str(voices_dir()))
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            f"Không tải được giọng Piper '{meta['id']}'. Kiểm tra kết nối mạng rồi thử lại. "
            f"Chi tiết: {type(e).__name__}: {str(e)[:200]}") from e
    if not voice_ready(voice):
        raise RuntimeError(f"Tải giọng Piper '{meta['id']}' chưa hoàn tất, hãy thử lại.")
    return onnx, cfg


def synthesize(text: str, out_path: str, *, voice: str, rate: int = 0, pitch: int = 0) -> None:
    try:
        from piper import PiperVoice, SynthesisConfig
    except ImportError as e:
        raise RuntimeError("Chưa cài thư viện piper-tts. Hãy chạy lại tệp khởi động để cài đủ thư viện.") from e
    meta = _meta(voice)
    with _lock:
        model = _loaded.get(meta["id"])
        if model is None:
            onnx, cfg = ensure_voice(meta["id"])
            model = PiperVoice.load(str(onnx), config_path=str(cfg))
            _loaded.clear()  # chỉ giữ một giọng trong bộ nhớ
            _loaded[meta["id"]] = model
        speed = 1.0 + max(-50, min(100, int(rate))) / 100.0
        with wave.open(out_path, "wb") as wf:
            model.synthesize_wav(text, wf, syn_config=SynthesisConfig(length_scale=1.0 / speed))


def unload() -> None:
    with _lock:
        _loaded.clear()
