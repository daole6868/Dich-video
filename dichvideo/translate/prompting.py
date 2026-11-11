"""Lời nhắc và việc đọc kết quả, dùng chung cho mọi bộ dịch AI (LLM)."""

from __future__ import annotations

import json
import re

from .. import config

SOURCE_NAMES = {
    "zh": "Chinese (Mandarin)", "yue": "Cantonese", "en": "English", "ja": "Japanese",
    "ko": "Korean", "auto": "the source language",
}

# Lược đồ JSON cho kết quả: mỗi câu một mục, giữ nguyên id.
RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, "vi": {"type": "string"}},
                "required": ["id", "vi"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["translations"],
    "additionalProperties": False,
}


def build_system_prompt(source_lang: str, style_id: str, context: str, terms: list[dict]) -> str:
    src = SOURCE_NAMES.get(source_lang, "the source language")
    style = next((s for s in config.TRANSLATE_STYLES if s["id"] == style_id), None)
    parts = [
        f"You are a professional subtitle translator who localizes {src} videos for Vietnamese "
        "audiences. Translate each subtitle line into natural, fluent Vietnamese.",
        "",
        "Rules:",
        "1. Be faithful to the meaning but write the way Vietnamese people really speak. "
        "No word-for-word translation.",
        "2. Keep every line concise: it is read on screen and also voiced by a narrator in the same "
        "time slot as the original line. Never add explanations, notes or brackets.",
        "3. Return exactly one translation per input line with the same id. Never merge, split, "
        "skip or reorder lines. When a line is a fragment of a longer sentence, translate just that "
        "fragment so consecutive lines read naturally together.",
        "4. Proper nouns from Chinese (people, places, sects, techniques, titles) use the "
        "Sino-Vietnamese (Hán-Việt) reading, e.g. 李明 -> Lý Minh, 北京 -> Bắc Kinh. Keep "
        "international brand names in their usual form.",
        "5. Choose Vietnamese forms of address (xưng hô) that fit the speakers' relationship and "
        "keep them consistent across lines.",
        "6. Convert numbers, units and money naturally (元 -> tệ, 万 -> vạn or chục nghìn as fits).",
        "7. When a glossary term appears in a line, use its given translation exactly.",
        "8. Output Vietnamese only: no Chinese characters, no pinyin.",
    ]
    if style and style.get("hint"):
        parts += ["", f"Genre and tone: {style['hint']}"]
    if context.strip():
        parts += ["", "About this video (from the user): " + context.strip()]
    if terms:
        parts += ["", "Glossary (source = required translation):"]
        parts += [f"- {t['source']} = {t['target']}" + (f"  ({t['note']})" if t.get("note") else "")
                  for t in terms]
    parts += [
        "",
        'Reply with JSON only, in this shape: {"translations": [{"id": 1, "vi": "..."}]}',
    ]
    return "\n".join(parts)


def build_user_prompt(batch: list[dict], before: list[dict], after: list[dict]) -> str:
    parts = []
    if before:
        parts.append("Previous lines, already translated (context only, do not output them):")
        for s in before:
            vi = (s.get("translation") or "").replace("\n", " ")
            parts.append(f"- {s['text']}" + (f"  =>  {vi}" if vi else ""))
        parts.append("")
    parts.append("Translate these lines:")
    parts.append(json.dumps([{"id": s["id"], "text": s["text"].replace("\n", " ")} for s in batch],
                            ensure_ascii=False))
    if after:
        parts.append("")
        parts.append("Following lines (context only, do not translate them):")
        parts += [f"- {s['text']}" for s in after]
    return "\n".join(parts)


_THINK_RE = re.compile(r"<think(?:ing)?>.*?</think(?:ing)?>", re.S | re.I)
_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.S)
_NUMBERED_RE = re.compile(r"^\s*[\[(]?(\d+)[\])]?\s*[:.|\-–]\s*(.+?)\s*$")


def _from_json(data, ids: list[int]) -> dict[int, str]:
    out: dict[int, str] = {}
    if isinstance(data, dict):
        for key in ("translations", "result", "results", "data", "lines"):
            if isinstance(data.get(key), list):
                return _from_json(data[key], ids)
        for k, v in data.items():  # dạng {"12": "..."}
            if str(k).strip().isdigit() and isinstance(v, str):
                out[int(k)] = v
        return out
    if isinstance(data, list):
        if data and all(isinstance(x, str) for x in data) and len(data) == len(ids):
            return dict(zip(ids, data))
        for item in data:
            if not isinstance(item, dict):
                continue
            raw_id = item.get("id", item.get("index"))
            text = next((item[k] for k in ("vi", "translation", "text", "target") if isinstance(item.get(k), str)), None)
            try:
                if raw_id is not None and text is not None:
                    out[int(raw_id)] = text
            except (TypeError, ValueError):
                continue
    return out


def parse_translations(text: str, ids: list[int]) -> dict[int, str]:
    """Đọc câu trả lời của mô hình thành ``{id: bản dịch}``; chịu được vài kiểu trả lời lệch."""
    text = _THINK_RE.sub("", text or "").strip()
    candidates = [text] + _FENCE_RE.findall(text)
    for opener, closer in (("{", "}"), ("[", "]")):
        a, b = text.find(opener), text.rfind(closer)
        if 0 <= a < b:
            candidates.append(text[a:b + 1])
    wanted = set(ids)
    for cand in candidates:
        try:
            got = _from_json(json.loads(cand), ids)
        except (ValueError, TypeError):
            continue
        got = {i: " ".join(str(v).split()) for i, v in got.items() if i in wanted and str(v).strip()}
        if got:
            return got
    # Không phải JSON: thử dạng "12: bản dịch" trên từng dòng.
    out: dict[int, str] = {}
    for line in text.splitlines():
        m = _NUMBERED_RE.match(line)
        if m and int(m.group(1)) in wanted:
            out[int(m.group(1))] = m.group(2).strip().strip('"')
    return out
