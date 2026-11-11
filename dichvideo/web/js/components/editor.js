// Trình sửa phụ đề: sửa lời gốc/bản dịch/mốc thời gian, gộp-tách câu, dịch lại, nghe thử, tự lưu.
import { api } from "../api.js";
import { commonComponents, confirmDialog, toast, toastError } from "../common.js";
import { clone, debounce, downloadBlob, fmtTime, parseTime, textLen } from "../util.js";

const PAGE = 100;
let keySeq = 0;
const withKey = (s) => ({ ...s, _k: ++keySeq });
const strip = (s) => { const { _k, ...rest } = s; return rest; };
const hasContent = (s) => !!((s.text || "").trim() || (s.translation || "").trim());

// Tự giãn chiều cao ô nhập theo nội dung.
const autogrow = {
  mounted(el) { autogrow.fit(el); },
  updated(el) { autogrow.fit(el); },
  fit(el) { el.style.height = "auto"; el.style.height = Math.max(34, el.scrollHeight + 2) + "px"; },
};

export const SubtitleEditor = {
  name: "SubtitleEditor",
  components: commonComponents,
  directives: { autogrow },
  props: {
    projectId: { type: String, required: true },
    segments: { type: Array, required: true },
    busy: Boolean,
    time: { type: Number, default: 0 },
    voices: { type: Array, default: () => [] },
    defaultVoice: { type: String, default: "" },
    maxSpeed: { type: Number, default: 1.5 },
    projectName: { type: String, default: "phu-de" },
  },
  emits: ["seek", "play-range", "saved", "run-translate"],
  data() {
    return {
      rows: this.segments.map(withKey), page: 0, filter: "", follow: true, state: "saved", rev: 0,
      undo: [], redo: [], menu: null, working: {}, find: null, shift: null, exportOpen: false, audio: null,
      fmtTime,
    };
  },
  computed: {
    filtered() {
      const q = this.filter.trim().toLowerCase();
      if (!q) return this.rows;
      return this.rows.filter((r) => (r.text + "\n" + r.translation).toLowerCase().includes(q));
    },
    pages() { return Math.max(1, Math.ceil(this.filtered.length / PAGE)); },
    shown() { return this.filtered.slice(this.page * PAGE, (this.page + 1) * PAGE); },
    activeKey() {
      const t = this.time;
      const r = this.rows.find((x) => t >= x.start && t <= x.end);
      return r ? r._k : null;
    },
    untranslated() { return this.rows.filter((r) => (r.text || "").trim() && !(r.translation || "").trim()).length; },
    warnings() { return this.rows.filter((r) => this.cps(r) > 22 || (r.dub && r.dub.speed > 1.3)).length; },
    locked() { return this.busy; },
    stateLabel() {
      return { saved: "Đã lưu", dirty: "Chưa lưu…", saving: "Đang lưu…", error: "Lưu thất bại" }[this.state];
    },
  },
  watch: {
    // Máy chủ vừa xử lý xong một bước: nạp lại danh sách câu (trừ khi người dùng đang sửa dở).
    segments(list) {
      if (this.state === "dirty" || this.state === "saving") return;
      this.rows = list.map(withKey);
      this.undo = []; this.redo = [];
      if (this.page >= this.pages) this.page = 0;
    },
    activeKey(k) {
      if (!this.follow || k === null || this.filter) return;
      const i = this.rows.findIndex((r) => r._k === k);
      if (i < 0) return;
      const p = Math.floor(i / PAGE);
      if (p !== this.page) this.page = p;
      this.$nextTick(() => {
        const el = this.$el.querySelector(`[data-k="${k}"]`);
        if (el && !this.$el.contains(document.activeElement)) el.scrollIntoView({ block: "nearest", behavior: "smooth" });
      });
    },
    filter() { this.page = 0; },
  },
  created() { this.saveSoon = debounce(() => this.save(), 1200); },
  beforeUnmount() { if (this.state === "dirty") this.save(); this.stopAudio(); },
  methods: {
    cps(r) { const d = Math.max(0.3, r.end - r.start); return textLen(r.translation) / d; },
    snapshot() {
      const snap = JSON.stringify(this.rows.map(strip));
      if (this.undo[this.undo.length - 1] !== snap) { this.undo.push(snap); if (this.undo.length > 60) this.undo.shift(); }
      this.redo = [];
    },
    restore(snap) { this.rows = JSON.parse(snap).map(withKey); this.touch(); },
    doUndo() { if (!this.undo.length) return; this.redo.push(JSON.stringify(this.rows.map(strip))); this.restore(this.undo.pop()); },
    doRedo() { if (!this.redo.length) return; this.undo.push(JSON.stringify(this.rows.map(strip))); this.restore(this.redo.pop()); },
    touch() {
      if (this.locked) return;
      this.rev++;
      this.state = "dirty";
      this.saveSoon();
    },
    edited(row) { delete row.dub; this.touch(); },
    async save() {
      if (this.locked) return false;
      this.saveSoon.cancel();
      const rev = this.rev;
      const sent = this.rows.filter(hasContent);
      this.state = "saving";
      try {
        const res = await api.put(`/api/projects/${this.projectId}/segments`, { segments: sent.map(strip) });
        if (res.segments.length === sent.length) {
          // Chỉ cập nhật số thứ tự để không làm mất con trỏ trong ô đang gõ.
          sent.forEach((row, i) => { row.id = res.segments[i].id; });
        } else {
          this.rows = res.segments.map(withKey);
        }
        this.state = this.rev === rev ? "saved" : "dirty";
        if (this.state === "dirty") this.saveSoon();
        this.$emit("saved", res);
        return true;
      } catch (e) {
        this.state = "error";
        toastError(e);
        return false;
      }
    },
    async flush() { return this.state === "saved" ? true : this.save(); },
    setTime(row, field, value) {
      const t = parseTime(value);
      if (t === null) { toast("Mốc thời gian không hợp lệ. Ví dụ: 01:23.450", "err"); this.$forceUpdate(); return; }
      this.snapshot();
      row[field] = t;
      if (row.end < row.start + 0.1) { if (field === "start") row.end = row.start + 0.5; else row.start = Math.max(0, row.end - 0.5); }
      this.rows.sort((a, b) => a.start - b.start || a.end - b.end);
      this.edited(row);
    },
    index(row) { return this.rows.indexOf(row); },
    insertAfter(row) {
      this.snapshot();
      const i = this.index(row), next = this.rows[i + 1];
      const start = row.end + 0.05;
      const end = next ? Math.max(start + 0.3, Math.min(next.start - 0.05, start + 2)) : start + 2;
      const fresh = withKey({ id: 0, start: Math.round(start * 1000) / 1000, end: Math.round(end * 1000) / 1000, text: "", translation: "" });
      this.rows.splice(i + 1, 0, fresh);
      this.menu = null;
      this.$nextTick(() => { const el = this.$el.querySelector(`[data-k="${fresh._k}"] textarea.vi`); if (el) el.focus(); });
    },
    remove(row) { this.snapshot(); this.rows.splice(this.index(row), 1); this.menu = null; this.touch(); },
    mergeNext(row) {
      const i = this.index(row), next = this.rows[i + 1];
      if (!next) return;
      this.snapshot();
      const joinZh = /[㐀-鿿]/.test(row.text + next.text) ? "，" : " ";
      row.text = [row.text, next.text].filter(Boolean).join(joinZh);
      row.translation = [row.translation, next.translation].filter(Boolean).join(" ");
      row.end = Math.max(row.end, next.end);
      this.rows.splice(i + 1, 1);
      this.menu = null;
      this.edited(row);
    },
    split(row) {
      const vi = (row.translation || "").trim(), zh = (row.text || "").trim();
      if (textLen(vi) < 2 && textLen(zh) < 2) { toast("Câu quá ngắn, không tách được.", "err"); return; }
      this.snapshot();
      // Tách bản dịch tại khoảng trắng gần giữa nhất; lời gốc tách theo cùng tỉ lệ.
      let cut = Math.floor(vi.length / 2);
      const spaces = [...vi.matchAll(/\s+/g)].map((m) => m.index);
      if (spaces.length) cut = spaces.reduce((best, p) => (Math.abs(p - vi.length / 2) < Math.abs(best - vi.length / 2) ? p : best), spaces[0]);
      const ratio = vi.length ? cut / vi.length : 0.5;
      let zcut = Math.round(zh.length * ratio);
      const punct = [...zh.matchAll(/[，,、；;：:。！？!?\s]/g)].map((m) => m.index + 1);
      if (punct.length) zcut = punct.reduce((best, p) => (Math.abs(p - zh.length * ratio) < Math.abs(best - zh.length * ratio) ? p : best), punct[0]);
      const mid = Math.round((row.start + (row.end - row.start) * ratio) * 1000) / 1000;
      const second = withKey({ id: 0, start: mid + 0.02, end: row.end, text: zh.slice(zcut).trim(), translation: vi.slice(cut).trim() });
      if (row.voice) second.voice = row.voice;
      row.text = zh.slice(0, zcut).trim().replace(/[，,、；;：:]$/, "");
      row.translation = vi.slice(0, cut).trim();
      row.end = mid;
      this.rows.splice(this.index(row) + 1, 0, second);
      this.menu = null;
      this.edited(row);
    },
    async retranslate(row) {
      if (!(row.text || "").trim()) { toast("Câu này không có lời gốc để dịch.", "err"); return; }
      this.menu = null;
      if (!(await this.flush())) return;
      this.working[row._k] = "tr";
      try {
        const res = await api.post(`/api/projects/${this.projectId}/segments/translate`, { ids: [row.id] });
        const got = res.segments.find((s) => s.id === row.id);
        if (got) { this.snapshot(); row.translation = got.translation; delete row.dub; }
        this.$emit("saved", res);
      } catch (e) { toastError(e); } finally { delete this.working[row._k]; }
    },
    async translateEmpty() {
      if (!(await this.flush())) return;
      this.working.all = true;
      try {
        const res = await api.post(`/api/projects/${this.projectId}/segments/translate`, { only_empty: true });
        this.rows = res.segments.map(withKey);
        this.$emit("saved", res);
        toast(`Đã dịch ${res.result.translated} câu` + (res.result.missing ? `, còn ${res.result.missing} câu trống.` : "."), "ok");
      } catch (e) { toastError(e); } finally { delete this.working.all; }
    },
    stopAudio() { if (this.audio) { this.audio.pause(); URL.revokeObjectURL(this.audio.src); this.audio = null; } },
    async listen(row) {
      this.menu = null;
      const text = (row.translation || "").trim();
      if (!text) { toast("Câu này chưa có bản dịch để đọc.", "err"); return; }
      this.stopAudio();
      this.working[row._k] = "tts";
      try {
        const blob = await api.blob("POST", `/api/projects/${this.projectId}/tts-line`, { text, voice: row.voice || "" });
        this.audio = new Audio(URL.createObjectURL(blob));
        this.audio.play().catch(() => {});
      } catch (e) { toastError(e); } finally { delete this.working[row._k]; }
    },
    setVoice(row, v) { this.snapshot(); if (v) row.voice = v; else delete row.voice; this.edited(row); },
    voiceName(id) { const v = this.voices.find((x) => x.id === id); return v ? v.name : id; },
    seek(row) { this.$emit("seek", row.start + 0.01); },
    play(row) { this.$emit("play-range", row.start, row.end); },
    focusNeighbor(e, row, dir) {
      const list = this.shown, i = list.indexOf(row) + dir;
      if (i < 0 || i >= list.length) return;
      const cls = e.target.classList.contains("zh") ? "zh" : "vi";
      const el = this.$el.querySelector(`[data-k="${list[i]._k}"] textarea.${cls}`);
      if (el) { e.preventDefault(); el.focus(); }
    },
    // ---- tìm & thay
    openFind() { this.find = { q: "", r: "", field: "translation", count: null }; },
    countFind() {
      const f = this.find;
      f.count = f.q ? this.rows.reduce((n, row) => n + ((row[f.field] || "").split(f.q).length - 1), 0) : null;
    },
    applyFind() {
      const f = this.find;
      if (!f.q) return;
      this.snapshot();
      let n = 0;
      for (const row of this.rows) {
        const before = row[f.field] || "";
        if (before.includes(f.q)) { n += before.split(f.q).length - 1; row[f.field] = before.split(f.q).join(f.r); delete row.dub; }
      }
      this.find = null;
      if (n) { this.touch(); toast(`Đã thay ${n} chỗ.`, "ok"); } else toast("Không tìm thấy chỗ nào để thay.");
    },
    // ---- dịch chuyển thời gian
    openShift() { this.shift = { ms: 0, from: "all" }; },
    applyShift() {
      const d = Number(this.shift.ms) / 1000;
      if (!d) { this.shift = null; return; }
      this.snapshot();
      const from = this.shift.from === "here" ? this.time : -1;
      for (const row of this.rows) {
        if (row.start >= from) { row.start = Math.max(0, Math.round((row.start + d) * 1000) / 1000); row.end = Math.max(row.start + 0.1, Math.round((row.end + d) * 1000) / 1000); delete row.dub; }
      }
      this.shift = null;
      this.touch();
    },
    // ---- nhập / xuất
    pickImport(kind) { this.importKind = kind; this.$refs.imp.click(); },
    async onImport(e) {
      const file = e.target.files[0];
      e.target.value = "";
      if (!file) return;
      const ok = await confirmDialog({
        title: "Nhập phụ đề từ tệp?",
        message: this.importKind === "translation"
          ? "Bản dịch trong tệp sẽ được điền vào các câu hiện có (nếu số câu khớp), hoặc thay toàn bộ danh sách câu."
          : "Toàn bộ câu hiện có sẽ bị thay bằng nội dung của tệp (coi là lời gốc, chưa dịch).",
        okText: "Nhập",
      });
      if (!ok) return;
      try {
        const res = await api.postRaw(`/api/projects/${this.projectId}/subtitles/import?kind=${this.importKind}&filename=${encodeURIComponent(file.name)}`, file);
        this.rows = res.segments.map(withKey);
        this.state = "saved";
        this.$emit("saved", res);
        toast(`Đã nhập ${res.segments.length} câu.`, "ok");
      } catch (err) { toastError(err); }
    },
    async exportAs(format, mode) {
      this.exportOpen = false;
      if (!(await this.flush())) return;
      try {
        const blob = await api.blob("GET", `/api/projects/${this.projectId}/subtitles/export?format=${format}&mode=${mode}`);
        const suffix = { vi: "vi", zh: "goc", bilingual: "songngu" }[mode];
        downloadBlob(blob, `${this.projectName}.${suffix}.${format}`);
      } catch (e) { toastError(e); }
    },
    async askRetranslateAll() {
      const ok = await confirmDialog({ title: "Dịch lại toàn bộ?", okText: "Dịch lại",
        message: "Toàn bộ bản dịch hiện tại (kể cả phần bạn đã sửa tay) sẽ bị thay bằng bản dịch mới." });
      if (ok && (await this.flush())) this.$emit("run-translate");
    },
    closeMenus() { this.menu = null; this.exportOpen = false; },
  },
  template: `
    <div @click="closeMenus">
      <div class="ed-tools">
        <input class="input" style="flex: 1 1 90px; min-width: 90px; max-width: 180px" v-model="filter" placeholder="Lọc nội dung…">
        <button class="btn btn-sm" :disabled="locked || !untranslated || working.all" @click="translateEmpty" title="Dịch những câu chưa có bản dịch">
          <icon :name="working.all ? 'loader-circle' : 'languages'" :spin="!!working.all"></icon>Dịch câu trống<span v-if="untranslated"> ({{ untranslated }})</span></button>
        <button class="btn btn-sm" :disabled="locked" @click="askRetranslateAll"><icon name="refresh-cw"></icon>Dịch lại tất cả</button>
        <div style="position: relative" @click.stop>
          <button class="btn btn-sm" @click="exportOpen = !exportOpen"><icon name="sliders-horizontal"></icon>Công cụ<icon name="chevron-down" :size="14"></icon></button>
          <div class="menu" v-if="exportOpen" style="right: auto; left: 0; top: 34px">
            <button :disabled="locked" @click="exportOpen = false; openFind()"><icon name="replace"></icon>Tìm & thay…</button>
            <button :disabled="locked" @click="exportOpen = false; openShift()"><icon name="timer"></icon>Dịch chuyển thời gian…</button>
            <hr>
            <div class="menu-label">Tải phụ đề về</div>
            <button @click="exportAs('srt', 'vi')"><icon name="file-text"></icon>SRT tiếng Việt</button>
            <button @click="exportAs('srt', 'bilingual')"><icon name="file-text"></icon>SRT song ngữ</button>
            <button @click="exportAs('srt', 'zh')"><icon name="file-text"></icon>SRT lời gốc</button>
            <button @click="exportAs('vtt', 'vi')"><icon name="file-text"></icon>VTT tiếng Việt</button>
            <button @click="exportAs('ass', 'vi')"><icon name="file-text"></icon>ASS (kèm kiểu chữ)</button>
            <button @click="exportAs('txt', 'vi')"><icon name="file-text"></icon>Văn bản thuần</button>
            <hr>
            <div class="menu-label">Nhập từ tệp (.srt, .vtt, .ass)</div>
            <button :disabled="locked" @click="pickImport('source')"><icon name="upload"></icon>Nhập lời gốc</button>
            <button :disabled="locked" @click="pickImport('translation')"><icon name="upload"></icon>Nhập bản dịch</button>
          </div>
        </div>
        <input ref="imp" type="file" class="hidden" accept=".srt,.vtt,.ass,.ssa,.txt" @change="onImport">
        <span class="spacer"></span>
        <button class="btn btn-sm btn-ghost btn-icon" :disabled="!undo.length || locked" @click="doUndo" title="Hoàn tác"><icon name="undo-2"></icon></button>
        <button class="btn btn-sm btn-ghost btn-icon" :disabled="!redo.length || locked" @click="doRedo" title="Làm lại"><icon name="redo-2"></icon></button>
        <span class="ed-save" :style="{ color: state === 'error' ? 'var(--danger)' : '' }">
          <icon :name="state === 'saving' ? 'loader-circle' : state === 'saved' ? 'check' : state === 'error' ? 'circle-alert' : 'pencil'" :spin="state === 'saving'" :size="14"></icon>{{ stateLabel }}</span>
      </div>

      <div class="note warn" v-if="locked" style="margin: 10px 14px 0"><icon name="hourglass"></icon><div>Dự án đang được xử lý nên tạm thời chưa sửa phụ đề được.</div></div>

      <div class="ed-head"><div>#</div><div>Thời gian</div><div>Lời gốc</div><div>Bản dịch tiếng Việt</div><div></div></div>
      <div v-if="!rows.length" class="empty">
        <icon name="captions" :size="36"></icon>
        <div>Chưa có câu phụ đề nào.</div>
        <div class="small" style="margin-top: 4px">Chạy bước Nhận dạng, hoặc nhập tệp phụ đề có sẵn từ nút "Nhập / xuất".</div>
      </div>
      <div v-for="row in shown" :key="row._k" class="ed-row" :class="{ active: row._k === activeKey }" :data-k="row._k">
        <div class="ed-idx" @click="seek(row)" title="Tới câu này">
          <span>{{ rows.indexOf(row) + 1 }}</span>
          <button class="btn btn-ghost btn-icon btn-sm" style="width: 24px; height: 24px" @click.stop="play(row)" title="Phát câu này"><icon name="play" :size="13"></icon></button>
        </div>
        <div class="ed-time">
          <input :value="fmtTime(row.start)" :disabled="locked" @change="setTime(row, 'start', $event.target.value)" aria-label="Bắt đầu">
          <input :value="fmtTime(row.end)" :disabled="locked" @change="setTime(row, 'end', $event.target.value)" aria-label="Kết thúc">
        </div>
        <div>
          <textarea class="zh" rows="1" v-autogrow v-model="row.text" :disabled="locked" lang="zh" placeholder="(không có lời gốc)"
                    @focus="snapshot" @input="edited(row)" @keydown.alt.down="focusNeighbor($event, row, 1)" @keydown.alt.up="focusNeighbor($event, row, -1)"></textarea>
        </div>
        <div>
          <textarea class="vi" rows="1" v-autogrow v-model="row.translation" :disabled="locked" placeholder="(chưa dịch)"
                    @focus="snapshot" @input="edited(row)" @keydown.ctrl.enter.prevent="play(row)"
                    @keydown.alt.down="focusNeighbor($event, row, 1)" @keydown.alt.up="focusNeighbor($event, row, -1)"></textarea>
          <div class="ed-meta">
            <span>{{ (row.end - row.start).toFixed(1) }}s</span>
            <span v-if="row.translation" :class="{ warn: cps(row) > 22 && cps(row) <= 28, bad: cps(row) > 28 }" title="Số ký tự mỗi giây. Trên 22 là khó đọc kịp.">{{ cps(row).toFixed(0) }} ký tự/s</span>
            <span v-if="row.dub && row.dub.speed > 1.05" :class="{ warn: row.dub.speed > 1.3 && row.dub.speed < maxSpeed - 0.01, bad: row.dub.speed >= maxSpeed - 0.01 }"
                  title="Giọng lồng tiếng phải đọc nhanh hơn bình thường để vừa khoảng trống. Hãy rút gọn câu dịch nếu quá nhanh.">đọc nhanh ×{{ row.dub.speed.toFixed(2) }}</span>
            <span v-if="row.voice" class="badge pri" style="height: 18px; font-size: 11px">{{ voiceName(row.voice) }}</span>
            <span v-if="working[row._k]"><icon name="loader-circle" :size="12" spin></icon> {{ working[row._k] === 'tts' ? 'đang tạo giọng…' : 'đang dịch…' }}</span>
          </div>
        </div>
        <div @click.stop>
          <button class="btn btn-ghost btn-icon btn-sm" @click="menu = menu === row._k ? null : row._k" title="Thao tác với câu này"><icon name="ellipsis-vertical"></icon></button>
          <div class="menu" v-if="menu === row._k">
            <button @click="listen(row)"><icon name="volume-2"></icon>Nghe giọng đọc câu này</button>
            <button :disabled="locked" @click="retranslate(row)"><icon name="languages"></icon>Dịch lại câu này</button>
            <hr>
            <button :disabled="locked" @click="split(row)"><icon name="scissors"></icon>Tách làm hai câu</button>
            <button :disabled="locked || rows.indexOf(row) === rows.length - 1" @click="mergeNext(row)"><icon name="merge"></icon>Gộp với câu sau</button>
            <button :disabled="locked" @click="insertAfter(row)"><icon name="list-plus"></icon>Thêm câu phía sau</button>
            <template v-if="voices.length">
              <hr>
              <div class="menu-label">Giọng đọc riêng cho câu này</div>
              <div style="padding: 2px 8px 6px">
                <select :value="row.voice || ''" :disabled="locked" @change="setVoice(row, $event.target.value)" style="height: 30px; font-size: 12.5px">
                  <option value="">Theo giọng mặc định của dự án</option>
                  <option v-for="v in voices" :key="v.id" :value="v.id">{{ v.name }}{{ v.gender === 'female' ? ' (nữ)' : v.gender === 'male' ? ' (nam)' : '' }}</option>
                </select>
              </div>
            </template>
            <hr>
            <button class="danger" :disabled="locked" @click="remove(row)"><icon name="trash-2"></icon>Xoá câu</button>
          </div>
        </div>
      </div>

      <div class="ed-foot">
        <span class="muted small">{{ rows.length }} câu<span v-if="untranslated"> · {{ untranslated }} câu chưa dịch</span><span v-if="warnings"> · <span style="color: var(--warn)">{{ warnings }} câu nên rút gọn</span></span></span>
        <span class="spacer"></span>
        <label class="row small" style="gap: 6px; cursor: pointer"><input type="checkbox" v-model="follow">Cuộn theo video</label>
        <template v-if="pages > 1">
          <button class="btn btn-sm btn-icon" :disabled="page === 0" @click="page--" title="Trang trước"><icon name="chevron-left"></icon></button>
          <span class="small">Trang {{ page + 1 }} / {{ pages }}</span>
          <button class="btn btn-sm btn-icon" :disabled="page >= pages - 1" @click="page++" title="Trang sau"><icon name="chevron-right"></icon></button>
        </template>
      </div>

      <modal v-if="find" title="Tìm & thay" icon="replace" @close="find = null">
        <div class="col" style="gap: 14px">
          <div class="seg" style="align-self: flex-start">
            <button :class="{ on: find.field === 'translation' }" @click="find.field = 'translation'; countFind()">Trong bản dịch</button>
            <button :class="{ on: find.field === 'text' }" @click="find.field = 'text'; countFind()">Trong lời gốc</button>
          </div>
          <div class="field"><label>Tìm</label><input class="input" v-model="find.q" @input="countFind" placeholder="Cụm cần tìm (phân biệt hoa thường)"></div>
          <div class="field"><label>Thay bằng</label><input class="input" v-model="find.r" placeholder="Để trống = xoá cụm đó"></div>
          <div class="muted small" v-if="find.count !== null">Tìm thấy {{ find.count }} chỗ.</div>
        </div>
        <template #foot>
          <button class="btn" @click="find = null">Huỷ</button>
          <button class="btn btn-primary" :disabled="!find.q || find.count === 0" @click="applyFind">Thay tất cả</button>
        </template>
      </modal>

      <modal v-if="shift" title="Dịch chuyển thời gian" icon="timer" @close="shift = null">
        <div class="col" style="gap: 14px">
          <div class="field"><label>Độ lệch (mili-giây)</label>
            <input class="input" type="number" step="50" v-model.number="shift.ms">
            <div class="hint">Số dương: phụ đề hiện muộn hơn. Số âm: hiện sớm hơn. Ví dụ 500 = trễ nửa giây.</div></div>
          <div class="seg" style="align-self: flex-start">
            <button :class="{ on: shift.from === 'all' }" @click="shift.from = 'all'">Tất cả các câu</button>
            <button :class="{ on: shift.from === 'here' }" @click="shift.from = 'here'">Từ vị trí đang phát trở đi</button>
          </div>
        </div>
        <template #foot>
          <button class="btn" @click="shift = null">Huỷ</button>
          <button class="btn btn-primary" @click="applyShift">Áp dụng</button>
        </template>
      </modal>
    </div>`,
};
