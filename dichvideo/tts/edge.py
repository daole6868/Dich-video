"""Giọng đọc Microsoft Edge (thư viện edge-tts): miễn phí, cần mạng.

Đây là dịch vụ đọc văn bản của trình duyệt Edge, không phải API có cam kết; có thể
bị thay đổi hoặc giới hạn. Mô-đun gọi vừa phải và lùi lại khi gặp lỗi.
"""

from __future__ import annotations

import asyncio
import logging
import os

from .. import config

log = logging.getLogger(__name__)

# Danh sách dự phòng khi không hỏi được máy chủ.
FALLBACK_VOICES = [
    {"id": "vi-VN-HoaiMyNeural", "name": "Hoài My", "gender": "female", "lang": "vi-VN"},
    {"id": "vi-VN-NamMinhNeural", "name": "Nam Minh", "gender": "male", "lang": "vi-VN"},
]
_voices_cache: list[dict] | None = None


class NothingToSay(Exception):
    """Văn bản không có gì đọc được (chỉ dấu câu, ký hiệu)."""


def _run(coro):
    """Chạy coroutine từ luồng thường (luồng xử lý không có vòng lặp sự kiện)."""
    return asyncio.run(coro)


def list_voices(refresh: bool = False) -> list[dict]:
    global _voices_cache
    if _voices_cache is not None and not refresh:
        return _voices_cache
    try:
        import edge_tts

        raw = _run(asyncio.wait_for(edge_tts.list_voices(proxy=config.env_proxy()), timeout=20))
        voices = []
        for v in raw:
            short = v.get("ShortName", "")
            locale = v.get("Locale", "")
            if not (locale.startswith("vi-") or "Multilingual" in short):
                continue
            label = short.split("-")[-1].replace("MultilingualNeural", "").replace("Neural", "")
            if locale.startswith("vi-"):
                label = {"HoaiMy": "Hoài My", "NamMinh": "Nam Minh"}.get(label, label)
            else:
                label += " (đa ngữ)"
            voices.append({"id": short, "name": label,
                           "gender": "female" if v.get("Gender") == "Female" else "male", "lang": locale})
        voices.sort(key=lambda v: (not v["lang"].startswith("vi-"), v["name"]))
        if voices:
            _voices_cache = voices
            return voices
    except Exception as e:  # noqa: BLE001 - mất mạng thì dùng danh sách dự phòng
        log.warning("Không lấy được danh sách giọng Edge: %s", e)
    return FALLBACK_VOICES


async def _synthesize(text: str, out_path: str, voice: str, rate: int, pitch: int) -> None:
    import edge_tts

    last: Exception | None = None
    for attempt in range(4):
        try:
            com = edge_tts.Communicate(text, voice, rate=f"{int(rate):+d}%", pitch=f"{int(pitch):+d}Hz",
                                       proxy=config.env_proxy())
            await com.save(out_path)
            if os.path.isfile(out_path) and os.path.getsize(out_path) > 200:
                return
            last = RuntimeError("tệp âm thanh rỗng")
        except edge_tts.exceptions.NoAudioReceived as e:
            # Máy chủ không trả âm thanh: văn bản không đọc được, thử lại cũng vậy.
            raise NothingToSay(text) from e
        except Exception as e:  # noqa: BLE001 - lỗi mạng tạm thời: lùi lại rồi thử tiếp
            last = e
        await asyncio.sleep(1.5 * (2 ** attempt))
    raise RuntimeError(
        "Không tạo được giọng đọc Edge sau nhiều lần thử. Kiểm tra mạng, hoặc chuyển sang "
        f"giọng ngoại tuyến Piper. Chi tiết: {type(last).__name__}: {str(last)[:200]}")


def synthesize(text: str, out_path: str, *, voice: str, rate: int = 0, pitch: int = 0) -> None:
    rate = max(-50, min(100, int(rate)))
    pitch = max(-50, min(50, int(pitch)))
    _run(_synthesize(text, out_path, voice or FALLBACK_VOICES[0]["id"], rate, pitch))
