"""Cắt lời thoại thành các câu phụ đề vừa đọc, dựa trên mốc thời gian từng từ.

Whisper thường trả về đoạn dài tới 30 giây; phụ đề và lồng tiếng cần câu ngắn,
ngắt đúng dấu câu hoặc chỗ ngừng. Mô-đun này làm việc đó.
"""

from __future__ import annotations

import re

STRONG = "。！？!?；;…．"
WEAK = "，,、：:"
PUNCT_RE = re.compile(r"[\s。！？!?；;…．，,、：:\"'“”‘’（）()《》〈〉【】\[\]\-—~·.]+")
CJK_RE = re.compile(r"[㐀-鿿豈-﫿぀-ヿ가-힯]")


# Dấu câu "dạng nhỏ" (U+FE50..FE6B) mà Whisper đôi khi sinh ra -> dấu thường tương ứng.
_SMALL_FORMS = {"﹐": "，", "﹑": "、", "﹒": "。", "﹔": "，", "﹕": "：", "﹖": "？", "﹗": "！",
                "｡": "。", "､": "、"}
_SMALL_RE = re.compile("[" + "".join(_SMALL_FORMS) + "]")


def normalize_punct(text: str) -> str:
    return _SMALL_RE.sub(lambda m: _SMALL_FORMS[m.group(0)], text)


def is_cjk_text(text: str) -> bool:
    if not text:
        return False
    return len(CJK_RE.findall(text)) >= max(1, len(text.strip()) * 0.3)


def visible_len(text: str, cjk: bool) -> int:
    """Độ dài hiển thị: chữ Hán bỏ dấu câu/khoảng trắng; chữ Latin đếm cả khoảng trắng."""
    if cjk:
        return len(PUNCT_RE.sub("", text))
    return len(text.strip())


def join_words(words: list[dict], cjk: bool) -> str:
    text = "".join(w["text"] for w in words)
    if cjk:
        # Whisper đôi khi dùng khoảng trắng thay dấu phẩy giữa các vế câu tiếng Trung.
        text = re.sub(r"(?<=[㐀-鿿])\s+(?=[㐀-鿿])", "，", text.strip())
        text = re.sub(r"\s+", "", text) if not re.search(r"[A-Za-z]", text) else re.sub(r"\s+", " ", text)
        # Dấu câu kiểu Latin lẫn trong chữ Hán -> dấu toàn hình cho thống nhất.
        text = re.sub(r"(?<=[㐀-鿿])[,?!;:](?=[㐀-鿿]|$)",
                      lambda m: {",": "，", "?": "？", "!": "！", ";": "；", ":": "："}[m.group(0)], text)
    else:
        text = re.sub(r"\s+", " ", text)
    text = text.strip()
    return text.rstrip(WEAK + "；;").strip()  # dấu phẩy/chấm phẩy treo cuối dòng phụ đề trông thừa


def _ends_with(text: str, chars: str) -> bool:
    t = text.rstrip().rstrip("\"'”’）)】]》")
    return bool(t) and t[-1] in chars


# Từ viết tắt có dấu chấm nhưng không kết thúc câu (văn bản chữ Latin).
_ABBREVIATIONS = {"mr.", "mrs.", "ms.", "dr.", "st.", "vs.", "etc.", "e.g.", "i.e.", "no.", "jr.", "sr.", "prof."}


def _ends_sentence(text: str, cjk: bool) -> bool:
    """Từ này có kết thúc một câu không. Với chữ Latin, dấu chấm cuối từ cũng là hết câu."""
    if _ends_with(text, STRONG):
        return True
    if cjk:
        return False
    t = text.strip().rstrip("\"'”’)]")
    return t.endswith(".") and t.lower() not in _ABBREVIATIONS and not t[:-1].replace(".", "").isdigit()


def resegment(words: list[dict], *, max_chars: int = 22, max_duration: float = 7.0,
              pause: float = 0.6, cjk: bool | None = None) -> list[dict]:
    """``words``: [{"start", "end", "text"}] theo thứ tự thời gian -> danh sách câu."""
    words = [dict(w, text=normalize_punct(w["text"])) for w in words if (w.get("text") or "").strip()]
    if not words:
        return []
    if cjk is None:
        cjk = is_cjk_text("".join(w["text"] for w in words[:400]))
    limit = max(6, int(max_chars)) if cjk else max(20, int(max_chars * 3.6))
    soft = max(4, int(limit * 0.6))
    min_part = max(2, int(limit * 0.2))

    groups: list[list[dict]] = []
    buf: list[dict] = []

    def flush(upto: int | None = None) -> None:
        nonlocal buf
        part = buf if upto is None else buf[:upto]
        if part:
            groups.append(part)
        buf = [] if upto is None else buf[upto:]

    def buf_len(ws: list[dict]) -> int:
        return visible_len("".join(w["text"] for w in ws), cjk)

    for i, w in enumerate(words):
        buf.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        gap = (nxt["start"] - w["end"]) if nxt else 0.0
        text = w["text"]
        weak_end = _ends_with(text, WEAK) or bool(cjk and nxt and nxt["text"][:1].isspace())
        length = buf_len(buf)
        duration = buf[-1]["end"] - buf[0]["start"]

        if nxt is None or _ends_sentence(text, cjk) or gap >= pause:
            flush()
            continue
        if length >= limit or duration >= max_duration:
            # Tìm chỗ ngắt đẹp nhất phía trước: dấu phẩy gần nhất, rồi tới quãng ngừng dài nhất.
            cut = None
            for j in range(len(buf) - 1, 0, -1):
                if _ends_with(buf[j - 1]["text"], WEAK) and buf_len(buf[:j]) >= min_part:
                    cut = j
                    break
            if cut is None and weak_end:
                flush()
                continue
            if cut is None:
                best_gap, best_j = 0.12, None
                for j in range(1, len(buf)):
                    g = buf[j]["start"] - buf[j - 1]["end"]
                    if g > best_gap and buf_len(buf[:j]) >= min_part:
                        best_gap, best_j = g, j
                cut = best_j
            if cut is None:
                flush()
            else:
                flush(cut)
            continue
        if weak_end and length >= soft:
            flush()

    flush()

    # Gộp mẩu quá ngắn ("好了", "当然"...) vào câu liền kề: ưu tiên câu phía sau vì các từ
    # đệm thường mở đầu một ý; chỉ gộp về phía trước khi câu trước chưa kết thúc hẳn.
    tiny = 3 if cjk else 8
    merged: list[list[dict]] = []
    i = 0
    while i < len(groups):
        g = groups[i]
        nxt = groups[i + 1] if i + 1 < len(groups) else None
        if buf_len(g) <= tiny:
            if (nxt is not None and nxt[0]["start"] - g[-1]["end"] <= 1.0
                    and buf_len(g + nxt) <= limit and not _ends_sentence(g[-1]["text"], cjk)):
                groups[i + 1] = g + nxt
                i += 1
                continue
            if merged:
                prev = merged[-1]
                if (g[0]["start"] - prev[-1]["end"] <= 0.5 and buf_len(prev + g) <= int(limit * 1.25)
                        and not _ends_sentence(prev[-1]["text"], cjk)):
                    merged[-1] = prev + g
                    i += 1
                    continue
        merged.append(g)
        i += 1

    segs: list[dict] = []
    for g in merged:
        text = join_words(g, cjk)
        if not text or not visible_len(text, cjk):
            continue
        segs.append({"start": float(g[0]["start"]), "end": float(g[-1]["end"]), "text": text})
    return polish_timing(segs)


def polish_timing(segs: list[dict], *, min_duration: float = 0.6, linger: float = 0.2,
                  min_gap: float = 0.04) -> list[dict]:
    """Không cho các câu chồng nhau; kéo dài nhẹ câu quá ngắn nếu còn khoảng trống."""
    segs = sorted(segs, key=lambda s: s["start"])
    for i, seg in enumerate(segs):
        start = seg["start"]
        end = max(seg["end"], start + 0.1)
        want = max(end + linger, start + min_duration)
        if i + 1 < len(segs):
            ceiling = max(segs[i + 1]["start"] - min_gap, start + 0.1)
            want = min(want, ceiling)
        seg["start"] = round(start, 3)
        seg["end"] = round(want, 3)
    return segs


def split_by_punctuation(seg: dict, *, max_chars: int = 22, cjk: bool | None = None) -> list[dict]:
    """Chia một đoạn không có mốc thời gian từng từ: phân bổ thời gian theo số ký tự."""
    text = (seg.get("text") or "").strip()
    if not text:
        return []
    if cjk is None:
        cjk = is_cjk_text(text)
    limit = max(6, int(max_chars)) if cjk else max(20, int(max_chars * 3.6))
    if visible_len(text, cjk) <= limit:
        return [dict(seg, text=text.rstrip(WEAK))]
    # Biến văn bản thành "từ" giả với thời lượng tỉ lệ số ký tự rồi dùng lại resegment.
    tokens = re.findall(r"[^。！？!?；;…，,、：:\s]+[。！？!?；;…，,、：:]*\s*|[。！？!?；;…，,、：:]+\s*", text) if cjk \
        else re.findall(r"\S+\s*", text)
    if cjk:
        pieces: list[str] = []
        for tok in tokens:
            body = tok.rstrip()
            core = re.sub(r"[。！？!?；;…，,、：:]+$", "", body)
            tail = body[len(core):]
            chars = list(core)
            if not chars:
                if pieces:
                    pieces[-1] += tail
                continue
            chars[-1] += tail
            pieces.extend(chars)
        tokens = pieces
    total = sum(max(1, visible_len(t, cjk)) for t in tokens) or 1
    span = max(0.1, float(seg["end"]) - float(seg["start"]))
    t = float(seg["start"])
    words = []
    for tok in tokens:
        d = span * max(1, visible_len(tok, cjk)) / total
        words.append({"start": t, "end": t + d, "text": tok})
        t += d
    return resegment(words, max_chars=max_chars, max_duration=1e9, pause=1e9, cjk=cjk)
