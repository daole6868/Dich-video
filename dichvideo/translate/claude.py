"""Bộ dịch dùng Claude qua SDK chính thức của Anthropic.

Mặc định dùng ``claude-opus-5-5``. Kết quả được ràng buộc bằng lược đồ JSON
(structured outputs) nên luôn đọc được. Với các mô hình có bộ phân loại an toàn,
bật sẵn cơ chế dự phòng phía máy chủ để một yêu cầu bị từ chối được chạy lại tự động.
"""

from __future__ import annotations

import logging
import threading

import anthropic

from ..ffmpeg import Cancelled
from .errors import TranslateError
from .prompting import RESULT_SCHEMA

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_BASE = "https://api.anthropic.com"
SUGGESTED_MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-2"]

# Các mô hình hỗ trợ tham số fallbacks phía máy chủ (Haiku 5.5 không có).
FALLBACK_MODELS = {"claude-fable-5-2", "claude-fable-5-1", "claude-opus-5-5", "claude-opus-5",
                   "claude-sonnet-5-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def _client(cfg: dict) -> anthropic.Anthropic:
    key = (cfg.get("api_key") or "").strip()
    if not key:
        raise TranslateError("Chưa nhập khoá API Claude trong Cài đặt → Bộ dịch AI.")
    kwargs: dict = {"api_key": key, "max_retries": 3}
    base = (cfg.get("base_url") or "").strip().rstrip("/")
    if base and base != DEFAULT_BASE:
        kwargs["base_url"] = base
    return anthropic.Anthropic(**kwargs)


def _text_of(response) -> str:
    return next((b.text for b in response.content if b.type == "text"), "")


def complete(system: str, user: str, cfg: dict, *, name: str = "Claude",
             cancel: threading.Event | None = None) -> str:
    if cancel is not None and cancel.is_set():
        raise Cancelled()
    client = _client(cfg)
    model = (cfg.get("model") or "").strip() or DEFAULT_MODEL
    messages = [{"role": "user", "content": user}]
    params = dict(
        model=model,
        max_tokens=16000,
        # Lời nhắc hệ thống giống nhau giữa các lô của một video nên đặt điểm lưu đệm ở đây.
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=messages,
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": RESULT_SCHEMA}},
    )
    try:
        try:
            if model in FALLBACK_MODELS:
                response = client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **params)
            else:
                response = client.messages.create(**params)
        except anthropic.BadRequestError as first:
            # Mô hình đời cũ không nhận effort / lược đồ JSON: gửi lại dạng tối giản,
            # lời nhắc đã yêu cầu trả JSON nên vẫn đọc được.
            log.info("Claude từ chối tham số mở rộng (%s); gửi lại dạng tối giản.", first.message)
            response = client.messages.create(model=model, max_tokens=16000, system=system,
                                              messages=messages)
    except anthropic.BadRequestError as e:
        raise TranslateError(f"Claude báo yêu cầu không hợp lệ: {e.message}") from e
    except anthropic.AuthenticationError as e:
        raise TranslateError("Khoá API Claude không hợp lệ. Kiểm tra lại trong Cài đặt → Bộ dịch AI.") from e
    except anthropic.PermissionDeniedError as e:
        raise TranslateError(f"Khoá API Claude không có quyền dùng mô hình '{model}'.") from e
    except anthropic.NotFoundError as e:
        raise TranslateError(f"Claude: không tìm thấy mô hình '{model}'. Kiểm tra tên mô hình.") from e
    except anthropic.RateLimitError as e:
        raise TranslateError("Claude đang giới hạn tần suất với khoá API này. Hãy thử lại sau ít phút.") from e
    except anthropic.APIStatusError as e:
        raise TranslateError(f"Máy chủ Claude báo lỗi {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise TranslateError("Không kết nối được tới máy chủ Claude. Kiểm tra mạng hoặc proxy.") from e

    if response.stop_reason == "refusal":
        category = getattr(getattr(response, "stop_details", None), "category", None)
        raise TranslateError("Claude từ chối dịch đoạn này"
                             + (f" (phân loại: {category})" if category else "") + ".")
    if response.stop_reason == "max_tokens":
        raise TranslateError("Câu trả lời của Claude bị cắt vì quá dài. Hãy giảm số câu mỗi lô dịch.")
    text = _text_of(response)
    if not text:
        raise TranslateError("Claude không trả về nội dung.")
    return text


def list_models(cfg: dict, name: str = "Claude") -> list[str]:
    client = _client(cfg)
    try:
        return sorted(m.id for m in client.models.list())
    except anthropic.AuthenticationError as e:
        raise TranslateError("Khoá API Claude không hợp lệ.") from e
    except anthropic.APIStatusError as e:
        raise TranslateError(f"Máy chủ Claude báo lỗi {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise TranslateError("Không kết nối được tới máy chủ Claude. Kiểm tra mạng hoặc proxy.") from e
