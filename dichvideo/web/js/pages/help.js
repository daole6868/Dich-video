// Trang Hướng dẫn.
import { commonComponents } from "../common.js";

export const HelpPage = {
  name: "HelpPage",
  components: commonComponents,
  template: `
    <div class="page">
      <div class="page-head"><div>
        <h1 class="page-title">Hướng dẫn</h1>
        <div class="page-desc">Mọi thứ cần biết để dịch một video tiếng Trung sang tiếng Việt.</div>
      </div></div>

      <div class="prose">
        <h2>Bắt đầu nhanh</h2>
        <div class="steps-guide">
          <div class="card"><b><icon name="upload"></icon>1. Thả video vào</b><p class="small">Ở trang Dự án, kéo thả tệp video (hoặc dán liên kết). Ứng dụng tự chạy hết các bước.</p></div>
          <div class="card"><b><icon name="captions"></icon>2. Xem lại phụ đề</b><p class="small">Mở dự án, sửa câu nào chưa ưng ở thẻ Phụ đề. Mọi thay đổi được tự lưu.</p></div>
          <div class="card"><b><icon name="download"></icon>3. Xuất và tải về</b><p class="small">Bấm "Chạy tiếp các bước còn lại" nếu có sửa, rồi tải video ở thẻ Xuất & tải về.</p></div>
        </div>

        <h2>Năm bước xử lý</h2>
        <ol>
          <li><b>Chuẩn bị</b> — đọc thông tin video, tách âm thanh, kiểm tra xem video có phụ đề cứng không.</li>
          <li><b>Nhận dạng</b> — lấy lời thoại gốc kèm mốc thời gian, bằng một trong hai cách bên dưới.</li>
          <li><b>Dịch</b> — dịch từng câu sang tiếng Việt.</li>
          <li><b>Lồng tiếng</b> — tạo giọng đọc tiếng Việt cho từng câu, khớp vào đúng chỗ câu gốc, trộn với âm thanh gốc.</li>
          <li><b>Xuất video</b> — gắn phụ đề Việt, che phụ đề gốc, chèn logo, ghép tiếng lồng và xuất tệp MP4.</li>
        </ol>
        <p>Mỗi bước có thể chạy lại riêng. Bước nào có dữ liệu đầu vào đã đổi sẽ được đánh dấu "Cần chạy lại".</p>

        <h2>Lấy lời thoại: nghe giọng nói hay đọc phụ đề cứng?</h2>
        <ul>
          <li><b>Nghe giọng nói</b> dùng mô hình Whisper chạy ngay trên máy. Hợp với video nói rõ ràng. Hay nhầm tên riêng và từ đồng âm; có thể bỏ sót giọng hoạt hình, giọng hát, lời nói chen nhạc lớn.</li>
          <li><b>Đọc phụ đề cứng (OCR)</b> đọc chữ in sẵn trên hình. Khi video có phụ đề gốc, cách này thường đầy đủ và đúng chữ hơn.</li>
          <li><b>Tự động</b> (mặc định): nếu thấy video có phụ đề cứng, ứng dụng chạy cả hai cách rồi giữ kết quả đầy đủ hơn.</li>
        </ul>
        <p>OCR chỉ đọc <i>dòng phụ đề chính</i> trong vùng quét. Chữ nằm chỗ khác trên hình (tiêu đề, lời dẫn in nghệ thuật) không được lấy — bạn có thể thêm tay các câu đó ở thẻ Phụ đề, hoặc khoanh lại vùng quét ở thẻ Nhận dạng & Dịch.</p>

        <h2>Chọn bộ dịch</h2>
        <ul>
          <li><b>Google Dịch (miễn phí)</b> — không cần khoá, dùng ngay. Đây là cổng không chính thức nên có thể bị giới hạn khi dịch nhiều; khi đó ứng dụng sẽ chờ rồi báo lỗi rõ ràng, không cố vượt giới hạn. Bản dịch theo từng câu, không nắm ngữ cảnh.</li>
          <li><b>Bộ dịch AI</b> (Claude, GPT, Gemini, DeepSeek… hoặc Ollama chạy trên máy) — cần khoá API nhập ở trang Cài đặt. Hiểu ngữ cảnh, giữ xưng hô và tên riêng Hán-Việt nhất quán, nhận được mô tả video và bảng thuật ngữ.</li>
        </ul>
        <p>Dùng trang <a href="#/glossary">Thuật ngữ</a> để chốt cách dịch tên nhân vật, địa danh. Trong trình sửa phụ đề có nút dịch lại từng câu và "Dịch câu trống".</p>

        <h2>Lồng tiếng cho khớp</h2>
        <ul>
          <li>Câu tiếng Việt thường dài hơn câu tiếng Trung. Khi câu dịch dài hơn khoảng trống, giọng đọc được tăng tốc vừa đủ (không quá mức bạn đặt).</li>
          <li>Ở thẻ Phụ đề, câu nào ghi <b>"đọc nhanh ×1.4"</b> màu cam/đỏ nghĩa là nên rút gọn bản dịch.</li>
          <li>Bấm nút ⋮ ở mỗi câu để nghe thử giọng, hoặc gán giọng riêng cho câu đó (phân vai nhân vật).</li>
          <li>Tiếng gốc mặc định được giữ làm nền và tự hạ nhỏ khi có tiếng lồng.</li>
        </ul>

        <h2>Che phụ đề gốc</h2>
        <p>Ở thẻ Phụ đề & hình ảnh, kéo trên khung hình để khoanh vùng cần che (làm mờ hoặc che màu). Khi lời thoại được đọc từ phụ đề cứng, ứng dụng tự thêm vùng che đúng chỗ phụ đề gốc, chỉ bật lúc có câu thoại, và đặt phụ đề Việt đè lên đó. Nút "Xem thử chính xác" dựng một khung hình thật để bạn kiểm tra trước khi xuất.</p>

        <h2>Phím tắt</h2>
        <ul>
          <li><span class="kbd">Phím cách</span> — phát / tạm dừng (khi không gõ trong ô nhập).</li>
          <li><span class="kbd">Ctrl</span> + <span class="kbd">Enter</span> trong ô bản dịch — phát lại đúng câu đó.</li>
          <li><span class="kbd">Alt</span> + <span class="kbd">↑</span> / <span class="kbd">↓</span> — chuyển sang câu trước / sau.</li>
        </ul>

        <h2>Câu hỏi thường gặp</h2>
        <h3>Lần chạy đầu sao lâu?</h3>
        <p>Lần đầu ứng dụng phải tải mô hình nhận dạng (bản Turbo khoảng 1,6 GB) về thư mục <code>data/models</code>. Các lần sau không cần tải lại.</p>
        <h3>Máy tôi chậm, làm sao nhanh hơn?</h3>
        <p>Chọn mô hình nhận dạng nhỏ hơn, hoặc dùng "Nhận dạng qua API". Khi xuất video, chọn tốc độ mã hoá "Nhanh". Máy có card NVIDIA được dùng tự động nếu đã cài thư viện CUDA (xem tệp README).</p>
        <h3>Dữ liệu của tôi đi đâu?</h3>
        <p>Video, phụ đề và kết quả nằm trong thư mục <code>data/</code> trên máy bạn. Chỉ những thứ sau đi ra mạng, và chỉ khi bạn dùng tính năng tương ứng: câu thoại gửi tới bộ dịch đã chọn; câu tiếng Việt gửi tới dịch vụ giọng đọc (trừ giọng Piper chạy trên máy); âm thanh gửi tới dịch vụ nhận dạng nếu bạn chọn "Qua API".</p>
        <h3>Tôi được dùng video nào?</h3>
        <p>Chỉ tải và dịch những video bạn có quyền sử dụng. Tôn trọng bản quyền của tác giả gốc khi đăng lại.</p>
      </div>
    </div>`,
};
