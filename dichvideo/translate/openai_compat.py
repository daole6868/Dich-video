"""Bộ dịch AI qua giao thức Chat Completions tương thích OpenAI.

Dùng chung cho OpenAI, Gemini (cổng tương thích), DeepSeek, Groq, OpenRouter,
Ollama chạy trên máy và mọi máy chủ tự dựng nói cùng giao thức.
"""

from __future__ import annotations

import logging
import re
import threading
import time

import requests

from ..ffmpeg import Cancelled
from .errors import TranslateError

log = logging.getLogger(__name__)

_LOCAL_RE = re.compile(r"^https?://(127\.0\.0\.1|localhost|\[::1\]|0\.0\.0\.0)(:|/|$)")

# Một số máy chủ không nhận response_format hoặc temperature: thử dần từ đầy đủ đến tối giản.
_VARIANTS = (
    {"response_format": {"type": "json_object"}, "temperature": 0.3},
    {"temperature": 0.3},
    {},
)
_variant_for: dict[tuple[str, str], int] = {}


def _headers(cfg: dict) -> dict:
    key = (cfg.get("api_key") or "").strip()
    return {"Authorization": f"Bearer {key}"} if key else {}


def _base(cfg: dict, name: str) -> str:
    base = (cfg.get("base_url") or "").strip().rstrip("/")
    if not base:
        raise TranslateError(f"Chưa nhập địa chỉ API cho {name} trong Cài đặt → Bộ dịch AI.")
    if not (cfg.get("api_key") or "").strip() and not _LOCAL_RE.match(base):
        raise TranslateError(f"Chưa nhập khoá API cho {name} trong Cài đặt → Bộ dịch AI.")
    return base


def _error_text(r: requests.Response) -> str:
    try:
        err = r.json().get("error")
        if isinstance(err, dict):
            return str(err.get("message") or err)[:300]
        if err:
            return str(err)[:300]
    except (ValueError, AttributeError):
        pass
    return r.text[:300]


def complete(system: str, user: str, cfg: dict, *, name: str = "bộ dịch AI",
             cancel: threading.Event | None = None) -> str:
    base = _base(cfg, name)
    model = (cfg.get("model") or "").strip()
    if not model:
        raise TranslateError(f"Chưa nhập tên mô hình cho {name} trong Cài đặt → Bộ dịch AI.")
    timeout = 600 if _LOCAL_RE.match(base) else 180
    cache_key = (base, model)
    start = _variant_for.get(cache_key, 0)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    last = ""
    for vi in range(start, len(_VARIANTS)):
        payload = {"model": model, "messages": messages, **_VARIANTS[vi]}
        for attempt in range(4):
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            try:
                r = requests.post(base + "/chat/completions", json=payload, headers=_headers(cfg),
                                  timeout=timeout)
            except requests.RequestException as e:
                last = f"không kết nối được tới {base} ({type(e).__name__})"
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code == 200:
                _variant_for[cache_key] = vi
                try:
                    msg = r.json()["choices"][0]["message"]
                except (ValueError, KeyError, IndexError, TypeError) as e:
                    raise TranslateError(f"{name} trả về dữ liệu lạ, không đọc được.") from e
                content = msg.get("content")
                if isinstance(content, list):  # vài máy chủ trả mảng các phần văn bản
                    content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
                if not content:
                    raise TranslateError(f"{name} không trả về nội dung (có thể mô hình đã từ chối).")
                return str(content)
            if r.status_code in (401, 403):
                raise TranslateError(f"Khoá API của {name} không hợp lệ hoặc không đủ quyền: {_error_text(r)}")
            if r.status_code == 404:
                raise TranslateError(
                    f"{name}: không tìm thấy mô hình '{model}' hoặc sai địa chỉ API. {_error_text(r)}")
            if r.status_code == 400:
                last = _error_text(r)
                break  # thử biến thể yêu cầu tối giản hơn
            if r.status_code in (408, 409, 429) or r.status_code >= 500:
                try:
                    delay = float(r.headers.get("Retry-After", ""))
                except ValueError:
                    delay = 5.0 * (2 ** attempt)
                last = f"máy chủ báo {r.status_code}: {_error_text(r)}"
                delay = max(1.0, min(delay, 120.0))
                if cancel is not None:
                    if cancel.wait(delay):
                        raise Cancelled()
                else:
                    time.sleep(delay)
                continue
            raise TranslateError(f"{name} trả lỗi {r.status_code}: {_error_text(r)}")
        else:
            raise TranslateError(f"{name} không phản hồi sau nhiều lần thử ({last}).")
    raise TranslateError(f"{name} từ chối yêu cầu: {last}")


def list_models(cfg: dict, name: str = "bộ dịch AI") -> list[str]:
    base = _base(cfg, name)
    try:
        r = requests.get(base + "/models", headers=_headers(cfg), timeout=30)
    except requests.RequestException as e:
        raise TranslateError(f"Không kết nối được tới {base} ({type(e).__name__}).") from e
    if r.status_code != 200:
        raise TranslateError(f"{name} trả lỗi {r.status_code}: {_error_text(r)}")
    try:
        data = r.json()
    except ValueError as e:
        raise TranslateError(f"{name} trả về dữ liệu không phải JSON.") from e
    items = data.get("data") if isinstance(data, dict) else data
    ids = []
    for it in items or []:
        mid = it.get("id") if isinstance(it, dict) else it
        if isinstance(mid, str) and mid:
            ids.append(mid.removeprefix("models/"))
    return sorted(set(ids))
