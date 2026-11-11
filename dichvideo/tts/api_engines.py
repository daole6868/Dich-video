"""Giọng đọc qua API trả phí: dịch vụ tương thích OpenAI và ElevenLabs (cần khoá API)."""

from __future__ import annotations

import re
import time

import requests

from .. import config

_LOCAL_RE = re.compile(r"^https?://(127\.0\.0\.1|localhost|\[::1\])(:|/|$)")
ELEVENLABS_BASE = "https://api.elevenlabs.io"
OPENAI_VOICES = ["alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer"]


def _error_text(r: requests.Response) -> str:
    try:
        data = r.json()
        err = data.get("error") or data.get("detail") or data
        if isinstance(err, dict):
            return str(err.get("message") or err)[:300]
        return str(err)[:300]
    except (ValueError, AttributeError):
        return r.text[:300]


def _post_audio(url: str, *, headers: dict, payload: dict, label: str, out_path: str) -> None:
    last = ""
    for attempt in range(4):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=180)
        except requests.RequestException as e:
            last = f"lỗi mạng {type(e).__name__}"
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code == 200 and r.content:
            with open(out_path, "wb") as f:
                f.write(r.content)
            return
        if r.status_code in (401, 403):
            raise RuntimeError(f"Khoá API của {label} không hợp lệ hoặc không đủ quyền: {_error_text(r)}")
        if r.status_code in (408, 429) or r.status_code >= 500:
            try:
                delay = float(r.headers.get("Retry-After", ""))
            except ValueError:
                delay = 4.0 * (2 ** attempt)
            last = f"máy chủ báo {r.status_code}"
            time.sleep(max(1.0, min(delay, 90.0)))
            continue
        raise RuntimeError(f"{label} trả lỗi {r.status_code}: {_error_text(r)}")
    raise RuntimeError(f"{label} không phản hồi sau nhiều lần thử ({last}).")


# ------------------------------------------------------------------ OpenAI

def openai_voices() -> list[dict]:
    return [{"id": v, "name": v.capitalize(), "gender": "", "lang": "đa ngữ"} for v in OPENAI_VOICES]


def openai_synthesize(text: str, out_path: str, *, voice: str, rate: int = 0, pitch: int = 0) -> None:
    cfg = config.load_settings()["tts_openai"]
    base = (cfg.get("base_url") or "").strip().rstrip("/")
    key = (cfg.get("api_key") or "").strip()
    if not base:
        raise RuntimeError("Chưa nhập địa chỉ API giọng đọc trong Cài đặt → Giọng đọc qua API.")
    if not key and not _LOCAL_RE.match(base):
        raise RuntimeError("Chưa nhập khoá API giọng đọc trong Cài đặt → Giọng đọc qua API.")
    payload = {"model": cfg.get("model") or "gpt-4o-mini-tts", "input": text,
               "voice": voice or cfg.get("voice") or "alloy", "response_format": "mp3"}
    speed = 1.0 + max(-50, min(100, int(rate))) / 100.0
    if abs(speed - 1.0) > 0.01:
        payload["speed"] = round(speed, 2)
    _post_audio(base + "/audio/speech", headers={"Authorization": f"Bearer {key}"} if key else {},
                payload=payload, label="dịch vụ giọng đọc", out_path=out_path)


# ------------------------------------------------------------------ ElevenLabs

def _eleven_cfg() -> tuple[dict, str, str]:
    cfg = config.load_settings()["tts_elevenlabs"]
    key = (cfg.get("api_key") or "").strip()
    if not key:
        raise RuntimeError("Chưa nhập khoá API ElevenLabs trong Cài đặt → Giọng đọc qua API.")
    return cfg, key, (cfg.get("base_url") or ELEVENLABS_BASE).rstrip("/")


def elevenlabs_voices() -> list[dict]:
    cfg, key, base = _eleven_cfg()
    try:
        r = requests.get(base + "/v1/voices", headers={"xi-api-key": key}, timeout=30)
    except requests.RequestException as e:
        raise RuntimeError(f"Không kết nối được tới ElevenLabs ({type(e).__name__}).") from e
    if r.status_code != 200:
        raise RuntimeError(f"ElevenLabs trả lỗi {r.status_code}: {_error_text(r)}")
    out = []
    for v in (r.json().get("voices") or []):
        labels = v.get("labels") or {}
        out.append({"id": v.get("voice_id", ""), "name": v.get("name", ""),
                    "gender": labels.get("gender", ""), "lang": labels.get("language", "")})
    return [v for v in out if v["id"]]


def elevenlabs_synthesize(text: str, out_path: str, *, voice: str, rate: int = 0, pitch: int = 0) -> None:
    cfg, key, base = _eleven_cfg()
    voice = voice or cfg.get("voice") or ""
    if not voice:
        raise RuntimeError("Chưa chọn giọng ElevenLabs. Bấm 'Tải danh sách giọng' trong phần Lồng tiếng.")
    model = cfg.get("model") or "eleven_flash_v2_5"
    payload: dict = {"text": text, "model_id": model}
    if "v2_5" in model:  # chỉ các mô hình v2.5 nhận tham số ép ngôn ngữ
        payload["language_code"] = "vi"
    speed = 1.0 + max(-50, min(100, int(rate))) / 100.0
    if abs(speed - 1.0) > 0.01:
        payload["voice_settings"] = {"speed": round(max(0.7, min(1.2, speed)), 2)}
    _post_audio(f"{base}/v1/text-to-speech/{voice}?output_format=mp3_44100_128",
                headers={"xi-api-key": key}, payload=payload, label="ElevenLabs", out_path=out_path)
