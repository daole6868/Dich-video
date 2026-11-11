"""Test phần dịch với máy chủ giả lập cục bộ (không gọi dịch vụ thật)."""

import json
import threading

import pytest

from dichvideo import config
from dichvideo import translate
from dichvideo.ffmpeg import Cancelled
from dichvideo.translate import TranslateError, glossary, google, openai_compat, prompting

from mock_servers import MockServer, chat_reply, claude_reply


def make_segments(texts):
    return [{"id": i + 1, "start": i * 2.0, "end": i * 2.0 + 1.8, "text": t, "translation": ""}
            for i, t in enumerate(texts)]


def project_settings(engine, **tr):
    s = config.new_project_settings()
    s["translate"].update(engine=engine, **tr)
    return s


def ids_in_prompt(user_prompt: str) -> list[int]:
    """Lấy danh sách id trong phần 'Translate these lines' của lời nhắc."""
    line = next(ln for ln in user_prompt.splitlines() if ln.startswith("[{"))
    return [item["id"] for item in json.loads(line)]


def echo_json(req_json) -> str:
    user = req_json["messages"][-1]["content"]
    return json.dumps({"translations": [{"id": i, "vi": f"Câu {i}"} for i in ids_in_prompt(user)]},
                      ensure_ascii=False)


# ---------------------------------------------------------------- đọc kết quả

@pytest.mark.parametrize("raw", [
    '{"translations": [{"id": 1, "vi": "Xin chào"}, {"id": 2, "vi": "Tạm biệt"}]}',
    '```json\n{"translations": [{"id": 1, "vi": "Xin chào"}, {"id": 2, "vi": "Tạm biệt"}]}\n```',
    '<think>để tôi nghĩ {x}</think>\n[{"id": 1, "translation": "Xin chào"}, {"id": 2, "translation": "Tạm biệt"}]',
    'Đây là kết quả:\n{"1": "Xin chào", "2": "Tạm biệt"}',
    '["Xin chào", "Tạm biệt"]',
    '1: Xin chào\n2: Tạm biệt',
    '[1] - Xin chào\n[2] - Tạm biệt',
])
def test_parse_translations_formats(raw):
    assert prompting.parse_translations(raw, [1, 2]) == {1: "Xin chào", 2: "Tạm biệt"}


def test_parse_ignores_unknown_ids_and_blank():
    raw = '{"translations": [{"id": 1, "vi": "A"}, {"id": 9, "vi": "X"}, {"id": 2, "vi": "  "}]}'
    assert prompting.parse_translations(raw, [1, 2]) == {1: "A"}


def test_system_prompt_contains_glossary_style_context():
    terms = [{"source": "萧炎", "target": "Tiêu Viêm", "note": "nam chính"}]
    p = prompting.build_system_prompt("zh", "drama_ancient", "Phim tiên hiệp", terms)
    assert "萧炎 = Tiêu Viêm" in p and "nam chính" in p
    assert "Phim tiên hiệp" in p and "cổ trang" in p and "JSON" in p


# ---------------------------------------------------------------- từ điển

def test_glossary_roundtrip_and_substitute():
    saved = glossary.save([
        {"source": "乌坦城", "target": "Ô Thản Thành"},
        {"source": "乌坦城主", "target": "Thành chủ Ô Thản"},
        {"source": "乌坦城", "target": "trùng lặp"},
        {"source": "", "target": "bỏ"},
    ])
    assert [t["source"] for t in saved] == ["乌坦城", "乌坦城主"]
    assert glossary.load() == saved
    out = glossary.substitute("乌坦城主来了", saved)
    assert "Thành chủ Ô Thản" in out and "Ô Thản Thành" not in out
    assert glossary.relevant(saved, ["他去了乌坦城"]) == [saved[0]]


def test_glossary_parse_text():
    items = glossary.parse_text("# ghi chú\n萧炎 = Tiêu Viêm\n药老\tDược Lão\n斗气→Đấu khí\nkhông có dấu phân cách")
    assert [(t["source"], t["target"]) for t in items] == [("萧炎", "Tiêu Viêm"), ("药老", "Dược Lão"), ("斗气", "Đấu khí")]
    assert glossary.parse_text(glossary.to_text(items)) == items


# ---------------------------------------------------------------- tương thích OpenAI

def use_openai_server(url, provider="custom", key="sk-test-123456"):
    config.save_settings({"llm": {provider: {"base_url": url + "/v1", "api_key": key, "model": "test-model"}}})
    openai_compat._variant_for.clear()


def test_openai_compat_translates_and_sends_expected_request():
    def handler(req):
        return 200, {}, chat_reply(echo_json(req["json"]))

    with MockServer(handler) as srv:
        use_openai_server(srv.url)
        segs = make_segments(["你好", "再见", "谢谢"])
        res = translate.translate_segments(segs, project_settings("custom", context="Vlog du lịch"))
        assert res == {"translated": 3, "missing": 0, "engine": "custom"}
        assert [s["translation"] for s in segs] == ["Câu 1", "Câu 2", "Câu 3"]
        req = srv.requests[0]
        assert req["path"] == "/v1/chat/completions"
        assert req["headers"]["authorization"] == "Bearer sk-test-123456"
        body = req["json"]
        assert body["model"] == "test-model"
        assert [m["role"] for m in body["messages"]] == ["system", "user"]
        assert body["response_format"] == {"type": "json_object"}
        assert "Vlog du lịch" in body["messages"][0]["content"]


def test_openai_compat_falls_back_when_server_rejects_extras():
    def handler(req):
        if "response_format" in req["json"]:
            return 400, {}, {"error": {"message": "response_format is not supported"}}
        if "temperature" in req["json"]:
            return 400, {}, {"error": {"message": "temperature is not supported"}}
        return 200, {}, chat_reply(echo_json(req["json"]))

    with MockServer(handler) as srv:
        use_openai_server(srv.url)
        segs = make_segments(["你好"])
        translate.translate_segments(segs, project_settings("custom"))
        assert segs[0]["translation"] == "Câu 1"
        assert len(srv.requests) == 3
        # Lần gọi sau dùng ngay biến thể đã chạy được, không thử lại từ đầu.
        translate.translate_segments(make_segments(["再见"]), project_settings("custom"))
        assert len(srv.requests) == 4
        assert "response_format" not in srv.requests[-1]["json"]


def test_openai_compat_waits_on_rate_limit_then_succeeds():
    calls = []

    def handler(req):
        calls.append(1)
        if len(calls) == 1:
            return 429, {"Retry-After": "1"}, {"error": {"message": "slow down"}}
        return 200, {}, chat_reply(echo_json(req["json"]))

    with MockServer(handler) as srv:
        use_openai_server(srv.url)
        segs = make_segments(["你好"])
        translate.translate_segments(segs, project_settings("custom"))
        assert segs[0]["translation"] == "Câu 1" and len(calls) == 2


def test_openai_compat_auth_error_is_reported_in_vietnamese():
    with MockServer(lambda req: (401, {}, {"error": {"message": "Incorrect API key"}})) as srv:
        use_openai_server(srv.url)
        with pytest.raises(TranslateError, match="Khoá API"):
            translate.translate_segments(make_segments(["你好"]), project_settings("custom"))


def test_missing_key_is_reported_before_any_request():
    config.save_settings({"llm": {"openai": {"api_key": ""}}})
    with pytest.raises(TranslateError, match="Chưa nhập khoá API"):
        translate.translate_segments(make_segments(["你好"]), project_settings("openai"))


def test_local_server_needs_no_key():
    with MockServer(lambda req: (200, {}, chat_reply(echo_json(req["json"])))) as srv:
        use_openai_server(srv.url, provider="ollama", key="")
        segs = make_segments(["你好"])
        translate.translate_segments(segs, project_settings("ollama"))
        assert segs[0]["translation"] == "Câu 1"
        assert "authorization" not in srv.requests[0]["headers"]


def test_llm_retries_only_missing_lines():
    def handler(req):
        ids = ids_in_prompt(req["json"]["messages"][-1]["content"])
        keep = [i for i in ids if not (i == 2 and len(ids) > 1)]  # lần đầu bỏ sót câu 2
        return 200, {}, chat_reply(json.dumps({"translations": [{"id": i, "vi": f"Câu {i}"} for i in keep]}))

    with MockServer(handler) as srv:
        use_openai_server(srv.url)
        segs = make_segments(["一", "二", "三"])
        res = translate.translate_segments(segs, project_settings("custom"))
        assert res["missing"] == 0 and [s["translation"] for s in segs] == ["Câu 1", "Câu 2", "Câu 3"]
        assert ids_in_prompt(srv.requests[1]["json"]["messages"][-1]["content"]) == [2]


def test_llm_batches_and_passes_previous_translations_as_context():
    with MockServer(lambda req: (200, {}, chat_reply(echo_json(req["json"])))) as srv:
        use_openai_server(srv.url)
        segs = make_segments([f"第{i}句" for i in range(1, 13)])
        translate.translate_segments(segs, project_settings("custom", batch_size=5))
        assert len(srv.requests) == 3 and all(s["translation"] for s in segs)
        second = srv.requests[1]["json"]["messages"][-1]["content"]
        assert ids_in_prompt(second) == [6, 7, 8, 9, 10]
        assert "第5句  =>  Câu 5" in second  # ngữ cảnh câu trước kèm bản dịch
        assert "- 第11句" in second  # ngữ cảnh câu sau


def test_only_ids_and_only_empty():
    with MockServer(lambda req: (200, {}, chat_reply(echo_json(req["json"])))) as srv:
        use_openai_server(srv.url)
        segs = make_segments(["一", "二", "三"])
        segs[0]["translation"] = "đã có"
        translate.translate_segments(segs, project_settings("custom"), only_empty=True)
        assert [s["translation"] for s in segs] == ["đã có", "Câu 2", "Câu 3"]
        translate.translate_segments(segs, project_settings("custom"), only_ids={1})
        assert segs[0]["translation"] == "Câu 1"


def test_list_models_openai_compat():
    def handler(req):
        assert req["path"] == "/v1/models"
        return 200, {}, {"data": [{"id": "b-model"}, {"id": "models/a-model"}]}

    with MockServer(handler) as srv:
        use_openai_server(srv.url)
        assert translate.list_models("custom") == ["a-model", "b-model"]


# ---------------------------------------------------------------- Claude (SDK Anthropic)

def use_claude_server(url, model="claude-opus-5-5"):
    config.save_settings({"llm": {"anthropic": {"base_url": url, "api_key": "sk-ant-test", "model": model}}})


def claude_echo(req_json) -> str:
    user = req_json["messages"][-1]["content"]
    return json.dumps({"translations": [{"id": i, "vi": f"Câu {i}"} for i in ids_in_prompt(user)]})


def test_claude_request_shape_and_result():
    def handler(req):
        return 200, {}, claude_reply(claude_echo(req["json"]))

    with MockServer(handler) as srv:
        use_claude_server(srv.url)
        segs = make_segments(["你好", "再见"])
        res = translate.translate_segments(segs, project_settings("anthropic"))
        assert res["missing"] == 0 and [s["translation"] for s in segs] == ["Câu 1", "Câu 2"]
        req = srv.requests[0]
        assert req["path"] == "/v1/messages"
        # SDK tự chọn tiêu đề xác thực (x-api-key hoặc Authorization tuỳ phiên bản).
        sent_key = req["headers"].get("x-api-key") or req["headers"].get("authorization", "")
        assert sent_key.endswith("sk-ant-test")
        assert "server-side-fallback-2026-07-01" in req["headers"]["anthropic-beta"]
        body = req["json"]
        assert body["model"] == "claude-opus-5-5"
        assert body["fallbacks"] == "default"
        assert body["output_config"]["effort"] == "medium"
        assert body["output_config"]["format"]["type"] == "json_schema"
        assert body["output_config"]["format"]["schema"] == prompting.RESULT_SCHEMA
        assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
        # Các mô hình hiện tại từ chối tham số lấy mẫu và cấu hình thinking kiểu cũ.
        assert "temperature" not in body and "thinking" not in body and "top_p" not in body


def test_claude_haiku_sends_no_fallbacks():
    with MockServer(lambda req: (200, {}, claude_reply(claude_echo(req["json"]), model="claude-haiku-5-5"))) as srv:
        use_claude_server(srv.url, model="claude-haiku-5-5")
        segs = make_segments(["你好"])
        translate.translate_segments(segs, project_settings("anthropic"))
        body = srv.requests[0]["json"]
        assert "fallbacks" not in body and segs[0]["translation"] == "Câu 1"
        assert "server-side-fallback" not in srv.requests[0]["headers"].get("anthropic-beta", "")


def test_claude_refusal_is_reported():
    with MockServer(lambda req: (200, {}, claude_reply("", stop_reason="refusal"))) as srv:
        use_claude_server(srv.url)
        with pytest.raises(TranslateError, match="từ chối"):
            translate.translate_segments(make_segments(["你好"]), project_settings("anthropic"))


def test_claude_older_model_falls_back_to_minimal_request():
    def handler(req):
        if "output_config" in req["json"]:
            return 400, {}, {"type": "error", "error": {"type": "invalid_request_error",
                                                          "message": "output_config: Extra inputs are not permitted"}}
        return 200, {}, claude_reply("```json\n" + claude_echo(req["json"]) + "\n```", model="claude-old")

    with MockServer(handler) as srv:
        use_claude_server(srv.url, model="claude-old")
        segs = make_segments(["你好"])
        translate.translate_segments(segs, project_settings("anthropic"))
        assert segs[0]["translation"] == "Câu 1" and len(srv.requests) == 2
        assert isinstance(srv.requests[1]["json"]["system"], str)


def test_claude_bad_key_message():
    err = {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}}
    with MockServer(lambda req: (401, {}, err)) as srv:
        use_claude_server(srv.url)
        with pytest.raises(TranslateError, match="Khoá API Claude không hợp lệ"):
            translate.translate_segments(make_segments(["你好"]), project_settings("anthropic"))


# ---------------------------------------------------------------- Google (giả lập cổng gtx)

def gtx_reply(text: str, per_line=lambda s: "vi:" + s) -> list:
    lines = text.split("\n")
    chunks = [[per_line(ln) + ("\n" if i < len(lines) - 1 else ""), ln, None, None, 10]
              for i, ln in enumerate(lines)]
    return [chunks, None, "zh-CN"]


@pytest.fixture
def fast_google(monkeypatch):
    monkeypatch.setattr(google, "PAUSE", 0.0)

    def point_to(url):
        monkeypatch.setattr(google, "ENDPOINT", url + "/translate_a/single")

    return point_to


def test_google_batches_lines_and_keeps_order(fast_google):
    with MockServer(lambda req: (200, {}, gtx_reply(req["query"]["q"][0]))) as srv:
        fast_google(srv.url)
        lines = ["你好", "", "再见", "谢谢"]
        assert google.translate_lines(lines) == ["vi:你好", "", "vi:再见", "vi:谢谢"]
        assert len(srv.requests) == 1
        q = srv.requests[0]["query"]
        assert q["sl"] == ["zh-CN"] and q["tl"] == ["vi"] and q["client"] == ["gtx"]
        assert "python-requests" in srv.requests[0]["headers"]["user-agent"]  # không giả dạng trình duyệt


def test_google_splits_large_input_into_several_requests(fast_google):
    with MockServer(lambda req: (200, {}, gtx_reply(req["query"]["q"][0]))) as srv:
        fast_google(srv.url)
        lines = ["这是一句比较长的测试句子用来凑字数" * 3] * 30
        out = google.translate_lines(lines)
        assert out == ["vi:" + ln for ln in lines]
        assert len(srv.requests) > 1
        assert all(len(r["query"]["q"][0]) <= google.MAX_CHARS for r in srv.requests)


def test_google_falls_back_to_single_lines_when_count_mismatches(fast_google):
    def handler(req):
        q = req["query"]["q"][0]
        if "\n" in q:  # máy chủ gộp các dòng lại thành một
            return 200, {}, [[["gộp hết", q, None, None, 10]], None, "zh-CN"]
        return 200, {}, gtx_reply(q)

    with MockServer(handler) as srv:
        fast_google(srv.url)
        assert google.translate_lines(["你好", "再见"]) == ["vi:你好", "vi:再见"]
        assert len(srv.requests) == 3


def test_google_honours_retry_after_then_succeeds(fast_google):
    calls, notes = [], []

    def handler(req):
        calls.append(1)
        if len(calls) == 1:
            return 429, {"Retry-After": "2"}, b"too many"
        return 200, {}, gtx_reply(req["query"]["q"][0])

    with MockServer(handler) as srv:
        fast_google(srv.url)
        assert google.translate_lines(["你好"], notify=notes.append) == ["vi:你好"]
        assert len(calls) == 2 and "giới hạn tần suất" in notes[0]


def test_google_gives_up_with_clear_message(fast_google, monkeypatch):
    monkeypatch.setattr(google, "MAX_ATTEMPTS", 2)
    with MockServer(lambda req: (429, {"Retry-After": "2"}, b"too many")) as srv:
        fast_google(srv.url)
        with pytest.raises(TranslateError, match="giới hạn tần suất"):
            google.translate_lines(["你好"])
        assert len(srv.requests) == 2  # dừng đúng số lần cho phép, không gọi dồn dập


def test_google_cancel_during_backoff(fast_google):
    cancel = threading.Event()
    with MockServer(lambda req: (429, {"Retry-After": "60"}, b"too many")) as srv:
        fast_google(srv.url)
        threading.Timer(0.3, cancel.set).start()
        with pytest.raises(Cancelled):
            google.translate_lines(["你好"], cancel=cancel)


def test_google_engine_applies_glossary(fast_google):
    glossary.save([{"source": "萧炎", "target": "Tiêu Viêm"}])
    with MockServer(lambda req: (200, {}, gtx_reply(req["query"]["q"][0], per_line=lambda s: s))) as srv:
        fast_google(srv.url)
        segs = make_segments(["萧炎来了"])
        translate.translate_segments(segs, project_settings("google"))
        assert "Tiêu Viêm" in segs[0]["translation"] and "萧炎" not in srv.requests[0]["query"]["q"][0]
