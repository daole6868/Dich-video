// Trang Cài đặt: khoá API của các dịch vụ, mô hình nhận dạng, mạng, thông tin hệ thống.
import { api } from "../api.js";
import { commonComponents, confirmDialog, loadSettings, loadSystem, store, toast, toastError } from "../common.js";
import { clone, fmtBytes, same } from "../util.js";

export const SettingsPage = {
  name: "SettingsPage",
  components: commonComponents,
  data: () => ({
    store, form: clone(store.settings), saving: false, tab: "translate",
    testing: {}, testResult: {}, modelLists: {}, loadingModels: {}, models: null, show: {},
  }),
  computed: {
    dirty() { return !same(this.form, store.settings); },
    providers() { return store.system.llm_providers; },
    sys() { return store.system; },
    tabs() {
      return [
        { id: "translate", icon: "languages", label: "Bộ dịch AI" },
        { id: "asr", icon: "mic", label: "Nhận dạng" },
        { id: "tts", icon: "audio-lines", label: "Giọng đọc qua API" },
        { id: "system", icon: "cpu", label: "Hệ thống & mạng" },
      ];
    },
  },
  created() { this.loadModels(); },
  methods: {
    fmtBytes,
    async save(quiet) {
      this.saving = true;
      try {
        store.settings = await api.put("/api/settings", this.form);
        this.form = clone(store.settings);
        if (!quiet) toast("Đã lưu cài đặt.", "ok");
        return true;
      } catch (e) { toastError(e); return false; } finally { this.saving = false; }
    },
    reset() { this.form = clone(store.settings); },
    async testEngine(id) {
      if (this.dirty && !(await this.save(true))) return;
      this.testing[id] = true;
      this.testResult[id] = null;
      try {
        const r = await api.post("/api/llm/test", { engine: id });
        this.testResult[id] = { ok: true, text: `${r.sample} → ${r.translation}` };
      } catch (e) { this.testResult[id] = { ok: false, text: e.message }; } finally { this.testing[id] = false; }
    },
    async fetchModels(id) {
      if (this.dirty && !(await this.save(true))) return;
      this.loadingModels[id] = true;
      try {
        const r = await api.get(`/api/llm/models?engine=${id}`);
        this.modelLists[id] = r.models;
        toast(`Tìm thấy ${r.models.length} mô hình.`, "ok");
      } catch (e) { toastError(e); } finally { this.loadingModels[id] = false; }
    },
    suggestions(p) { return this.modelLists[p.id] || p.models || []; },
    async loadModels() {
      try { this.models = (await api.get("/api/models")).models; } catch (e) { this.models = []; }
    },
    async deleteModel(m) {
      const ok = await confirmDialog({ title: "Xoá mô hình?", danger: true, okText: "Xoá",
        message: `Xoá mô hình "${m.name}" (${m.disk_mb} MB) khỏi máy. Lần dùng sau sẽ phải tải lại.` });
      if (!ok) return;
      try { this.models = (await api.del(`/api/models/${m.id}`)).models; toast("Đã xoá mô hình.", "ok"); await loadSystem(); }
      catch (e) { toastError(e); }
    },
    async quit() {
      const ok = await confirmDialog({ title: "Thoát ứng dụng?", okText: "Thoát",
        message: "Ứng dụng sẽ dừng hẳn. Việc đang xử lý dở sẽ bị huỷ. Muốn dùng lại, hãy chạy lại tệp khởi động." });
      if (!ok) return;
      try { await api.post("/api/shutdown"); } catch (e) { /* máy chủ đã tắt */ }
      document.body.innerHTML = '<div style="display:grid;place-items:center;height:100vh;font:16px sans-serif;text-align:center">Đã thoát Dịch Video Studio.<br>Bạn có thể đóng thẻ này.</div>';
    },
  },
  async beforeUnmount() { await loadSettings().catch(() => {}); },
  template: `
    <div class="page">
      <div class="page-head">
        <div class="grow">
          <h1 class="page-title">Cài đặt</h1>
          <div class="page-desc">Khoá API chỉ lưu trên máy bạn (tệp <span class="mono">data/settings.json</span>) và chỉ gửi tới đúng dịch vụ tương ứng.</div>
        </div>
        <button class="btn" :disabled="!dirty" @click="reset">Hoàn tác</button>
        <button class="btn btn-primary" :disabled="!dirty || saving" @click="save()"><icon :name="saving ? 'loader-circle' : 'save'" :spin="saving"></icon>Lưu cài đặt</button>
      </div>

      <div class="card">
        <div class="tabs" style="padding: 0 8px">
          <button v-for="t in tabs" :key="t.id" class="tab" :class="{ on: tab === t.id }" @click="tab = t.id"><icon :name="t.icon"></icon>{{ t.label }}</button>
        </div>

        <div class="panel-body" v-show="tab === 'translate'">
          <div class="note" style="margin-bottom: 18px"><icon name="info"></icon>
            <div><b>Google Dịch (miễn phí)</b> dùng được ngay, không cần khoá, nhưng là cổng không chính thức nên có thể bị giới hạn khi dịch nhiều.
              Muốn bản dịch tự nhiên, đúng xưng hô và tên riêng Hán-Việt, hãy nhập khoá API của một bộ dịch AI dưới đây rồi chọn nó trong dự án.</div>
          </div>
          <div v-for="p in providers" :key="p.id" class="section">
            <div class="row wrap">
              <div class="section-title grow">{{ p.name }}
                <span class="badge ok" v-if="form.llm[p.id].api_key || p.id === 'ollama'">{{ p.id === 'ollama' ? 'Không cần khoá' : 'Đã có khoá' }}</span>
              </div>
              <a v-if="p.key_url" :href="p.key_url" target="_blank" rel="noopener" class="small">Lấy khoá API <icon name="external-link" :size="12"></icon></a>
            </div>
            <div class="form-grid">
              <div class="field" v-if="p.id !== 'ollama'">
                <label>Khoá API</label>
                <div class="row" style="gap: 6px">
                  <input class="input mono" :type="show[p.id] ? 'text' : 'password'" v-model="form.llm[p.id].api_key" placeholder="Dán khoá API vào đây" autocomplete="off" spellcheck="false">
                  <button class="btn btn-icon" @click="show[p.id] = !show[p.id]" :title="show[p.id] ? 'Ẩn' : 'Hiện'"><icon :name="show[p.id] ? 'eye-off' : 'eye'"></icon></button>
                </div>
              </div>
              <div class="field">
                <label>Mô hình</label>
                <div class="row" style="gap: 6px">
                  <input class="input mono" v-model="form.llm[p.id].model" :list="'models-' + p.id" spellcheck="false" :placeholder="p.model || 'tên mô hình'">
                  <datalist :id="'models-' + p.id"><option v-for="m in suggestions(p)" :key="m" :value="m"></option></datalist>
                  <button class="btn btn-icon" @click="fetchModels(p.id)" :disabled="loadingModels[p.id]" title="Lấy danh sách mô hình từ dịch vụ">
                    <icon :name="loadingModels[p.id] ? 'loader-circle' : 'list-ordered'" :spin="loadingModels[p.id]"></icon></button>
                </div>
                <div class="hint" v-if="p.id === 'anthropic'">Mặc định <span class="mono">claude-opus-5-5</span> (chất lượng cao nhất). Muốn tiết kiệm hơn có thể chọn
                  <span class="mono">claude-sonnet-5-5</span> hoặc <span class="mono">claude-haiku-5-5</span>.</div>
                <div class="hint" v-else>Tên mô hình thay đổi theo thời gian — bấm nút bên cạnh để lấy danh sách hiện có.</div>
              </div>
              <div class="field full" v-if="p.id !== 'anthropic'">
                <label>Địa chỉ API</label>
                <input class="input mono" v-model="form.llm[p.id].base_url" spellcheck="false" :placeholder="p.base_url || 'https://…/v1'">
              </div>
            </div>
            <div class="row wrap">
              <button class="btn btn-sm" @click="testEngine(p.id)" :disabled="testing[p.id]"><icon :name="testing[p.id] ? 'loader-circle' : 'zap'" :spin="testing[p.id]"></icon>Dịch thử một câu</button>
              <span v-if="testResult[p.id]" class="small" :style="{ color: testResult[p.id].ok ? 'var(--ok)' : 'var(--danger)' }">{{ testResult[p.id].text }}</span>
            </div>
          </div>
        </div>

        <div class="panel-body" v-show="tab === 'asr'">
          <div class="section">
            <div class="section-title"><icon name="hard-drive"></icon>Mô hình nhận dạng trên máy (Whisper)</div>
            <p class="muted small">Mô hình được tải về tự động ở lần đầu dùng và lưu trong <span class="mono">data/models</span>. Chọn mô hình cho từng dự án ở thẻ "Nhận dạng & Dịch".</p>
            <table class="table" v-if="models">
              <thead><tr><th>Mô hình</th><th>Mô tả</th><th>Dung lượng</th><th>Trạng thái</th><th></th></tr></thead>
              <tbody>
                <tr v-for="m in models" :key="m.id">
                  <td><b>{{ m.name }}</b><div class="mono muted">{{ m.id }}</div></td>
                  <td class="small">{{ m.desc }}</td>
                  <td class="nowrap">{{ m.downloaded ? m.disk_mb : m.size_mb }} MB</td>
                  <td><span class="badge" :class="m.downloaded ? 'ok' : ''">{{ m.downloaded ? 'Đã tải' : 'Chưa tải' }}</span></td>
                  <td><button v-if="m.downloaded" class="btn btn-ghost btn-icon btn-sm" @click="deleteModel(m)" title="Xoá khỏi máy"><icon name="trash-2"></icon></button></td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="section">
            <div class="section-title"><icon name="globe"></icon>Nhận dạng qua API (cho máy cấu hình yếu)</div>
            <p class="muted small">Dịch vụ tương thích OpenAI (ví dụ OpenAI, Groq). Âm thanh của video sẽ được gửi lên dịch vụ này khi dự án chọn "Nhận dạng qua API".</p>
            <div class="form-grid">
              <div class="field full"><label>Địa chỉ API</label><input class="input mono" v-model="form.asr_api.base_url" spellcheck="false"></div>
              <div class="field"><label>Khoá API</label><input class="input mono" type="password" v-model="form.asr_api.api_key" autocomplete="off" spellcheck="false" placeholder="Dán khoá API vào đây"></div>
              <div class="field"><label>Mô hình</label><input class="input mono" v-model="form.asr_api.model" spellcheck="false"></div>
            </div>
          </div>
        </div>

        <div class="panel-body" v-show="tab === 'tts'">
          <div class="note" style="margin-bottom: 18px"><icon name="info"></icon>
            <div>Giọng <b>Microsoft Edge</b> (cần mạng) và <b>Piper</b> (ngoại tuyến) dùng miễn phí, không cần cài đặt gì ở đây.
              Phần dưới chỉ dành cho ai muốn dùng dịch vụ giọng đọc trả phí.</div>
          </div>
          <div class="section">
            <div class="section-title">API giọng đọc tương thích OpenAI</div>
            <div class="form-grid">
              <div class="field full"><label>Địa chỉ API</label><input class="input mono" v-model="form.tts_openai.base_url" spellcheck="false"></div>
              <div class="field"><label>Khoá API</label><input class="input mono" type="password" v-model="form.tts_openai.api_key" autocomplete="off" spellcheck="false" placeholder="Dán khoá API vào đây"></div>
              <div class="field"><label>Mô hình</label><input class="input mono" v-model="form.tts_openai.model" spellcheck="false"></div>
            </div>
          </div>
          <div class="section">
            <div class="section-title">ElevenLabs</div>
            <div class="form-grid">
              <div class="field"><label>Khoá API</label><input class="input mono" type="password" v-model="form.tts_elevenlabs.api_key" autocomplete="off" spellcheck="false" placeholder="Dán khoá API vào đây"></div>
              <div class="field"><label>Mô hình</label><input class="input mono" v-model="form.tts_elevenlabs.model" spellcheck="false">
                <div class="hint">Dùng mô hình có hỗ trợ tiếng Việt (ví dụ dòng v2.5).</div></div>
            </div>
          </div>
        </div>

        <div class="panel-body" v-show="tab === 'system'">
          <div class="section">
            <div class="section-title"><icon name="monitor-play"></icon>Thông tin hệ thống</div>
            <table class="table">
              <tbody>
                <tr><td class="muted" style="width: 220px">Phiên bản ứng dụng</td><td>{{ sys.app }} {{ sys.version }}</td></tr>
                <tr><td class="muted">Hệ điều hành</td><td>{{ sys.platform }} · Python {{ sys.python }}</td></tr>
                <tr><td class="muted">Bộ xử lý video (ffmpeg)</td><td>
                  <span class="badge" :class="sys.ffmpeg.ok ? 'ok' : 'err'">{{ sys.ffmpeg.ok ? 'Sẵn sàng' : 'Có vấn đề' }}</span>
                  <span class="mono muted" style="margin-left: 8px">{{ sys.ffmpeg.version || sys.ffmpeg.error }}</span></td></tr>
                <tr><td class="muted">Tăng tốc nhận dạng</td><td>{{ sys.gpu ? 'Card NVIDIA (CUDA)' : 'CPU — ' + sys.cpu_count + ' luồng' }}</td></tr>
                <tr><td class="muted">Dung lượng đĩa còn trống</td><td>{{ fmtBytes(sys.disk_free) }}</td></tr>
                <tr><td class="muted">Thư mục dữ liệu</td><td class="mono">{{ sys.data_dir }}</td></tr>
              </tbody>
            </table>
          </div>
          <div class="section">
            <div class="section-title"><icon name="globe"></icon>Mạng</div>
            <div class="form-grid">
              <div class="field"><label>Proxy (nếu mạng của bạn cần)</label><input class="input mono" v-model="form.network.proxy" placeholder="http://127.0.0.1:7890" spellcheck="false"></div>
              <div class="field"><label>Máy chủ gương Hugging Face</label><input class="input mono" v-model="form.network.hf_endpoint" placeholder="để trống = huggingface.co" spellcheck="false">
                <div class="hint">Chỉ cần khi không tải được mô hình nhận dạng.</div></div>
            </div>
          </div>
          <div class="section">
            <div class="section-title"><icon name="sliders-horizontal"></icon>Nâng cao</div>
            <div class="form-grid cols-3">
              <div class="field"><label>Số luồng CPU cho nhận dạng</label><input class="input" type="number" min="0" max="64" v-model.number="form.advanced.cpu_threads"><div class="hint">0 = tự chọn</div></div>
              <div class="field"><label>Số yêu cầu giọng đọc song song</label><input class="input" type="number" min="1" max="8" v-model.number="form.advanced.tts_concurrency"></div>
              <div class="field"><label>Đường dẫn ffmpeg riêng</label><input class="input mono" v-model="form.advanced.ffmpeg_path" placeholder="để trống = dùng bản kèm theo" spellcheck="false"></div>
            </div>
          </div>
          <div class="section">
            <div class="row"><div class="grow"><b>Thoát ứng dụng</b><div class="muted small">Dừng hẳn chương trình đang chạy nền.</div></div>
              <button class="btn btn-danger" @click="quit"><icon name="power"></icon>Thoát</button></div>
          </div>
        </div>
      </div>
    </div>`,
};
