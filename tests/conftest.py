"""Cấu hình chung cho bộ test: dữ liệu chạy nằm trong thư mục tạm, không đụng dữ liệu thật."""

import os
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

# Tên thư mục cố ý có dấu tiếng Việt và khoảng trắng: nhiều máy Windows có tên người dùng như vậy,
# nên mọi test đều phải chạy được với đường dẫn kiểu này.
_tmp = tempfile.mkdtemp(prefix="dịch video thử-")
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


@pytest.fixture(scope="session")
def base():
    """Địa chỉ của một máy chủ ứng dụng thật chạy trong tiến trình test."""
    import requests
    import uvicorn

    from dichvideo.server import create_app

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    app = create_app()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    app.state.server = server
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            requests.get(url + "/api/jobs", timeout=1)
            break
        except requests.RequestException:
            time.sleep(0.1)
    yield url
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture(scope="session")
def http():
    import requests

    s = requests.Session()
    s.trust_env = False
    return s


@pytest.fixture(scope="session")
def wait_idle(http, base):
    """Hàm chờ một dự án chạy xong rồi trả về thông tin dự án."""

    def _wait(pid: str, timeout: float = 180) -> dict:
        end = time.time() + timeout
        while time.time() < end:
            p = http.get(f"{base}/api/projects/{pid}").json()
            if not p["busy"]:
                return p
            time.sleep(0.3)
        raise AssertionError("dự án không chạy xong trong thời gian cho phép")

    return _wait
