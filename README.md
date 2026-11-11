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
| **Windows 10/11** | Bấm đúp **`Chay_Windows.bat`**. Nếu Windows hỏi vì tệp tải từ mạng, chọn *Run* (hoặc *More info → Run anyway*) |
| **macOS** | Bấm đúp **`Chay_macOS.command`**. Lần đầu macOS sẽ chặn vì tệp tải từ mạng — xem ghi chú ngay bên dưới |
| **Linux** | Mở terminal trong thư mục và chạy `./chay_linux.sh` |

**Ghi chú cho macOS.** Tệp tải từ mạng bị macOS chặn ở lần mở đầu tiên. Chọn một trong hai cách:

- Mở *Terminal*, gõ `bash ` (có dấu cách), kéo thả tệp `chay_linux.sh` vào cửa sổ rồi nhấn Enter. Cách này
  không bị chặn.
- Hoặc bấm đúp `Chay_macOS.command`, đóng hộp cảnh báo, rồi vào *System Settings → Privacy & Security* bấm
  **Open Anyway** (macOS 14 trở về trước: bấm chuột phải vào tệp → *Open*).

Lần chạy đầu cần mạng. Tệp khởi động tự làm các việc sau:

1. Tải công cụ cài đặt `uv` vào `runtime/` (nếu máy chưa có).
2. Tạo môi trường Python 3.12 riêng trong `.venv/` — **không cần cài Python trước**, không đụng tới Python sẵn có.
3. Cài thư viện (vài trăm MB, đã gồm cả ffmpeg).
4. Mở giao diện tại `http://127.0.0.1:8760`.

Các lần sau khởi động trong vài giây. Giữ cửa sổ dòng lệnh mở trong lúc dùng; đóng nó (hoặc nhấn `Ctrl+C`) để thoát —
việc đang xử lý dở sẽ dừng theo. Bấm đúp tệp khởi động khi ứng dụng đang chạy chỉ mở lại giao diện, không chạy bản thứ hai.

Bạn có thể đổi tên hoặc chuyển thư mục ứng dụng đi chỗ khác bất cứ lúc nào; tên thư mục có dấu tiếng Việt, khoảng
trắng hay dấu ngoặc đều dùng được. Dự án, mô hình và cài đặt nằm trong `data/` nên đi theo thư mục.

**Những thứ nằm ngoài thư mục ứng dụng** (chỉ có hai):

- Bản Python 3.12 do `uv` tải về, khoảng 100 MB: `%APPDATA%\uv\python` trên Windows, `~/.local/share/uv/python` trên
  macOS và Linux.
- Riêng Windows, khi thư mục ứng dụng có dấu và bạn dùng giọng Piper: một lối tắt thư mục (không chứa dữ liệu) trong
  `C:\ProgramData\DichVideoStudio`, vì thư viện phát âm của Piper không đọc được đường dẫn có dấu.

Muốn gỡ: xoá thư mục ứng dụng, và nếu muốn sạch hẳn thì xoá thêm hai chỗ trên.

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

Ứng dụng không thu thập hay gửi số liệu sử dụng. Hai thư viện kèm theo có sẵn cơ chế gửi số liệu về nhà phát triển
của chúng (ONNX Runtime về Microsoft, Hugging Face Hub); ứng dụng đã tắt cả hai.

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

Nói rõ để bạn biết phần nào đã được chứng minh, phần nào chưa.

**Đã kiểm thử trên cả Windows, macOS và Linux** (máy ảo của GitHub Actions: Windows x64, macOS Apple Silicon,
Ubuntu x64 — quy trình nằm trong `.github/workflows/kiem-tra.yml` của kho mã). Mỗi lượt làm đúng như người dùng mới:

- Giải nén bản zip vào một thư mục tên có dấu tiếng Việt, khoảng trắng, dấu ngoặc và dấu `&`; chạy tệp khởi động:
  tự tải `uv`, tự tải Python 3.12 (đặt trong thư mục có dấu, như máy có tên người dùng có dấu), cài đúng bộ thư viện
  đã khoá phiên bản, tự kiểm tra đạt. Chạy lại lần hai không cài lại. Đổi tên thư mục rồi chạy lại vẫn dùng được.
- Khởi động máy chủ, mở trang chủ, tắt bằng lệnh tắt.
- Toàn bộ test tự động (`tests/`, hơn 100 test): phụ đề, tách câu, khớp thời lượng lồng tiếng, trộn âm thanh, dựng
  video thật (kể cả kích thước lẻ và điểm ảnh không vuông), logic OCR, kho dự án, cấu hình, các bộ dịch và giọng đọc
  qua máy chủ giả lập, API chạy trên máy chủ thật, tua video, tệp bị khoá, tải video từ liên kết (máy chủ cục bộ).
- Một lượt xử lý trọn vẹn bằng bộ máy thật: giọng Piper đọc một câu → Whisper (mô hình `tiny`) nhận dạng → dịch →
  lồng tiếng bằng Piper → xuất MP4 có phụ đề; sau đó Whisper nghe lại video kết quả và phải nghe ra đúng câu lồng tiếng.
- **Google Dịch miễn phí** với một lô 12 câu tiếng Trung thật: đủ 12 câu, đúng thứ tự, đúng nghĩa.
- **Giọng Edge** mặc định (Hoài My): đọc một câu, Whisper nghe lại khớp khoảng 85%.
- Riêng macOS: bộ mã hoá phần cứng VideoToolbox được dùng và cho video đúng. Riêng Windows: ffmpeg chạy ngầm tự
  tắt khi ứng dụng bị đóng đột ngột.

Việc chạy thử trên Windows đã bắt được hai lỗi thật, đều đã sửa và có test: thư viện phát âm của giọng Piper làm
tắt cả ứng dụng khi thư mục có dấu, và các lệnh in tiếng Việt ra cửa sổ dòng lệnh.

**Đã kiểm thử thêm trên máy phát triển** (Linux x64, CPU 4 nhân, không có card đồ hoạ):

- Trọn quy trình trên **một video thật** dài 2 phút 7 giây (720p, có phụ đề cứng, giọng hoạt hình trên nền nhạc), với
  mô hình mặc định `large-v3-turbo`: OCR đọc được 23 câu, nghe giọng nói được 10 câu (khớp phụ đề cứng 79–100%),
  lồng tiếng 23 câu bằng giọng Edge, xuất video có phụ đề Việt đè lên vùng che. Rãnh tiếng lồng được Whisper nghe
  lại đủ 101/101 từ, độ khớp 90%. Bản dịch của lần chạy này được viết tay rồi nhập vào, vì hôm đó Google Dịch từ
  chối máy phát triển (lỗi 429).
- **Video dài**: ghép lặp video trên thành 12 phút 40 giây. Ra 138 câu, toàn bộ quy trình mất khoảng 11 phút. Bộ
  nhớ của ứng dụng lên cao nhất khoảng 3 GB lúc nhận dạng giọng nói rồi trở về khoảng 350 MB; không tăng theo độ
  dài video. Trình sửa phụ đề (mỗi trang 100 câu) và việc phát, tua video kết quả 150 MB đều chạy tốt.
- Giao diện, bằng trình duyệt Chromium điều khiển tự động, trên một bản cài mới từ tệp zip: tải video lên, chờ xử
  lý, sửa phụ đề, tách/hoàn tác, đổi phông, vẽ/di chuyển/đổi cỡ vùng che, xuất lại, phát và tua video kết quả; không
  có lỗi trong console.
- Tắt ứng dụng rồi mở lại ngay vẫn ở địa chỉ cũ; mở thêm lần nữa khi đang chạy thì chỉ báo địa chỉ của bản đang chạy.
- Cả 14 giọng Edge và 2 giọng Piper đọc tiếng Việt, Whisper nhận dạng lại đúng 92–100%.

**Chỉ kiểm thử bằng máy chủ giả lập** (đúng giao thức, chưa gọi dịch vụ thật vì không có khoá API):
bộ dịch Claude và các bộ dịch tương thích OpenAI, nhận dạng qua API, giọng đọc OpenAI và ElevenLabs.

**Chưa kiểm thử được:**

- **Thao tác bằng tay trên Windows và macOS**: máy ảo không có màn hình, nên việc bấm đúp tệp khởi động, các hộp
  cảnh báo bảo mật của hệ điều hành và việc tự mở trình duyệt chưa được thử; giao diện mới chỉ thử trên Chromium
  (Chrome, Edge), chưa thử Safari và Firefox.
- Máy Mac dùng chip Intel và Windows trên chip ARM. Danh sách thư viện có bản dựng sẵn cho Mac Intel; chưa chạy thử.
- Card NVIDIA và các bộ mã hoá phần cứng NVENC, Quick Sync, AMF. Ứng dụng thử bộ mã hoá trước khi dùng và tự
  chuyển về CPU nếu không chạy được.
- Tải video từ các trang thật (YouTube, Bilibili, Douyin…).
- Video dài hơn 15 phút (ví dụ cả tập phim 45 phút) và nhiều video xếp hàng liên tiếp.

Nếu gặp lỗi, hãy gửi nội dung thẻ *Nhật ký* của dự án và tệp `data/logs/app.log`.

## Gỡ rối

| Hiện tượng | Cách xử lý |
|---|---|
| Tệp khởi động báo không tải được `uv` | Mạng chặn GitHub. Cài Python 3.12 từ python.org (tích *Add python.exe to PATH*) rồi chạy lại — tệp khởi động sẽ dùng Python đó. |
| Cài thư viện dừng giữa chừng | Kiểm tra mạng rồi chạy lại tệp khởi động; nó cài tiếp phần còn thiếu. |
| Windows báo đường dẫn quá dài | Giải nén ứng dụng vào thư mục ngắn, ví dụ `C:\DichVideoStudio`. |
| Bước Dịch báo Google giới hạn tần suất | Chờ ít phút rồi bấm *Thử lại*, hoặc chọn một bộ dịch AI. |
| Không tải được mô hình nhận dạng | Kiểm tra mạng. Có thể đặt máy chủ gương Hugging Face trong *Cài đặt → Hệ thống & mạng*. |
| Giọng Edge báo lỗi | Dịch vụ tạm ngưng hoặc mạng chặn. Chuyển sang giọng Piper (ngoại tuyến). |
| Nhận dạng quá chậm | Chọn mô hình "Nhỏ", hoặc dùng "Nhận dạng qua API". |
| Trình duyệt không phát video trong trình sửa | Chạy lại bước *Chuẩn bị* để tạo bản xem trước. |
| Cổng 8760 do chương trình khác dùng | Ứng dụng tự chuyển sang cổng kế tiếp; xem địa chỉ in trong cửa sổ dòng lệnh. |
| Xuất lại báo không ghi đè được tệp kết quả | Tệp video cũ đang mở trong trình phát khác. Đóng trình phát rồi xuất lại. |
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

Chạy test (cần thêm `pytest`; trên Windows thay `runtime/uv` bằng `runtime\uv.exe` và `.venv/bin/python` bằng
`.venv\Scripts\python.exe`):

```
runtime/uv pip install --python .venv/bin/python pytest
.venv/bin/python -m pytest tests                          # không cần mạng
DVS_LIVE=1 .venv/bin/python -m pytest tests/test_live.py  # bộ máy và dịch vụ thật: tải ~140 MB mô hình, gọi Google Dịch và giọng Edge
```

Đóng gói: `python tools/build_zip.py` → `dist/DichVideoStudio-<phiên bản>.zip`.

## Giấy phép

Mã nguồn phát hành theo giấy phép MIT (tệp `LICENSE`). Phông chữ, thư viện và mô hình của bên thứ ba giữ giấy phép
riêng — xem `THIRD_PARTY_NOTICES.md`.
