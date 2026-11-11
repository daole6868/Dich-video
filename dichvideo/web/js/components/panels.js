// Các bảng cài đặt trong không gian làm việc của một dự án.
import { api } from "../api.js";
import { commonComponents, confirmDialog, store, toast, toastError } from "../common.js";
import { RegionEditor } from "./region.js";
import { fmtBytes } from "../util.js";

const base = { components: { ...commonComponents, RegionEditor } };

// ------------------------------------------------------------------ Nhận dạng & Dịch
export const RecognizePanel = {
  ...base,
  name: "RecognizePanel",
  props: { proj: Object, st: Object, busy: Boolean, time: Number },
  emits: ["run"],
  data: () => ({ store, frameT: 0, regionSel: 0, glossaryCount: null }),
  computed: {
    sys() { return store.system; },
    hasVideo() { return !!(this.proj.media && this.proj.media.has_video); },
    info() { return (this.proj.steps.transcribe && this.proj.steps.transcribe.info) || {}; },
    hardsub() { return this.proj.hardsub || null; },
    usesOcr() { return this.st.subtitle_source !== "asr" && this.hasVideo; },
    usesAsr() { return this.st.subtitle_source !== "ocr"; },
    ocrRegions: {
      get() { const r = this.st.ocr.region; return r ? [{ x: r[0], y: r[1], w: r[2], h: r[3] }] : []; },
      set(list) { const r = list[0]; this.st.ocr.region = r ? [r.x, r.y, r.w, r.h] : null; },
    },
    frameUrl() { return `/api/projects/${this.proj.id}/frame?t=${this.frameT.toFixed(1)}`; },
    engines() { return [{ id: "google", name: "Google Dịch (miễn phí, không cần khoá)" }, ...this.sys.llm_providers.map((p) => ({ id: p.id, name: p.name }))]; },
    isLlm() { return this.st.translate.engine !== "google"; },
    missingKey() {
      const e = this.st.translate.engine;
      if (e === "google" || e === "ollama") return false;
      const cfg = store.settings.llm[e];
      return !cfg || !cfg.api_key;
    },
    styleHint() { const s = this.sys.translate_styles.find((x) => x.id === this.st.translate.style); return s ? s.hint : ""; },
    model() { return this.sys.whisper_models.find((m) => m.id === this.st.asr.model); },
    sourceSummary() {
      const i = this.info;
      if (!i.source) return "";
      const name = { ocr: "đọc phụ đề cứng (OCR)", asr: "nghe giọng nói", import: "nhập từ tệp phụ đề" }[i.source] || i.source;
      let s = `Lần gần nhất: ${name} — ${i.segments ?? "?"} câu.`;
      if (i.auto) s += ` Chế độ tự động đã so hai cách: OCR được ${i.ocr_lines} câu, nghe giọng nói được ${i.asr_lines} câu.`;
      return s;
    },
  },
  async created() {
    this.frameT = Math.min(this.time || 0, Math.max(0, (this.proj.media.duration || 1) - 0.2));
    try { this.glossaryCount = (await api.get("/api/glossary")).items.length; } catch (e) { /* bỏ qua */ }
  },
  methods: {
    useCurrentFrame() { this.frameT = this.time || 0; },
    resetRegion() { this.st.ocr.region = null; },
    async rerun() {
      const ok = await confirmDialog({ title: "Nhận dạng lại lời thoại?", okText: "Nhận dạng lại",
        message: "Toàn bộ câu phụ đề hiện tại (kể cả phần đã sửa tay và bản dịch) sẽ được thay bằng kết quả mới, rồi dịch lại." });
      if (ok) this.$emit("run", ["transcribe", "translate"]);
    },
    async retranslate() {
      const ok = await confirmDialog({ title: "Dịch lại toàn bộ?", okText: "Dịch lại",
        message: "Toàn bộ bản dịch hiện tại (kể cả phần bạn đã sửa tay) sẽ bị thay bằng bản dịch mới." });
      if (ok) this.$emit("run", ["translate"]);
    },
  },
  template: `
    <div class="panel-body">
      <div class="section">
        <div class="section-title"><icon name="mic"></icon>Lấy lời thoại từ video</div>
        <div class="form-grid" style="grid-template-columns: minmax(0, 1fr) auto">
          <div class="field">
            <label>Ngôn ngữ trong video</label>
            <select v-model="st.source_lang"><option v-for="l in sys.source_langs" :key="l.id" :value="l.id">{{ l.name }}</option></select>
          </div>
          <div class="field">
            <label>Cách lấy lời thoại</label>
            <div class="seg" style="align-self: flex-start; white-space: nowrap">
              <button :class="{ on: st.subtitle_source === 'auto' }" @click="st.subtitle_source = 'auto'"><icon name="wand-sparkles" :size="14"></icon>Tự động</button>
              <button :class="{ on: st.subtitle_source === 'asr' }" @click="st.subtitle_source = 'asr'"><icon name="mic" :size="14"></icon>Nghe giọng nói</button>
              <button :class="{ on: st.subtitle_source === 'ocr' }" :disabled="!hasVideo" @click="st.subtitle_source = 'ocr'"><icon name="scan-text" :size="14"></icon>Đọc phụ đề cứng</button>
            </div>
          </div>
        </div>
        <div class="note" v-if="hardsub && hasVideo" :class="hardsub.found ? 'ok' : ''">
          <icon :name="hardsub.found ? 'badge-check' : 'info'"></icon>
          <div v-if="hardsub.found"><b>Video này có phụ đề cứng</b> (thấy chữ ở {{ hardsub.hits }}/{{ hardsub.samples }} khung hình mẫu).
            Ở chế độ Tự động, ứng dụng chạy cả hai cách rồi giữ kết quả đầy đủ hơn — phụ đề cứng thường đúng tên riêng hơn so với nghe giọng nói.</div>
          <div v-else>Không thấy phụ đề cứng trong các khung hình mẫu, nên chế độ Tự động sẽ nghe giọng nói. Nếu video thật sự có phụ đề in sẵn, hãy chọn "Đọc phụ đề cứng" và khoanh vùng bên dưới.</div>
        </div>
        <div class="muted small" v-if="sourceSummary">{{ sourceSummary }}</div>

        <template v-if="usesAsr">
          <div class="form-grid">
            <div class="field">
              <label>Bộ nhận dạng giọng nói</label>
              <div class="seg">
                <button :class="{ on: st.asr.engine === 'local' }" @click="st.asr.engine = 'local'">Chạy trên máy này</button>
                <button :class="{ on: st.asr.engine === 'api' }" @click="st.asr.engine = 'api'">Qua API</button>
              </div>
              <div class="hint" v-if="st.asr.engine === 'api'">Âm thanh sẽ được gửi tới dịch vụ đã khai báo ở <a href="#/settings">Cài đặt → Nhận dạng</a>.</div>
            </div>
            <div class="field" v-if="st.asr.engine === 'local'">
              <label>Mô hình</label>
              <select v-model="st.asr.model">
                <option v-for="m in sys.whisper_models" :key="m.id" :value="m.id">{{ m.name }} — {{ m.size_mb }} MB{{ m.downloaded ? ' (đã tải)' : '' }}</option>
              </select>
              <div class="hint" v-if="model">{{ model.desc }}<span v-if="!model.downloaded"> Sẽ tự tải về ở lần chạy đầu.</span></div>
            </div>
          </div>
          <div class="field">
            <label>Gợi ý cho bộ nhận dạng (tuỳ chọn)</label>
            <input class="input" v-model="st.asr.prompt" placeholder="Ví dụ tên riêng hay bị nghe nhầm: 李明、王芳" lang="zh">
            <div class="hint">Viết bằng ngôn ngữ của video. Để trống là tốt nhất trong đa số trường hợp.</div>
          </div>
        </template>

        <template v-if="usesOcr">
          <div class="field">
            <label class="row" style="justify-content: space-between">
              <span>Vùng quét phụ đề cứng <span class="muted" style="font-weight: 400">— kéo trên hình để khoanh đúng chỗ phụ đề gốc</span></span>
              <span class="row" style="gap: 6px">
                <button class="btn btn-sm" @click="useCurrentFrame"><icon name="image"></icon>Lấy khung hình đang xem</button>
                <button class="btn btn-sm" :disabled="!st.ocr.region" @click="resetRegion">Dùng vùng mặc định</button>
              </span>
            </label>
            <region-editor v-model="ocrRegions" v-model:selected="regionSel" :frame-url="frameUrl" single :label="() => 'Vùng quét'"></region-editor>
            <div class="hint">{{ st.ocr.region ? 'Đang dùng vùng bạn khoanh.' : 'Chưa khoanh: dùng dải phía dưới khung hình (video dọc thì cao hơn một chút).' }}
              Chữ nằm lệch khỏi dòng phụ đề chính sẽ tự bị bỏ qua.</div>
          </div>
          <div class="form-grid">
            <div class="field">
              <label>Số khung hình quét mỗi giây</label>
              <select v-model.number="st.ocr.fps"><option :value="2">2 — nhanh</option><option :value="4">4 — khuyên dùng</option><option :value="6">6 — mốc thời gian sát hơn, chậm hơn</option></select>
            </div>
          </div>
        </template>

        <div class="form-grid cols-3" v-if="usesAsr">
          <slider label="Độ dài tối đa mỗi câu gốc" v-model="st.segment.max_chars" :min="10" :max="40" unit=" chữ" hint="Câu ngắn dễ đọc và dễ lồng tiếng hơn."></slider>
          <slider label="Thời lượng tối đa mỗi câu" v-model="st.segment.max_duration" :min="3" :max="12" :step="0.5" unit=" giây"></slider>
          <slider label="Ngắt câu khi ngừng nói" v-model="st.segment.pause" :min="0.3" :max="1.5" :step="0.1" unit=" giây"></slider>
        </div>
        <div class="row"><button class="btn" :disabled="busy" @click="rerun"><icon name="refresh-cw"></icon>Nhận dạng lại</button>
          <span class="muted small">Áp dụng các thiết lập ở trên rồi dịch lại.</span></div>
      </div>

      <div class="section">
        <div class="section-title"><icon name="languages"></icon>Dịch sang tiếng Việt</div>
        <div class="form-grid">
          <div class="field">
            <label>Bộ dịch</label>
            <select v-model="st.translate.engine"><option v-for="e in engines" :key="e.id" :value="e.id">{{ e.name }}</option></select>
            <div class="hint" v-if="!isLlm">Dùng ngay được nhưng là cổng không chính thức: dịch nhiều có thể bị giới hạn, và không nắm được ngữ cảnh/xưng hô.</div>
            <div class="hint" v-else-if="missingKey" style="color: var(--danger)">Chưa có khoá API cho bộ dịch này. <a href="#/settings">Mở Cài đặt</a> để nhập.</div>
            <div class="hint" v-else>Bộ dịch AI hiểu ngữ cảnh, giữ xưng hô và tên riêng Hán-Việt nhất quán.</div>
          </div>
          <div class="field">
            <label>Thể loại / văn phong</label>
            <select v-model="st.translate.style" :disabled="!isLlm"><option v-for="s in sys.translate_styles" :key="s.id" :value="s.id">{{ s.name }}</option></select>
            <div class="hint">{{ isLlm ? (styleHint || 'Để bộ dịch tự nhận biết.') : 'Chỉ áp dụng cho bộ dịch AI.' }}</div>
          </div>
          <div class="field full">
            <label>Mô tả video cho bộ dịch (tuỳ chọn)</label>
            <textarea rows="2" v-model="st.translate.context" :disabled="!isLlm" placeholder="Ví dụ: Phim ngắn hiện đại về hai chị em ở chung nhà. 李明 là Lý Minh (anh trai), 王芳 là Vương Phương (bạn gái của Minh); hai người xưng anh - em."></textarea>
            <div class="hint">{{ isLlm ? 'Càng nói rõ nhân vật và quan hệ, bản dịch càng đúng xưng hô.' : 'Chỉ áp dụng cho bộ dịch AI.' }}</div>
          </div>
        </div>
        <div class="row wrap">
          <toggle v-model="st.translate.use_glossary" label="Dùng bảng thuật ngữ" :hint="glossaryCount === null ? '' : glossaryCount + ' thuật ngữ đã lưu'"></toggle>
          <a href="#/glossary" class="small">Mở bảng thuật ngữ</a>
          <span class="spacer"></span>
          <toggle v-model="st.stop_for_review" label="Dừng sau khi dịch để duyệt" hint="Khi chạy tự động"></toggle>
        </div>
        <div class="row"><button class="btn" :disabled="busy || !proj.counts.segments" @click="retranslate"><icon name="languages"></icon>Dịch lại toàn bộ</button></div>
      </div>
    </div>`,
};

// ------------------------------------------------------------------ Lồng tiếng
export const DubPanel = {
  ...base,
  name: "DubPanel",
  props: { proj: Object, st: Object, busy: Boolean, voices: Array, voicesLoading: Boolean, voicesError: String },
  emits: ["run", "reload-voices"],
  data: () => ({ store, sample: "Xin chào, đây là giọng đọc thử của Dịch Video Studio.", playing: "", audio: null }),
  computed: {
    dub() { return this.st.dub; },
    engines() { return store.system.tts_engines; },
    engine() { return this.engines.find((e) => e.id === this.dub.engine); },
    info() { return (this.proj.steps.dub && this.proj.steps.dub.info) || null; },
    done() { return this.proj.steps.dub && ["done", "stale"].includes(this.proj.steps.dub.status); },
  },
  beforeUnmount() { this.stop(); },
  methods: {
    stop() { if (this.audio) { this.audio.pause(); URL.revokeObjectURL(this.audio.src); this.audio = null; } this.playing = ""; },
    async preview(v) {
      this.stop();
      this.playing = v.id;
      try {
        const blob = await api.blob("POST", "/api/tts/preview", { text: this.sample, engine: this.dub.engine, voice: v.id, rate: this.dub.rate, pitch: this.dub.pitch });
        this.audio = new Audio(URL.createObjectURL(blob));
        this.audio.onended = () => { this.playing = ""; };
        await this.audio.play();
      } catch (e) { this.playing = ""; toastError(e); }
    },
    pick(v) { this.dub.voice = v.id; },
    setEngine(id) {
      if (this.dub.engine === id) return;
      this.dub.engine = id;
      this.dub.voice = "";
      this.$emit("reload-voices");
    },
    genderLabel(v) { return v.gender === "female" ? "Nữ" : v.gender === "male" ? "Nam" : ""; },
  },
  watch: {
    // Đổi engine xong, khi có danh sách giọng thì chọn giọng đầu tiên.
    voices(list) { if (list.length && !list.some((v) => v.id === this.dub.voice)) this.dub.voice = list[0].id; },
  },
  template: `
    <div class="panel-body">
      <div class="section">
        <toggle v-model="dub.enabled" label="Lồng tiếng Việt cho video" hint="Tắt đi nếu bạn chỉ cần phụ đề"></toggle>
      </div>
      <template v-if="dub.enabled">
        <div class="section">
          <div class="section-title"><icon name="audio-lines"></icon>Giọng đọc</div>
          <div class="seg" style="flex-wrap: wrap; align-self: flex-start">
            <button v-for="e in engines" :key="e.id" :class="{ on: dub.engine === e.id }" @click="setEngine(e.id)">{{ e.name }}</button>
          </div>
          <div class="muted small" v-if="engine">{{ engine.desc }}
            <span v-if="dub.engine === 'edge'">Đây là dịch vụ đọc văn bản của trình duyệt Edge (không phải API có cam kết), đôi khi có thể tạm ngưng.</span>
            <span v-if="dub.engine === 'piper'">Giọng được tải về ở lần dùng đầu (khoảng 63 MB mỗi giọng).</span>
            <span v-if="dub.engine === 'openai' || dub.engine === 'elevenlabs'"><a href="#/settings">Mở Cài đặt</a> để nhập khoá.</span>
          </div>
          <div class="field">
            <label>Câu đọc thử</label>
            <input class="input" v-model="sample">
          </div>
          <div v-if="voicesLoading" class="muted small"><icon name="loader-circle" spin></icon> Đang lấy danh sách giọng…</div>
          <div v-else-if="voicesError" class="note err"><icon name="circle-alert"></icon><div>{{ voicesError }}
            <button class="btn btn-sm" style="margin-left: 8px" @click="$emit('reload-voices')">Thử lại</button></div></div>
          <div v-else class="voice-grid">
            <div v-for="v in voices" :key="v.id" class="voice" :class="{ on: dub.voice === v.id }" @click="pick(v)" tabindex="0" @keydown.enter="pick(v)">
              <div class="avatar"><icon name="user"></icon></div>
              <div class="grow">
                <div class="name truncate">{{ v.name }}</div>
                <div class="sub">{{ genderLabel(v) }}{{ v.lang && v.lang.startsWith('vi') ? ' · tiếng Việt' : v.lang ? ' · ' + v.lang : '' }}</div>
              </div>
              <button class="btn btn-ghost btn-icon btn-sm" @click.stop="playing === v.id ? stop() : preview(v)" :title="playing === v.id ? 'Dừng' : 'Nghe thử'">
                <icon :name="playing === v.id ? 'square' : 'play'" :size="14"></icon></button>
            </div>
          </div>
          <div class="muted small" v-if="dub.engine === 'edge'">Hai giọng tiếng Việt bản ngữ là Hoài My và Nam Minh. Các giọng "đa ngữ" đọc được tiếng Việt rõ ràng nhưng có thể mang ngữ điệu nước ngoài — hợp để phân vai nhân vật. Gán giọng riêng cho từng câu ở thẻ Phụ đề (nút ⋮).</div>
          <div class="form-grid">
            <slider label="Tốc độ đọc" v-model="dub.rate" :min="-30" :max="60" :step="5" :format="(v) => (v > 0 ? '+' : '') + v + '%'"></slider>
            <slider label="Cao độ giọng" v-model="dub.pitch" :min="-10" :max="10" :format="(v) => (v > 0 ? '+' : '') + v" hint="Số âm: trầm hơn. Số dương: cao hơn."></slider>
          </div>
        </div>
        <div class="section">
          <div class="section-title"><icon name="sliders-horizontal"></icon>Khớp thời lượng và âm thanh nền</div>
          <div class="form-grid">
            <slider label="Tăng tốc tối đa khi câu dịch dài" v-model="dub.max_speed" :min="1" :max="2" :step="0.05" :format="(v) => '×' + v.toFixed(2)"
                    hint="Câu dịch dài hơn khoảng trống sẽ được đọc nhanh lên, nhưng không quá mức này."></slider>
            <slider label="Âm lượng tiếng lồng" v-model="dub.dub_volume" :min="50" :max="150" :step="5" unit="%"></slider>
            <div class="field">
              <label>Tiếng gốc của video</label>
              <div class="seg">
                <button :class="{ on: dub.background === 'original' }" @click="dub.background = 'original'">Giữ làm nền</button>
                <button :class="{ on: dub.background === 'mute' }" @click="dub.background = 'mute'">Tắt hẳn</button>
              </div>
            </div>
            <slider v-if="dub.background === 'original'" label="Âm lượng tiếng gốc khi có tiếng lồng" v-model="dub.original_volume" :min="0" :max="60" unit="%"></slider>
          </div>
          <toggle v-if="dub.background === 'original'" v-model="dub.ducking" label="Chỉ hạ tiếng gốc lúc có tiếng lồng"
                  hint="Bật: nhạc nền, tiếng động giữ nguyên ở chỗ không có lời. Tắt: tiếng gốc nhỏ suốt video."></toggle>
        </div>
        <div class="section">
          <div class="row wrap">
            <button class="btn btn-primary" :disabled="busy || !proj.counts.translated" @click="$emit('run', ['dub'])"><icon name="mic"></icon>{{ done ? 'Tạo lại lồng tiếng' : 'Tạo lồng tiếng' }}</button>
            <span class="muted small" v-if="!proj.counts.translated">Cần có bản dịch trước.</span>
          </div>
          <div class="note" v-if="info && info.clips" :class="info.overflow ? 'warn' : 'ok'">
            <icon :name="info.overflow ? 'triangle-alert' : 'circle-check'"></icon>
            <div>Đã lồng tiếng {{ info.clips }} câu. {{ info.sped_up }} câu phải đọc nhanh hơn bình thường (nhanh nhất ×{{ (info.max_speed || 1).toFixed(2) }}).
              <span v-if="info.overflow">{{ info.overflow }} câu vẫn dài hơn khoảng trống dù đã tăng tốc tối đa — hãy rút gọn các câu có chữ đỏ "đọc nhanh" ở thẻ Phụ đề.</span></div>
          </div>
        </div>
      </template>
    </div>`,
};

// ------------------------------------------------------------------ Phụ đề & hình ảnh
const PRESETS = [
  { name: "Trắng viền đen", s: { color: "#FFFFFF", outline_color: "#000000", outline: 3, shadow: 1, box: false } },
  { name: "Vàng viền đen", s: { color: "#FFE14A", outline_color: "#000000", outline: 3, shadow: 1, box: false } },
  { name: "Nền hộp đen", s: { color: "#FFFFFF", box: true, box_color: "#000000", box_opacity: 70 } },
  { name: "Trắng viền xanh", s: { color: "#FFFFFF", outline_color: "#0B3D91", outline: 4, shadow: 0, box: false } },
  { name: "Đen nền trắng", s: { color: "#111111", box: true, box_color: "#FFFFFF", box_opacity: 85 } },
];

export const VisualPanel = {
  ...base,
  name: "VisualPanel",
  props: { proj: Object, st: Object, busy: Boolean, time: Number },
  emits: ["reload"],
  data: () => ({ store, PRESETS, frameT: 0, sel: -1, preview: null, previewBusy: false }),
  computed: {
    sub() { return this.st.subtitle; },
    fonts() { return store.system.fonts; },
    family() { return this.fonts.find((f) => f.family === this.sub.font); },
    hasVideo() { return !!(this.proj.media && this.proj.media.has_video); },
    frameUrl() { return `/api/projects/${this.proj.id}/frame?t=${this.frameT.toFixed(1)}`; },
    region() { return this.sel >= 0 ? this.st.cover[this.sel] : null; },
    logo() { return this.st.logo; },
  },
  created() { this.frameT = Math.min(this.time || 0, Math.max(0, (this.proj.media.duration || 1) - 0.2)); if (this.st.cover.length) this.sel = 0; },
  methods: {
    apply(p) { Object.assign(this.sub, p.s); },
    presetStyle(p) {
      const s = { color: p.s.color, fontFamily: `"sub:${this.sub.font}", sans-serif`, fontWeight: 700 };
      if (p.s.box) { s.background = p.s.box_color; s.padding = "1px 8px"; s.borderRadius = "2px"; }
      else { s.webkitTextStroke = `3px ${p.s.outline_color}`; s.paintOrder = "stroke fill"; }
      return s;
    },
    useCurrentFrame() { this.frameT = this.time || 0; },
    addDetected() {
      const r = this.proj.ocr_region || (this.proj.hardsub && this.proj.hardsub.region);
      if (!r) return;
      const x0 = Math.max(0, r[0] - 0.04), x1 = Math.min(1, r[0] + r[2] + 0.04);
      this.st.cover.push({ x: +x0.toFixed(4), y: r[1], w: +(x1 - x0).toFixed(4), h: r[3], mode: "blur", strength: 60 });
      this.sel = this.st.cover.length - 1;
    },
    removeRegion() { this.st.cover.splice(this.sel, 1); this.sel = this.st.cover.length ? 0 : -1; },
    // Đặt dòng phụ đề Việt vào giữa vùng che đang chọn.
    alignToRegion() {
      const r = this.region, m = this.proj.media;
      if (!r) return;
      const scale = Math.min(m.width, m.height) / 1080;
      const half = 0.62 * this.sub.size * scale;
      const fromBottom = m.height * (1 - (r.y + r.h / 2));
      this.sub.align = "bottom";
      this.sub.margin_v = Math.max(0, Math.round(((fromBottom - half) / m.height) * 1000) / 10);
      toast("Đã căn phụ đề vào giữa vùng che.", "ok");
    },
    pickLogo() { this.$refs.logo.click(); },
    async onLogo(e) {
      const file = e.target.files[0];
      e.target.value = "";
      if (!file) return;
      try {
        await api.postRaw(`/api/projects/${this.proj.id}/logo?filename=${encodeURIComponent(file.name)}`, file);
        this.$emit("reload");
        toast("Đã tải logo lên.", "ok");
      } catch (err) { toastError(err); }
    },
    async exactPreview() {
      this.previewBusy = true;
      try {
        const blob = await api.blob("POST", `/api/projects/${this.proj.id}/preview-frame`, { t: this.time || 0, settings: this.st });
        if (this.preview) URL.revokeObjectURL(this.preview);
        this.preview = URL.createObjectURL(blob);
      } catch (e) { toastError(e); } finally { this.previewBusy = false; }
    },
    closePreview() { if (this.preview) URL.revokeObjectURL(this.preview); this.preview = null; },
    regionLabel(r, i) { return (r.mode === "box" ? "Che màu" : "Làm mờ") + " " + (i + 1) + (r.auto ? " (tự động)" : ""); },
  },
  template: `
    <div class="panel-body">
      <div class="section">
        <div class="row wrap">
          <toggle v-model="sub.burn" label="Gắn phụ đề tiếng Việt vào hình"></toggle>
          <toggle v-model="sub.bilingual" label="Song ngữ" hint="Thêm dòng lời gốc bên dưới" :disabled="!sub.burn"></toggle>
          <span class="spacer"></span>
          <button class="btn" :disabled="!hasVideo || previewBusy" @click="exactPreview" title="Dựng một khung hình thật tại vị trí đang xem, đúng như video xuất ra">
            <icon :name="previewBusy ? 'loader-circle' : 'eye'" :spin="previewBusy"></icon>Xem thử chính xác</button>
        </div>
      </div>

      <div class="section" v-if="sub.burn">
        <div class="section-title"><icon name="type"></icon>Kiểu chữ phụ đề</div>
        <div class="swatch-row">
          <button v-for="p in PRESETS" :key="p.name" class="preset" @click="apply(p)" :title="p.name"><span :style="presetStyle(p)">Phụ đề</span></button>
        </div>
        <div class="form-grid">
          <div class="field">
            <label>Phông chữ</label>
            <select v-model="sub.font"><option v-for="f in fonts" :key="f.family" :value="f.family">{{ f.family }}{{ f.origin === 'nguoi-dung' ? ' (của bạn)' : '' }}{{ f.vietnamese ? '' : ' — thiếu dấu tiếng Việt' }}</option></select>
            <div class="hint" v-if="family && !family.vietnamese" style="color: var(--danger)">Phông này thiếu một số chữ có dấu tiếng Việt.</div>
            <div class="hint" v-else>Thêm phông riêng: chép tệp .ttf/.otf vào thư mục <span class="mono">data/fonts</span> rồi tải lại trang.</div>
          </div>
          <slider label="Cỡ chữ" v-model="sub.size" :min="20" :max="110" hint="Tính trên video cao 1080; video khác cỡ sẽ tự co theo."></slider>
          <div class="field">
            <label>Kiểu</label>
            <div class="row wrap">
              <toggle v-model="sub.bold" label="Đậm"></toggle>
              <toggle v-model="sub.italic" label="Nghiêng"></toggle>
              <toggle v-model="sub.uppercase" label="IN HOA"></toggle>
            </div>
          </div>
          <div class="field">
            <label>Màu chữ</label>
            <div class="row"><input type="color" v-model="sub.color"><span class="mono muted">{{ sub.color }}</span></div>
          </div>
          <div class="field full"><toggle v-model="sub.box" label="Nền hộp sau chữ" hint="Thay cho viền chữ; dễ đọc trên nền rối"></toggle></div>
          <template v-if="sub.box">
            <div class="field"><label>Màu nền hộp</label><div class="row"><input type="color" v-model="sub.box_color"><span class="mono muted">{{ sub.box_color }}</span></div></div>
            <slider label="Độ đậm nền hộp" v-model="sub.box_opacity" :min="10" :max="100" :step="5" unit="%"></slider>
          </template>
          <template v-else>
            <div class="field"><label>Màu viền</label><div class="row"><input type="color" v-model="sub.outline_color"><span class="mono muted">{{ sub.outline_color }}</span></div></div>
            <slider label="Độ dày viền" v-model="sub.outline" :min="0" :max="8" :step="0.5"></slider>
            <slider label="Bóng đổ" v-model="sub.shadow" :min="0" :max="6" :step="0.5"></slider>
          </template>
          <div class="field">
            <label>Vị trí</label>
            <div class="seg">
              <button :class="{ on: sub.align === 'bottom' }" @click="sub.align = 'bottom'">Dưới</button>
              <button :class="{ on: sub.align === 'middle' }" @click="sub.align = 'middle'">Giữa</button>
              <button :class="{ on: sub.align === 'top' }" @click="sub.align = 'top'">Trên</button>
            </div>
          </div>
          <slider v-if="sub.align !== 'middle'" :label="sub.align === 'top' ? 'Cách mép trên' : 'Cách mép dưới'" v-model="sub.margin_v" :min="0" :max="60" :step="0.5" unit="%"></slider>
          <slider label="Lề hai bên" v-model="sub.margin_h" :min="0" :max="30" :step="0.5" unit="%" hint="Lề lớn hơn thì dòng dài sẽ xuống hàng sớm hơn."></slider>
          <template v-if="sub.bilingual">
            <slider label="Cỡ dòng lời gốc" v-model="sub.secondary_scale" :min="40" :max="100" :step="5" unit="%"></slider>
            <div class="field"><label>Màu dòng lời gốc</label><div class="row"><input type="color" v-model="sub.secondary_color"><span class="mono muted">{{ sub.secondary_color }}</span></div></div>
          </template>
        </div>
      </div>

      <div class="section" v-if="hasVideo">
        <div class="section-title"><icon name="square-dashed"></icon>Che phụ đề gốc / chữ trên hình</div>
        <div class="row wrap">
          <span class="muted small grow">Kéo trên hình để thêm vùng che. Bấm vào một vùng để chỉnh hoặc xoá.</span>
          <button class="btn btn-sm" @click="useCurrentFrame"><icon name="image"></icon>Lấy khung hình đang xem</button>
          <button class="btn btn-sm" v-if="proj.ocr_region || (proj.hardsub && proj.hardsub.region)" @click="addDetected"><icon name="scan-text"></icon>Thêm vùng phụ đề đã phát hiện</button>
        </div>
        <region-editor v-model="st.cover" v-model:selected="sel" :frame-url="frameUrl" :label="regionLabel"></region-editor>
        <div class="form-grid" v-if="region">
          <div class="field">
            <label>Cách che vùng đang chọn</label>
            <div class="seg">
              <button :class="{ on: region.mode !== 'box' }" @click="region.mode = 'blur'">Làm mờ</button>
              <button :class="{ on: region.mode === 'box' }" @click="region.mode = 'box'; region.color = region.color || '#000000'; region.opacity = region.opacity ?? 100">Che màu</button>
            </div>
          </div>
          <slider v-if="region.mode !== 'box'" label="Độ mờ" :model-value="region.strength ?? 60" @update:model-value="region.strength = $event" :min="20" :max="100" :step="5"></slider>
          <template v-else>
            <div class="field"><label>Màu che</label><div class="row"><input type="color" v-model="region.color"><span class="mono muted">{{ region.color }}</span></div></div>
            <slider label="Độ đậm" :model-value="region.opacity ?? 100" @update:model-value="region.opacity = $event" :min="20" :max="100" :step="5" unit="%"></slider>
          </template>
          <div class="field full row wrap">
            <button class="btn btn-sm" :disabled="!sub.burn" @click="alignToRegion"><icon name="corner-down-right"></icon>Căn phụ đề Việt vào giữa vùng này</button>
            <button class="btn btn-sm btn-danger" @click="removeRegion"><icon name="trash-2"></icon>Xoá vùng này</button>
          </div>
        </div>
        <div class="form-grid">
          <div class="field">
            <label>Thời điểm che</label>
            <select v-model="st.cover_when">
              <option value="auto">Tự động</option>
              <option value="subtitle">Chỉ lúc có câu thoại</option>
              <option value="always">Suốt video</option>
            </select>
            <div class="hint">Tự động: nếu lời thoại lấy từ phụ đề cứng thì chỉ che đúng lúc phụ đề gốc hiện ra, còn lại che suốt video.</div>
          </div>
          <div class="field"><label>&nbsp;</label>
            <toggle v-model="st.auto_cover" label="Tự che phụ đề gốc" hint="Khi đọc được phụ đề cứng mà chưa có vùng che nào"></toggle></div>
        </div>
      </div>

      <div class="section" v-if="hasVideo">
        <div class="section-title"><icon name="image"></icon>Logo / hình mờ</div>
        <input ref="logo" type="file" class="hidden" accept=".png,.jpg,.jpeg,.webp" @change="onLogo">
        <div class="row wrap">
          <button class="btn" @click="pickLogo"><icon name="upload"></icon>{{ logo.file ? 'Đổi logo' : 'Tải logo lên' }}</button>
          <toggle v-if="logo.file" v-model="logo.enabled" label="Hiện logo trên video"></toggle>
          <span class="muted small" v-else>Nên dùng ảnh PNG nền trong suốt.</span>
        </div>
        <div class="form-grid" v-if="logo.file && logo.enabled">
          <div class="field">
            <label>Vị trí</label>
            <select v-model="logo.position">
              <option value="top-left">Góc trên trái</option><option value="top-right">Góc trên phải</option>
              <option value="bottom-left">Góc dưới trái</option><option value="bottom-right">Góc dưới phải</option>
            </select>
          </div>
          <slider label="Kích thước" v-model="logo.scale" :min="4" :max="40" unit="% chiều rộng"></slider>
          <slider label="Độ đậm" v-model="logo.opacity" :min="10" :max="100" :step="5" unit="%"></slider>
          <slider label="Cách mép" v-model="logo.margin" :min="0" :max="12" :step="0.5" unit="%"></slider>
        </div>
      </div>

      <modal v-if="preview" title="Khung hình xuất thử" icon="eye" wide @close="closePreview">
        <img :src="preview" alt="Khung hình xem thử" style="width: 100%; border-radius: 8px; display: block">
        <p class="muted small" style="margin-top: 10px">Đây là khung hình dựng thật bằng đúng bộ xử lý sẽ xuất video (phụ đề, vùng che, logo). Nếu vị trí đang xem không có câu thoại, một câu mẫu được dùng để bạn thấy kiểu chữ.</p>
      </modal>
    </div>`,
};

// ------------------------------------------------------------------ Xuất & tải về
const FILE_INFO = {
  video: { icon: "film", label: "Video đã dịch", desc: "MP4 (H.264 + AAC)" },
  dub_audio: { icon: "audio-lines", label: "Rãnh tiếng lồng", desc: "Chỉ giọng đọc tiếng Việt (M4A)" },
  srt_vi: { icon: "captions", label: "Phụ đề tiếng Việt", desc: "SRT" },
  srt_bilingual: { icon: "captions", label: "Phụ đề song ngữ", desc: "SRT" },
  srt_source: { icon: "captions", label: "Phụ đề lời gốc", desc: "SRT" },
};

export const ExportPanel = {
  ...base,
  name: "ExportPanel",
  props: { proj: Object, st: Object, busy: Boolean },
  emits: ["run"],
  data: () => ({ store }),
  computed: {
    out() { return this.st.output; },
    hasVideo() { return !!(this.proj.media && this.proj.media.has_video); },
    files() {
      const o = this.proj.outputs || {};
      return ["video", "dub_audio", "srt_vi", "srt_bilingual", "srt_source"].filter((k) => o[k]).map((k) => ({ key: k, name: o[k], ...FILE_INFO[k] }));
    },
    info() { return (this.proj.steps.render && this.proj.steps.render.info) || {}; },
    renderState() { return this.proj.steps.render ? this.proj.steps.render.status : "pending"; },
    needDub() {
      const d = this.proj.steps.dub;
      return this.st.dub.enabled && (!d || d.status !== "done");
    },
    videoUrl() { const v = (this.proj.outputs || {}).video; return v ? `/api/projects/${this.proj.id}/files/${encodeURIComponent(v)}?inline=1&v=${encodeURIComponent(this.proj.updated_at)}` : ""; },
    encoderNote() {
      const e = this.info.encoder;
      if (!e) return "";
      if (e === "copy") return "Lần xuất gần nhất chép nguyên hình ảnh gốc (không mã hoá lại).";
      return `Lần xuất gần nhất: ${e === "libx264" ? "mã hoá bằng CPU" : "mã hoá bằng card đồ hoạ (" + e + ")"}, ${this.info.width}×${this.info.height}, ${fmtBytes(this.info.size)}.`;
    },
  },
  methods: {
    href(f) { return `/api/projects/${this.proj.id}/files/${encodeURIComponent(f.name)}?v=${encodeURIComponent(this.proj.updated_at)}`; },
    go() { this.$emit("run", this.needDub ? ["dub", "render"] : ["render"]); },
  },
  template: `
    <div class="panel-body">
      <div class="section" v-if="hasVideo">
        <div class="section-title"><icon name="sliders-horizontal"></icon>Thiết lập xuất video</div>
        <div class="form-grid">
          <div class="field">
            <label>Độ phân giải</label>
            <select v-model="out.resolution">
              <option value="source">Giữ nguyên như video gốc</option>
              <option value="2160">Tối đa 4K (2160p)</option><option value="1440">Tối đa 2K (1440p)</option>
              <option value="1080">Tối đa Full HD (1080p)</option><option value="720">Tối đa HD (720p)</option><option value="480">Tối đa 480p</option>
            </select>
            <div class="hint">Chỉ thu nhỏ, không phóng to video.</div>
          </div>
          <div class="field">
            <label>Chất lượng hình</label>
            <div class="seg">
              <button :class="{ on: out.quality === 'high' }" @click="out.quality = 'high'">Cao</button>
              <button :class="{ on: out.quality === 'medium' }" @click="out.quality = 'medium'">Cân bằng</button>
              <button :class="{ on: out.quality === 'small' }" @click="out.quality = 'small'">Tệp nhỏ</button>
            </div>
            <div class="hint">Cao cho tệp lớn hơn rõ rệt; Cân bằng hợp với đa số video.</div>
          </div>
          <div class="field">
            <label>Tốc độ mã hoá</label>
            <div class="seg">
              <button :class="{ on: out.speed === 'fast' }" @click="out.speed = 'fast'">Nhanh</button>
              <button :class="{ on: out.speed === 'medium' }" @click="out.speed = 'medium'">Vừa</button>
              <button :class="{ on: out.speed === 'slow' }" @click="out.speed = 'slow'">Kỹ</button>
            </div>
            <div class="hint">Mã hoá kỹ cho tệp nhỏ hơn ở cùng chất lượng nhưng lâu hơn.</div>
          </div>
          <div class="field">
            <label>Bộ mã hoá</label>
            <select v-model="out.encoder">
              <option value="auto">Tự động (dùng card đồ hoạ nếu chạy được)</option>
              <option value="cpu">Chỉ dùng CPU</option>
              <option value="nvenc">NVIDIA (NVENC)</option><option value="qsv">Intel (Quick Sync)</option>
              <option value="amf">AMD (AMF)</option><option value="videotoolbox">Apple (VideoToolbox)</option>
            </select>
            <div class="hint">Nếu bộ mã hoá đã chọn không chạy được trên máy, ứng dụng tự chuyển về CPU.</div>
          </div>
        </div>
        <toggle v-model="out.soft_subs" label="Kèm phụ đề mềm trong tệp MP4" hint="Người xem bật/tắt được trong trình phát (ngoài phụ đề gắn cứng)"></toggle>
      </div>

      <div class="section">
        <div class="row wrap">
          <button class="btn btn-primary btn-lg" :disabled="busy || !proj.counts.translated" @click="go">
            <icon name="clapperboard" :size="18"></icon>{{ hasVideo ? (renderState === 'done' ? 'Xuất lại video' : 'Xuất video') : 'Xuất kết quả' }}</button>
          <span class="muted small" v-if="!proj.counts.translated">Cần có bản dịch trước khi xuất.</span>
          <span class="muted small" v-else-if="needDub">Sẽ tạo lồng tiếng trước rồi xuất video.</span>
          <span class="badge warn" v-else-if="renderState === 'stale'">Phụ đề hoặc thiết lập đã đổi — nên xuất lại</span>
        </div>
        <div class="muted small" v-if="encoderNote">{{ encoderNote }}</div>
      </div>

      <div class="section">
        <div class="section-title"><icon name="download"></icon>Tệp kết quả</div>
        <div v-if="!files.length" class="muted">Chưa có tệp nào. Kết quả sẽ hiện ở đây sau khi xuất.</div>
        <template v-else>
          <video v-if="videoUrl" :key="videoUrl" :src="videoUrl" controls preload="metadata" style="width: 100%; max-height: 420px; background: #000; border-radius: 10px"></video>
          <div>
            <div v-for="f in files" :key="f.key" class="file-row">
              <div class="file-ico"><icon :name="f.icon" :size="18"></icon></div>
              <div class="grow"><div style="font-weight: 600">{{ f.label }}</div><div class="muted small truncate">{{ f.name }} · {{ f.desc }}</div></div>
              <a class="btn btn-sm" :href="href(f)" download><icon name="download"></icon>Tải về</a>
            </div>
          </div>
        </template>
      </div>
    </div>`,
};

// ------------------------------------------------------------------ Nhật ký
export const LogPanel = {
  ...base,
  name: "LogPanel",
  props: { proj: Object, busy: Boolean },
  data: () => ({ log: "", loading: false, timer: null }),
  created() { this.load(); this.timer = setInterval(() => { if (this.busy) this.load(true); }, 2500); },
  unmounted() { clearInterval(this.timer); },
  methods: {
    async load(quiet) {
      if (!quiet) this.loading = true;
      try {
        this.log = (await api.get(`/api/projects/${this.proj.id}/log`)).log;
        this.$nextTick(() => { const el = this.$refs.box; if (el) el.scrollTop = el.scrollHeight; });
      } catch (e) { if (!quiet) toastError(e); } finally { this.loading = false; }
    },
  },
  template: `
    <div class="panel-body">
      <div class="row" style="margin-bottom: 10px">
        <span class="muted small grow">Ghi lại từng bước xử lý của dự án. Khi cần hỗ trợ, hãy gửi kèm nội dung này.</span>
        <button class="btn btn-sm" @click="load()"><icon :name="loading ? 'loader-circle' : 'refresh-cw'" :spin="loading"></icon>Làm mới</button>
      </div>
      <div class="log" ref="box">{{ log || 'Chưa có gì.' }}</div>
    </div>`,
};
