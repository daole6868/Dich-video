"""Từ điển thuật ngữ: tên riêng, địa danh, thuật ngữ cần dịch thống nhất.

Lưu ở ``data/glossary.json`` dưới dạng danh sách ``{"source", "target", "note"}``.
"""

from __future__ import annotations

import threading

from .. import config

_lock = threading.RLock()


def _clean(items) -> list[dict]:
    out, seen = [], set()
    for it in items or []:
        if not isinstance(it, dict):
            continue
        src = str(it.get("source") or "").strip()
        tgt = str(it.get("target") or "").strip()
        if not src or not tgt or src in seen:
            continue
        seen.add(src)
        out.append({"source": src, "target": tgt, "note": str(it.get("note") or "").strip()})
    return out


def load() -> list[dict]:
    with _lock:
        return _clean(config.read_json(config.GLOSSARY_FILE, []))


def save(items) -> list[dict]:
    with _lock:
        cleaned = _clean(items)
        config.write_json_atomic(config.GLOSSARY_FILE, cleaned)
        return cleaned


def relevant(terms: list[dict], texts: list[str]) -> list[dict]:
    """Chỉ giữ các thuật ngữ thật sự xuất hiện trong lô câu đang dịch."""
    blob = "\n".join(texts)
    return [t for t in terms if t["source"] in blob]


def substitute(text: str, terms: list[dict]) -> str:
    """Thay thuật ngữ gốc bằng bản dịch đã chốt trước khi gửi cho máy dịch thường.

    Thay cụm dài trước để "乌坦城主" không bị "乌坦城" cắt ngang.
    """
    for t in sorted(terms, key=lambda t: -len(t["source"])):
        if t["source"] in text:
            text = text.replace(t["source"], f" {t['target']} ")
    return " ".join(text.split()) if terms else text


def parse_text(raw: str) -> list[dict]:
    """Nhập nhanh từ văn bản: mỗi dòng ``gốc = dịch`` (chấp nhận ``=``, tab, ``→``, ``|``)."""
    items = []
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for sep in ("\t", "=>", "→", "=", "|", "："):
            if sep in line:
                src, tgt = line.split(sep, 1)
                items.append({"source": src.strip(), "target": tgt.strip(), "note": ""})
                break
    return _clean(items)


def to_text(items: list[dict]) -> str:
    return "\n".join(f"{t['source']} = {t['target']}" for t in items) + ("\n" if items else "")
