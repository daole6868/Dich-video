# Dịch Video Studio — dịch video tiếng Trung sang tiếng Việt

Ứng dụng chạy ngay trên máy bạn, giao diện tiếng Việt trong trình duyệt. Thả một video tiếng Trung vào,
ứng dụng sẽ lấy lời thoại, dịch sang tiếng Việt, lồng tiếng Việt và xuất video có phụ đề.

```
Video gốc ─► Chuẩn bị ─► Nhận dạng lời thoại ─► Dịch ─► Lồng tiếng ─► Xuất video MP4
                         (nghe giọng nói hoặc
                          đọc phụ đề cứng)
```

## Tính năng

- **Hai cách lấy lời thoại**: nghe giọng nói bằng Whisper chạy trên máy, hoặc đọc phụ đề cứng in sẵn trên
  hình bằng OCR. Chế độ *Tự động* phát hiện video có phụ đề cứng, chạy cả hai cách và giữ kết quả đầy đủ hơn.
- **Dịch**: Google Dịch miễn phí (không cần khoá), hoặc bộ dịch AI qua khoá API của bạn — Claude, GPT, Gemini,
  DeepSeek, Groq, OpenRouter, Ollama chạy trên máy, hay bất kỳ dịch vụ tương thích OpenAI nào. Bộ dịch AI nhận
  mô tả video, thể loại và **bảng thuật ngữ** (tên nhân vật, địa danh).
- **Lồng tiếng Việt**: giọng Microsoft Edge (miễn phí, cần mạng), giọng Piper (ngoại tuyến), hoặc API giọng đọc
  trả phí. Tự khớp thời lượng từng câu, tự hạ tiếng gốc khi có tiếng lồng, gán giọng riêng cho từng câu.
- **Trình sửa phụ đề**: sửa lời gốc, bản dịch, mốc thời gian; tách, gộp, thêm, xoá câu; dịch lại từng câu;
  nghe thử giọng đọc; tìm và thay; dịch chuyển thời gian; hoàn tác; tự lưu. Cảnh báo câu quá dài so với thời lượng.
- **Hình ảnh**: gắn cứng phụ đề với 12 họ phông tiếng Việt kèm sẵn, chỉnh cỡ/màu/viền/nền hộp/vị trí, phụ đề
  song ngữ; **che phụ đề gốc** (làm mờ hoặc che màu, có thể chỉ bật đúng lúc có câu thoại); chèn logo.
- **Xuất**: MP4 (H.264 + AAC), chọn độ phân giải và chất lượng, phụ đề mềm kèm theo; tệp phụ đề SRT, VTT, ASS,
  TXT (tiếng Việt, lời gốc, song ngữ); rãnh tiếng lồng riêng.
- **Khác**: tải video từ liên kết (yt-dlp), xử lý nhiều video nối tiếp, nhập phụ đề có sẵn, giao diện sáng/tối.

## Cài đặt và chạy

Giải nén tệp zip vào một thư mục bất kỳ rồi:

| Hệ điều hành | Cách chạy |
|---|---|
| **Windows 10/11** | Bấm đúp **`Chay_Windows.bat`** |
| **macOS** | Bấm đúp **`Chay_macOS.command`** (lần đầu: bấm chuột phải → *Open* để vượt qua cảnh báo của macOS) |
| **Linux** | Mở terminal trong thư mục và chạy `./chay_linux.sh` |

Lần chạy đầu cần mạng. Tệp khởi động tự làm các việc sau, tất cả nằm gọn trong thư mục ứng dụng:

1. Tải công cụ cài đặt `uv` vào `runtime/` (nếu máy chưa có).
2. Tạo môi trường Python 3.12 riêng trong `.venv/` — **không cần cài Python trước**, không đụng tới Python sẵn có.
3. Cài thư viện (vài trăm MB, đã gồm cả ffmpeg).
4. Mở giao diện tại `http://127.0.0.1:8760`.

Các lần sau khởi động trong vài giây. Giữ cửa sổ dòng lệnh mở trong lúc dùng; đóng nó (hoặc nhấn `Ctrl+C`) để thoát.

Muốn gỡ: xoá cả thư mục ứng dụng. Dữ liệu của bạn nằm trong `data/`.

### Yêu cầu

- Windows 10/11 64-bit, macOS, hoặc Linux 64-bit.
- RAM từ 8 GB (mô hình nhận dạng mặc định cần khoảng 3 GB; máy 4 GB hãy chọn mô hình "Nhỏ").
- Ổ đĩa trống khoảng 5 GB: thư viện, mô hình nhận dạng (bản Turbo ~1,6 GB, tải ở lần nhận dạng đầu tiên), dữ liệu dự án.
- Card đồ hoạ không bắt buộc. Xem mục *Tăng tốc bằng card NVIDIA*.

### Tuỳ chọn dòng lệnh

```
Chay_Windows.bat --port 9000      đổi cổng
Chay_Windows.bat --lan            cho máy khác trong mạng nội bộ truy cập
Chay_Windows.bat --no-browser     không tự mở trình duyệt
Chay_Windows.bat --check          tự kiểm tra bản cài (không cần mạng) rồi thoát
```

(Trên macOS/Linux thay bằng `./chay_linux.sh …`.)

## Dùng nhanh

1. **Thả video** vào trang *Dự án* (hoặc dán liên kết). Chọn nhanh: gắn phụ đề, lồng tiếng, bộ dịch.
   Bật *Duyệt phụ đề trước khi xuất* nếu muốn xem lại bản dịch trước khi lồng tiếng.
2. Ứng dụng chạy lần lượt 5 bước. Mở dự án để theo dõi tiến độ.
3. Ở thẻ **Phụ đề**, sửa câu nào chưa ưng. Câu ghi *"đọc nhanh ×1.4"* nghĩa là bản dịch dài hơn khoảng trống —
   nên rút gọn.
4. Chỉnh giọng đọc ở thẻ **Lồng tiếng**, kiểu chữ và vùng che ở thẻ **Hình ảnh**. Nút *Xem thử chính xác*
   dựng một khung hình thật để kiểm tra.
5. Bấm **Chạy tiếp các bước còn lại**, rồi tải kết quả ở thẻ **Xuất**.

Trong ứng dụng có trang *Hướng dẫn* chi tiết hơn.

## Bộ dịch

| Bộ dịch | Cần gì | Ghi chú |
|---|---|---|
| Google Dịch (miễn phí) | Không cần khoá | Mặc định. Dùng cổng công khai **không chính thức** của Google nên có thể bị giới hạn khi dịch nhiều. Khi bị giới hạn, ứng dụng chờ theo đúng thời gian máy chủ yêu cầu rồi báo lỗi rõ ràng; nó không tìm cách vượt giới hạn. Dịch từng câu, không nắm ngữ cảnh. |
| Claude (Anthropic) | Khoá API | Gọi qua SDK chính thức. Mặc định dùng `claude-opus-5-5` (chất lượng cao nhất); muốn tiết kiệm có thể đổi sang `claude-sonnet-5-5` hoặc `claude-haiku-5-5` trong Cài đặt. Đã bật sẵn cơ chế dự phòng phía máy chủ (`fallbacks`) cho các mô hình hỗ trợ. |
| OpenAI, Gemini, DeepSeek, Groq, OpenRouter | Khoá API | Qua giao thức tương thích OpenAI. Tên mô hình thay đổi theo thời gian — trong Cài đặt có nút lấy danh sách mô hình hiện có. |
| Ollama | Cài Ollama trên máy | Dịch hoàn toàn ngoại tuyến bằng mô hình bạn tự tải. |
| Tuỳ chỉnh | Địa chỉ API + khoá | Mọi dịch vụ tương thích OpenAI. |

Khoá API chỉ lưu trong `data/settings.json` trên máy bạn và chỉ gửi tới đúng dịch vụ tương ứng.

## Giọng đọc

| Giọng | Ghi chú |
|---|---|
| Microsoft Edge | Mặc định, miễn phí, cần mạng. Hai giọng tiếng Việt bản ngữ (Hoài My, Nam Minh) và 12 giọng "đa ngữ" đọc được tiếng Việt. Đây là dịch vụ đọc văn bản của trình duyệt Edge, **không phải API có cam kết**, nên có lúc có thể tạm ngưng. |
| Piper | Miễn phí, chạy trên máy, không cần mạng sau khi tải giọng (~63 MB). Chất lượng thấp hơn Edge. |
| API tương thích OpenAI, ElevenLabs | Cần khoá API. |

## Tăng tốc bằng card NVIDIA (tuỳ chọn)

Mặc định ứng dụng nhận dạng bằng CPU. Nếu máy có card NVIDIA, cài thêm thư viện CUDA vào môi trường của ứng dụng:

```
runtime\uv.exe pip install --python .venv\Scripts\python.exe nvidia-cublas-cu12 nvidia-cudnn-cu12
```

Sau đó khởi động lại. Khi không dùng được GPU, ứng dụng tự quay về CPU. **Phần này chưa được kiểm thử** vì máy
kiểm thử không có card đồ hoạ.

## Dữ liệu và quyền riêng tư

Mọi thứ nằm trong thư mục `data/` cạnh ứng dụng: dự án, video, phụ đề, mô hình, cài đặt. Ứng dụng chỉ lắng nghe
trên máy của bạn (`127.0.0.1`) và từ chối yêu cầu đến từ trang web khác.

Chỉ những dữ liệu sau rời khỏi máy, và chỉ khi bạn dùng tính năng tương ứng:

- Câu thoại gửi tới bộ dịch bạn chọn.
- Câu tiếng Việt gửi tới dịch vụ giọng đọc (trừ giọng Piper).
- Âm thanh gửi tới dịch vụ nhận dạng, nếu bạn chọn "Nhận dạng qua API".
- Yêu cầu tải mô hình (Hugging Face) và tải video từ liên kết bạn dán vào.

Chỉ dịch và đăng lại những video bạn có quyền sử dụng.

## Giới hạn đã biết

- OCR chỉ đọc **dòng phụ đề chính** trong vùng quét. Chữ nằm chỗ khác trên hình (tiêu đề, lời dẫn in nghệ thuật)
  không được lấy và không tự bị che; bạn có thể thêm câu bằng tay và vẽ thêm vùng che.
- Nghe giọng nói có thể bỏ sót giọng hoạt hình, giọng hát, lời nói chen nhạc lớn, và hay nhầm tên riêng đồng âm.
  Với video có phụ đề cứng, OCR thường tốt hơn.
- Vùng che làm mờ là hình chữ nhật, mép còn nhìn thấy trên nền nhiều chi tiết.
- Các giọng Edge "đa ngữ" đọc tiếng Việt rõ nhưng có thể mang ngữ điệu nước ngoài.
- Chưa có tách giọng khỏi nhạc nền: khi lồng tiếng, tiếng gốc được hạ nhỏ chứ không xoá riêng giọng nói.
- Mỗi lúc chỉ xử lý một dự án; các dự án khác xếp hàng chờ.

## Tình trạng kiểm thử

Nói rõ để bạn biết phần nào đã được chứng minh, phần nào chưa:

**Đã kiểm thử** (Linux x86_64, Python 3.12, CPU 4 nhân, không có card đồ hoạ):

- 99 test tự động (`tests/`): phụ đề, tách câu, khớp thời lượng lồng tiếng, trộn âm thanh, dựng video thật
  (kể cả video kích thước lẻ và điểm ảnh không vuông), logic OCR, kho dự án, cấu hình, API chạy trên máy chủ thật.
- Chạy trọn quy trình trên **một video thật** dài 2 phút 7 giây (720p, có phụ đề cứng, giọng hoạt hình trên nền nhạc):
  OCR đọc được 23 câu, nghe giọng nói được 10 câu (khớp phụ đề cứng 79–100%), lồng tiếng 23 câu bằng giọng Edge,
  xuất video có phụ đề Việt đè lên vùng che. Rãnh tiếng lồng được nhận dạng lại bằng Whisper: đủ 101/101 từ,
  độ khớp 90%. Bản dịch của lần chạy này được viết tay rồi nhập vào (xem mục dưới).
- Giao diện: chạy bằng trình duyệt Chromium tự động — tải video lên, chờ xử lý, sửa phụ đề, tách/hoàn tác,
  đổi phông, vẽ/di chuyển/đổi cỡ vùng che, xuất lại; không có lỗi trong console.
- Bộ cài Linux: giải nén zip vào thư mục sạch, tự tải `uv`, tạo môi trường, cài thư viện, tự kiểm tra đạt.
- Giọng đọc: cả 14 giọng Edge và 2 giọng Piper đọc tiếng Việt được Whisper nhận dạng lại đúng 92–100%.

**Chỉ kiểm thử bằng máy chủ giả lập** (đúng giao thức, chưa gọi dịch vụ thật vì không có khoá API):
bộ dịch Claude và các bộ dịch tương thích OpenAI, nhận dạng qua API, giọng đọc OpenAI và ElevenLabs.

**Chưa kiểm thử được:**

- **Google Dịch miễn phí trên dữ liệu thật**: từ máy kiểm thử, cổng này trả lỗi giới hạn tần suất (429) nên chỉ
  xác nhận được một lần gọi đơn lẻ và phần xử lý lỗi. Việc gộp nhiều câu vào một yêu cầu được kiểm bằng máy chủ giả lập.
- **Windows và macOS**: tệp khởi động được viết cẩn thận và danh sách thư viện đã được xác nhận là có bản dựng sẵn
  cho Windows x64, macOS (Apple Silicon và Intel) và Linux, nhưng chưa được chạy trên máy thật.
- Card NVIDIA và các bộ mã hoá phần cứng (NVENC, Quick Sync, AMF, VideoToolbox). Ứng dụng thử bộ mã hoá trước
  khi dùng và tự chuyển về CPU nếu không chạy được.
- Tải video từ các trang thật (YouTube, Bilibili, Douyin…): chỉ thử với máy chủ tệp cục bộ.

Nếu gặp lỗi ở những phần chưa kiểm thử, hãy gửi nội dung thẻ *Nhật ký* của dự án và tệp `data/logs/app.log`.

## Gỡ rối

| Hiện tượng | Cách xử lý |
|---|---|
| Tệp khởi động báo không tải được `uv` | Mạng chặn GitHub. Cài Python 3.12 từ python.org (tích *Add python.exe to PATH*) rồi chạy lại — tệp khởi động sẽ dùng Python đó. |
| Bước Dịch báo Google giới hạn tần suất | Chờ ít phút rồi bấm *Thử lại*, hoặc chọn một bộ dịch AI. |
| Không tải được mô hình nhận dạng | Kiểm tra mạng. Có thể đặt máy chủ gương Hugging Face trong *Cài đặt → Hệ thống & mạng*. |
| Giọng Edge báo lỗi | Dịch vụ tạm ngưng hoặc mạng chặn. Chuyển sang giọng Piper (ngoại tuyến). |
| Nhận dạng quá chậm | Chọn mô hình "Nhỏ", hoặc dùng "Nhận dạng qua API". |
| Trình duyệt không phát video trong trình sửa | Chạy lại bước *Chuẩn bị* để tạo bản xem trước. |
| Cổng 8760 đang bận | Ứng dụng tự chuyển sang cổng kế tiếp; xem địa chỉ in trong cửa sổ dòng lệnh. |
| Muốn kiểm tra bản cài | Chạy tệp khởi động kèm `--check`. |

## Dành cho lập trình viên

```
dichvideo/
  config.py       cấu hình mặc định, đọc/ghi cài đặt
  ffmpeg.py       tìm và gọi ffmpeg, đọc thông tin tệp
  asr.py          nhận dạng giọng nói (faster-whisper, API)
  ocr.py          đọc phụ đề cứng, phát hiện video có phụ đề cứng
  segmenter.py    cắt lời thoại thành câu phụ đề
  translate/      Google, bộ dịch tương thích OpenAI, Claude, bảng thuật ngữ
  tts/            giọng Edge, Piper, API
  dubbing.py      khớp thời lượng, ghép rãnh tiếng, trộn âm thanh
  render.py       tệp ASS, chuỗi bộ lọc, mã hoá MP4
  pipeline.py     năm bước xử lý;  jobs.py  hàng đợi;  projects.py  kho dự án
  server.py       API (Starlette);  web/  giao diện (Vue 3, không cần bước build)
tests/            test tự động
tools/            bootstrap.py (cài thư viện), build_zip.py (đóng gói), gen_notices.py
```

Chạy test (cần thêm `pytest`):

```
.venv/bin/python -m pip install pytest      # hoặc: runtime/uv pip install --python .venv/bin/python pytest
.venv/bin/python -m pytest tests
```

Đóng gói: `python tools/build_zip.py` → `dist/DichVideoStudio-<phiên bản>.zip`.

## Giấy phép

Mã nguồn phát hành theo giấy phép MIT (tệp `LICENSE`). Phông chữ, thư viện và mô hình của bên thứ ba giữ giấy phép
riêng — xem `THIRD_PARTY_NOTICES.md`.
