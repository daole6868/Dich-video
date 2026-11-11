#!/usr/bin/env bash
# Dịch Video Studio - bấm đúp tệp này trên macOS để chạy.
cd "$(dirname "$0")" || exit 1
bash ./chay_linux.sh "$@"
status=$?
if [ $status -ne 0 ]; then
  echo ""
  read -r -p "Nhấn Enter để đóng cửa sổ…" _
fi
exit $status
