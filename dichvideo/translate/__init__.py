"""Dịch phụ đề: điều phối các bộ dịch (Google miễn phí, các bộ dịch AI)."""

from __future__ import annotations

import logging
import re
import threading
from typing import Callable

from .. import config
from ..ffmpeg import Cancelled
from . import glossary, google, prompting
from .errors import TranslateError

log = logging.getLogger(__name__)

__all__ = ["TranslateError", "translate_segments", "list_models", "test_engine", "engine_label"]

_CJK_RE = re.compile(r"[㐀-鿿]")


def engine_label(engine: str) -> str:
    if engine == "google":
        return "Google Dịch"
    return config.LLM_PROVIDERS.get(engine, {}).get("name", engine)


def _llm_backend(engine: str):
    """Trả về (hàm complete, cấu hình, tên hiển thị) của một bộ dịch AI."""
    if engine not in config.LLM_PROVIDERS:
        raise TranslateError(f"Bộ dịch không hợp lệ: {engine}")
    cfg = config.load_settings()["llm"].get(engine, {})
    name = engine_label(engine)
    if engine == "anthropic":
        from . import claude

        return claude.complete, cfg, name
    from . import openai_compat

    return openai_compat.complete, cfg, name


def list_models(engine: str) -> list[str]:
    if engine not in config.LLM_PROVIDERS:
        raise TranslateError(f"Bộ dịch không hợp lệ: {engine}")
    cfg = config.load_settings()["llm"].get(engine, {})
    if engine == "anthropic":
        from . import claude

        return claude.list_models(cfg)
    from . import openai_compat

    return openai_compat.list_models(cfg, engine_label(engine))


def _translate_llm(targets: list[dict], all_segments: list[dict], settings: dict, terms: list[dict],
                   progress: Callable[[float, str], None] | None,
                   cancel: threading.Event | None) -> int:
    tr = settings["translate"]
    complete, cfg, name = _llm_backend(tr["engine"])
    batch_size = max(5, min(80, int(tr.get("batch_size") or 30)))
    index = {s["id"]: i for i, s in enumerate(all_segments)}
    done = 0
    missing_total = 0
    for start in range(0, len(targets), batch_size):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        batch = targets[start:start + batch_size]
        first_i, last_i = index[batch[0]["id"]], index[batch[-1]["id"]]
        before = [s for s in all_segments[max(0, first_i - 5):first_i] if s.get("text")]
        after = [s for s in all_segments[last_i + 1:last_i + 4] if s.get("text")]
        system = prompting.build_system_prompt(
            settings.get("source_lang", "zh"), tr.get("style", "auto"), tr.get("context", ""),
            glossary.relevant(terms, [s["text"] for s in batch]))
        pending = batch
        for round_no in range(2):  # lần 2 chỉ gửi lại các câu còn thiếu
            ids = [s["id"] for s in pending]
            raw = complete(system, prompting.build_user_prompt(pending, before, after), cfg,
                           name=name, cancel=cancel)
            got = prompting.parse_translations(raw, ids)
            for s in pending:
                vi = got.get(s["id"], "").strip()
                if vi:
                    s["translation"] = vi
            pending = [s for s in pending if not (got.get(s["id"]) or "").strip()]
            if not pending:
                break
            if round_no == 0 and len(pending) == len(batch) and not got:
                log.warning("%s trả lời không đọc được, thử lại lô %d", name, start // batch_size + 1)
        missing_total += len(pending)
        done += len(batch)
        if progress:
            progress(done / len(targets), f"Đang dịch bằng {name}… {done}/{len(targets)} câu")
    return missing_total


def _translate_google(targets: list[dict], settings: dict, terms: list[dict],
                      progress: Callable[[float, str], None] | None,
                      cancel: threading.Event | None) -> int:
    done = [0]
    total = len(targets)

    def step(n: int) -> None:
        done[0] += n
        if progress:
            progress(done[0] / total, f"Đang dịch bằng Google… {done[0]}/{total} câu")

    def notify(msg: str) -> None:
        if progress:
            progress(done[0] / total, msg)

    lines = [glossary.substitute(s["text"], glossary.relevant(terms, [s["text"]])) for s in targets]
    result = google.translate_lines(lines, settings.get("source_lang", "zh"), "vi",
                                    cancel=cancel, progress=step, notify=notify)
    missing = 0
    for s, vi in zip(targets, result):
        if vi.strip():
            s["translation"] = vi.strip()
        else:
            missing += 1
    return missing


def translate_segments(segments: list[dict], settings: dict, *,
                       progress: Callable[[float, str], None] | None = None,
                       cancel: threading.Event | None = None,
                       only_ids: set[int] | None = None, only_empty: bool = False) -> dict:
    """Điền ``translation`` cho các câu. Trả về ``{"translated", "missing", "engine"}``."""
    targets = [s for s in segments if (s.get("text") or "").strip()
               and (only_ids is None or s["id"] in only_ids)
               and not (only_empty and (s.get("translation") or "").strip())]
    engine = settings["translate"].get("engine", "google")
    if not targets:
        return {"translated": 0, "missing": 0, "engine": engine}
    terms = glossary.load() if settings["translate"].get("use_glossary", True) else []
    if progress:
        progress(0.0, f"Đang dịch bằng {engine_label(engine)}…")
    if engine == "google":
        missing = _translate_google(targets, settings, terms, progress, cancel)
    else:
        missing = _translate_llm(targets, segments, settings, terms, progress, cancel)
    if missing == len(targets):
        raise TranslateError(f"{engine_label(engine)} không dịch được câu nào. Hãy kiểm tra cấu hình bộ dịch.")
    if progress:
        progress(1.0, "Đã dịch xong" + (f" (còn {missing} câu trống)" if missing else ""))
    return {"translated": len(targets) - missing, "missing": missing, "engine": engine}


def test_engine(engine: str, source_lang: str = "zh") -> str:
    """Dịch thử một câu ngắn để kiểm tra khoá API / kết nối. Trả về bản dịch."""
    sample = [{"id": 1, "start": 0.0, "end": 2.0, "text": "你好，欢迎收看今天的节目。", "translation": ""}]
    settings = config.new_project_settings()
    settings["source_lang"] = source_lang
    settings["translate"].update(engine=engine, use_glossary=False)
    translate_segments(sample, settings)
    return sample[0]["translation"]


def looks_untranslated(text: str) -> bool:
    return bool(_CJK_RE.search(text or ""))
