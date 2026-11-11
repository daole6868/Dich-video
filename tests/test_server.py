"""Test API bằng một máy chủ thật chạy trong tiến trình test (không cần mạng, không cần mô hình)."""

import json
import socket

import pytest
import requests

from dichvideo import config, ffmpeg
from dichvideo.translate import openai_compat
from mock_servers import MockServer, chat_reply


@pytest.fixture(scope="module")
def video(tmp_path_factory):
    out = tmp_path_factory.mktemp("api") / "phim thử.mp4"
    ffmpeg.run(["-f", "lavfi", "-i", "testsrc2=s=640x360:r=25:d=4", "-f", "lavfi", "-i", "sine=f=330:d=4",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out)])
    return out


SRT_ZH = "1\n00:00:00,300 --> 00:00:01,500\n你好\n\n2\n00:00:02,000 --> 00:00:03,500\n再见\n"
SRT_VI = "1\n00:00:00,300 --> 00:00:01,500\nXin chào\n\n2\n00:00:02,000 --> 00:00:03,500\nTạm biệt\n"


def test_guard_blocks_foreign_host_and_cross_site_writes(base, http):
    assert http.get(base + "/api/system", headers={"Host": "trang-la.example"}).status_code == 403
    r = http.post(base + "/api/projects", json={}, headers={"Origin": "https://trang-la.example"})
    assert r.status_code == 403 and "từ chối" in r.json()["error"]
    assert http.post(base + "/api/projects", json={}, headers={"Origin": "null"}).status_code == 403
    assert http.post(base + "/api/projects", json={}, headers={"Origin": base}).status_code == 400  # cùng nguồn: qua cổng bảo vệ
    assert http.get(base + "/api/system", headers={"Origin": "https://trang-la.example"}).status_code == 200  # đọc không đổi dữ liệu


def test_ping_and_second_launch_detection(base, http):
    import run

    info = http.get(base + "/api/ping").json()
    assert info["app"] == "Dịch Video Studio" and info["data_dir"] == str(config.DATA_DIR)
    port = int(base.rsplit(":", 1)[1])
    assert run.running_instance(port) is True and run.port_free("127.0.0.1", port) is False
    with socket.socket() as s:  # cổng chưa ai dùng
        s.bind(("127.0.0.1", 0))
        free = s.getsockname()[1]
    assert run.running_instance(free) is False


def test_static_pages_and_fonts(base, http):
    r = http.get(base + "/")
    assert r.status_code == 200 and "Dịch Video Studio" in r.text and r.headers["cache-control"] == "no-cache"
    assert http.get(base + "/static/js/main.js").status_code == 200
    assert http.get(base + "/static/vendor/vue.global.prod.js").headers["content-type"].startswith(("text/javascript", "application/javascript"))
    font = http.get(base + "/fonts/BeVietnamPro-Bold.ttf")
    assert font.status_code == 200 and len(font.content) > 100_000
    assert http.get(base + "/fonts/..%2Frun.py").status_code == 404 and http.get(base + "/fonts/khong-co.ttf").status_code == 404


def test_system_settings_glossary(base, http):
    sysinfo = http.get(base + "/api/system").json()
    assert sysinfo["ffmpeg"]["ok"] and len(sysinfo["fonts"]) >= 10 and sysinfo["default_settings"]["source_lang"] == "zh"
    assert [e["id"] for e in sysinfo["tts_engines"]] == ["edge", "piper", "openai", "elevenlabs"]
    saved = http.put(base + "/api/settings", json={"llm": {"deepseek": {"api_key": "sk-bi-mat-123456789"}}}).json()
    assert saved["llm"]["deepseek"]["api_key"] == "••••6789"
    assert "sk-bi-mat" not in http.get(base + "/api/settings").text
    g = http.put(base + "/api/glossary", json={"text": "萧炎 = Tiêu Viêm\n药老 = Dược Lão"}).json()
    assert [t["target"] for t in g["items"]] == ["Tiêu Viêm", "Dược Lão"]
    assert http.get(base + "/api/glossary").json()["text"] == "萧炎 = Tiêu Viêm\n药老 = Dược Lão\n"
    assert http.put(base + "/api/settings", data="{hỏng", headers={"Content-Type": "application/json"}).status_code == 400


def test_project_flow_without_network(base, http, video, wait_idle):
    assert http.post(base + "/api/projects", json={"filename": "tai-lieu.pdf"}).status_code == 400
    proj = http.post(base + "/api/projects", json={"filename": video.name, "settings": {"dub": {"enabled": False}}}).json()
    pid = proj["id"]
    assert proj["name"] == "phim thử" and not proj["source"]["ready"]
    assert http.post(f"{base}/api/projects/{pid}/run", json={}).status_code == 409  # chưa có video
    with open(video, "rb") as f:
        up = http.put(f"{base}/api/projects/{pid}/source", data=f, headers={"Content-Type": "application/octet-stream"})
    assert up.status_code == 200 and up.json()["source"]["ready"]
    assert http.put(f"{base}/api/projects/{pid}/source", data=b"x").status_code == 409  # không ghi đè video đã có

    # --- chuẩn bị: đọc thông tin, ảnh thu nhỏ, kiểm tra phụ đề cứng
    assert http.post(f"{base}/api/projects/{pid}/run", json={"steps": ["prepare"]}).status_code == 200
    proj = wait_idle(pid)
    assert proj["steps"]["prepare"]["status"] == "done", proj["steps"]["prepare"]
    assert (proj["media"]["width"], proj["media"]["height"]) == (640, 360) and proj["hardsub"]["found"] is False
    assert http.get(f"{base}/api/projects/{pid}/thumb").headers["content-type"] == "image/jpeg"
    assert http.get(f"{base}/api/projects/{pid}/frame?t=1.5").content[:2] == b"\xff\xd8"
    # --- phát video: tua bằng Range (máy chủ tự gửi từng khối, không giữ tệp mở)
    url = f"{base}/api/projects/{pid}/video"
    whole = http.get(url)
    size = len(whole.content)
    assert whole.status_code == 200 and whole.headers["accept-ranges"] == "bytes" and size > 300_000
    assert int(whole.headers["content-length"]) == size and whole.content == video.read_bytes()
    part = http.get(url, headers={"Range": "bytes=100-199"})
    assert part.status_code == 206 and part.content == whole.content[100:200]
    assert part.headers["content-range"] == f"bytes 100-199/{size}" and part.headers["content-length"] == "100"
    assert http.get(url, headers={"Range": "bytes=-50"}).content == whole.content[-50:]
    rest = http.get(url, headers={"Range": f"bytes={size - 10}-{size + 999}"})
    assert rest.status_code == 206 and rest.content == whole.content[-10:]
    assert http.get(url, headers={"Range": f"bytes={size}-"}).status_code == 416
    head = http.head(url, headers={"Range": "bytes=0-9"})
    assert head.status_code == 206 and head.headers["content-length"] == "10" and not head.content
    stale = http.get(url, headers={"Range": "bytes=0-9", "If-Range": '"phiên-bản-cũ"'.encode().decode("latin-1")})
    assert stale.status_code == 200 and len(stale.content) == size
    assert http.get(url, headers={"Range": "bytes=0-9", "If-Range": whole.headers["etag"]}).status_code == 206

    # --- nhập lời gốc rồi nhập bản dịch: thông tin nguồn lời thoại phải được giữ
    r = http.post(f"{base}/api/projects/{pid}/subtitles/import?kind=source&filename=goc.srt", data=SRT_ZH.encode())
    assert r.status_code == 200 and [s["text"] for s in r.json()["segments"]] == ["你好", "再见"]
    assert r.json()["project"]["steps"]["transcribe"]["info"]["source"] == "import"
    r = http.post(f"{base}/api/projects/{pid}/subtitles/import?kind=translation&filename=dich.srt", data=SRT_VI.encode())
    body = r.json()
    assert [s["translation"] for s in body["segments"]] == ["Xin chào", "Tạm biệt"] and body["segments"][0]["text"] == "你好"
    assert body["project"]["steps"]["transcribe"]["info"]["file"] == "goc.srt"  # không bị ghi đè bởi lần nhập bản dịch
    assert body["project"]["steps"]["translate"]["status"] == "done" and body["project"]["counts"]["translated"] == 2
    assert http.post(f"{base}/api/projects/{pid}/subtitles/import?kind=source", data=b"khong phai phu de").status_code == 400

    # --- sửa câu, xuất phụ đề
    segs = body["segments"]
    segs[1]["translation"] = "Hẹn gặp lại nhé"
    segs.append({"start": 3.6, "end": 3.9, "text": "", "translation": ""})  # câu rỗng bị bỏ
    saved = http.put(f"{base}/api/projects/{pid}/segments", json={"segments": segs}).json()
    assert len(saved["segments"]) == 2 and saved["segments"][1]["translation"] == "Hẹn gặp lại nhé"
    srt = http.get(f"{base}/api/projects/{pid}/subtitles/export?format=srt&mode=bilingual")
    assert "Hẹn gặp lại nhé\n再见" in srt.content.decode("utf-8-sig") and "filename*=UTF-8''phim%20th%E1%BB%AD.songngu.srt" in srt.headers["content-disposition"]
    assert "[V4+ Styles]" in http.get(f"{base}/api/projects/{pid}/subtitles/export?format=ass&mode=vi").text
    assert http.get(f"{base}/api/projects/{pid}/subtitles/export?format=exe").status_code == 400

    # --- xem trước và xuất video (không lồng tiếng nên không cần mạng)
    patched = http.patch(f"{base}/api/projects/{pid}", json={"name": "Tập 1", "settings": {
        "cover": [{"x": 0.1, "y": 0.75, "w": 0.8, "h": 0.2, "mode": "box", "color": "#000000"}], "subtitle": {"size": 60}}}).json()
    assert patched["name"] == "Tập 1" and len(patched["settings"]["cover"]) == 1 and patched["settings"]["subtitle"]["size"] == 60
    prev = http.post(f"{base}/api/projects/{pid}/preview-frame", json={"t": 1.0, "settings": {"subtitle": {"font": "Kanit"}}})
    assert prev.status_code == 200 and prev.content[:2] == b"\xff\xd8"
    assert http.post(f"{base}/api/projects/{pid}/run", json={"steps": ["render"]}).status_code == 200
    assert http.put(f"{base}/api/projects/{pid}/segments", json={"segments": segs}).status_code in (200, 409)  # đang chạy thì bị khoá
    proj = wait_idle(pid)
    assert proj["steps"]["render"]["status"] == "done", proj["steps"]["render"]
    assert proj["steps"]["dub"]["status"] == "pending" and proj["steps"]["render"]["info"]["dubbed"] is False
    assert set(proj["outputs"]) == {"video", "srt_vi", "srt_source", "srt_bilingual"} and proj["outputs"]["video"] == "Tập 1.vi.mp4"
    out = http.get(f"{base}/api/projects/{pid}/files/{requests.utils.quote(proj['outputs']['video'])}")
    assert out.status_code == 200 and out.headers["cache-control"] == "no-cache" and out.content[4:8] == b"ftyp"
    assert http.get(f"{base}/api/projects/{pid}/files/..%2Fproject.json").status_code == 404
    assert "Xuất video xong" in http.get(f"{base}/api/projects/{pid}/log").json()["log"]

    # --- sửa phụ đề sau khi xuất: bước xuất bị đánh dấu cần chạy lại
    segs = http.get(f"{base}/api/projects/{pid}/segments").json()["segments"]
    segs[0]["translation"] = "Chào bạn"
    after = http.put(f"{base}/api/projects/{pid}/segments", json={"segments": segs}).json()["project"]
    assert after["steps"]["render"]["status"] == "stale"
    listed = http.get(base + "/api/projects").json()["projects"]
    assert any(p["id"] == pid and p["has_thumb"] for p in listed)

    assert http.delete(f"{base}/api/projects/{pid}").json() == {"ok": True}
    assert http.get(f"{base}/api/projects/{pid}").status_code == 404


def test_continue_keeps_typed_translations_but_retranslate_all_overwrites(base, http, video, wait_idle):
    """"Chạy tiếp" không được ghi đè câu người dùng đã tự dịch; "Dịch lại toàn bộ" thì dịch lại hết."""
    def translator(req):
        user = req["json"]["messages"][-1]["content"]
        rows = json.loads(next(ln for ln in user.splitlines() if ln.startswith("[{")))
        return 200, {}, chat_reply(json.dumps({"translations": [{"id": r["id"], "vi": f"Máy dịch {r['id']}"} for r in rows]},
                                              ensure_ascii=False))

    def asked(srv):  # id các câu được gửi đi dịch trong yêu cầu gần nhất
        user = srv.requests[-1]["json"]["messages"][-1]["content"]
        return [r["id"] for r in json.loads(next(ln for ln in user.splitlines() if ln.startswith("[{")))]

    proj = http.post(base + "/api/projects", json={"filename": video.name, "settings": {
        "translate": {"engine": "custom"}, "dub": {"enabled": False}, "subtitle": {"burn": False}}}).json()
    pid = proj["id"]
    with open(video, "rb") as f:
        assert http.put(f"{base}/api/projects/{pid}/source", data=f).status_code == 200
    assert http.post(f"{base}/api/projects/{pid}/run", json={"steps": ["prepare"]}).status_code == 200
    wait_idle(pid)
    segs = http.post(f"{base}/api/projects/{pid}/subtitles/import?kind=source&filename=goc.srt", data=SRT_ZH.encode()).json()["segments"]
    segs[0]["translation"] = "Câu tôi tự dịch"
    assert http.put(f"{base}/api/projects/{pid}/segments", json={"segments": segs}).status_code == 200
    with MockServer(translator) as llm:
        config.save_settings({"llm": {"custom": {"base_url": llm.url + "/v1", "api_key": "sk-test-0000", "model": "m"}}})
        openai_compat._variant_for.clear()
        assert http.post(f"{base}/api/projects/{pid}/run", json={}).status_code == 200  # chạy tiếp
        done = wait_idle(pid)
        assert done["steps"]["translate"]["status"] == "done" and done["steps"]["render"]["status"] == "done", done["steps"]
        assert done["steps"]["translate"]["info"]["kept"] == 1 and done["steps"]["translate"]["info"]["translated"] == 1
        got = [s["translation"] for s in http.get(f"{base}/api/projects/{pid}/segments").json()["segments"]]
        assert got == ["Câu tôi tự dịch", "Máy dịch 2"] and asked(llm) == [2]
        assert http.post(f"{base}/api/projects/{pid}/run", json={"steps": ["translate"]}).status_code == 200  # dịch lại toàn bộ
        wait_idle(pid)
        got = [s["translation"] for s in http.get(f"{base}/api/projects/{pid}/segments").json()["segments"]]
        assert got == ["Máy dịch 1", "Máy dịch 2"] and asked(llm) == [1, 2]
    assert http.delete(f"{base}/api/projects/{pid}").json() == {"ok": True}


def test_bad_ids_and_inputs(base, http):
    assert http.get(base + "/api/projects/khong-hop-le").status_code == 404
    assert http.get(base + "/api/projects/20200101-000000-abcd").status_code == 404
    assert http.post(base + "/api/projects/from-url", json={"url": "file:///etc/passwd"}).status_code == 400
    assert http.get(base + "/api/voices?engine=khong-co").status_code == 400
    assert http.delete(base + "/api/models/khong-co").status_code == 404
    assert http.get(base + "/api/voices?engine=piper").json()["voices"][0]["id"].startswith("vi_VN")
