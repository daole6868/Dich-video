"""Cấu hình chung cho bộ test: dữ liệu chạy nằm trong thư mục tạm, không đụng dữ liệu thật."""

import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="dichvideo-test-")
os.environ["DICHVIDEO_DATA"] = _tmp
# Máy chủ giả lập chạy ở 127.0.0.1 nên không được đi qua proxy.
for _k in ("NO_PROXY", "no_proxy"):
    os.environ[_k] = ",".join(x for x in (os.environ.get(_k, ""), "127.0.0.1", "localhost") if x)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from dichvideo import config  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_settings():
    """Mỗi test bắt đầu với cài đặt mặc định."""
    config.ensure_dirs()
    for f in (config.SETTINGS_FILE, config.GLOSSARY_FILE):
        if f.exists():
            f.unlink()
    config._cache = None
    yield
    config._cache = None
