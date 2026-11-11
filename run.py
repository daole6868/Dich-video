"""Khởi chạy Dịch Video Studio.

    python run.py                 mở giao diện tại http://127.0.0.1:8760
    python run.py --port 9000     đổi cổng
    python run.py --lan           cho máy khác trong mạng nội bộ truy cập
    python run.py --no-browser    không tự mở trình duyệt
    python run.py --check         tự kiểm tra bản cài (không cần mạng)
"""

from __future__ import annotations

import argparse
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
    for _ in range(20):  # cổng bận (đã mở một bản khác?) thì thử cổng kế tiếp
        if port_free(host, port):
            break
        port += 1
    else:
        print(f"Không tìm được cổng trống quanh {args.port}.")
        return 1

    setup_logging()
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
