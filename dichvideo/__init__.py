"""Dịch Video Studio — công cụ dịch video tiếng Trung sang tiếng Việt."""

__version__ = "1.0.0"
APP_NAME = "Dịch Video Studio"

# Phải đặt trước khi thư viện tương ứng được nạp, nên để ngay ở đây.
# ONNX Runtime (dùng cho OCR và giọng Piper) mặc định gửi số liệu sử dụng về Microsoft và tạo mã định
# danh máy trong thư mục người dùng; ứng dụng này không gửi gì ngoài những thứ ghi trong README.
import os as _os

_os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")
_os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
