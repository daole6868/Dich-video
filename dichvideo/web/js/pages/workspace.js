// Không gian làm việc của một dự án: trình phát bên trái, các thẻ chức năng bên phải.
import { api } from "../api.js";
import { commonComponents, confirmDialog, loadSystem, store, toast, toastError } from "../common.js";
import { Player } from "../components/player.js";
import { SubtitleEditor } from "../components/editor.js";
import { DubPanel, ExportPanel, LogPanel, RecognizePanel, VisualPanel } from "../components/panels.js";
import { STEPS, STEP_NAMES, STATUS_NAMES, clone, debounce, fmtDuration, projectState, same } from "../util.js";

const TABS = [
  { id: "subs", icon: "captions", label: "Phụ đề" },
  { id: "recognize", icon: "languages", label: "Nhận dạng & Dịch" },
  { id: "dub", icon: "mic", label: "Lồng tiếng" },
  { id: "visual", icon: "palette", label: "Hình ảnh" },
  { id: "export", icon: "download", label: "Xuất" },
  { id: "log", icon: "file-text", label: "Nhật ký" },
];
const STEP_TAB = { prepare: "log", transcribe: "recognize", translate: "recognize", dub: "dub", render: "export" };
const COVER_PAD = 0.3, COVER_MERGE = 0.6;

export const WorkspacePage = {
  name: "WorkspacePage",
  components: { ...commonComponents, Player, SubtitleEditor, RecognizePanel, DubPanel, VisualPanel, ExportPanel, LogPanel },
  props: { projectId: String, initialTab: String },
  data() {
    return {
      store, TABS, STEPS, STEP_NAMES, STATUS_NAMES, STEP_TAB,
      proj: null, st: null, segs: [], error: "", tab: TABS.some((t) => t.id === this.initialTab) ? this.initialTab : "subs",
      time: 0, name: "", timer: null, settingsState: "saved",
      voices: [], voicesFor: "", voicesLoading: false, voicesError: "",
    };
  },
  computed: {
    busy() { return !!(this.proj && this.proj.busy); },
    waiting() { return !!(this.proj && (!this.proj.source.ready || this.proj.downloading)); },
    state() { return projectState({ ...this.proj, mode: { dub: this.proj.settings.dub.enabled } }); },
    running() { return STEPS.find((s) => this.proj.steps[s].status === "running") || null; },
    failed() { return STEPS.find((s) => this.proj.steps[s].status === "error") || null; },
    review() {
      const s = this.proj.steps;
      return !this.busy && s.translate.status === "done" && ["pending", "stale"].includes(s.render.status)
        && (s.dub.status === "pending" || !this.proj.settings.dub.enabled) && !this.failed;
    },
    allDone() { return this.state.key === "done"; },
    download() { return this.proj.download || null; },
    primary() {
      if (this.busy) return { label: "Dừng", icon: "square", cls: "btn-danger", act: "cancel" };
      if (this.waiting) return null;
      if (this.failed) return { label: "Thử lại", icon: "rotate-ccw", cls: "btn-primary", act: "auto" };
      if (this.allDone) return { label: "Tải kết quả", icon: "download", cls: "btn-primary", act: "export" };
      if (this.state.key === "new") return { label: "Bắt đầu xử lý", icon: "play", cls: "btn-primary", act: "auto" };
      return { label: "Chạy tiếp các bước còn lại", icon: "play", cls: "btn-primary", act: "auto" };
    },
    // Các khoảng thời gian vùng che được bật (giống cách máy chủ tính khi xuất video).
    coverSpans() {
      const src = (this.proj.steps.transcribe.info || {}).source;
      const when = this.st.cover_when;
      const timed = when === "subtitle" || (when === "auto" && src === "ocr");
      if (!timed) return null;
      const spans = [];
      for (const s of this.segs) {
        const a = Math.max(0, s.start - COVER_PAD), b = s.end + COVER_PAD;
        const last = spans[spans.length - 1];
        if (last && a - last[1] <= COVER_MERGE) last[1] = Math.max(last[1], b); else spans.push([a, b]);
      }
      return spans;
    },
  },
  watch: {
    st: { deep: true, handler() { if (this.proj && !same(this.st, this.proj.settings)) { this.settingsState = "dirty"; this.saveSettingsSoon(); } } },
    tab(t) { if (location.hash !== `#/p/${this.projectId}/${t}`) history.replaceState(null, "", `#/p/${this.projectId}/${t}`); },
    // Người dùng bấm Lùi/Tới của trình duyệt hoặc mở liên kết có sẵn tên thẻ.
    initialTab(t) { if (TABS.some((x) => x.id === t)) this.tab = t; },
    "st.dub.engine"() { this.loadVoices(); },
  },
  async created() {
    this.saveSettingsSoon = debounce(() => this.saveSettings(), 700);
    this._key = (e) => this.onKey(e);
    window.addEventListener("keydown", this._key);
    await this.load();
  },
  beforeUnmount() {
    clearTimeout(this.timer);
    window.removeEventListener("keydown", this._key);
    if (this.settingsState === "dirty") this.saveSettings();
  },
  methods: {
    fmtDuration,
    async load() {
      try {
        const [proj, segs] = await Promise.all([
          api.get(`/api/projects/${this.projectId}`), api.get(`/api/projects/${this.projectId}/segments`)]);
        this.proj = proj;
        this.st = clone(proj.settings);
        this.segs = segs.segments;
        this.name = proj.name;
        this.loadVoices();
        this.schedule();
      } catch (e) { this.error = e.message || String(e); }
    },
    schedule() {
      clearTimeout(this.timer);
      if (!this.proj) return;
      const active = this.busy || this.waiting;
      this.timer = setTimeout(() => this.poll(), active ? 1000 : 6000);
    },
    async poll() {
      try {
        const before = this.proj;
        const proj = await api.get(`/api/projects/${this.projectId}`);
        const changed = STEPS.some((s) => before.steps[s].status !== proj.steps[s].status) || before.busy !== proj.busy;
        const settingsClean = same(this.st, before.settings);
        this.proj = proj;
        if (changed) {
          // Một bước vừa xong: nạp lại câu phụ đề và cài đặt (máy chủ có thể đã tự thêm vùng che).
          const segs = await api.get(`/api/projects/${this.projectId}/segments`);
          this.segs = segs.segments;
          if (settingsClean) this.st = clone(proj.settings);
          if (before.busy && !proj.busy) this.finished(proj);
        }
      } catch (e) {
        if (e.status === 404) { this.error = "Dự án không còn tồn tại."; return; }
      }
      this.schedule();
    },
    finished(proj) {
      const st = projectState({ ...proj, mode: { dub: proj.settings.dub.enabled } });
      if (st.key === "done") { toast("Hoàn tất! Video đã dịch sẵn sàng để tải về.", "ok", 7000); this.tab = "export"; loadSystem().catch(() => {}); }
      else if (st.key === "error") toast(proj.steps[st.step].error || "Có lỗi khi xử lý.", "err");
    },
    async saveSettings() {
      this.saveSettingsSoon.cancel();
      if (!this.proj || same(this.st, this.proj.settings)) { this.settingsState = "saved"; return true; }
      const sent = clone(this.st);
      this.settingsState = "saving";
      try {
        const proj = await api.patch(`/api/projects/${this.projectId}`, { settings: sent });
        this.proj = proj;
        // Nếu người dùng chưa sửa thêm gì trong lúc chờ thì đồng bộ theo bản máy chủ đã chuẩn hoá.
        if (same(this.st, sent)) this.st = clone(proj.settings);
        this.settingsState = same(this.st, proj.settings) ? "saved" : "dirty";
        if (this.settingsState === "dirty") this.saveSettingsSoon();
        return true;
      } catch (e) { this.settingsState = "error"; toastError(e); return false; }
    },
    async run(steps) {
      if (!(await this.saveSettings())) return;
      const ed = this.$refs.editor;
      if (ed && !(await ed.flush())) return;
      try {
        this.proj = await api.post(`/api/projects/${this.projectId}/run`, steps ? { steps } : {});
        this.schedule();
      } catch (e) { toastError(e); }
    },
    async cancel() {
      const ok = await confirmDialog({ title: "Dừng xử lý?", okText: "Dừng", danger: true,
        message: "Bước đang chạy sẽ bị huỷ. Các bước đã xong vẫn được giữ lại, bạn có thể chạy tiếp sau." });
      if (!ok) return;
      try { const r = await api.post(`/api/projects/${this.projectId}/cancel`); this.proj = r.project; this.schedule(); } catch (e) { toastError(e); }
    },
    act() {
      const a = this.primary && this.primary.act;
      if (a === "cancel") this.cancel();
      else if (a === "export") this.tab = "export";
      else if (a === "auto") this.run(null);
    },
    async rename() {
      const name = this.name.trim();
      if (!name || name === this.proj.name) { this.name = this.proj.name; return; }
      try { this.proj = await api.patch(`/api/projects/${this.projectId}`, { name }); this.name = this.proj.name; } catch (e) { toastError(e); }
    },
    async loadVoices() {
      const engine = this.st.dub.engine;
      this.voicesFor = engine;
      this.voicesLoading = true;
      this.voicesError = "";
      try {
        const r = await api.get(`/api/voices?engine=${engine}`);
        if (this.voicesFor === engine) this.voices = r.voices;
      } catch (e) { if (this.voicesFor === engine) { this.voices = []; this.voicesError = e.message; } }
      finally { if (this.voicesFor === engine) this.voicesLoading = false; }
    },
    onSaved(res) { if (res.project) this.proj = res.project; if (res.segments) this.segs = res.segments; },
    async reloadProject() { try { this.proj = await api.get(`/api/projects/${this.projectId}`); this.st = clone(this.proj.settings); } catch (e) { toastError(e); } },
    seek(t) { this.$refs.player && this.$refs.player.seek(t); },
    playRange(a, b) { this.$refs.player && this.$refs.player.playRange(a, b); },
    coverActive(t) { const spans = this.coverSpans; return !spans || spans.some(([a, b]) => t >= a && t <= b); },
    onKey(e) {
      const tag = (e.target.tagName || "").toLowerCase();
      if (["input", "textarea", "select", "button"].includes(tag) || e.target.isContentEditable) return;
      if (e.code === "Space" && this.$refs.player) { e.preventDefault(); this.$refs.player.toggle(); }
    },
    stepClass(s) {
      if (s === "dub" && !this.proj.settings.dub.enabled) return "skipped";
      return this.proj.steps[s].status;
    },
    stepTitle(s) {
      const st = this.proj.steps[s];
      if (s === "dub" && !this.proj.settings.dub.enabled) return "Đã tắt lồng tiếng";
      return STATUS_NAMES[st.status] + (st.error ? ": " + st.error : st.info && st.info.seconds ? ` (${st.info.seconds} giây)` : "");
    },
  },
  template: `
    <div v-if="error" class="page"><div class="note err"><icon name="circle-alert"></icon><div>{{ error }}<br><a href="#/">← Về danh sách dự án</a></div></div></div>
    <div v-else-if="!proj" class="page"><div class="empty"><icon name="loader-circle" :size="28" spin></icon><div>Đang mở dự án…</div></div></div>
    <div v-else>
      <div class="ws-top">
        <a class="btn btn-ghost btn-icon" href="#/" title="Về danh sách dự án"><icon name="arrow-left" :size="18"></icon></a>
        <input class="ws-name" v-model="name" @blur="rename" @keydown.enter="$event.target.blur()" aria-label="Tên dự án" :size="Math.max(12, Math.min(40, name.length + 2))">
        <div class="stepper">
          <template v-for="(s, i) in STEPS" :key="s">
            <span class="step-sep" v-if="i"></span>
            <button class="step" :class="stepClass(s)" :title="stepTitle(s)" @click="tab = STEP_TAB[s]" style="cursor: pointer">
              <span class="num">
                <icon v-if="proj.steps[s].status === 'done'" name="check" :size="13"></icon>
                <icon v-else-if="proj.steps[s].status === 'running'" name="loader-circle" :size="13" spin></icon>
                <icon v-else-if="proj.steps[s].status === 'error'" name="x" :size="13"></icon>
                <template v-else>{{ i + 1 }}</template>
              </span>{{ STEP_NAMES[s] }}
            </button>
          </template>
        </div>
        <span class="spacer"></span>
        <span class="muted small" v-if="settingsState !== 'saved'">{{ settingsState === 'saving' ? 'Đang lưu thiết lập…' : settingsState === 'error' ? 'Chưa lưu được thiết lập' : '' }}</span>
        <button v-if="primary" class="btn" :class="primary.cls" @click="act"><icon :name="primary.icon"></icon>{{ primary.label }}</button>
      </div>

      <div class="ws-status" v-if="waiting">
        <icon name="loader-circle" spin></icon>
        <span v-if="download && download.status === 'error'" style="color: var(--danger)">{{ download.message }}</span>
        <template v-else>
          <span>{{ download ? download.message : 'Đang nhận video…' }}</span>
          <div class="progress" :class="{ indet: !download || !download.progress }"><i :style="{ width: ((download && download.progress) || 0) * 100 + '%' }"></i></div>
        </template>
      </div>
      <div class="ws-status" v-else-if="running">
        <icon name="loader-circle" spin></icon>
        <b>{{ STEP_NAMES[running] }}</b>
        <span class="grow truncate">{{ proj.steps[running].message }}</span>
        <div class="progress" :class="{ indet: !proj.steps[running].progress }"><i :style="{ width: proj.steps[running].progress * 100 + '%' }"></i></div>
        <span class="mono">{{ Math.round(proj.steps[running].progress * 100) }}%</span>
      </div>
      <div class="ws-status" v-else-if="busy"><icon name="hourglass"></icon><span>Đang chờ đến lượt xử lý (một dự án khác đang chạy)…</span></div>
      <div class="ws-status err" v-else-if="failed">
        <icon name="circle-alert" style="color: var(--danger)"></icon>
        <span class="grow" style="white-space: pre-line"><b>Lỗi ở bước {{ STEP_NAMES[failed] }}:</b> {{ proj.steps[failed].error }}</span>
      </div>
      <div class="ws-status warn" v-else-if="review">
        <icon name="eye" style="color: var(--warn)"></icon>
        <span class="grow">Đã dịch xong {{ proj.counts.translated }}/{{ proj.counts.segments }} câu. Hãy xem lại phụ đề, sửa nếu cần, rồi bấm <b>Chạy tiếp các bước còn lại</b>.</span>
      </div>
      <div class="ws-status ok" v-else-if="allDone">
        <icon name="circle-check" style="color: var(--ok)"></icon>
        <span class="grow">Hoàn tất. Video đã dịch nằm ở thẻ <a href="javascript:void 0" @click="tab = 'export'">Xuất</a>.</span>
      </div>
      <div class="ws-status warn" v-else-if="state.key === 'stale'">
        <icon name="triangle-alert" style="color: var(--warn)"></icon>
        <span class="grow">Phụ đề hoặc thiết lập đã thay đổi sau lần xuất gần nhất. Bấm <b>Chạy tiếp các bước còn lại</b> để cập nhật video.</span>
      </div>

      <div class="ws-body">
        <div class="ws-left">
          <player ref="player" :project-id="proj.id" :media="proj.media.duration ? proj.media : { duration: 0, has_video: true, width: 16, height: 9 }"
                  :segments="segs" :settings="st" :version="proj.steps.prepare.info.seconds || proj.created_at" :cover-active="coverActive" @time="time = $event"></player>
          <div class="card card-pad small" v-if="proj.media.duration">
            <div class="row wrap" style="gap: 6px 14px; color: var(--text-2)">
              <span><icon name="clock" :size="14"></icon> {{ fmtDuration(proj.media.duration) }}</span>
              <span v-if="proj.media.has_video"><icon name="monitor-play" :size="14"></icon> {{ proj.media.width }}×{{ proj.media.height }} · {{ proj.media.fps }} hình/giây</span>
              <span><icon name="captions" :size="14"></icon> {{ proj.counts.segments }} câu · đã dịch {{ proj.counts.translated }}</span>
              <span class="muted truncate" :title="proj.source.original_name">{{ proj.source.original_name }}</span>
            </div>
          </div>
        </div>

        <div class="card panel">
          <div class="tabs" style="padding: 0 8px">
            <button v-for="t in TABS" :key="t.id" class="tab" :class="{ on: tab === t.id }" @click="tab = t.id">
              <icon :name="t.icon"></icon>{{ t.label }}<span class="count" v-if="t.id === 'subs' && proj.counts.segments">{{ proj.counts.segments }}</span>
            </button>
          </div>
          <subtitle-editor v-show="tab === 'subs'" ref="editor" :project-id="proj.id" :segments="segs" :busy="busy" :time="time"
                           :voices="voices" :default-voice="st.dub.voice" :max-speed="st.dub.max_speed" :project-name="proj.name"
                           @seek="seek" @play-range="playRange" @saved="onSaved" @run-translate="run(['translate'])"></subtitle-editor>
          <recognize-panel v-if="tab === 'recognize'" :proj="proj" :st="st" :busy="busy" :time="time" @run="run"></recognize-panel>
          <dub-panel v-if="tab === 'dub'" :proj="proj" :st="st" :busy="busy" :voices="voices" :voices-loading="voicesLoading" :voices-error="voicesError"
                     @run="run" @reload-voices="loadVoices"></dub-panel>
          <visual-panel v-if="tab === 'visual'" :proj="proj" :st="st" :busy="busy" :time="time" @reload="reloadProject"></visual-panel>
          <export-panel v-if="tab === 'export'" :proj="proj" :st="st" :busy="busy" @run="run"></export-panel>
          <log-panel v-if="tab === 'log'" :proj="proj" :busy="busy"></log-panel>
        </div>
      </div>
    </div>`,
};
