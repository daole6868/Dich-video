#!/usr/bin/env bash
# Dịch Video Studio - tệp khởi động cho Linux và macOS.
# Lần đầu: tự tải công cụ uv, tạo môi trường Python 3.12 riêng trong thư mục này và cài thư viện.
set -u
cd "$(dirname "$0")" || exit 1
ROOT="$(pwd)"
PY="$ROOT/.venv/bin/python"
UV="$ROOT/runtime/uv"
# Bộ đệm tải về của uv đặt trong thư mục ứng dụng, cài xong sẽ được xoá (không để rác ở thư mục người dùng).
export UV_CACHE_DIR="$ROOT/runtime/cache"

say() { printf '%s\n' "$*"; }

download_uv() {
  local os arch target url tmp
  os="$(uname -s)"; arch="$(uname -m)"
  case "$os" in
    Linux)  case "$arch" in x86_64|amd64) target="x86_64-unknown-linux-gnu";; aarch64|arm64) target="aarch64-unknown-linux-gnu";; *) return 1;; esac;;
    Darwin) case "$arch" in arm64) target="aarch64-apple-darwin";; x86_64) target="x86_64-apple-darwin";; *) return 1;; esac;;
    *) return 1;;
  esac
  url="https://github.com/astral-sh/uv/releases/latest/download/uv-$target.tar.gz"
  mkdir -p "$ROOT/runtime" || return 1
  tmp="$ROOT/runtime/uv-tai-ve.tar.gz"
  say "  Đang tải công cụ cài đặt uv…"
  if command -v curl >/dev/null 2>&1; then curl -fsSL "$url" -o "$tmp" || return 1
  elif command -v wget >/dev/null 2>&1; then wget -q "$url" -O "$tmp" || return 1
  else return 1; fi
  tar -xzf "$tmp" -C "$ROOT/runtime" --strip-components=1 || return 1
  rm -f "$tmp"
  [ -x "$UV" ]
}

if [ ! -x "$PY" ]; then
  say ""
  say "=== Dịch Video Studio: cài đặt lần đầu (cần mạng, mất vài phút) ==="
  if [ ! -x "$UV" ]; then
    if command -v uv >/dev/null 2>&1; then UV="$(command -v uv)"; else download_uv || UV=""; fi
  fi
  if [ -n "$UV" ]; then
    say "  Đang tạo môi trường Python 3.12…"
    "$UV" venv --python 3.12 "$ROOT/.venv" || true
  fi
  if [ ! -x "$PY" ]; then
    say "  Không dùng được uv; thử Python có sẵn trên máy…"
    for cand in python3.12 python3.13 python3.11 python3; do
      if command -v "$cand" >/dev/null 2>&1; then "$cand" -m venv "$ROOT/.venv" 2>/dev/null && break; fi
    done
  fi
  if [ ! -x "$PY" ]; then
    say ""
    say "[LỖI] Không tạo được môi trường Python."
    say "Hãy cài Python 3.12 (https://www.python.org/downloads/) rồi chạy lại tệp này."
    exit 1
  fi
fi

"$PY" "$ROOT/tools/bootstrap.py" --uv "${UV:-}" || { say ""; say "[LỖI] Cài thư viện chưa xong. Kiểm tra mạng rồi chạy lại tệp này."; exit 1; }
exec "$PY" "$ROOT/run.py" "$@"
