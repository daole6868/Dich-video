"""Test "bộ máy thật": các thư viện gốc chạy thật trên máy này, không giả lập.

Mặc định bị bỏ qua vì cần mạng để tải hai mô hình nhỏ (Whisper "tiny" ~75 MB, một giọng Piper ~63 MB).
Bật bằng biến môi trường ``DVS_LIVE=1``::

    DVS_LIVE=1 python -m pytest tests/test_live.py -v

Mục đích: xác nhận trên một hệ điều hành mới rằng CTranslate2 (Whisper), ONNX Runtime (Piper, OCR),
espeak và ffmpeg/libass đều chạy được, kể cả khi thư mục dữ liệu có dấu tiếng Việt và khoảng trắng
(xem ``conftest.py``). Riêng bộ dịch vẫn là máy chủ giả lập vì test không có khoá API.
"""

import difflib
import json
import logging
import os
import re
import unicodedata

import numpy as np
import pytest
import requests

from dichvideo import asr, config, ffmpeg, ocr, tts
from dichvideo.translate import TranslateError, google, openai_compat
from mock_servers import MockServer, chat_reply

log = logging.getLogger("test_live")

pytestmark = pytest.mark.skipif(os.environ.get("DVS_LIVE") != "1",
                                reason="cần mạng để tải mô hình; bật bằng DVS_LIVE=1")

VOICE = "vi_VN-vais1000-medium"
SPOKEN = "Xin chào các bạn. Hôm nay chúng ta cùng học tiếng Việt."
DUB_LINE = "Chúc các bạn một ngày vui vẻ."


def plain(text: str) -> str:
    """Bỏ dấu, chữ thường, chỉ giữ chữ và số - để so lời nghe được với lời gốc."""
    text = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return " ".join(re.findall(r"[a-z0-9]+", text))


def heard_in(path, language="vi") -> str:
    wav16 = str(path) + ".16k.wav"
    ffmpeg.extract_audio(path, wav16)
    res = asr.transcribe_local(wav16, language=language, model="tiny", device="cpu", vad=False)
    assert res["device"] == "cpu"
    return " ".join(w["text"] for w in res["words"])


@pytest.fixture(scope="module")
def speech(tmp_path_factory):
    out = tmp_path_factory.mktemp("giọng đọc") / "câu nói.wav"
    assert tts.synthesize(SPOKEN, str(out), engine="piper", voice=VOICE)
    return out


def test_piper_speaks_and_whisper_hears_it(speech):
    info = ffmpeg.probe(speech)
    assert info["has_audio"] and 2.0 < info["duration"] < 12.0
    heard = heard_in(speech)
    ratio = difflib.SequenceMatcher(None, plain(heard), plain(SPOKEN)).ratio()
    assert ratio > 0.6, f"Whisper nghe được: {heard!r}"


def test_ocr_engine_reads_text_from_a_frame():
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (960, 160), (20, 24, 32))
    font = ImageFont.truetype(str(config.ROOT / "fonts" / "BeVietnamPro-Bold.ttf"), 72)
    ImageDraw.Draw(img).text((60, 30), "VIDEO 2026", font=font, fill=(255, 255, 255))
    items = ocr.read_frame_texts(ocr._make_engine(), np.asarray(img)[:, :, ::-1].copy(), need_cjk=False)
    text = " ".join(it["text"] for it in items)
    assert "2026" in text and "VIDEO" in text.upper(), text


def test_edge_voice_speaks_vietnamese(tmp_path):
    """Giọng mặc định (Microsoft Edge). Dịch vụ ngoài không phản hồi thì bỏ qua, không tính là lỗi."""
    out = tmp_path / "giọng edge.mp3"
    try:
        made = tts.synthesize(DUB_LINE, str(out), engine="edge", voice="vi-VN-HoaiMyNeural")
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"dịch vụ giọng đọc Edge không phản hồi từ máy này: {type(e).__name__}: {e}")
    assert made and 1.0 < ffmpeg.probe(out)["duration"] < 10.0
    heard = heard_in(out)
    ratio = difflib.SequenceMatcher(None, plain(heard), plain(DUB_LINE)).ratio()
    log.info("Edge đọc, Whisper nghe được: %r (khớp %.2f)", heard, ratio)
    assert ratio > 0.6


def test_google_free_translation_with_real_batches(monkeypatch):
    """Google Dịch miễn phí (bộ dịch mặc định) với một lô câu thật. Bị giới hạn tần suất thì bỏ qua."""
    lines = ["你好，很高兴认识你。", "今天天气很好。", "我们明天去学校。", "这本书很有意思。", "他在北京工作了三年。",
             "请问火车站怎么走？", "我想喝一杯咖啡。", "这部电影我看过两次。", "妈妈做的饭最好吃。", "别担心，一切都会好的。",
             "你什么时候回来？", "谢谢你的帮助。"]
    monkeypatch.setattr(google, "MAX_ATTEMPTS", 2)  # test không cố nài khi máy chủ đã từ chối
    try:
        out = google.translate_lines(lines, "zh", "vi")
    except TranslateError as e:
        pytest.skip(f"Google Dịch miễn phí từ chối máy này: {e}")
    for zh, vi in zip(lines, out):
        log.info("%s  =>  %s", zh, vi)
    assert len(out) == len(lines) and all(v.strip() and v != z for z, v in zip(lines, out))
    assert not any(re.search(r"[\u4e00-\u9fff]", v) for v in out), "bản dịch còn sót chữ Hán"
    # Thứ tự câu phải được giữ nguyên qua việc gộp lô: kiểm vài từ khoá chắc chắn.
    assert "trường" in out[2].lower() and "cà phê" in out[6].lower() and "cảm ơn" in out[11].lower()


def test_whole_pipeline_with_real_engines(base, http, wait_idle, speech, tmp_path):
    # --- video nguồn: hình thử + câu nói do Piper đọc, bắt đầu ở giây 0,5
    src = tmp_path / "phim có tiếng.mp4"
    length = ffmpeg.probe(speech)["duration"] + 1.5
    ffmpeg.run(["-f", "lavfi", "-i", f"testsrc2=s=640x360:r=25:d={length:.2f}", "-i", str(speech),
                "-af", "adelay=500:all=1,apad", "-t", f"{length:.2f}", "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)])

    def translator(req):
        user = req["json"]["messages"][-1]["content"]
        rows = json.loads(user[user.index("["):user.rindex("]") + 1])
        return 200, {}, chat_reply(json.dumps({"translations": [{"id": r["id"], "vi": DUB_LINE} for r in rows]},
                                              ensure_ascii=False))

    with MockServer(translator) as llm:
        config.save_settings({"llm": {"custom": {"base_url": llm.url + "/v1", "api_key": "sk-test-0000", "model": "m"}}})
        openai_compat._variant_for.clear()
        proj = http.post(base + "/api/projects", json={"filename": src.name, "settings": {
            "source_lang": "auto", "subtitle_source": "asr", "asr": {"model": "tiny", "device": "cpu"},
            "translate": {"engine": "custom"},
            "dub": {"enabled": True, "engine": "piper", "voice": VOICE, "original_volume": 0},
            "output": {"soft_subs": True}}}).json()
        pid = proj["id"]
        with open(src, "rb") as f:
            assert http.put(f"{base}/api/projects/{pid}/source", data=f).status_code == 200
        assert http.post(f"{base}/api/projects/{pid}/run", json={}).status_code == 200
        proj = wait_idle(pid, timeout=900)
        log = http.get(f"{base}/api/projects/{pid}/log").json()["log"]
        assert {k: v["status"] for k, v in proj["steps"].items()} == dict.fromkeys(
            ["prepare", "transcribe", "translate", "dub", "render"], "done"), log
        assert llm.requests, "bộ dịch giả lập phải được gọi"

    segs = http.get(f"{base}/api/projects/{pid}/segments").json()["segments"]
    assert segs and all(s["text"].strip() and s["translation"] == DUB_LINE for s in segs)
    assert all(s["dub"]["duration"] > 0.5 for s in segs)
    assert proj["steps"]["transcribe"]["info"]["source"] == "asr"
    assert proj["steps"]["render"]["info"]["dubbed"] is True
    assert {"video", "dub_audio", "srt_vi", "srt_source", "srt_bilingual"} <= set(proj["outputs"])

    out = tmp_path / "kết quả.mp4"
    out.write_bytes(http.get(f"{base}/api/projects/{pid}/files/{requests.utils.quote(proj['outputs']['video'])}").content)
    info = ffmpeg.probe(out)
    assert info["has_video"] and info["has_audio"] and (info["width"], info["height"]) == (640, 360)
    assert abs(info["duration"] - length) < 0.6
    # Tiếng gốc đã tắt (original_volume = 0) nên lời nghe được trong video kết quả phải là câu lồng tiếng.
    heard = plain(heard_in(out))
    want = plain(DUB_LINE)
    best = max(difflib.SequenceMatcher(None, heard[i:i + len(want)], want).ratio()
               for i in range(0, max(1, len(heard) - len(want) + 1)))
    assert best > 0.6, f"Whisper nghe được trong video kết quả: {heard!r}"
    assert http.delete(f"{base}/api/projects/{pid}").json() == {"ok": True}
