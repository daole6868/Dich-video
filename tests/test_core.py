"""Test các mô-đun lõi: lồng tiếng, xuất video, logic OCR, cấu hình, dự án, phông chữ, giọng đọc."""

import json
import os
import subprocess
import sys
import threading
import time
import wave

import numpy as np
import pytest

from dichvideo import asr, config, dubbing, ffmpeg, fileops, fonts, ocr, pipeline, projects, render, tts
from dichvideo.ffmpeg import Cancelled

from mock_servers import MockServer


@pytest.fixture(scope="session")
def sample_video(tmp_path_factory):
    """Video thử 3 giây 640x360 có tiếng, tạo bằng ffmpeg (không cần tệp ngoài)."""
    out = tmp_path_factory.mktemp("media") / "mau.mp4"
    ffmpeg.run(["-f", "lavfi", "-i", "testsrc2=s=640x360:r=25:d=3", "-f", "lavfi", "-i", "sine=f=440:d=3",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out)])
    return out


def tone(seconds: float, freq: float = 220.0, amp: float = 0.3) -> np.ndarray:
    t = np.arange(int(dubbing.SR * seconds)) / dubbing.SR
    return (np.sin(2 * np.pi * freq * t) * amp * 32767).astype(np.int16)


# ---------------------------------------------------------------- ffmpeg

def test_probe_parses_ffmpeg_banner_variants():
    text = """Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'a.mp4':
  Duration: 00:02:06.73, start: 0.000000, bitrate: 924 kb/s
  Stream #0:0[0x1](und): Video: h264 (High) (avc1 / 0x31637661), yuv420p(tv, bt709, progressive), 1280x720 [SAR 1:1 DAR 16:9], 749 kb/s, 30 fps, 30 tbr, 16k tbn (default)
  Stream #0:1[0x2](und): Audio: aac (LC) (mp4a / 0x6134706D), 44100 Hz, stereo, fltp, 164 kb/s (default)"""
    info = ffmpeg.parse_probe(text)
    assert info["duration"] == pytest.approx(126.73) and (info["width"], info["height"]) == (1280, 720)
    assert info["fps"] == 30 and info["video_codec"] == "h264" and info["audio_codec"] == "aac"
    rotated = """  Duration: 00:00:10.00, start: 0.0
  Stream #0:0(eng): Video: hevc (Main), yuv420p, 1920x1080, 60 fps
    Side data:
      displaymatrix: rotation of -90.00 degrees
  Stream #0:1: Audio: aac, 48000 Hz, stereo"""
    info = ffmpeg.parse_probe(rotated)
    assert (info["width"], info["height"]) == (1080, 1920) and info["rotation"] == 270
    assert (info["frame_width"], info["frame_height"]) == (1080, 1920)
    wide = "  Duration: 00:00:10.00\n  Stream #0:0: Video: mpeg2video, yuv420p, 720x576 [SAR 64:45 DAR 16:9], 25 fps"
    info = ffmpeg.parse_probe(wide)
    assert (info["width"], info["height"], info["frame_width"]) == (1024, 576, 720) and info["sar"] == pytest.approx(1.4222, abs=1e-3)
    cover = "  Duration: 00:03:00.00\n  Stream #0:0: Audio: mp3, 44100 Hz\n  Stream #0:1: Video: mjpeg, yuvj420p, 600x600 (attached pic)"
    info = ffmpeg.parse_probe(cover)
    assert info["has_audio"] and not info["has_video"]


def test_probe_extract_audio_and_frame(sample_video, tmp_path):
    info = ffmpeg.probe(sample_video)
    assert info["has_video"] and info["has_audio"] and (info["width"], info["height"]) == (640, 360)
    assert info["duration"] == pytest.approx(3.0, abs=0.2)
    seen = []
    ffmpeg.extract_audio(sample_video, tmp_path / "a.wav", duration=info["duration"], progress=seen.append)
    with wave.open(str(tmp_path / "a.wav")) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2)
    assert seen and seen[-1] == 1.0
    ffmpeg.extract_frame(sample_video, 1.0, tmp_path / "f.jpg", max_width=320)
    from PIL import Image
    assert Image.open(tmp_path / "f.jpg").size == (320, 180)
    with pytest.raises(ffmpeg.FFmpegError):
        ffmpeg.probe(tmp_path / "khong-co.mp4")


def test_run_can_be_cancelled(tmp_path):
    cancel = threading.Event()
    threading.Timer(0.5, cancel.set).start()
    with pytest.raises(Cancelled):
        ffmpeg.run(["-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=600", "-c:v", "libx264", "-preset", "slow",
                    str(tmp_path / "dai.mp4")], cancel=cancel)


# ---------------------------------------------------------------- nhận dạng (phần không cần mô hình)

def test_snap_leading_word_fixes_early_first_word():
    w = [{"start": 19.47, "end": 19.75, "text": "去"}, {"start": 23.0, "end": 23.3, "text": "超市"}]
    fixed = asr.snap_leading_word([dict(x) for x in w])
    assert fixed[0]["end"] == 23.0 and 22.5 < fixed[0]["start"] < 23.0
    near = [{"start": 1.0, "end": 1.2, "text": "你"}, {"start": 1.3, "end": 1.5, "text": "好"}]
    assert asr.snap_leading_word([dict(x) for x in near]) == near


def test_hallucination_filter():
    assert asr.is_hallucination("字幕由Amara.org社区提供")
    assert asr.is_hallucination("请不吝点赞 订阅 转发 打赏支持明镜与点点栏目")
    assert asr.is_hallucination("谢谢观看", no_speech_prob=0.8)
    assert not asr.is_hallucination("谢谢观看", no_speech_prob=0.1)  # có người nói thật thì giữ
    assert not asr.is_hallucination("今天我们去超市")


def test_transcribe_api_sends_audio_and_reads_words(tmp_path):
    wav = tmp_path / "a16k.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes((np.sin(np.arange(16000 * 4) / 20) * 8000).astype(np.int16).tobytes())

    def handler(req):
        assert req["path"] == "/v1/audio/transcriptions" and req["headers"]["authorization"] == "Bearer khoa"
        assert b'name="model"' in req["raw"] and b"whisper-thu" in req["raw"] and b'filename="audio.mp3"' in req["raw"]
        return 200, {}, {"text": "你好世界", "segments": [{"start": 0.5, "end": 2.0, "text": "你好世界"}],
                         "words": [{"word": "你好", "start": 0.5, "end": 1.0}, {"word": "世界", "start": 1.1, "end": 2.0}]}

    with MockServer(handler) as srv:
        res = asr.transcribe_api(wav, language="zh", api={"base_url": srv.url + "/v1", "api_key": "khoa", "model": "whisper-thu"})
    segs = asr.words_to_segments(res)
    assert [s["text"] for s in segs] == ["你好世界。"] and segs[0]["start"] == 0.5
    with pytest.raises(RuntimeError, match="khoá API"):
        asr.transcribe_api(wav, api={"base_url": "https://vi-du.invalid/v1", "api_key": "", "model": "x"})


# ---------------------------------------------------------------- lồng tiếng

def clips_for(durations):
    return {i + 1: {"pcm": f"c{i + 1}.pcm", "duration": d} for i, d in enumerate(durations)}


def test_schedule_keeps_natural_speed_when_it_fits():
    segs = [{"id": 1, "start": 1.0, "end": 3.0}, {"id": 2, "start": 5.0, "end": 7.0}]
    plan = dubbing.schedule(segs, clips_for([1.5, 2.0]), 10.0)
    assert [(p["start"], p["speed"]) for p in plan] == [(1.0, 1.0), (5.0, 1.0)]
    assert dubbing.summarize(plan)["sped_up"] == 0


def test_schedule_uses_gap_before_next_line_then_speeds_up():
    segs = [{"id": 1, "start": 0.0, "end": 2.0}, {"id": 2, "start": 4.0, "end": 6.0}]
    # Câu 1 dài 3,5 giây: khoảng trống tới câu 2 là 4 giây nên không cần tăng tốc.
    assert dubbing.schedule(segs, clips_for([3.5, 1.0]), 10.0)[0]["speed"] == 1.0
    # Dài 5 giây: phải nhanh lên ~1,27 lần để xong trước khi câu 2 bắt đầu.
    plan = dubbing.schedule(segs, clips_for([5.0, 1.0]), 10.0)
    assert plan[0]["speed"] == pytest.approx(5.0 / (4.0 - dubbing.MIN_GAP), abs=0.01)
    assert plan[0]["start"] + plan[0]["duration"] <= 4.0 and plan[1]["start"] == 4.0


def test_schedule_caps_speed_and_pushes_next_line():
    segs = [{"id": 1, "start": 0.0, "end": 1.0}, {"id": 2, "start": 1.0, "end": 2.0}, {"id": 3, "start": 20.0, "end": 21.0}]
    plan = dubbing.schedule(segs, clips_for([4.0, 1.0, 1.0]), 30.0, max_speed=1.5)
    assert plan[0]["speed"] == 1.5 and plan[0]["overflow"] > 0
    assert plan[1]["start"] == pytest.approx(4.0 / 1.5 + dubbing.MIN_GAP, abs=0.01) and plan[1]["late"] > 1.0
    assert plan[2]["start"] == 20.0 and plan[2]["late"] == 0  # tới chỗ có khoảng trống thì hết trễ
    for a, b in zip(plan, plan[1:]):
        assert a["start"] + a["duration"] <= b["start"] + 1e-6  # không bao giờ chồng tiếng
    s = dubbing.summarize(plan)
    assert s["clips"] == 3 and s["sped_up"] >= 1 and s["overflow"] == 1 and s["max_speed"] == 1.5


def test_trim_silence_and_normalize_level():
    quiet = np.zeros(dubbing.SR // 2, dtype=np.int16)
    clip = np.concatenate([quiet, tone(1.0, amp=0.05), quiet])
    trimmed = dubbing.trim_silence(clip)
    assert len(trimmed) / dubbing.SR == pytest.approx(1.04, abs=0.03)
    assert len(dubbing.trim_silence(quiet)) == 0
    loud = dubbing.normalize_level(trimmed)
    rms = np.sqrt((loud.astype(np.float32) / 32768) ** 2).mean()
    assert 0.05 < rms < 0.12 and np.abs(loud).max() <= 32767


def test_tempo_and_pitch_change_keep_expected_duration():
    clip = tone(2.0)
    fast = dubbing.change_tempo(clip, 1.5)
    assert len(fast) / dubbing.SR == pytest.approx(2.0 / 1.5, abs=0.05)
    assert dubbing.change_tempo(clip, 1.0) is clip
    shifted = dubbing.shift_pitch(clip, 3)
    assert len(shifted) / dubbing.SR == pytest.approx(2.0, abs=0.06)


def test_duck_envelope_is_down_during_speech_and_ramps():
    plan = [{"start": 2.0, "duration": 1.0}, {"start": 3.2, "duration": 1.0}]
    env = dubbing.duck_envelope(plan, 10.0, base=1.0, ducked=0.15)
    at = lambda t: float(env[int(t / 0.01)])  # noqa: E731
    assert at(0.5) == pytest.approx(1.0) and at(9.0) == pytest.approx(1.0)
    assert at(2.0) == pytest.approx(0.15, abs=0.01) and at(3.9) == pytest.approx(0.15, abs=0.01)
    assert at(3.1) == pytest.approx(0.15, abs=0.01)  # hai câu sát nhau: nền không phập phồng ở giữa
    assert 0.15 < at(1.65) < 1.0  # đoạn chuyển mượt


def test_build_track_and_mix_end_to_end(sample_video, tmp_path):
    for i, d in ((1, 0.8), (2, 1.6)):
        (tmp_path / f"c{i}.pcm").write_bytes(tone(d, 300 * i).tobytes())
    segs = [{"id": 1, "start": 0.2, "end": 1.0}, {"id": 2, "start": 1.1, "end": 2.0}]
    clips = {1: {"pcm": str(tmp_path / "c1.pcm"), "duration": 0.8}, 2: {"pcm": str(tmp_path / "c2.pcm"), "duration": 1.6}}
    plan = dubbing.schedule(segs, clips, 3.0, max_speed=1.2)
    length = dubbing.build_track(plan, tmp_path / "dub.wav", 3.0)
    assert length >= 3.0
    with wave.open(str(tmp_path / "dub.wav")) as w:
        dub = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        assert w.getnchannels() == 1 and w.getframerate() == dubbing.SR
    assert np.abs(dub[: int(0.15 * dubbing.SR)]).max() == 0  # trước câu đầu là im lặng
    assert np.abs(dub[int(0.4 * dubbing.SR): int(0.6 * dubbing.SR)]).max() > 1000
    dubbing.mix(sample_video, tmp_path / "dub.wav", tmp_path / "mix.wav", plan, 3.0, background_volume=0.2)
    dubbing.mix(None, tmp_path / "dub.wav", tmp_path / "solo.wav", plan, 3.0)
    for name in ("mix.wav", "solo.wav"):
        with wave.open(str(tmp_path / name)) as w:
            assert w.getnchannels() == 2 and w.getnframes() / w.getframerate() == pytest.approx(3.0, abs=0.01)


# ---------------------------------------------------------------- xuất video

MEDIA = {"width": 1920, "height": 1080, "duration": 60.0, "has_video": True, "has_audio": True, "video_codec": "h264"}


def test_output_size_only_downscales_and_stays_even():
    assert render.output_size(MEDIA, {"resolution": "source"}) == (1920, 1080)
    assert render.output_size(MEDIA, {"resolution": "720"}) == (1280, 720)
    assert render.output_size(MEDIA, {"resolution": "2160"}) == (1920, 1080)
    assert render.output_size({"width": 1080, "height": 1920}, {"resolution": "720"}) == (720, 1280)
    assert render.output_size({"width": 853, "height": 479}, {"resolution": "source"}) == (854, 480)


def test_cover_intervals_pad_and_merge():
    segs = [{"start": 1.12, "end": 2.12, "text": "a"}, {"start": 2.38, "end": 3.62, "text": "b"},
            {"start": 8.6, "end": 9.9, "text": "c"}, {"start": 59.9, "end": 61.0, "text": "d"}, {"start": 30, "end": 31, "text": ""}]
    assert render.cover_intervals(segs, 60.0) == [(0.82, 3.92), (8.3, 10.2), (59.6, 60.0)]


def test_cover_timing_modes():
    assert render.cover_timed({"cover_when": "auto"}, "ocr") and not render.cover_timed({"cover_when": "auto"}, "asr")
    assert render.cover_timed({"cover_when": "subtitle"}, "asr") and not render.cover_timed({"cover_when": "always"}, "ocr")


def test_video_chain_static_and_timed():
    st = {"cover": [{"x": 0.1, "y": 0.8, "w": 0.8, "h": 0.1, "mode": "blur", "strength": 60},
                    {"x": 0, "y": 0, "w": 0.2, "h": 0.1, "mode": "box", "color": "#102030", "opacity": 80},
                    {"x": 0.5, "y": 0.5, "w": 0.001, "h": 0.001}]}
    graph, label, cmds = render.build_video_chain(1280, 720, (1280, 720), st, ass_name="subs.ass", logo_input=None)
    assert "gblur" in graph and "drawbox=x=0:y=0:w=256:h=72:color=0x102030@0.80:t=fill" in graph
    assert graph.endswith(f"ass=subs.ass:fontsdir=fonts[{label}]") and "sendcmd" not in graph and cmds == ""
    assert graph.count("crop=") == 1  # vùng quá nhỏ bị bỏ
    graph, _label, cmds = render.build_video_chain(1280, 720, (1920, 1080), st, ass_name=None, logo_input=1,
                                                   cover_times=[(1.0, 2.5)])
    assert graph.startswith("[0:v]scale=1280:720") and "sendcmd=f=cover.cmd" in graph
    assert "overlay@cv1=" in graph and "drawbox@cv2=" in graph and graph.count(":enable=0") == 2
    assert cmds == "1.000 overlay@cv1 enable 1, drawbox@cv2 enable 1;\n2.500 overlay@cv1 enable 0, drawbox@cv2 enable 0;\n"
    assert "[1:v]scale=" in graph and "colorchannelmixer" in graph
    assert render.build_video_chain(1280, 720, (1280, 720), {"cover": []}, ass_name=None, logo_input=None) is None
    off = render.build_video_chain(1280, 720, (1280, 720), st, ass_name="subs.ass", logo_input=None, cover_on=False)
    assert "gblur" not in off[0] and "drawbox" not in off[0]


def test_auto_cover_region_and_margin():
    cover = render.auto_cover_region([0.35, 0.80, 0.30, 0.12])
    assert cover["x"] == pytest.approx(0.31) and cover["w"] == pytest.approx(0.38) and cover["mode"] == "blur"
    assert render.auto_cover_region([0.0, 0.8, 1.0, 0.1])["w"] == 1.0
    margin = render.margin_for_region(cover, {"size": 46}, 1280, 720)
    center_from_bottom = 720 * (1 - 0.86)
    assert margin == pytest.approx((center_from_bottom - 0.62 * 46 * 720 / 1080) / 720 * 100, abs=0.1)


def test_encoder_args_and_fallback_choice():
    assert render.encoder_args("libx264", "medium", "medium") == ["-c:v", "libx264", "-preset", "fast", "-crf", "23"]
    assert "h264_nvenc" in render.encoder_args("h264_nvenc", "high", "fast")
    assert ffmpeg.pick_encoder("cpu") == "libx264"
    assert not ffmpeg.encoder_usable("bo_ma_hoa_khong_ton_tai")


def test_render_real_video_with_subtitles_cover_and_soft_subs(sample_video, tmp_path):
    media = ffmpeg.probe(sample_video)
    segs = [{"id": 1, "start": 0.3, "end": 1.4, "text": "你好", "translation": "Xin chào các bạn"},
            {"id": 2, "start": 1.6, "end": 2.8, "text": "再见", "translation": "Hẹn gặp lại"}]
    st = config.new_project_settings()
    st["cover"] = [{"x": 0.1, "y": 0.75, "w": 0.8, "h": 0.2, "mode": "blur", "strength": 60}]
    st["cover_when"] = "subtitle"
    st["output"]["soft_subs"] = True
    seen = []
    info = render.render(sample_video, tmp_path / "ra.mp4", project_dir=tmp_path, segments=segs, settings=st,
                         media=media, progress=lambda p, m: seen.append(p))
    assert info["burned"] and info["soft_subs"] and info["cover"] == "subtitle"
    # Máy có bộ mã hoá phần cứng dùng được (ví dụ VideoToolbox trên Mac) thì chế độ tự động chọn nó.
    assert info["encoder"] == ffmpeg.pick_encoder("auto")
    out = ffmpeg.probe(tmp_path / "ra.mp4")
    assert (out["width"], out["height"]) == (640, 360) and out["duration"] == pytest.approx(3.0, abs=0.2)
    assert seen and seen[-1] == 1.0
    assert (tmp_path / "work" / "render" / "cover.cmd").read_text(encoding="utf-8").startswith("0.000 overlay@cv1 enable 1;")
    assert "Xin chào các bạn" in (tmp_path / "work" / "render" / "subs.ass").read_text(encoding="utf-8")
    # Phụ đề thực sự được vẽ lên hình: khung có câu thoại khác khung cùng thời điểm khi không gắn phụ đề.
    from PIL import Image, ImageChops
    st2 = config.new_project_settings()
    st2["subtitle"]["burn"] = False
    info2 = render.render(sample_video, tmp_path / "tron.mp4", project_dir=tmp_path, segments=segs, settings=st2, media=media)
    # Không gắn phụ đề, không che: hình được chép nguyên, không mã hoá lại.
    assert info2["encoder"] == "copy" and ffmpeg.probe(tmp_path / "tron.mp4")["video_codec"] == "h264"
    ffmpeg.extract_frame(tmp_path / "ra.mp4", 0.8, tmp_path / "a.png")
    ffmpeg.extract_frame(tmp_path / "tron.mp4", 0.8, tmp_path / "b.png")
    diff = ImageChops.difference(Image.open(tmp_path / "a.png").convert("L"), Image.open(tmp_path / "b.png").convert("L"))
    band = diff.crop((0, 250, 640, 360))
    assert np.asarray(band).mean() > 3.0
    render.preview_frame(sample_video, 0.8, tmp_path / "xem.jpg", project_dir=tmp_path, segments=segs, settings=st, media=media)
    assert Image.open(tmp_path / "xem.jpg").size == (640, 360)


def test_render_odd_sized_source_is_scaled_to_even(tmp_path):
    src = tmp_path / "le.mkv"
    # Bộ mã hoá ffv1 + màu 4:4:4 giữ được kích thước lẻ (nguồn testsrc2 tự làm tròn về số chẵn nên phải co lại).
    ffmpeg.run(["-f", "lavfi", "-i", "testsrc2=s=854x480:r=25:d=1", "-vf", "scale=853:479,setsar=1", "-c:v", "ffv1",
                "-pix_fmt", "yuv444p", str(src)])
    media = ffmpeg.probe(src)
    assert (media["width"], media["height"], media["sar"]) == (853, 479, 1.0)
    st = config.new_project_settings()
    segs = [{"id": 1, "start": 0.1, "end": 0.9, "text": "你好", "translation": "Xin chào"}]
    for burn in (True, False):  # có và không có bộ lọc hình: đều phải ra kích thước chẵn
        st["subtitle"]["burn"] = burn
        info = render.render(src, tmp_path / f"ra{burn}.mp4", project_dir=tmp_path, segments=segs, settings=st, media=media)
        out = ffmpeg.probe(tmp_path / f"ra{burn}.mp4")
        assert (out["width"], out["height"]) == (854, 480) == (info["width"], info["height"])


def test_render_non_square_pixels_become_square(tmp_path):
    """Video điểm ảnh không vuông (kiểu DVD 720x576 hiển thị 16:9) phải ra đúng tỉ lệ hiển thị."""
    src = tmp_path / "dvd.mkv"
    ffmpeg.run(["-f", "lavfi", "-i", "testsrc2=s=720x576:r=25:d=1", "-vf", "setsar=64/45", "-c:v", "libx264",
                "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(src)])
    media = ffmpeg.probe(src)
    assert (media["frame_width"], media["frame_height"]) == (720, 576) and (media["width"], media["height"]) == (1024, 576)
    assert render.source_frame_size(media) == (0, 0)
    st = config.new_project_settings()
    st["subtitle"]["burn"] = False
    st["output"]["encoder"] = "cpu"  # ép mã hoá bằng CPU dù máy có bộ mã hoá phần cứng
    info = render.render(src, tmp_path / "ra.mp4", project_dir=tmp_path, segments=[], settings=st, media=media)
    out = ffmpeg.probe(tmp_path / "ra.mp4")
    assert (out["width"], out["height"], out["sar"]) == (1024, 576, 1.0) and info["encoder"] == "libx264"


# ---------------------------------------------------------------- OCR (phần logic, không cần mô hình)

def test_merge_frames_groups_same_text_and_tolerates_one_miss():
    f = [(0.0, "", 0), (0.25, "你好世界", 0.9), (0.5, "你好世界", 0.95), (0.75, "", 0), (1.0, "你好世界", 0.9),
         (1.25, "", 0), (1.5, "", 0), (2.0, "再见", 0.9), (2.25, "再见", 0.9), (3.0, "闪一下", 0.9)]
    events = ocr.merge_frames(f, 0.25)
    assert [(e["text"], e["start"], e["end"]) for e in events] == [("你好世界", 0.125, 1.125), ("再见", 1.875, 2.375)]


def test_merge_frames_progressive_text_and_misreads():
    f = [(0.0, "今", 0.9), (0.25, "今天", 0.9), (0.5, "今天天气", 0.9), (0.75, "今天天气很好", 0.9), (1.0, "今天天气很好", 0.9),
         (1.25, "今天天气很奸", 0.7)]
    events = ocr.merge_frames(f, 0.25)
    assert len(events) == 1 and events[0]["text"] == "今天天气很好"


def test_similarity_and_signature():
    assert ocr.similar("你好，世界！", "你好世界") == 1.0 and ocr.similar("你好", "") == 0.0
    assert ocr.similar("今天天气很好", "明天去公园玩") < ocr.SAME_TEXT
    a = np.zeros((40, 320, 3), dtype=np.uint8)
    b = a.copy(); b[10:30, 100:220] = 255
    c = b.copy(); c[12:14, 110:112] = 0
    assert ocr.same_signature(ocr.frame_signature(b), ocr.frame_signature(c))
    assert not ocr.same_signature(ocr.frame_signature(a), ocr.frame_signature(b))


def test_dominant_line_drops_scene_text():
    def item(text, y, h=48, x=500):
        return {"text": text, "score": 0.95, "box": (x, y, x + 40 * len(text), y + h)}

    subs = [item("这是一句字幕", 110) for _ in range(20)]
    noise = [item("山", 4, h=25), item("池", 0, h=200), item("口", 52)]
    line = ocr.dominant_line(subs + noise)
    assert line is not None and line[0] == pytest.approx(134, abs=3) and line[1] == 48
    assert all(ocr.on_subtitle_line(s, line) for s in subs)
    assert not ocr.on_subtitle_line(noise[0], line) and not ocr.on_subtitle_line(noise[1], line)
    assert ocr.on_subtitle_line(item("第二行字幕", 110 + 52), line)  # dòng thứ hai của phụ đề hai dòng
    assert ocr.dominant_line(subs[:3]) is None  # quá ít dữ liệu thì không lọc


def test_ocr_regions():
    assert ocr.default_region({"width": 1920, "height": 1080})[1] > ocr.default_region({"width": 1080, "height": 1920})[1]
    assert ocr.valid_region([0.1, 0.5, 2.0, 0.9], {"width": 100, "height": 100}) == [0.1, 0.5, 0.9, 0.5]
    assert ocr.valid_region("rác", {"width": 1920, "height": 1080}) == ocr.default_region({"width": 1920, "height": 1080})


# ---------------------------------------------------------------- cấu hình, dự án, quy trình

def test_settings_merge_conform_and_secret_masking():
    assert config.deep_merge({"a": {"b": 1, "c": 2}}, {"a": {"b": 5}, "d": 1}) == {"a": {"b": 5, "c": 2}, "d": 1}
    broken = config.conform_project_settings({"dub": "hỏng", "segment": {"max_chars": "x"}, "subtitle": {"size": 60.7}})
    assert broken["dub"]["engine"] == "edge" and broken["segment"]["max_chars"] == 22 and broken["subtitle"]["size"] == 60
    config.update_settings_from_client({"llm": {"openai": {"api_key": "  sk-abcdefghijklmnop  "}}})
    assert config.load_settings()["llm"]["openai"]["api_key"] == "sk-abcdefghijklmnop"
    public = config.public_settings()
    assert public["llm"]["openai"]["api_key"] == "••••mnop"
    public["llm"]["openai"]["model"] = "mo-hinh-moi"
    config.update_settings_from_client(public)  # gửi lại khoá dạng che: khoá thật phải được giữ nguyên
    saved = config.load_settings()["llm"]["openai"]
    assert saved["api_key"] == "sk-abcdefghijklmnop" and saved["model"] == "mo-hinh-moi"
    config.update_settings_from_client({"llm": {"openai": {"api_key": ""}}})
    assert config.load_settings()["llm"]["openai"]["api_key"] == ""
    config.SETTINGS_FILE.write_text("{hỏng", encoding="utf-8")
    config._cache = None
    assert config.load_settings()["defaults"]["source_lang"] == "zh"  # tệp cài đặt hỏng không làm sập ứng dụng


def test_project_store_lifecycle():
    with pytest.raises(projects.ProjectError):
        projects.create("x", "tai-lieu.pdf")
    p = projects.create("  Phim: tập 1/2?  ", "phim tap 1.MKV", settings={"dub": {"enabled": False}, "la": 1})
    pid = p["id"]
    assert projects.ID_RE.match(pid) and p["name"] == "Phim tập 1 2" and p["source"]["file"] == "source.mkv"
    assert p["settings"]["dub"]["enabled"] is False and p["settings"]["subtitle"]["font"] == "Be Vietnam Pro"
    saved = projects.save_segments(pid, [{"start": 2, "end": 3, "text": "b", "translation": "B"}, {"start": 0, "end": 1, "text": "a"}])
    assert [s["id"] for s in saved] == [1, 2] and projects.load(pid)["counts"] == {"segments": 2, "translated": 1}
    projects.set_step(pid, "render", status="done")
    projects.set_step(pid, "dub", status="running")
    projects.mark_stale(pid, ["render", "translate"])
    assert projects.load(pid)["steps"]["render"]["status"] == "stale" and projects.load(pid)["steps"]["translate"]["status"] == "pending"
    assert projects.recover_interrupted() >= 1 and projects.load(pid)["steps"]["dub"]["status"] == "error"
    assert any(x["id"] == pid for x in projects.list_all())
    projects.log(pid, "dòng nhật ký")
    assert "dòng nhật ký" in projects.read_log(pid)
    for bad in ("../../etc", "20261111-000000-zzzz", "", None):
        with pytest.raises(projects.ProjectError):
            projects.check_id(bad)
    projects.delete(pid)
    with pytest.raises(projects.ProjectError):
        projects.load(pid)


def test_fileops_retry_when_a_file_is_briefly_locked(tmp_path, monkeypatch):
    """Giả lập Windows: tệp đích đang bị chương trình khác giữ nên ghi đè / xoá bị từ chối."""
    src, dst = tmp_path / "moi.tmp", tmp_path / "du lieu.json"
    src.write_text("mới", encoding="utf-8")
    dst.write_text("cũ", encoding="utf-8")
    real_replace, calls = os.replace, []

    def locked_twice(a, b):
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError(13, "tệp đang được dùng")
        real_replace(a, b)

    monkeypatch.setattr(fileops.os, "replace", locked_twice)
    fileops.replace(src, dst, wait=2.0)
    assert dst.read_text(encoding="utf-8") == "mới" and len(calls) == 3 and not src.exists()

    def always_locked(*_):
        raise PermissionError(13, "tệp đang được dùng")

    monkeypatch.setattr(fileops.os, "replace", always_locked)
    with pytest.raises(PermissionError):
        fileops.replace(dst, tmp_path / "khac.json", wait=0.1)
    with pytest.raises(PermissionError):  # ghi cài đặt: báo lỗi thật chứ không âm thầm bỏ qua, và dọn tệp tạm
        config.write_json_atomic(tmp_path / "cai dat.json", {"a": 1})
    assert [f.name for f in tmp_path.iterdir()] == ["du lieu.json"]
    assert fileops.remove(tmp_path / "không có") is True
    monkeypatch.setattr(fileops.os, "remove", always_locked)
    assert fileops.remove(dst, wait=0.05) is False and dst.exists()


def test_project_delete_with_locked_file_then_leftovers_are_cleaned(monkeypatch):
    p = projects.create("Thử xoá", "phim.mp4")
    d = projects.project_dir(p["id"])
    (d / "source.mp4").write_bytes(b"video")
    # Một tệp trong dự án còn bị giữ nên thư mục không xoá hết được ngay.
    monkeypatch.setattr(fileops, "remove_tree", lambda path, wait=0.0: False)
    projects.delete(p["id"])
    assert d.is_dir() and not (d / "project.json").exists()
    assert all(x["id"] != p["id"] for x in projects.list_all())
    with pytest.raises(projects.ProjectError):
        projects.load(p["id"])
    monkeypatch.undo()
    assert projects.remove_leftovers() == 1 and not d.exists()
    assert projects.remove_leftovers() == 0


@pytest.mark.skipif(sys.platform != "win32", reason="cơ chế job object chỉ có trên Windows")
def test_ffmpeg_child_is_killed_when_the_app_dies(tmp_path):
    """Ứng dụng bị tắt đột ngột (đóng cửa sổ) thì ffmpeg đang chạy ngầm cũng phải dừng theo."""
    import ctypes

    k32 = ctypes.windll.kernel32
    k32.OpenProcess.restype = ctypes.c_void_p

    def alive(pid: int) -> bool:
        handle = k32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            return False
        try:
            return k32.WaitForSingleObject(ctypes.c_void_p(handle), 0) == 0x102  # WAIT_TIMEOUT: còn chạy
        finally:
            k32.CloseHandle(ctypes.c_void_p(handle))

    script = tmp_path / "ung dung gia.py"
    script.write_text(
        "import sys, time\n"
        f"sys.path.insert(0, {str(config.ROOT)!r})\n"
        "from dichvideo import ffmpeg\n"
        "p = ffmpeg.spawn([ffmpeg.ffmpeg_path(), '-hide_banner', '-loglevel', 'error', '-nostdin', '-re',\n"
        "                  '-f', 'lavfi', '-i', 'testsrc2=d=120', '-f', 'null', '-'])\n"
        "print(p.pid, flush=True)\n"
        "time.sleep(120)\n", encoding="utf-8")
    app = subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE)
    child = 0
    try:
        child = int(app.stdout.readline())
        time.sleep(0.5)
        assert alive(child), "ffmpeg lẽ ra phải đang chạy"
        app.kill()
        app.wait()
        end = time.time() + 10
        while alive(child) and time.time() < end:
            time.sleep(0.2)
        assert not alive(child), "ffmpeg vẫn chạy ngầm sau khi ứng dụng đã tắt"
    finally:
        if app.poll() is None:
            app.kill()
        if child and alive(child):
            subprocess.run(["taskkill", "/PID", str(child), "/F"], capture_output=True)


def test_native_path_is_unchanged_when_no_alias_is_needed(tmp_path):
    plain = tmp_path / "thu muc"
    plain.mkdir()
    if os.name != "nt":
        assert fileops.native_path(tmp_path / "thư mục có dấu") == str(tmp_path / "thư mục có dấu")
    elif str(plain).isascii():
        assert fileops.native_path(plain) == str(plain)


@pytest.mark.skipif(os.name != "nt", reason="chỉ Windows mới cần đường dẫn thay thế")
def test_native_path_gives_ascii_alias_for_accented_folders(tmp_path):
    """Thư viện C không hiểu đường dẫn có dấu trên Windows: phải có đường dẫn ASCII trỏ tới cùng chỗ."""
    folder = tmp_path / "thư mục có dấu"
    folder.mkdir()
    (folder / "phontab").write_bytes(b"du lieu")
    alias = fileops.native_path(folder)
    assert alias.isascii() and os.path.samefile(alias, folder)
    assert open(os.path.join(alias, "phontab"), "rb").read() == b"du lieu"
    one = fileops.native_path(folder / "phontab")
    assert one.isascii() and os.path.samefile(one, folder / "phontab")
    # Nhánh lối tắt thư mục (junction) - dùng khi ổ đĩa không tạo tên ngắn 8.3.
    link = fileops._junction_alias(str(folder))
    assert link and link.isascii() and os.path.samefile(link, folder)
    assert fileops._junction_alias(str(folder)) == link  # gọi lại thì dùng lại lối tắt cũ
    os.rmdir(link)  # gỡ lối tắt không được đụng tới thư mục thật
    assert (folder / "phontab").is_file()


def test_piper_never_lets_espeak_kill_the_app(tmp_path, monkeypatch):
    """espeak gọi exit(1) khi không đọc được dữ liệu; ứng dụng phải chặn trước và báo lỗi bình thường."""
    import piper.phonemize_espeak as espeak

    from dichvideo.tts import piper_engine

    monkeypatch.setattr(espeak, "ESPEAK_DATA_DIR", tmp_path / "không có")
    with pytest.raises(RuntimeError, match="Piper"):
        piper_engine._espeak_data_dir()
    monkeypatch.undo()
    safe = piper_engine._espeak_data_dir()
    assert os.path.isfile(os.path.join(safe, "phontab")) and (os.name != "nt" or safe.isascii())


def test_safe_name_keeps_unicode_and_strips_reserved():
    assert projects.safe_name('Tập 1: "鲤鱼" <thử>|.') == "Tập 1 鲤鱼 thử"
    assert projects.safe_name("con") == "_con" and projects.safe_name("NUL.phim") == "_NUL.phim"
    assert projects.safe_name("concert") == "concert" and projects.safe_name("...") == "video"
    assert projects.safe_name("   ...   ") == "video" and len(projects.safe_name("a" * 300)) == 80


def test_pipeline_source_choice_and_step_planning():
    data = {"settings": config.new_project_settings(), "media": {"has_video": True, "has_audio": True},
            "hardsub": {"found": True}, "steps": projects.blank_steps()}
    assert pipeline.resolve_source(data) == "both"
    data["hardsub"] = {"found": False}
    assert pipeline.resolve_source(data) == "asr"
    data["media"]["has_audio"] = False
    assert pipeline.resolve_source(data) == "ocr"
    data["settings"]["subtitle_source"] = "asr"
    assert pipeline.resolve_source(data) == "asr"
    long_ocr = [{"text": "这是字幕里的一句话"}] * 10
    assert pipeline.choose_source(long_ocr, [{"text": "这是听到的一句话"}] * 10) == "ocr"
    assert pipeline.choose_source([{"text": "山"}], [{"text": "这是听到的一句话"}] * 10) == "asr"
    assert pipeline.choose_source([], [{"text": "a"}]) == "asr" and pipeline.choose_source(long_ocr, []) == "ocr"
    assert pipeline.plan_steps(data, None) == projects.STEPS
    data["steps"]["prepare"]["status"] = data["steps"]["transcribe"]["status"] = "done"
    assert pipeline.plan_steps(data, None) == ["translate", "dub", "render"]
    data["settings"]["dub"]["enabled"] = False
    assert pipeline.plan_steps(data, None) == ["translate", "render"]
    assert pipeline.plan_steps(data, ["render", "dub", "translate"]) == ["translate", "render"]


# ---------------------------------------------------------------- phông chữ, giọng đọc

def test_bundled_fonts_cover_vietnamese_and_have_sane_metrics():
    fams = fonts.catalog(refresh=True)["families"]
    names = [f["family"] for f in fams]
    assert names[0] == "Be Vietnam Pro" and len(names) >= 10
    assert all(f["vietnamese"] for f in fams if f["origin"] == "kem-theo")
    assert all(0.3 < f["em_ratio"] < 1.0 for f in fams)
    main = fams[0]
    assert main["has_bold"] and main["has_italic"] and fonts.em_ratio("Be Vietnam Pro") == pytest.approx(0.6553, abs=0.001)
    assert fonts.resolve_family("Phông Không Có") == "Be Vietnam Pro" and fonts.em_ratio("Phông Không Có") == 0.7


def test_tts_text_cleaning_and_cache_key():
    assert tts.clean_text('  "Xin chào" [nhạc]…  ') == "Xin chào nhạc"
    assert tts.clean_text("50% & hơn") == "50 phần trăm và hơn"
    assert tts.clean_text("…!!! ~~") == "" and tts.clean_text("") == ""
    k = tts.cache_key("Xin chào", "edge", "vi-VN-HoaiMyNeural", 0, 0)
    assert k == tts.cache_key('"Xin chào"', "edge", "vi-VN-HoaiMyNeural", 0, 0)
    assert k != tts.cache_key("Xin chào", "edge", "vi-VN-NamMinhNeural", 0, 0) != tts.cache_key("Xin chào", "edge", "", 10, 0)


def test_tts_batch_uses_cache_skips_silent_lines_and_reports_progress(tmp_path, monkeypatch):
    calls = []

    def fake(text, out, *, voice, rate=0, pitch=0):
        calls.append(text)
        with open(out, "wb") as f:
            f.write(b"x" * 500)

    monkeypatch.setitem(tts._SYNTH, "edge", fake)
    (tmp_path / "co-san.mp3").write_bytes(b"y" * 500)
    jobs = [{"key": "a", "text": "Xin chào", "out_path": str(tmp_path / "a.mp3"), "engine": "edge", "voice": "v"},
            {"key": "b", "text": "…", "out_path": str(tmp_path / "b.mp3"), "engine": "edge", "voice": "v"},
            {"key": "c", "text": "Đã có", "out_path": str(tmp_path / "co-san.mp3"), "engine": "edge", "voice": "v"}]
    seen = []
    result = tts.synthesize_batch(jobs, progress=lambda d, t: seen.append((d, t)))
    assert result == {"a": True, "b": False, "c": True} and calls == ["Xin chào"]
    assert seen[0] == (1, 3) and seen[-1] == (3, 3) and not (tmp_path / "b.mp3").exists()
    cancel = threading.Event(); cancel.set()
    with pytest.raises(Cancelled):
        tts.synthesize_batch([{"key": "z", "text": "Câu mới", "out_path": str(tmp_path / "z.mp3"), "engine": "edge"}], cancel=cancel)


def test_api_tts_engines_send_expected_requests(tmp_path):
    def handler(req):
        if req["path"] == "/v1/audio/speech":
            assert req["json"] == {"model": "gpt-4o-mini-tts", "input": "Xin chào", "voice": "nova", "response_format": "mp3", "speed": 1.2}
            assert req["headers"]["authorization"] == "Bearer khoa-tts"
            return 200, {"Content-Type": "audio/mpeg"}, b"ID3" + b"\x00" * 600
        if req["path"] == "/v1/voices":
            return 200, {}, {"voices": [{"voice_id": "abc", "name": "Lan", "labels": {"gender": "female", "language": "vi"}}]}
        assert req["path"] == "/v1/text-to-speech/abc" and req["headers"]["xi-api-key"] == "khoa-11"
        assert req["json"]["language_code"] == "vi" and req["json"]["model_id"] == "eleven_flash_v2_5"
        return 200, {"Content-Type": "audio/mpeg"}, b"ID3" + b"\x00" * 600

    with MockServer(handler) as srv:
        config.save_settings({"tts_openai": {"base_url": srv.url + "/v1", "api_key": "khoa-tts"},
                              "tts_elevenlabs": {"api_key": "khoa-11", "base_url": srv.url}})
        assert tts.synthesize("Xin chào", str(tmp_path / "o.mp3"), engine="openai", voice="nova", rate=20)
        assert tts.list_voices("elevenlabs") == [{"id": "abc", "name": "Lan", "gender": "female", "lang": "vi"}]
        assert tts.synthesize("Xin chào", str(tmp_path / "e.mp3"), engine="elevenlabs", voice="abc")
    assert (tmp_path / "o.mp3").stat().st_size > 500 and (tmp_path / "e.mp3").stat().st_size > 500
    config.save_settings({"tts_openai": {"api_key": "", "base_url": "https://vi-du.invalid/v1"}})
    with pytest.raises(RuntimeError, match="khoá API"):
        tts.synthesize("Xin chào", str(tmp_path / "x.mp3"), engine="openai", voice="nova")
    assert json.loads(json.dumps(tts.list_voices("piper")))[0]["id"].startswith("vi_VN")


# ---------------------------------------------------------------- tải video từ liên kết

def test_download_from_link_with_local_server(sample_video, tmp_path):
    import functools
    import http.server

    from dichvideo import downloader

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(sample_video.parent))
    handler.log_message = lambda *a, **k: None
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        seen = []
        got = downloader.download(f"{base}/{sample_video.name}", tmp_path / "tai", progress=lambda p, m: seen.append(p))
        assert got["path"].name == "source.mp4" and got["path"].stat().st_size == sample_video.stat().st_size
        assert got["title"] == "mau" and seen[-1] == 1.0
        with pytest.raises(downloader.DownloadError, match="Không tải được video"):
            downloader.download(f"{base}/khong-co.mp4", tmp_path / "hong")
        stop = threading.Event(); stop.set()
        with pytest.raises(Cancelled):
            downloader.download(f"{base}/{sample_video.name}", tmp_path / "huy", cancel=stop)
    finally:
        httpd.shutdown()
        httpd.server_close()
    for bad in ("ftp://may-chu/phim.mp4", "khong phai lien ket", "", "file:///etc/passwd"):
        with pytest.raises(downloader.DownloadError):
            downloader.check_url(bad)

