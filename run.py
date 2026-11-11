"""Khởi chạy Dịch Video Studio.

    python run.py                 mở giao diện tại http://127.0.0.1:8760
    python run.py --port 9000     đổi cổng
    python run.py --lan           cho máy khác trong mạng nội bộ truy cập
    python run.py --no-browser    không tự mở trình duyệt
    python run.py --check         tự kiểm tra bản cài (không cần mạng)
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import webbrowser


def utf8_console() -> None:
    """Cửa sổ dòng lệnh Windows mặc định không in được tiếng Việt có dấu: chuyển sang UTF-8."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def keep_console_responsive() -> None:
    """Windows: bấm chuột vào cửa sổ dòng lệnh làm chương trình "đứng hình" cho tới khi nhấn Enter
    (chế độ QuickEdit) - người dùng dễ tưởng ứng dụng bị treo. Tắt chế độ đó trong lúc chạy."""
    if sys.platform != "win32":
        return
    try:
        import atexit
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.windll.kernel32
        k32.GetStdHandle.argtypes = [wintypes.DWORD]
        k32.GetStdHandle.restype = wintypes.HANDLE
        k32.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        k32.GetConsoleMode.restype = wintypes.BOOL
        k32.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k32.SetConsoleMode.restype = wintypes.BOOL
        handle = k32.GetStdHandle(0xFFFFFFF6)  # STD_INPUT_HANDLE (-10)
        mode = wintypes.DWORD()
        if not handle or not k32.GetConsoleMode(handle, ctypes.byref(mode)):
            return  # không chạy trong cửa sổ dòng lệnh
        quick_edit, extended = 0x0040, 0x0080
        if k32.SetConsoleMode(handle, (mode.value & ~quick_edit) | extended):
            atexit.register(k32.SetConsoleMode, handle, mode.value)  # trả lại như cũ khi thoát
    except Exception:  # noqa: BLE001 - chỉ là tiện ích, không được cản việc khởi động
        pass


def running_instance(port: int) -> bool:
    """Cổng đang bận vì chính ứng dụng này (cùng thư mục dữ liệu) đã chạy sẵn?"""
    import json
    import urllib.request

    from dichvideo import APP_NAME, config

    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{port}/api/ping", timeout=2) as resp:
            info = json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - cổng do chương trình khác dùng
        return False
    same_data = os.path.normcase(str(info.get("data_dir", ""))) == os.path.normcase(str(config.DATA_DIR))
    return info.get("app") == APP_NAME and same_data


def port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def main() -> int:
    utf8_console()
    parser = argparse.ArgumentParser(description="Dịch Video Studio - dịch video tiếng Trung sang tiếng Việt")
    parser.add_argument("--host", default="127.0.0.1", help="địa chỉ lắng nghe (mặc định chỉ máy này)")
    parser.add_argument("--port", type=int, default=8760, help="cổng (mặc định 8760)")
    parser.add_argument("--lan", action="store_true", help="cho phép máy khác trong mạng nội bộ truy cập")
    parser.add_argument("--no-browser", action="store_true", help="không tự mở trình duyệt")
    parser.add_argument("--check", action="store_true", help="tự kiểm tra bản cài rồi thoát (không cần mạng)")
    args = parser.parse_args()

    if sys.version_info < (3, 10):
        print("Cần Python 3.10 trở lên. Hãy chạy bằng tệp khởi động kèm theo để tự cài đúng phiên bản.")
        return 1
    try:
        import uvicorn

        from dichvideo import APP_NAME, __version__
        from dichvideo.server import create_app, setup_logging
    except ImportError as e:
        print(f"Thiếu thư viện: {e}\nHãy chạy tệp khởi động (Chay_Windows.bat / Chay_macOS.command / "
              "chay_linux.sh) để cài đặt tự động.")
        return 1

    if args.check:
        from dichvideo import selfcheck

        return selfcheck.run()

    host = "0.0.0.0" if args.lan else args.host
    port = args.port
    if not port_free(host, port) and running_instance(port):
        # Bấm đúp tệp khởi động lần nữa: không mở bản thứ hai (hai bản cùng ghi một thư mục dữ liệu
        # sẽ giẫm chân nhau), chỉ mở lại giao diện của bản đang chạy.
        url = f"http://127.0.0.1:{port}"
        print(f"{APP_NAME} đang chạy sẵn tại {url} - mở lại giao diện.")
        if not args.no_browser:
            webbrowser.open(url)
        return 0
    for _ in range(20):  # cổng do chương trình khác dùng thì thử cổng kế tiếp
        if port_free(host, port):
            break
        port += 1
    else:
        print(f"Không tìm được cổng trống quanh {args.port}.")
        return 1

    setup_logging()
    keep_console_responsive()
    app = create_app(allow_lan=args.lan or host not in ("127.0.0.1", "localhost"))
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning", access_log=False))
    app.state.server = server
    url = f"http://127.0.0.1:{port}"
    print("=" * 62)
    print(f"  {APP_NAME} {__version__}")
    print(f"  Giao diện: {url}")
    if args.lan:
        print(f"  Máy khác trong mạng nội bộ: http://<IP máy này>:{port}")
    print("  Giữ cửa sổ này mở trong lúc dùng. Nhấn Ctrl+C để thoát.")
    print("=" * 62)
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    try:
        server.run()
    finally:
        # Thoát bằng Ctrl+C hay nút "Tắt ứng dụng": dừng việc đang chạy (kể cả ffmpeg) trước khi thoát.
        from dichvideo import jobs

        jobs.manager.shutdown(wait=8.0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
