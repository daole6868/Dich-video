"""Máy chủ web cục bộ: API JSON + giao diện tĩnh."""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import platform
import re
import shutil
import sys
import threading
from email.utils import formatdate
from pathlib import Path
from urllib.parse import quote, urlparse

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import APP_NAME, __version__, asr, config, downloader, ffmpeg, fileops, fonts, jobs, pipeline, projects
from . import render, subtitles, translate, tts
from .projects import ProjectError
from .translate import glossary

log = logging.getLogger(__name__)

LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}
MAX_SMALL_UPLOAD = 20 * 1024 * 1024
_preview_locks: dict[str, threading.Lock] = {}
_downloads: dict[str, threading.Event] = {}
_gpu: bool | None = None


# --------------------------------------------------------------------------
# Tiện ích
# --------------------------------------------------------------------------

def err(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def api(fn):
    """Bọc endpoint: đổi lỗi nghiệp vụ thành JSON ``{"error": ...}`` có thông điệp tiếng Việt."""
    async def wrapper(request: Request):
        try:
            return await fn(request)
        except ProjectError as e:
            return err(str(e), e.status)
        except (translate.TranslateError, ffmpeg.FFmpegError, downloader.DownloadError, pipeline.StepError) as e:
            return err(str(e), 400)
        except json.JSONDecodeError:
            return err("Dữ liệu gửi lên không phải JSON hợp lệ.", 400)
        except (ValueError, RuntimeError) as e:
            return err(str(e) or type(e).__name__, 400)
        except Exception as e:  # noqa: BLE001
            log.exception("Lỗi không mong đợi ở %s", request.url.path)
            return err(f"Lỗi máy chủ: {type(e).__name__}: {e}", 500)

    wrapper.__name__ = fn.__name__
    return wrapper


async def body_json(request: Request) -> dict:
    raw = await request.body()
    if not raw:
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Dữ liệu gửi lên phải là một đối tượng JSON.")
    return data


async def body_limited(request: Request, limit: int = MAX_SMALL_UPLOAD) -> bytes:
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise ProjectError(f"Tệp quá lớn (tối đa {limit // (1024 * 1024)} MB).", 413)
        chunks.append(chunk)
    return b"".join(chunks)


def pid_of(request: Request) -> str:
    return projects.check_id(request.path_params["pid"])


def download_headers(filename: str) -> dict:
    ascii_name = filename.encode("ascii", "ignore").decode() or "download"
    ascii_name = ascii_name.replace('"', "")
    return {"Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"}


def project_payload(pid: str) -> dict:
    data = projects.load(pid)
    d = projects.project_dir(pid)
    data["busy"] = jobs.manager.busy(pid)
    data["has_thumb"] = (d / "thumb.jpg").is_file()
    data["has_proxy"] = (d / "work" / "preview.mp4").is_file()
    data["downloading"] = pid in _downloads
    return data


def gpu_available() -> bool:
    global _gpu
    if _gpu is None:
        _gpu = asr.gpu_available()
    return _gpu


# --------------------------------------------------------------------------
# Bảo vệ: chỉ nhận yêu cầu từ chính giao diện của ứng dụng
# --------------------------------------------------------------------------

class GuardMiddleware(BaseHTTPMiddleware):
    """Chặn trang web lạ gọi vào máy chủ cục bộ (CSRF, DNS rebinding)."""

    async def dispatch(self, request: Request, call_next):
        allow_lan = bool(getattr(request.app.state, "allow_lan", False))
        host = (request.headers.get("host") or "").strip().lower()
        hostname = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
        if not allow_lan and hostname not in LOCAL_HOSTS:
            return err("Địa chỉ truy cập không được phép.", 403)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and origin != "null":
                if urlparse(origin).netloc.lower() != host:
                    return err("Yêu cầu từ trang khác bị từ chối.", 403)
            elif origin == "null":
                return err("Yêu cầu từ trang khác bị từ chối.", 403)
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        return response


# --------------------------------------------------------------------------
# Hệ thống, cài đặt
# --------------------------------------------------------------------------

@api
async def get_system(request: Request):
    def build() -> dict:
        try:
            caps = dict(ffmpeg.capabilities())
            caps["ok"] = bool(caps.get("subtitles") and caps.get("libx264"))
        except ffmpeg.FFmpegError as e:
            caps = {"ok": False, "error": str(e)}
        try:
            free = shutil.disk_usage(config.DATA_DIR).free
        except OSError:
            free = 0
        return {
            "app": APP_NAME, "version": __version__,
            "platform": f"{platform.system()} {platform.release()}", "python": platform.python_version(),
            "ffmpeg": caps, "gpu": gpu_available(), "cpu_count": os.cpu_count() or 1,
            "disk_free": free, "data_dir": str(config.DATA_DIR),
            "source_langs": config.SOURCE_LANGS, "translate_styles": config.TRANSLATE_STYLES,
            "llm_providers": [{"id": k, **v} for k, v in config.LLM_PROVIDERS.items()],
            "whisper_models": asr.list_models(), "tts_engines": tts.ENGINES,
            "fonts": fonts.catalog(refresh=True)["families"],
            "default_settings": config.DEFAULT_PROJECT_SETTINGS,
            "video_ext": sorted(projects.VIDEO_EXT), "audio_ext": sorted(projects.AUDIO_EXT),
            "allow_lan": bool(getattr(request.app.state, "allow_lan", False)),
        }

    return JSONResponse(await run_in_threadpool(build))


@api
async def get_settings(request: Request):
    return JSONResponse(config.public_settings())


@api
async def put_settings(request: Request):
    data = await body_json(request)
    result = await run_in_threadpool(config.update_settings_from_client, data)
    ffmpeg.reset_cache()
    return JSONResponse(result)


@api
async def get_glossary(request: Request):
    items = glossary.load()
    return JSONResponse({"items": items, "text": glossary.to_text(items)})


@api
async def put_glossary(request: Request):
    data = await body_json(request)
    items = glossary.parse_text(data["text"]) if isinstance(data.get("text"), str) else data.get("items")
    saved = glossary.save(items)
    return JSONResponse({"items": saved, "text": glossary.to_text(saved)})


@api
async def get_models(request: Request):
    return JSONResponse({"models": asr.list_models()})


@api
async def delete_model(request: Request):
    name = request.path_params["name"]
    if name not in asr.WHISPER_REPOS:
        return err("Mô hình không hợp lệ.", 404)
    await run_in_threadpool(asr.delete_model, name)
    return JSONResponse({"models": asr.list_models()})


@api
async def get_voices(request: Request):
    engine = request.query_params.get("engine", "edge")
    refresh = request.query_params.get("refresh") == "1"
    voices = await run_in_threadpool(tts.list_voices, engine, refresh)
    return JSONResponse({"engine": engine, "voices": voices})


@api
async def tts_preview(request: Request):
    data = await body_json(request)
    text = str(data.get("text") or "Xin chào, đây là giọng đọc thử của Dịch Video Studio.")[:400]
    engine = str(data.get("engine") or "edge")
    voice = str(data.get("voice") or "")
    rate, pitch = int(data.get("rate") or 0), int(data.get("pitch") or 0)
    ext = tts.engine_ext(engine)
    folder = config.TMP_DIR / "nghe-thu"
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{tts.cache_key(text, engine, voice, rate, pitch)}.{ext}"

    def make() -> bool:
        if out.is_file() and out.stat().st_size > 200:
            return True
        # Cao độ: Edge nhận đơn vị Hz (x5); engine khác chỉnh sau nên ở đây nghe giọng gốc.
        return tts.synthesize(text, str(out), engine=engine, voice=voice, rate=rate,
                              pitch=pitch * 5 if engine == "edge" else 0)

    if not await run_in_threadpool(make):
        return err("Câu này không có nội dung đọc được.", 400)
    return FileResponse(out, media_type="audio/mpeg" if ext == "mp3" else "audio/wav",
                        headers={"Cache-Control": "no-store"})


@api
async def llm_models(request: Request):
    engine = request.query_params.get("engine", "")
    models = await run_in_threadpool(translate.list_models, engine)
    return JSONResponse({"engine": engine, "models": models})


@api
async def llm_test(request: Request):
    data = await body_json(request)
    engine = str(data.get("engine") or "google")
    result = await run_in_threadpool(translate.test_engine, engine)
    return JSONResponse({"engine": engine, "sample": "你好，欢迎收看今天的节目。", "translation": result})


@api
async def get_jobs(request: Request):
    return JSONResponse(jobs.manager.state())


@api
async def post_shutdown(request: Request):
    server = getattr(request.app.state, "server", None)
    jobs.manager.shutdown()
    if server is not None:
        server.should_exit = True
    return JSONResponse({"ok": True})


# --------------------------------------------------------------------------
# Dự án
# --------------------------------------------------------------------------

@api
async def list_projects(request: Request):
    items = await run_in_threadpool(projects.list_all)
    busy = jobs.manager.state()
    return JSONResponse({"projects": items, "jobs": busy})


@api
async def create_project(request: Request):
    data = await body_json(request)
    filename = Path(str(data.get("filename") or "")).name
    if not filename:
        return err("Thiếu tên tệp video.")
    proj = projects.create(str(data.get("name") or ""), filename, settings=data.get("settings"))
    return JSONResponse(proj, status_code=201)


@api
async def upload_source(request: Request):
    """Nhận tệp video dạng luồng thô (không qua multipart) và ghi thẳng xuống đĩa."""
    pid = pid_of(request)
    data = projects.load(pid)
    if data["source"].get("ready"):
        return err("Dự án này đã có video nguồn.", 409)
    dest = projects.source_path(data)
    tmp = dest.with_name(dest.name + ".part")
    size = 0
    try:
        with open(tmp, "wb") as f:
            async for chunk in request.stream():
                if chunk:
                    f.write(chunk)
                    size += len(chunk)
        if size == 0:
            raise ProjectError("Tệp tải lên bị rỗng.")
        fileops.replace(tmp, dest)
    except OSError as e:
        raise ProjectError(f"Không ghi được tệp (có thể hết dung lượng đĩa): {e}", 507) from e
    finally:
        fileops.remove(tmp)
    projects.update(pid, lambda d: d["source"].update(ready=True, size=size))
    projects.log(pid, f"Đã nhận video nguồn: {data['source']['original_name']} ({size / 1e6:.1f} MB)")
    if request.query_params.get("start") == "1":
        await run_in_threadpool(jobs.manager.submit, pid, None)
    return JSONResponse(project_payload(pid))


def _download_worker(pid: str, url: str, autostart: bool, cancel: threading.Event) -> None:
    d = projects.project_dir(pid)
    try:
        def progress(value: float, message: str) -> None:
            projects.update(pid, lambda x: x.__setitem__("download", {"status": "running", "progress": value,
                                                                       "message": message}))

        result = downloader.download(url, d / "work" / "tai-ve", progress=progress, cancel=cancel)
        src: Path = result["path"]
        final = d / f"source{src.suffix.lower()}"
        shutil.move(str(src), final)
        shutil.rmtree(d / "work" / "tai-ve", ignore_errors=True)

        def done(x: dict) -> None:
            x["source"].update(ready=True, file=final.name, size=final.stat().st_size)
            if result.get("title") and x["name"] in ("Video từ liên kết", ""):
                x["name"] = projects.safe_name(result["title"])
            x["download"] = {"status": "done", "progress": 1.0, "message": "Đã tải xong"}

        projects.update(pid, done)
        projects.log(pid, f"Đã tải video từ liên kết: {url}")
        _downloads.pop(pid, None)
        if autostart:
            jobs.manager.submit(pid, None)
    except ffmpeg.Cancelled:
        projects.update(pid, lambda x: x.__setitem__("download", {"status": "cancelled", "progress": 0,
                                                                   "message": "Đã huỷ tải"}))
    except ProjectError:
        pass  # dự án đã bị xoá trong lúc tải
    except Exception as e:  # noqa: BLE001
        message = str(e) if isinstance(e, downloader.DownloadError) else f"{type(e).__name__}: {e}"
        try:
            projects.update(pid, lambda x: x.__setitem__("download", {"status": "error", "progress": 0,
                                                                       "message": message}))
            projects.log(pid, f"✖ Tải video lỗi: {message}")
        except ProjectError:
            pass
    finally:
        _downloads.pop(pid, None)


@api
async def create_from_url(request: Request):
    data = await body_json(request)
    url = downloader.check_url(str(data.get("url") or ""))
    proj = projects.create(str(data.get("name") or "Video từ liên kết"), "video.mp4", kind="url", url=url,
                           settings=data.get("settings"))
    pid = proj["id"]
    projects.update(pid, lambda x: x.__setitem__("download", {"status": "running", "progress": 0.0,
                                                               "message": "Đang kết nối…"}))
    cancel = threading.Event()
    _downloads[pid] = cancel
    threading.Thread(target=_download_worker, args=(pid, url, data.get("start", True) is not False, cancel),
                     daemon=True, name=f"tai-{pid}").start()
    return JSONResponse(project_payload(pid), status_code=201)


@api
async def get_project(request: Request):
    return JSONResponse(await run_in_threadpool(project_payload, pid_of(request)))


@api
async def patch_project(request: Request):
    pid = pid_of(request)
    data = await body_json(request)
    old = projects.load(pid)

    def apply(d: dict) -> None:
        if isinstance(data.get("name"), str) and data["name"].strip():
            d["name"] = projects.safe_name(data["name"], d["name"])
        if isinstance(data.get("settings"), dict):
            d["settings"] = config.conform_project_settings(config.deep_merge(d["settings"], data["settings"]))
            if isinstance(data["settings"].get("cover"), list):  # danh sách: thay nguyên chứ không trộn
                d["settings"]["cover"] = [r for r in data["settings"]["cover"] if isinstance(r, dict)][:8]

    new = projects.update(pid, apply)
    if not jobs.manager.busy(pid):
        a, b = old["settings"], new["settings"]
        if a["dub"] != b["dub"]:
            projects.mark_stale(pid, ["dub", "render"])
        elif any(a[k] != b[k] for k in ("subtitle", "cover", "cover_when", "logo", "output")):
            projects.mark_stale(pid, ["render"])
    return JSONResponse(project_payload(pid))


@api
async def delete_project(request: Request):
    pid = pid_of(request)
    jobs.manager.cancel(pid)
    ev = _downloads.pop(pid, None)
    if ev:
        ev.set()
    if jobs.manager.busy(pid):
        return err("Dự án đang dừng xử lý, hãy thử xoá lại sau vài giây.", 409)
    await run_in_threadpool(projects.delete, pid)
    return JSONResponse({"ok": True})


@api
async def run_project(request: Request):
    pid = pid_of(request)
    data = await body_json(request)
    steps = data.get("steps")
    if steps is not None and (not isinstance(steps, list) or any(s not in projects.STEPS for s in steps)):
        return err("Danh sách bước không hợp lệ.")
    await run_in_threadpool(jobs.manager.submit, pid, steps or None)
    return JSONResponse(project_payload(pid))


@api
async def cancel_project(request: Request):
    pid = pid_of(request)
    ev = _downloads.get(pid)
    if ev:
        ev.set()
    found = jobs.manager.cancel(pid) or bool(ev)
    return JSONResponse({"cancelled": found, "project": project_payload(pid)})


# --------------------------------------------------------------------------
# Câu phụ đề
# --------------------------------------------------------------------------

@api
async def get_segments(request: Request):
    return JSONResponse({"segments": projects.load_segments(pid_of(request))})


def _clean_incoming(items: list) -> list[dict]:
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        seg = {"start": it.get("start", 0), "end": it.get("end", 0), "text": str(it.get("text") or ""),
               "translation": str(it.get("translation") or "")}
        if isinstance(it.get("voice"), str) and it["voice"].strip():
            seg["voice"] = it["voice"].strip()[:80]
        if isinstance(it.get("dub"), dict):
            seg["dub"] = it["dub"]
        out.append(seg)
    return out


@api
async def put_segments(request: Request):
    pid = pid_of(request)
    if jobs.manager.busy(pid):
        return err("Dự án đang được xử lý. Hãy chờ xong hoặc bấm Dừng trước khi sửa phụ đề.", 409)
    data = await body_json(request)
    if not isinstance(data.get("segments"), list):
        return err("Thiếu danh sách câu phụ đề.")
    def key(seg: dict) -> tuple:
        return (round(float(seg["start"]), 2), round(float(seg["end"]), 2), seg.get("text", ""),
                seg.get("translation", ""), seg.get("voice", ""))

    old_keys = {key(seg) for seg in projects.load_segments(pid)}
    new = subtitles.normalize(_clean_incoming(data["segments"]))
    for seg in new:
        if key(seg) not in old_keys:
            seg.pop("dub", None)  # câu đã sửa: thông tin khớp tiếng lồng cũ không còn đúng
    changed = {key(seg) for seg in new} != old_keys
    saved = await run_in_threadpool(projects.save_segments, pid, new)
    if changed:
        projects.mark_stale(pid, ["dub", "render"])
    return JSONResponse({"segments": saved, "project": project_payload(pid)})


@api
async def translate_lines(request: Request):
    pid = pid_of(request)
    if jobs.manager.busy(pid):
        return err("Dự án đang được xử lý. Hãy chờ xong rồi dịch lại.", 409)
    data = await body_json(request)
    ids = data.get("ids")
    only_empty = bool(data.get("only_empty"))
    if ids is not None and not isinstance(ids, list):
        return err("Danh sách câu không hợp lệ.")

    def work() -> dict:
        proj = projects.load(pid)
        segs = projects.load_segments(pid)
        settings = proj["settings"]
        if isinstance(data.get("engine"), str):
            settings = config.deep_merge(settings, {"translate": {"engine": data["engine"]}})
        try:
            result = translate.translate_segments(segs, settings, only_ids={int(i) for i in ids} if ids else None,
                                                  only_empty=only_empty)
        finally:
            projects.save_segments(pid, segs, renumber=False)
        projects.mark_stale(pid, ["dub", "render"])
        return {"result": result, "segments": projects.load_segments(pid)}

    out = await run_in_threadpool(work)
    out["project"] = project_payload(pid)
    return JSONResponse(out)


@api
async def import_subtitles(request: Request):
    pid = pid_of(request)
    if jobs.manager.busy(pid):
        return err("Dự án đang được xử lý, chưa nhập phụ đề được.", 409)
    kind = request.query_params.get("kind", "source")
    filename = request.query_params.get("filename", "phude.srt")
    raw = await body_limited(request)
    incoming = subtitles.parse_subtitle_file(raw, filename)
    if not incoming:
        return err("Không đọc được câu phụ đề nào trong tệp. Hỗ trợ: .srt, .vtt, .ass")
    current = projects.load_segments(pid)
    kept_source = False  # True: chỉ điền bản dịch vào các câu sẵn có, lời thoại gốc và mốc thời gian giữ nguyên
    if kind == "translation":
        if current and len(current) == len(incoming):
            for seg, inc in zip(current, incoming):
                seg["translation"] = inc["text"]
                seg.pop("dub", None)
            merged = current
            kept_source = True
        else:
            merged = [{"start": s["start"], "end": s["end"], "text": "", "translation": s["text"]} for s in incoming]
    else:
        merged = [{"start": s["start"], "end": s["end"], "text": s["text"], "translation": ""} for s in incoming]
    saved = projects.save_segments(pid, merged)

    def mark(d: dict) -> None:
        note = {"source": "import", "segments": len(saved), "file": filename}
        if not kept_source:  # danh sách câu được thay mới: nguồn lời thoại giờ là tệp nhập vào
            d["steps"]["transcribe"].update(status="done", progress=1.0, message="Đã nhập từ tệp", error="", info=note)
        if kind == "translation":
            d["steps"]["translate"].update(status="done", progress=1.0, message="Đã nhập từ tệp", error="",
                                           info={"engine": "import", "translated": len(saved), "file": filename})
        elif d["steps"]["translate"]["status"] == "done":
            d["steps"]["translate"].update(status="stale", message="Phụ đề gốc đã thay, cần dịch lại")

    projects.update(pid, mark)
    projects.mark_stale(pid, ["dub", "render"])
    projects.log(pid, f"Đã nhập {len(saved)} câu phụ đề ({'bản dịch' if kind == 'translation' else 'bản gốc'}) từ {filename}")
    return JSONResponse({"segments": saved, "project": project_payload(pid)})


@api
async def export_subtitles(request: Request):
    pid = pid_of(request)
    fmt = request.query_params.get("format", "srt")
    mode = request.query_params.get("mode", "vi")
    if fmt not in ("srt", "vtt", "ass", "txt") or mode not in ("vi", "zh", "bilingual"):
        return err("Định dạng xuất không hợp lệ.")
    data = projects.load(pid)
    segs = projects.load_segments(pid)
    if fmt == "srt":
        body, ctype = subtitles.to_srt(segs, mode), "application/x-subrip"
    elif fmt == "vtt":
        body, ctype = subtitles.to_vtt(segs, mode), "text/vtt"
    elif fmt == "txt":
        body, ctype = subtitles.to_txt(segs, mode), "text/plain"
    else:
        w, h = render.output_size(data.get("media") or {}, data["settings"]["output"])
        style = dict(data["settings"]["subtitle"])
        style["font"] = fonts.resolve_family(str(style.get("font") or ""))
        body, ctype = subtitles.build_ass(segs, style, w, h, mode=mode,
                                          em_ratio=fonts.em_ratio(style["font"])), "text/x-ssa"
    suffix = {"vi": "vi", "zh": "goc", "bilingual": "songngu"}[mode]
    name = f"{projects.safe_name(data['name'])}.{suffix}.{fmt}"
    payload = ("﻿" + body if fmt in ("srt", "txt") else body).encode("utf-8")
    return Response(payload, media_type=f"{ctype}; charset=utf-8", headers=download_headers(name))


# --------------------------------------------------------------------------
# Tệp phương tiện
# --------------------------------------------------------------------------

_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")
STREAM_CHUNK = 256 * 1024


def stream_file(request: Request, path: Path, media_type: str, headers: dict[str, str] | None = None) -> Response:
    """Gửi tệp lớn (video, kết quả) có hỗ trợ tua (Range) mà không giữ tệp mở giữa các lần gửi.

    ``FileResponse`` giữ tệp mở suốt lúc trình duyệt còn nhận dữ liệu - với thẻ <video> đang tạm dừng
    thì có thể là rất lâu. Trên Windows, tệp đang mở không ghi đè hay xoá được, nên xuất lại video
    hoặc xoá dự án trong lúc đó sẽ lỗi. Ở đây mỗi khối dữ liệu được đọc bằng một lần mở-đọc-đóng.
    """
    try:
        st = path.stat()
    except OSError:
        return err("Không tìm thấy tệp.", 404)
    size = st.st_size
    etag = f'"{st.st_mtime_ns:x}-{size:x}"'
    out = {"Accept-Ranges": "bytes", "ETag": etag, "Last-Modified": formatdate(st.st_mtime, usegmt=True),
           **(headers or {})}
    start, end, status = 0, size - 1, 200
    wanted = (request.headers.get("range") or "").strip()
    if_range = request.headers.get("if-range")
    if wanted and size > 0 and (not if_range or if_range == etag):
        m = _RANGE_RE.match(wanted)  # nhiều khoảng một lúc (hiếm gặp): bỏ qua, gửi cả tệp
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
            else:
                start = max(0, size - int(m.group(2)))
            if start >= size or start > end:
                return Response(status_code=416, headers={**out, "Content-Range": f"bytes */{size}"})
            status = 206
            out["Content-Range"] = f"bytes {start}-{end}/{size}"
    out["Content-Length"] = str(end - start + 1)
    if request.method == "HEAD":
        return Response(status_code=status, headers=out, media_type=media_type)

    def read_block(pos: int, n: int) -> bytes:
        try:
            with open(path, "rb") as f:
                f.seek(pos)
                return f.read(n)
        except OSError:
            return b""  # tệp vừa bị thay hoặc xoá: kết thúc luồng, trình duyệt sẽ tự tải lại

    async def body():
        pos = start
        while pos <= end:
            block = await run_in_threadpool(read_block, pos, min(STREAM_CHUNK, end - pos + 1))
            if not block:
                return
            pos += len(block)
            yield block

    return StreamingResponse(body(), status_code=status, headers=out, media_type=media_type)


@api
async def get_video(request: Request):
    pid = pid_of(request)
    data = projects.load(pid)
    proxy = projects.project_dir(pid) / "work" / "preview.mp4"
    path = proxy if proxy.is_file() else projects.source_path(data)
    if not path.is_file():
        return err("Chưa có video.", 404)
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return stream_file(request, path, ctype)


@api
async def get_thumb(request: Request):
    path = projects.project_dir(pid_of(request)) / "thumb.jpg"
    if not path.is_file():
        return err("Chưa có ảnh thu nhỏ.", 404)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-cache"})


@api
async def get_frame(request: Request):
    pid = pid_of(request)
    data = projects.load(pid)
    if not data.get("media", {}).get("has_video"):
        return err("Dự án không có hình ảnh.", 404)
    try:
        t = max(0.0, min(float(request.query_params.get("t", "0")), float(data["media"]["duration"]) - 0.05))
    except ValueError:
        t = 0.0
    folder = projects.project_dir(pid) / "work" / "frames"
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"f{int(t * 10):07d}.jpg"
    if not out.is_file():
        await run_in_threadpool(ffmpeg.extract_frame, projects.source_path(data), t, out, max_width=1280)
    return FileResponse(out, media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})


@api
async def post_preview_frame(request: Request):
    pid = pid_of(request)
    body = await body_json(request)
    data = projects.load(pid)
    media = data.get("media") or {}
    if not media.get("has_video"):
        return err("Dự án không có hình ảnh.", 404)
    settings = data["settings"]
    if isinstance(body.get("settings"), dict):  # xem thử cài đặt chưa lưu
        settings = config.conform_project_settings(config.deep_merge(settings, body["settings"]))
        if isinstance(body["settings"].get("cover"), list):
            settings["cover"] = [r for r in body["settings"]["cover"] if isinstance(r, dict)][:8]
    t = max(0.0, min(float(body.get("t") or 0), float(media["duration"]) - 0.05))
    d = projects.project_dir(pid)
    (d / "work" / "preview").mkdir(parents=True, exist_ok=True)
    out = d / "work" / "preview" / "khung.jpg"
    lock = _preview_locks.setdefault(pid, threading.Lock())

    def make() -> bytes:
        with lock:
            render.preview_frame(projects.source_path(data), t, out, project_dir=d,
                                 segments=projects.load_segments(pid), settings=settings, media=media,
                                 source=pipeline.transcribe_source(data))
            return out.read_bytes()

    return Response(await run_in_threadpool(make), media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@api
async def upload_logo(request: Request):
    pid = pid_of(request)
    filename = Path(request.query_params.get("filename", "logo.png")).name
    ext = Path(filename).suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        return err("Logo phải là ảnh PNG, JPG hoặc WEBP (nên dùng PNG nền trong suốt).")
    raw = await body_limited(request, 8 * 1024 * 1024)
    if not raw:
        return err("Tệp logo bị rỗng.")
    d = projects.project_dir(pid)
    for old in d.glob("logo.*"):
        fileops.remove(old)
    (d / f"logo{ext}").write_bytes(raw)
    projects.update(pid, lambda x: x["settings"]["logo"].update(file=f"logo{ext}", enabled=True))
    projects.mark_stale(pid, ["render"])
    return JSONResponse(project_payload(pid))


@api
async def get_logo(request: Request):
    pid = pid_of(request)
    name = Path(str(projects.load(pid)["settings"]["logo"].get("file") or "")).name
    path = projects.project_dir(pid) / name
    if not name or not path.is_file():
        return err("Chưa có logo.", 404)
    return FileResponse(path, headers={"Cache-Control": "no-cache"})


@api
async def get_output_file(request: Request):
    pid = pid_of(request)
    name = Path(request.path_params["name"]).name
    path = projects.project_dir(pid) / "output" / name
    if not path.is_file():
        return err("Không tìm thấy tệp.", 404)
    inline = request.query_params.get("inline") == "1"
    ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
    # Tệp kết quả bị ghi đè mỗi lần xuất lại: buộc trình duyệt hỏi lại máy chủ, không dùng bản đã lưu đệm.
    headers = {"Cache-Control": "no-cache"}
    if not inline:
        headers.update(download_headers(name))
    return stream_file(request, path, ctype, headers)


@api
async def get_log(request: Request):
    return JSONResponse({"log": projects.read_log(pid_of(request))})


@api
async def tts_line(request: Request):
    """Tạo giọng đọc cho một câu để nghe thử ngay trong trình sửa phụ đề."""
    pid = pid_of(request)
    body = await body_json(request)
    data = projects.load(pid)
    dub = data["settings"]["dub"]
    text = str(body.get("text") or "").strip()
    if not text:
        return err("Câu này chưa có bản dịch để đọc.")
    engine = dub.get("engine", "edge")
    voice = str(body.get("voice") or dub.get("voice") or "")
    rate, pitch = int(dub.get("rate", 0)), int(dub.get("pitch", 0))
    folder = projects.project_dir(pid) / "work" / "tts"
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{tts.cache_key(text, engine, voice, rate, pitch)}.{tts.engine_ext(engine)}"

    def make() -> bool:
        if out.is_file() and out.stat().st_size > 200:
            return True
        return tts.synthesize(text, str(out), engine=engine, voice=voice, rate=rate,
                              pitch=pitch * 5 if engine == "edge" else 0)

    if not await run_in_threadpool(make):
        return err("Câu này không có nội dung đọc được.")
    return FileResponse(out, media_type="audio/mpeg" if out.suffix == ".mp3" else "audio/wav",
                        headers={"Cache-Control": "no-store"})


# --------------------------------------------------------------------------
# Tệp tĩnh
# --------------------------------------------------------------------------

async def index(request: Request):
    return FileResponse(config.WEB_DIR / "index.html", media_type="text/html; charset=utf-8")


async def get_font(request: Request):
    name = Path(request.path_params["name"]).name
    folder = config.USER_FONTS_DIR if request.path_params.get("scope") == "user" else config.FONTS_DIR
    path = folder / name
    if path.suffix.lower() not in fonts.EXTENSIONS or not path.is_file():
        return err("Không tìm thấy phông.", 404)
    return FileResponse(path, media_type="font/otf" if path.suffix.lower() == ".otf" else "font/ttf",
                        headers={"Cache-Control": "max-age=86400"})


def create_app(*, allow_lan: bool = False) -> Starlette:
    config.ensure_dirs()
    config.apply_network_settings()
    P = "/api/projects/{pid}"
    routes = [
        Route("/", index),
        Route("/fonts/{name}", get_font),
        Route("/fonts/{scope}/{name}", get_font),
        Route("/api/system", get_system),
        Route("/api/settings", get_settings, methods=["GET"]),
        Route("/api/settings", put_settings, methods=["PUT"]),
        Route("/api/glossary", get_glossary, methods=["GET"]),
        Route("/api/glossary", put_glossary, methods=["PUT"]),
        Route("/api/models", get_models),
        Route("/api/models/{name}", delete_model, methods=["DELETE"]),
        Route("/api/voices", get_voices),
        Route("/api/tts/preview", tts_preview, methods=["POST"]),
        Route("/api/llm/models", llm_models),
        Route("/api/llm/test", llm_test, methods=["POST"]),
        Route("/api/jobs", get_jobs),
        Route("/api/shutdown", post_shutdown, methods=["POST"]),
        Route("/api/projects", list_projects, methods=["GET"]),
        Route("/api/projects", create_project, methods=["POST"]),
        Route("/api/projects/from-url", create_from_url, methods=["POST"]),
        Route(P, get_project, methods=["GET"]),
        Route(P, patch_project, methods=["PATCH"]),
        Route(P, delete_project, methods=["DELETE"]),
        Route(P + "/source", upload_source, methods=["PUT"]),
        Route(P + "/run", run_project, methods=["POST"]),
        Route(P + "/cancel", cancel_project, methods=["POST"]),
        Route(P + "/segments", get_segments, methods=["GET"]),
        Route(P + "/segments", put_segments, methods=["PUT"]),
        Route(P + "/segments/translate", translate_lines, methods=["POST"]),
        Route(P + "/subtitles/import", import_subtitles, methods=["POST"]),
        Route(P + "/subtitles/export", export_subtitles, methods=["GET"]),
        Route(P + "/video", get_video),
        Route(P + "/thumb", get_thumb),
        Route(P + "/frame", get_frame),
        Route(P + "/preview-frame", post_preview_frame, methods=["POST"]),
        Route(P + "/logo", upload_logo, methods=["POST"]),
        Route(P + "/logo", get_logo, methods=["GET"]),
        Route(P + "/files/{name}", get_output_file),
        Route(P + "/log", get_log),
        Route(P + "/tts-line", tts_line, methods=["POST"]),
        Mount("/static", StaticFiles(directory=str(config.WEB_DIR)), name="static"),
    ]
    app = Starlette(routes=routes, middleware=[Middleware(GuardMiddleware)])
    app.state.allow_lan = allow_lan
    app.state.server = None
    projects.remove_leftovers()
    recovered = projects.recover_interrupted()
    if recovered:
        log.info("Đã đánh dấu %d dự án bị gián đoạn từ lần chạy trước.", recovered)
    jobs.manager.start()
    return app


def setup_logging() -> None:
    config.ensure_dirs()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(isinstance(h, logging.FileHandler) for h in root.handlers):
        fh = logging.FileHandler(config.LOG_DIR / "app.log", encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        sh.setLevel(logging.WARNING)
        root.addHandler(sh)
    for noisy in ("httpx", "httpx2", "httpcore", "httpcore2", "huggingface_hub", "faster_whisper", "urllib3",
                  "asyncio", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

