"""Đường dẫn, cấu hình mặc định và việc đọc/ghi cài đặt.

Mọi dữ liệu chạy (dự án, mô hình, cài đặt) nằm trong thư mục ``data/`` cạnh
mã nguồn, nên có thể chép cả thư mục ứng dụng sang máy khác mà không mất gì.
"""

from __future__ import annotations

import copy
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from . import fileops

ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = Path(__file__).resolve().parent
WEB_DIR = PACKAGE_DIR / "web"
FONTS_DIR = ROOT / "fonts"

DATA_DIR = Path(os.environ.get("DICHVIDEO_DATA") or (ROOT / "data")).resolve()
PROJECTS_DIR = DATA_DIR / "projects"
MODELS_DIR = DATA_DIR / "models"
USER_FONTS_DIR = DATA_DIR / "fonts"
LOG_DIR = DATA_DIR / "logs"
TMP_DIR = DATA_DIR / "tmp"
SETTINGS_FILE = DATA_DIR / "settings.json"
GLOSSARY_FILE = DATA_DIR / "glossary.json"


def ensure_dirs() -> None:
    for d in (DATA_DIR, PROJECTS_DIR, MODELS_DIR, USER_FONTS_DIR, LOG_DIR, TMP_DIR):
        d.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------
# Danh mục cố định dùng chung cho backend và giao diện
# --------------------------------------------------------------------------

SOURCE_LANGS = [
    {"id": "zh", "name": "Tiếng Trung (Phổ thông)"},
    {"id": "yue", "name": "Tiếng Quảng Đông"},
    {"id": "auto", "name": "Tự nhận diện"},
    {"id": "en", "name": "Tiếng Anh"},
    {"id": "ja", "name": "Tiếng Nhật"},
    {"id": "ko", "name": "Tiếng Hàn"},
]

# Kích thước gần đúng (MB) để hiển thị tiến độ tải khi không hỏi được máy chủ.
WHISPER_MODELS = [
    {"id": "large-v3-turbo", "name": "Turbo (khuyên dùng)", "size_mb": 1620,
     "desc": "Chính xác cao, tốc độ gần bằng bản Nhỏ. Cần khoảng 3 GB RAM."},
    {"id": "large-v3", "name": "Lớn v3 (chính xác nhất)", "size_mb": 3090,
     "desc": "Chính xác nhất nhưng chậm trên máy không có card NVIDIA."},
    {"id": "medium", "name": "Vừa", "size_mb": 1530,
     "desc": "Chất lượng khá, chậm hơn Turbo."},
    {"id": "small", "name": "Nhỏ", "size_mb": 484,
     "desc": "Nhẹ, dành cho máy yếu (4 GB RAM)."},
    {"id": "base", "name": "Cơ bản", "size_mb": 145,
     "desc": "Rất nhẹ, độ chính xác thấp."},
    {"id": "tiny", "name": "Siêu nhẹ", "size_mb": 75,
     "desc": "Chỉ để thử nhanh."},
]

# Nhà cung cấp LLM dùng giao thức tương thích OpenAI (trừ Anthropic có API riêng).
LLM_PROVIDERS = {
    "openai": {"name": "OpenAI (GPT)", "base_url": "https://api.openai.com/v1",
               "model": "gpt-4o-mini", "key_url": "https://platform.openai.com/api-keys"},
    "gemini": {"name": "Google Gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
               "model": "gemini-2.5-flash", "key_url": "https://aistudio.google.com/apikey"},
    "deepseek": {"name": "DeepSeek", "base_url": "https://api.deepseek.com/v1",
                 "model": "deepseek-chat", "key_url": "https://platform.deepseek.com/api_keys"},
    "anthropic": {"name": "Anthropic Claude", "base_url": "https://api.anthropic.com",
                  "model": "claude-opus-5-5", "key_url": "https://platform.claude.com/settings/keys",
                  "models": ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-2"]},
    "groq": {"name": "Groq", "base_url": "https://api.groq.com/openai/v1",
             "model": "llama-3.3-70b-versatile", "key_url": "https://console.groq.com/keys"},
    "openrouter": {"name": "OpenRouter", "base_url": "https://openrouter.ai/api/v1",
                   "model": "google/gemini-2.5-flash", "key_url": "https://openrouter.ai/keys"},
    "ollama": {"name": "Ollama (chạy trên máy)", "base_url": "http://127.0.0.1:11434/v1",
               "model": "qwen2.5:7b", "key_url": ""},
    "custom": {"name": "Tuỳ chỉnh (tương thích OpenAI)", "base_url": "",
               "model": "", "key_url": ""},
}

TRANSLATE_STYLES = [
    {"id": "auto", "name": "Tự động", "hint": ""},
    {"id": "drama_modern", "name": "Phim hiện đại",
     "hint": "Phim/short drama bối cảnh hiện đại. Lời thoại đời thường, xưng hô tự nhiên theo quan hệ nhân vật (anh/em, tôi/cô, mẹ/con...)."},
    {"id": "drama_ancient", "name": "Phim cổ trang / tiên hiệp",
     "hint": "Phim cổ trang, kiếm hiệp, tiên hiệp. Dùng văn phong cổ trang, tên người, địa danh, chiêu thức phiên âm Hán-Việt; xưng hô ta/ngươi, huynh/muội, sư phụ/đồ nhi..."},
    {"id": "review", "name": "Review / tóm tắt phim",
     "hint": "Video thuyết minh, review, tóm tắt phim. Giọng kể chuyện cuốn hút, mạch lạc, câu ngắn dễ đọc thành tiếng."},
    {"id": "documentary", "name": "Tài liệu / tin tức",
     "hint": "Phim tài liệu, tin tức, phóng sự. Văn phong trang trọng, chính xác, khách quan."},
    {"id": "vlog", "name": "Vlog / đời sống",
     "hint": "Vlog, ẩm thực, du lịch, đời sống. Văn nói gần gũi, vui tươi."},
    {"id": "education", "name": "Bài giảng / hướng dẫn",
     "hint": "Bài giảng, hướng dẫn kỹ thuật. Rõ ràng, dùng thuật ngữ chuyên ngành chuẩn tiếng Việt."},
    {"id": "ecommerce", "name": "Bán hàng / quảng cáo",
     "hint": "Video giới thiệu sản phẩm, livestream bán hàng. Ngắn gọn, hấp dẫn, thuyết phục."},
]

DEFAULT_PROJECT_SETTINGS: dict[str, Any] = {
    "source_lang": "zh",
    "subtitle_source": "auto",  # auto (tự chọn) | asr (nghe giọng nói) | ocr (đọc phụ đề cứng)
    "asr": {
        "engine": "local",  # local | api
        "model": "large-v3-turbo",
        "device": "auto",  # auto | cpu | cuda
        "beam_size": 5,
        "vad": True,
        "prompt": "",
    },
    "segment": {
        "max_chars": 22,  # số ký tự tối đa mỗi câu gốc (tiếng Trung)
        "max_duration": 7.0,
        "pause": 0.6,
    },
    "ocr": {
        "region": None,  # [x, y, w, h] theo tỉ lệ 0..1; None = 1/4 dưới khung hình
        "fps": 4,
    },
    "translate": {
        "engine": "google",
        "style": "auto",
        "context": "",
        "use_glossary": True,
        "batch_size": 30,
    },
    "dub": {
        "enabled": True,
        "engine": "edge",
        "voice": "vi-VN-HoaiMyNeural",
        "rate": 0,  # % nhanh/chậm so với giọng gốc của engine
        "pitch": 0,  # Hz
        "max_speed": 1.5,  # hệ số tăng tốc tối đa khi câu dịch dài hơn khoảng trống
        "original_volume": 15,  # % âm lượng tiếng gốc
        "dub_volume": 100,
        "ducking": True,
        "background": "original",  # original (giữ tiếng gốc làm nền) | mute (chỉ còn tiếng lồng)
    },
    "subtitle": {
        "burn": True,
        "bilingual": False,
        "font": "Be Vietnam Pro",
        "size": 46,  # cỡ chữ (em) tính bằng px trên video cao 1080
        "bold": True,
        "italic": False,
        "uppercase": False,
        "color": "#FFFFFF",
        "outline_color": "#000000",
        "outline": 3,
        "shadow": 1,
        "box": False,
        "box_color": "#000000",
        "box_opacity": 65,
        "align": "bottom",  # bottom | top | middle
        "margin_v": 6.0,  # % chiều cao
        "margin_h": 5.0,  # % chiều rộng
        "secondary_scale": 70,
        "secondary_color": "#FFE27A",
    },
    # Tự thêm vùng che lên phụ đề gốc khi lời thoại được đọc từ phụ đề cứng (và chưa có vùng che nào).
    "auto_cover": True,
    "cover": [],  # [{x, y, w, h, mode: blur|box, color, strength}]
    # Khi nào bật vùng che: always (suốt video) | subtitle (chỉ lúc có câu thoại) |
    # auto (subtitle nếu lời thoại lấy từ phụ đề cứng, ngược lại always)
    "cover_when": "auto",
    "logo": {
        "enabled": False,
        "file": "",
        "position": "top-right",
        "scale": 14,  # % chiều rộng video
        "opacity": 100,
        "margin": 3,  # % cạnh ngắn
    },
    "output": {
        "resolution": "source",  # source | 2160 | 1440 | 1080 | 720 | 480
        "encoder": "auto",  # auto | cpu | nvenc | qsv | amf | videotoolbox
        "quality": "medium",  # high (tệp lớn) | medium | small
        "speed": "medium",  # fast | medium | slow
        "soft_subs": False,
        "audio_bitrate": 192,
    },
    "stop_for_review": False,
}

DEFAULT_SETTINGS: dict[str, Any] = {
    "defaults": DEFAULT_PROJECT_SETTINGS,
    "llm": {pid: {"api_key": "", "base_url": p["base_url"], "model": p["model"]}
            for pid, p in LLM_PROVIDERS.items()},
    "asr_api": {
        "base_url": "https://api.groq.com/openai/v1",
        "api_key": "",
        "model": "whisper-large-v3",
    },
    "tts_openai": {
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "model": "gpt-4o-mini-tts",
        "voice": "alloy",
    },
    "tts_elevenlabs": {
        "api_key": "",
        "model": "eleven_flash_v2_5",
        "voice": "",
    },
    "network": {
        "proxy": "",
        "hf_endpoint": "",
    },
    "advanced": {
        "ffmpeg_path": "",
        "cpu_threads": 0,
        "tts_concurrency": 4,
    },
    "ui": {"theme": "auto"},
}

# Các khoá bí mật: khi gửi ra giao diện chỉ hiện 4 ký tự cuối.
SECRET_PATHS = [("llm", pid, "api_key") for pid in LLM_PROVIDERS] + [
    ("asr_api", "api_key"),
    ("tts_openai", "api_key"),
    ("tts_elevenlabs", "api_key"),
]
MASK_PREFIX = "••••"


def deep_merge(base: Any, override: Any) -> Any:
    """Trộn ``override`` lên ``base`` (đệ quy với dict), trả về bản sao mới."""
    if isinstance(base, dict) and isinstance(override, dict):
        out = {k: copy.deepcopy(v) for k, v in base.items()}
        for k, v in override.items():
            out[k] = deep_merge(base[k], v) if k in base else copy.deepcopy(v)
        return out
    return copy.deepcopy(override)


def _conform(value: Any, template: Any) -> Any:
    """Ép kiểu giá trị theo mẫu mặc định để file cài đặt hỏng không làm sập ứng dụng."""
    if isinstance(template, dict):
        if not isinstance(value, dict):
            return copy.deepcopy(template)
        out = {}
        for k, tv in template.items():
            out[k] = _conform(value[k], tv) if k in value else copy.deepcopy(tv)
        for k, v in value.items():  # giữ khoá lạ (tương thích phiên bản sau)
            if k not in out:
                out[k] = v
        return out
    if isinstance(template, bool):
        return bool(value) if isinstance(value, (bool, int)) else template
    if isinstance(template, int) and not isinstance(template, bool):
        if isinstance(value, bool):
            return template
        if isinstance(value, (int, float)):
            return int(value)
        return template
    if isinstance(template, float):
        if isinstance(value, bool):
            return template
        return float(value) if isinstance(value, (int, float)) else template
    if isinstance(template, str):
        return value if isinstance(value, str) else template
    return value  # None / list: nhận nguyên


_lock = threading.RLock()
_cache: dict[str, Any] | None = None


def write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp{os.getpid()}_{threading.get_ident()}")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    try:
        fileops.replace(tmp, path)
    except OSError:
        fileops.remove(tmp)
        raise


def read_json(path: Path, default: Any = None) -> Any:
    for attempt in range(4):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except PermissionError:  # Windows: tệp đang bị chương trình khác giữ trong chốc lát
            time.sleep(0.05 * (attempt + 1))
        except (OSError, ValueError):
            return default
    return default


def load_settings() -> dict[str, Any]:
    global _cache
    with _lock:
        if _cache is None:
            raw = read_json(SETTINGS_FILE, {})
            _cache = _conform(raw if isinstance(raw, dict) else {}, DEFAULT_SETTINGS)
        return copy.deepcopy(_cache)


def save_settings(new: dict[str, Any]) -> dict[str, Any]:
    global _cache
    with _lock:
        merged = _conform(deep_merge(load_settings(), new), DEFAULT_SETTINGS)
        write_json_atomic(SETTINGS_FILE, merged)
        _cache = merged
        apply_network_settings(merged)
        return copy.deepcopy(merged)


def _get_path(d: dict, path: tuple) -> Any:
    for k in path:
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def _set_path(d: dict, path: tuple, value: Any) -> None:
    for k in path[:-1]:
        d = d.setdefault(k, {})
    d[path[-1]] = value


def mask_secret(value: str) -> str:
    if not value:
        return ""
    return MASK_PREFIX + value[-4:] if len(value) > 8 else MASK_PREFIX


def public_settings() -> dict[str, Any]:
    """Cài đặt để gửi ra giao diện (đã che các khoá API)."""
    s = load_settings()
    for path in SECRET_PATHS:
        v = _get_path(s, path)
        if isinstance(v, str):
            _set_path(s, path, mask_secret(v))
    return s


def update_settings_from_client(incoming: dict[str, Any]) -> dict[str, Any]:
    """Lưu cài đặt từ giao diện; khoá API còn ở dạng che nghĩa là giữ nguyên."""
    incoming = copy.deepcopy(incoming)
    current = load_settings()
    for path in SECRET_PATHS:
        v = _get_path(incoming, path)
        if isinstance(v, str) and v.startswith(MASK_PREFIX):
            _set_path(incoming, path, _get_path(current, path) or "")
        elif isinstance(v, str):
            _set_path(incoming, path, v.strip())
    save_settings(incoming)
    return public_settings()


def apply_network_settings(settings: dict[str, Any] | None = None) -> None:
    """Đưa proxy / máy chủ gương Hugging Face trong cài đặt vào biến môi trường."""
    s = settings or load_settings()
    net = s.get("network", {})
    proxy = (net.get("proxy") or "").strip()
    if proxy:
        for k in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
            os.environ[k] = proxy
    hf = (net.get("hf_endpoint") or "").strip().rstrip("/")
    if hf:
        os.environ["HF_ENDPOINT"] = hf


def env_proxy() -> str | None:
    return os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or None


def new_project_settings() -> dict[str, Any]:
    return copy.deepcopy(load_settings()["defaults"])


def conform_project_settings(value: Any) -> dict[str, Any]:
    return _conform(value, DEFAULT_PROJECT_SETTINGS)
