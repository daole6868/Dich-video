"""Test đọc/ghi phụ đề và tách câu."""

import pytest

from dichvideo import segmenter, subtitles


# ---------------------------------------------------------------- thời gian

@pytest.mark.parametrize("t, srt, ass", [
    (0, "00:00:00,000", "0:00:00.00"),
    (1.5, "00:00:01,500", "0:00:01.50"),
    (59.9996, "00:01:00,000", "0:01:00.00"),
    (3723.456, "01:02:03,456", "1:02:03.46"),
    (-2, "00:00:00,000", "0:00:00.00"),
])
def test_time_formatting(t, srt, ass):
    assert subtitles.srt_time(t) == srt
    assert subtitles.vtt_time(t) == srt.replace(",", ".")
    assert subtitles.ass_time(t) == ass


@pytest.mark.parametrize("text, expected", [
    ("00:00:01,500", 1.5), ("01:02:03.456", 3723.456), ("1:23.4", 83.4), ("0:05", 5.0), ("abc", None),
])
def test_parse_time(text, expected):
    assert subtitles.parse_time(text) == expected


# ---------------------------------------------------------------- đọc tệp

SRT = """1
00:00:01,000 --> 00:00:02,500
<i>你好</i>

2
00:00:03,000 --> 00:00:05,000
第一行
第二行
3
00:00:06,000 --> 00:00:07,000
{\\an8}没有空行分隔
"""


def test_parse_srt_handles_markup_multiline_and_missing_blank_line():
    segs = subtitles.parse_srt(SRT)
    assert [(s["start"], s["end"], s["text"]) for s in segs] == [
        (1.0, 2.5, "你好"), (3.0, 5.0, "第一行\n第二行"), (6.0, 7.0, "没有空行分隔")]


def test_parse_vtt_and_ass():
    vtt = "WEBVTT\n\n00:01.000 --> 00:02.000\nXin chào\n\n00:03.000 --> 00:04.000 align:start\n<v Nam>Tạm biệt\n"
    assert [s["text"] for s in subtitles.parse_srt(vtt)] == ["Xin chào", "Tạm biệt"]
    ass = ("[Script Info]\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
           "Dialogue: 0,0:00:01.00,0:00:02.50,Default,,0,0,0,,{\\b1}Dòng một\\NDòng hai, có dấu phẩy\n")
    segs = subtitles.parse_subtitle_file(ass.encode("utf-8"), "a.ass")
    assert segs[0]["text"] == "Dòng một\nDòng hai, có dấu phẩy" and segs[0]["end"] == 2.5


def test_decode_old_chinese_and_bom_files():
    assert subtitles.decode_bytes("你好".encode("gb18030")) == "你好"
    assert subtitles.decode_bytes("﻿Xin chào".encode("utf-8")) == "Xin chào"
    assert subtitles.decode_bytes("Xin chào".encode("utf-16")) == "Xin chào"


def test_normalize_sorts_renumbers_and_fixes_times():
    out = subtitles.normalize([
        {"start": 5, "end": 4, "text": "sau"},
        {"start": 1, "end": 2, "text": "  trước  ", "voice": "x"},
        {"start": 3, "end": 4, "text": "", "translation": ""},
        {"start": "hỏng", "end": 1, "text": "bỏ"},
    ])
    assert [(s["id"], s["text"]) for s in out] == [(1, "trước"), (2, "sau")]
    assert out[0]["voice"] == "x" and out[1]["end"] > out[1]["start"]


# ---------------------------------------------------------------- ghi tệp

SEGS = [{"id": 1, "start": 1.0, "end": 2.5, "text": "你好", "translation": "Xin chào"},
        {"id": 2, "start": 3.0, "end": 4.0, "text": "没翻译", "translation": ""}]


def test_srt_export_modes_and_roundtrip():
    vi = subtitles.to_srt(SEGS, "vi")
    assert "Xin chào" in vi and "没翻译" not in vi and vi.startswith("1\n00:00:01,000 --> 00:00:02,500")
    both = subtitles.to_srt(SEGS, "bilingual")
    assert "Xin chào\n你好" in both and "2\n00:00:03,000" in both
    again = subtitles.parse_srt(subtitles.to_srt(SEGS, "zh"))
    assert [s["text"] for s in again] == ["你好", "没翻译"]
    assert subtitles.to_vtt(SEGS).startswith("WEBVTT") and subtitles.to_txt(SEGS, "zh") == "你好\n没翻译\n"


def test_ass_color_and_escape():
    assert subtitles.ass_color("#FF8000") == "&H000080FF"
    assert subtitles.ass_color("#000000", 50) == "&H80000000"
    assert subtitles.ass_color("rác") == "&H00FFFFFF"
    assert subtitles.ass_escape("a{b}\\c\nd") == "a(b)/c\\Nd"


def test_build_ass_scales_size_by_em_ratio_and_resolution():
    style = {"font": "Be Vietnam Pro", "size": 46, "outline": 3, "margin_v": 10, "margin_h": 5, "bold": True}
    ass = subtitles.build_ass(SEGS, style, 1280, 720, em_ratio=0.6553)
    assert "PlayResX: 1280" in ass and "PlayResY: 720" in ass
    line = next(ln for ln in ass.splitlines() if ln.startswith("Style: Chinh"))
    fields = line.split(",")
    assert fields[1] == "Be Vietnam Pro"
    assert float(fields[2]) == pytest.approx(46 * 720 / 1080 / 0.6553, abs=0.1)  # cỡ em -> cỡ ASS
    assert fields[7] == "-1" and fields[-2] == "72"  # đậm; lề dưới 10% của 720
    assert ass.count("Dialogue:") == 1  # câu chưa dịch không hiện ở chế độ tiếng Việt


def test_build_ass_bilingual_box_and_uppercase():
    style = {"font": "Kanit", "size": 40, "box": True, "box_color": "#102030", "box_opacity": 50, "uppercase": True}
    ass = subtitles.build_ass(SEGS, style, 1920, 1080, mode="bilingual", cjk_font="Noto Sans CJK SC")
    main = next(ln for ln in ass.splitlines() if ln.startswith("Style: Chinh")).split(",")
    assert main[15] == "3" and main[5] == "&H80302010"  # kiểu hộp, màu hộp nửa trong suốt
    assert "XIN CHÀO\\N{\\rPhu}你好" in ass and "Style: Phu,Noto Sans CJK SC" in ass
    assert ass.count("Dialogue:") == 2  # câu chỉ có lời gốc vẫn hiện ở chế độ song ngữ


# ---------------------------------------------------------------- tách câu

def words(spec):
    """'你好，|0.0-0.5' ... -> danh sách từ có mốc thời gian."""
    out = []
    for item in spec:
        text, span = item.split("|")
        a, b = span.split("-")
        out.append({"text": text, "start": float(a), "end": float(b)})
    return out


def chars(text, start=0.0, step=0.2):
    """Mỗi ký tự một 'từ', dấu câu dính vào ký tự đứng trước (giống Whisper với tiếng Trung)."""
    out = []
    for ch in text:
        if ch in "，。！？、；" and out:
            out[-1]["text"] += ch
        else:
            t = start + len(out) * step
            out.append({"text": ch, "start": round(t, 2), "end": round(t + step, 2)})
    return out


def test_resegment_splits_on_sentence_end_and_pause():
    segs = segmenter.resegment(chars("今天天气很好。我们去公园吧"))
    assert [s["text"] for s in segs] == ["今天天气很好。", "我们去公园吧"]
    gap = words(["你好|0.0-0.4", "吗|0.4-0.6", "我很好|2.0-2.6"])
    assert [s["text"] for s in segmenter.resegment(gap)] == ["你好吗", "我很好"]


def test_resegment_long_sentence_breaks_at_comma_within_limit():
    text = "最近几年人工智能技术进步非常快，尤其是大语言模型，已经可以帮助我们写文章"
    segs = segmenter.resegment(chars(text), max_chars=18)
    assert len(segs) >= 2
    assert all(segmenter.visible_len(s["text"], True) <= 22 for s in segs)
    assert "".join(s["text"] for s in segs).replace("，", "") == text.replace("，", "")
    assert not any(s["text"].endswith(("，", ",")) for s in segs)  # không để dấu phẩy treo cuối dòng


def test_resegment_merges_tiny_filler_into_next_sentence():
    w = words(["好了，|0.0-0.4"]) + chars("今天的视频就到这里", start=1.1)
    segs = segmenter.resegment(w)
    assert [s["text"] for s in segs] == ["好了，今天的视频就到这里"]


def test_resegment_normalizes_odd_punctuation_from_whisper():
    w = words(["大家好﹔|0.0-0.5", "欢迎|0.5-0.9", "收看﹔|0.9-1.3"])
    segs = segmenter.resegment(w)
    assert "﹔" not in "".join(s["text"] for s in segs)
    assert segs[0]["text"] == "大家好，欢迎收看"


def test_resegment_latin_text_keeps_spaces():
    w = words([" Hello|0.0-0.3", " world.|0.3-0.6", " How|0.7-0.9", " are|0.9-1.0", " you?|1.0-1.3"])
    assert [s["text"] for s in segmenter.resegment(w, cjk=False)] == ["Hello world.", "How are you?"]
    # Dấu chấm của từ viết tắt và số thập phân không phải hết câu.
    w = words([" Dr.|0.0-0.2", " Lee|0.2-0.5", " paid|0.5-0.8", " 3.5|0.8-1.1", " dollars.|1.1-1.5"])
    assert [s["text"] for s in segmenter.resegment(w, cjk=False)] == ["Dr. Lee paid 3.5 dollars."]


def test_polish_timing_removes_overlap_and_extends_short_lines():
    segs = segmenter.polish_timing([{"start": 0.0, "end": 1.5, "text": "a"}, {"start": 1.2, "end": 1.3, "text": "b"},
                                    {"start": 5.0, "end": 5.1, "text": "c"}])
    assert segs[0]["end"] <= segs[1]["start"]
    assert segs[2]["end"] - segs[2]["start"] == pytest.approx(0.6, abs=1e-6)  # câu ngắn được kéo dài tới mức tối thiểu
    assert all(s["end"] > s["start"] for s in segs)


def test_split_by_punctuation_distributes_time():
    seg = {"start": 10.0, "end": 20.0, "text": "这是第一句话，这是第二句话，这是第三句话。"}
    parts = segmenter.split_by_punctuation(seg, max_chars=8)
    assert len(parts) == 3 and parts[0]["start"] == 10.0
    assert abs(parts[-1]["end"] - 20.0) < 0.3 and parts[1]["start"] > parts[0]["start"]
    short = segmenter.split_by_punctuation({"start": 0, "end": 1, "text": "很短，"}, max_chars=22)
    assert short == [{"start": 0, "end": 1, "text": "很短"}]
