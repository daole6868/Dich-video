"""Tìm và gọi ffmpeg: dò thông tin tệp, chạy có tiến độ, trích âm thanh/khung hình.

Chỉ dùng tệp thực thi ``ffmpeg`` (không cần ffprobe) để gói ``imageio-ffmpeg``
cài qua pip là đủ, người dùng không phải tự cài ffmpeg.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Iterable, Sequence

from . import config

log = logging.getLogger(__name__)

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


class FFmpegError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# Tiến trình con
# --------------------------------------------------------------------------

_job_handle = None
_job_lock = threading.Lock()


def _tie_to_this_process(proc: subprocess.Popen) -> None:
    """Windows: cho tiến trình con tự tắt khi ứng dụng bị đóng (kể cả khi bấm nút X của cửa sổ).

    ffmpeg được chạy không kèm cửa sổ dòng lệnh nên không nhận được tín hiệu Ctrl+C hay "đóng cửa sổ";
    nếu không làm gì, nó sẽ tiếp tục mã hoá ngầm sau khi ứng dụng đã tắt. Gắn nó vào một "job object"
    có cờ KILL_ON_JOB_CLOSE: khi tiến trình của ứng dụng kết thúc vì bất cứ lý do gì, Windows đóng
    job và tắt luôn các tiến trình trong đó. Trên Linux/macOS, đóng cửa sổ dòng lệnh hay Ctrl+C đã
    gửi tín hiệu tới cả nhóm tiến trình nên không cần.
    """
    if sys.platform != "win32":
        return
    global _job_handle
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.AssignProcessToJobObject.restype = wintypes.BOOL
        with _job_lock:
            if _job_handle is None:
                class BasicLimits(ctypes.Structure):
                    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                                ("PerJobUserTimeLimit", ctypes.c_longlong),
                                ("LimitFlags", wintypes.DWORD),
                                ("MinimumWorkingSetSize", ctypes.c_size_t),
                                ("MaximumWorkingSetSize", ctypes.c_size_t),
                                ("ActiveProcessLimit", wintypes.DWORD),
                                ("Affinity", ctypes.c_size_t),
                                ("PriorityClass", wintypes.DWORD),
                                ("SchedulingClass", wintypes.DWORD)]

                class ExtendedLimits(ctypes.Structure):
                    _fields_ = [("BasicLimitInformation", BasicLimits),
                                ("IoInfo", ctypes.c_ulonglong * 6),
                                ("ProcessMemoryLimit", ctypes.c_size_t),
                                ("JobMemoryLimit", ctypes.c_size_t),
                                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                                ("PeakJobMemoryUsed", ctypes.c_size_t)]

                k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
                k32.CreateJobObjectW.restype = wintypes.HANDLE
                k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
                k32.SetInformationJobObject.restype = wintypes.BOOL
                job = k32.CreateJobObjectW(None, None)
                if not job:
                    raise ctypes.WinError(ctypes.get_last_error())
                limits = ExtendedLimits()
                limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                # 9 = JobObjectExtendedLimitInformation
                if not k32.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                    raise ctypes.WinError(ctypes.get_last_error())
                _job_handle = job  # giữ mở suốt đời ứng dụng; Windows tự đóng khi tiến trình kết thúc
        if not k32.AssignProcessToJobObject(_job_handle, int(proc._handle)):  # type: ignore[attr-defined]
            raise ctypes.WinError(ctypes.get_last_error())
    except Exception as e:  # noqa: BLE001 - chỉ là lớp bảo vệ thêm, không được làm hỏng việc chính
        log.debug("Không gắn được tiến trình con vào job: %s", e)


def spawn(cmd: Sequence[str], **kwargs) -> subprocess.Popen:
    """``subprocess.Popen`` cho ffmpeg: không hiện cửa sổ, và tự tắt theo ứng dụng trên Windows."""
    proc = subprocess.Popen(list(cmd), creationflags=_NO_WINDOW, **kwargs)
    _tie_to_this_process(proc)
    return proc


class Cancelled(Exception):
    """Người dùng huỷ tác vụ."""


_ffmpeg_path: str | None = None
_caps: dict | None = None
_lock = threading.Lock()


def _candidates() -> Iterable[str]:
    s = config.load_settings()
    custom = (s.get("advanced", {}).get("ffmpeg_path") or "").strip()
    if custom:
        yield custom
    exe = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    yield str(config.ROOT / "tools" / exe)
    try:
        import imageio_ffmpeg

        yield imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001 - gói tuỳ chọn, thiếu thì dùng ffmpeg hệ thống
        pass
    found = shutil.which("ffmpeg")
    if found:
        yield found


def _works(path: str) -> bool:
    try:
        r = subprocess.run([path, "-hide_banner", "-version"], capture_output=True,
                           timeout=30, creationflags=_NO_WINDOW)
        return r.returncode == 0 and b"ffmpeg version" in r.stdout
    except (OSError, subprocess.SubprocessError):
        return False


def ffmpeg_path() -> str:
    """Đường dẫn ffmpeg dùng được; báo lỗi rõ ràng nếu không tìm thấy."""
    global _ffmpeg_path
    with _lock:
        if _ffmpeg_path:
            return _ffmpeg_path
        for cand in _candidates():
            if cand and os.path.isfile(cand) and _works(cand):
                _ffmpeg_path = cand
                log.info("Dùng ffmpeg: %s", cand)
                return cand
        raise FFmpegError(
            "Không tìm thấy ffmpeg. Hãy chạy lại tệp khởi động để cài đủ thư viện, "
            "hoặc đặt đường dẫn ffmpeg trong Cài đặt → Nâng cao."
        )


def reset_cache() -> None:
    global _ffmpeg_path, _caps
    with _lock:
        _ffmpeg_path = None
        _caps = None


def _run_capture(args: Sequence[str], timeout: float = 120) -> subprocess.CompletedProcess:
    return subprocess.run([ffmpeg_path(), "-hide_banner", *args], capture_output=True,
                          timeout=timeout, creationflags=_NO_WINDOW)


def capabilities() -> dict:
    """Phiên bản, bộ lọc và bộ mã hoá quan trọng của ffmpeg đang dùng."""
    global _caps
    if _caps is not None:
        return _caps
    path = ffmpeg_path()
    ver = _run_capture(["-version"]).stdout.decode("utf-8", "replace")
    m = re.search(r"ffmpeg version (\S+)", ver)
    filters = _run_capture(["-filters"]).stdout.decode("utf-8", "replace")
    encoders = _run_capture(["-encoders"]).stdout.decode("utf-8", "replace")

    def has_filter(name: str) -> bool:
        return re.search(rf"^\s*\S+\s+{re.escape(name)}\s", filters, re.M) is not None

    def has_encoder(name: str) -> bool:
        return re.search(rf"^\s*\S+\s+{re.escape(name)}\s", encoders, re.M) is not None

    caps = {
        "path": path,
        "version": m.group(1) if m else "?",
        "subtitles": has_filter("ass") or has_filter("subtitles"),
        "rubberband": has_filter("rubberband"),
        "libx264": has_encoder("libx264"),
        "hw_listed": [e for e in ("h264_nvenc", "h264_qsv", "h264_amf", "h264_videotoolbox")
                      if has_encoder(e)],
    }
    with _lock:
        _caps = caps
    return caps


_hw_cache: dict[str, bool] = {}


def encoder_usable(encoder: str, args: Sequence[str] | None = None) -> bool:
    """Thử mã hoá vài khung hình để biết bộ mã hoá (kèm đúng tham số sẽ dùng) có chạy thật không.

    Máy không có card tương ứng, trình điều khiển cũ hay tham số không hợp đều làm phép thử
    thất bại, khi đó nơi gọi sẽ dùng libx264.
    """
    enc_args = list(args) if args else ["-c:v", encoder]
    key = " ".join(enc_args)
    if key in _hw_cache:
        return _hw_cache[key]
    ok = False
    try:
        r = _run_capture(
            ["-f", "lavfi", "-i", "color=c=black:s=640x360:r=25:d=0.4", "-pix_fmt", "yuv420p",
             *enc_args, "-f", "null", "-"], timeout=60)
        ok = r.returncode == 0
    except (OSError, subprocess.SubprocessError, FFmpegError):
        ok = False
    _hw_cache[key] = ok
    return ok


def pick_encoder(preference: str = "auto") -> str:
    """Chọn bộ mã hoá H.264. ``auto`` ưu tiên phần cứng nếu chạy được."""
    order = {
        "nvenc": ["h264_nvenc"], "qsv": ["h264_qsv"], "amf": ["h264_amf"],
        "videotoolbox": ["h264_videotoolbox"], "cpu": [],
        "auto": ["h264_nvenc", "h264_videotoolbox", "h264_qsv", "h264_amf"],
    }.get(preference, [])
    listed = capabilities()["hw_listed"]
    for enc in order:
        if enc in listed and encoder_usable(enc):
            return enc
    return "libx264"


# --------------------------------------------------------------------------
# Dò thông tin tệp
# --------------------------------------------------------------------------

_DUR_RE = re.compile(r"Duration:\s*(\d+):(\d\d):(\d\d(?:\.\d+)?)")
_STREAM_RE = re.compile(r"Stream #\d+:(\d+)[^:]*?:\s*(Video|Audio|Subtitle):\s*(.*)")
_SIZE_RE = re.compile(r",\s(\d{2,5})x(\d{2,5})(?=[\s,\[]|$)")
_FPS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*fps")
_TBR_RE = re.compile(r"(\d+(?:\.\d+)?)(k?)\s*tbr")
_ROT_RE = re.compile(r"rotation of (-?\d+(?:\.\d+)?) degrees")
_SAR_RE = re.compile(r"SAR (\d+):(\d+)")


def parse_probe(text: str) -> dict:
    """Phân tích phần thông tin ``ffmpeg -i`` in ra stderr."""
    info: dict = {"duration": 0.0, "has_video": False, "has_audio": False, "width": 0,
                  "height": 0, "fps": 0.0, "video_codec": "", "audio_codec": "",
                  "audio_streams": 0, "rotation": 0}
    m = _DUR_RE.search(text)
    if m:
        info["duration"] = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    lines = text.splitlines()
    for i, line in enumerate(lines):
        sm = _STREAM_RE.search(line)
        if not sm:
            continue
        kind, desc = sm.group(2), sm.group(3)
        if kind == "Video":
            if "attached pic" in desc or info["has_video"]:
                continue  # ảnh bìa của tệp nhạc không phải luồng video
            size = _SIZE_RE.search(desc)
            if not size:
                continue
            fw, fh = int(size.group(1)), int(size.group(2))
            sar = 1.0
            sm_sar = _SAR_RE.search(desc)
            if sm_sar and int(sm_sar.group(1)) > 0 and int(sm_sar.group(2)) > 0:
                sar = int(sm_sar.group(1)) / int(sm_sar.group(2))
            # Thông tin xoay nằm ở các dòng "Side data" ngay sau dòng Stream.
            for extra in lines[i + 1:i + 8]:
                if "Stream #" in extra:
                    break
                rm = _ROT_RE.search(extra)
                if rm:
                    info["rotation"] = int(round(float(rm.group(1)))) % 360
            if info["rotation"] in (90, 270):  # ffmpeg tự xoay khung hình khi xử lý
                fw, fh = fh, fw
                sar = 1.0 / sar
            # width/height: kích thước hiển thị (điểm ảnh vuông). frame_*: kích thước khung hình thật
            # đi vào bộ lọc; hai cặp chỉ khác nhau ở video có điểm ảnh không vuông (SAR khác 1).
            w, h = int(round(fw * sar)), fh
            info.update(frame_width=fw, frame_height=fh, sar=round(sar, 5))
            fps = 0.0
            fm = _FPS_RE.search(desc)
            if fm:
                fps = float(fm.group(1))
            else:
                tm = _TBR_RE.search(desc)
                if tm:
                    fps = float(tm.group(1)) * (1000 if tm.group(2) else 1)
            if fps <= 0 or fps > 240:
                fps = 30.0 if fps > 240 else fps
            info.update(has_video=True, width=w, height=h, fps=round(fps, 3),
                        video_codec=desc.split(",")[0].split("(")[0].strip())
        elif kind == "Audio":
            info["audio_streams"] += 1
            if not info["has_audio"]:
                info.update(has_audio=True, audio_codec=desc.split(",")[0].split("(")[0].strip())
    return info


def probe(path: str | os.PathLike) -> dict:
    path = str(path)
    if not os.path.isfile(path):
        raise FFmpegError(f"Không tìm thấy tệp: {path}")
    r = _run_capture(["-i", path], timeout=120)
    text = r.stderr.decode("utf-8", "replace")
    info = parse_probe(text)
    if not info["has_video"] and not info["has_audio"]:
        tail = [ln for ln in text.strip().splitlines() if ln.strip()][-1:] or [""]
        raise FFmpegError("Tệp không phải video/âm thanh hợp lệ hoặc bị hỏng. " + tail[0][:200])
    if info["duration"] <= 0:
        info["duration"] = _duration_by_decoding(path)
    info["size"] = os.path.getsize(path)
    return info


def _duration_by_decoding(path: str) -> float:
    """Một số tệp (webm ghi trực tiếp, luồng thô) không ghi thời lượng: giải mã để đo."""
    try:
        r = _run_capture(["-i", path, "-map", "0:a:0?", "-map", "0:v:0?", "-c", "copy",
                          "-f", "null", "-"], timeout=600)
        times = re.findall(r"time=(\d+):(\d\d):(\d\d(?:\.\d+)?)", r.stderr.decode("utf-8", "replace"))
        if times:
            h, m, s = times[-1]
            return int(h) * 3600 + int(m) * 60 + float(s)
    except (subprocess.SubprocessError, OSError):
        pass
    return 0.0


# --------------------------------------------------------------------------
# Chạy ffmpeg có tiến độ và cho phép huỷ
# --------------------------------------------------------------------------

def run(args: Sequence[str], *, duration: float | None = None,
        progress: Callable[[float], None] | None = None,
        cancel: threading.Event | None = None, cwd: str | os.PathLike | None = None,
        log_file: str | os.PathLike | None = None) -> None:
    """Chạy ffmpeg; ``progress`` nhận giá trị 0..1 dựa trên ``duration`` (giây đầu ra)."""
    cmd = [ffmpeg_path(), "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
           "-progress", "pipe:1", "-nostats", *args]
    stderr_path = Path(config.TMP_DIR) / f"ffmpeg_{os.getpid()}_{threading.get_ident()}_{time.time_ns()}.log"
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(stderr_path, "wb") as errf:
            proc = spawn(cmd, stdout=subprocess.PIPE, stderr=errf, cwd=cwd)
            if cancel is not None:
                # Luồng canh: huỷ được ngay cả khi ffmpeg đang im lặng (không in tiến độ).
                def _watch() -> None:
                    while proc.poll() is None:
                        if cancel.wait(0.25):
                            try:
                                proc.kill()
                            except OSError:
                                pass
                            return

                threading.Thread(target=_watch, daemon=True).start()
            try:
                assert proc.stdout is not None
                for raw in proc.stdout:
                    if progress and duration and raw.startswith(b"out_time_us="):
                        try:
                            us = int(raw.split(b"=", 1)[1].strip())
                        except ValueError:
                            continue
                        if us >= 0:
                            progress(max(0.0, min(0.999, us / 1e6 / duration)))
                proc.wait()
            except BaseException:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
                raise
            if cancel is not None and cancel.is_set():
                raise Cancelled()
        err = stderr_path.read_text("utf-8", "replace").strip()
        if log_file and err:
            with open(log_file, "a", encoding="utf-8") as lf:
                lf.write(err + "\n")
        if proc.returncode != 0:
            tail = "\n".join(err.splitlines()[-6:])
            raise FFmpegError(f"ffmpeg báo lỗi (mã {proc.returncode}):\n{tail}")
        if progress:
            progress(1.0)
    finally:
        try:
            stderr_path.unlink()
        except OSError:
            pass


def run_pipe(args: Sequence[str], input_bytes: bytes | None = None, timeout: float = 600) -> bytes:
    """Chạy ffmpeg và trả về dữ liệu đầu ra chuẩn (dùng cho PCM thô, ảnh nhỏ)."""
    cmd = [ffmpeg_path(), "-hide_banner", "-loglevel", "error"]
    if input_bytes is None:
        cmd.append("-nostdin")
    cmd += list(args)
    r = subprocess.run(cmd, input=input_bytes, capture_output=True, timeout=timeout,
                       creationflags=_NO_WINDOW)
    if r.returncode != 0:
        tail = "\n".join(r.stderr.decode("utf-8", "replace").strip().splitlines()[-4:])
        raise FFmpegError(f"ffmpeg báo lỗi (mã {r.returncode}):\n{tail}")
    return r.stdout


# --------------------------------------------------------------------------
# Tiện ích thường dùng
# --------------------------------------------------------------------------

def extract_audio(src: str | os.PathLike, dst: str | os.PathLike, *, sample_rate: int = 16000,
                  channels: int = 1, duration: float | None = None,
                  progress: Callable[[float], None] | None = None,
                  cancel: threading.Event | None = None) -> None:
    run(["-i", str(src), "-map", "0:a:0", "-vn", "-ac", str(channels), "-ar", str(sample_rate),
         "-c:a", "pcm_s16le", str(dst)], duration=duration, progress=progress, cancel=cancel)


def extract_frame(src: str | os.PathLike, t: float, dst: str | os.PathLike, *,
                  vf: str | None = None, max_width: int | None = None, quality: int = 3) -> None:
    """Lấy một khung hình tại giây ``t`` (đã xoay/chuẩn hoá điểm ảnh vuông)."""
    filters = ["scale='trunc(iw*sar/2)*2':ih", "setsar=1"]
    if vf:
        filters.append(vf)
    if max_width:
        filters.append(f"scale='min({max_width},iw)':-2")
    args = ["-ss", f"{max(0.0, t):.3f}", "-i", str(src), "-map", "0:v:0", "-frames:v", "1",
            "-vf", ",".join(filters), "-q:v", str(quality), "-update", "1", str(dst)]
    run(args)
    if not os.path.isfile(dst) or os.path.getsize(dst) == 0:
        # Sát cuối video có thể không còn khung nào: lùi về đầu.
        run(["-i", str(src), "-map", "0:v:0", "-frames:v", "1", "-vf", ",".join(filters),
             "-q:v", str(quality), "-update", "1", str(dst)])


def read_pcm(path: str | os.PathLike, sample_rate: int, *, start: float | None = None,
             duration: float | None = None):
    """Giải mã tệp âm thanh bất kỳ thành mảng int16 mono."""
    import numpy as np

    args: list[str] = []
    if start is not None:
        args += ["-ss", f"{start:.3f}"]
    if duration is not None:
        args += ["-t", f"{duration:.3f}"]
    args += ["-i", str(path), "-vn", "-ac", "1", "-ar", str(sample_rate), "-f", "s16le", "-"]
    data = run_pipe(args)
    return np.frombuffer(data, dtype=np.int16)
