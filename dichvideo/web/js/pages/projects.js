// Trang Dự án: tạo dự án mới (kéo thả tệp hoặc dán liên kết) và danh sách dự án.
import { api } from "../api.js";
import { commonComponents, confirmDialog, store, toast, toastError } from "../common.js";
import { STEPS, fmtBytes, fmtDate, fmtDuration, projectState } from "../util.js";

const QUICK_KEY = "dvs-quick";

export const ProjectsPage = {
  name: "ProjectsPage",
  components: commonComponents,
  data() {
    const d = store.settings.defaults;
    let quick = { source_lang: d.source_lang, burn: d.subtitle.burn, dub: d.dub.enabled,
                  review: d.stop_for_review, engine: d.translate.engine };
    try { quick = { ...quick, ...JSON.parse(localStorage.getItem(QUICK_KEY) || "{}") }; } catch (e) { /* bỏ qua */ }
    return { store, projects: null, uploads: [], url: "", urlBusy: false, over: false, quick, timer: null, STEPS };
  },
  computed: {
    langs() { return store.system.source_langs; },
    engines() {
      return [{ id: "google", name: "Google Dịch (miễn phí)" },
              ...store.system.llm_providers.map((p) => ({ id: p.id, name: p.name }))];
    },
    accept() { return [...store.system.video_ext, ...store.system.audio_ext].join(","); },
    anyActive() {
      return this.uploads.length > 0 || (this.projects || []).some((p) => ["running", "queued", "wait"].includes(this.state(p).key));
    },
  },
  watch: {
    quick: { deep: true, handler(v) { try { localStorage.setItem(QUICK_KEY, JSON.stringify(v)); } catch (e) { /* bỏ qua */ } } },
  },
  created() { this.refresh(); this.schedule(); },
  unmounted() { clearTimeout(this.timer); },
  methods: {
    fmtDuration, fmtDate, fmtBytes,
    state(p) { return projectState(p); },
    schedule() {
      clearTimeout(this.timer);
      this.timer = setTimeout(async () => { await this.refresh(true); this.schedule(); }, this.anyActive ? 1500 : 7000);
    },
    async refresh(quiet) {
      try {
        const data = await api.get("/api/projects");
        this.projects = data.projects;
      } catch (e) { if (!quiet) toastError(e); }
    },
    overrides() {
      return { source_lang: this.quick.source_lang, stop_for_review: this.quick.review,
               subtitle: { burn: this.quick.burn }, dub: { enabled: this.quick.dub },
               translate: { engine: this.quick.engine } };
    },
    pick() { this.$refs.file.click(); },
    onPick(e) { this.addFiles([...e.target.files]); e.target.value = ""; },
    onDrop(e) { this.over = false; this.addFiles([...(e.dataTransfer ? e.dataTransfer.files : [])]); },
    async addFiles(files) {
      if (!this.quick.burn && !this.quick.dub) {
        toast("Hãy bật ít nhất một trong hai: Gắn phụ đề hoặc Lồng tiếng.", "err");
        return;
      }
      for (const file of files) {
        const ext = (file.name.match(/\.[^.]+$/) || [""])[0].toLowerCase();
        if (!this.accept.split(",").includes(ext)) {
          toast(`"${file.name}" không phải tệp video/âm thanh được hỗ trợ.`, "err");
          continue;
        }
        const item = Vue.reactive({ name: file.name, size: file.size, progress: 0, abort: null });
        this.uploads.push(item);
        try {
          const proj = await api.post("/api/projects", { filename: file.name, settings: this.overrides() });
          const up = api.upload(`/api/projects/${proj.id}/source?start=1`, file, (p) => { item.progress = p; });
          item.abort = async () => { up.abort(); try { await api.del(`/api/projects/${proj.id}`); } catch (e) { /* đã xoá */ } };
          await up.promise;
          toast(`Đã nhận "${file.name}" — bắt đầu xử lý.`, "ok");
        } catch (e) {
          if (e.message !== "Đã huỷ tải lên.") toastError(e);
        } finally {
          this.uploads.splice(this.uploads.indexOf(item), 1);
          this.refresh(true);
          this.schedule();
        }
      }
    },
    async addUrl() {
      const url = this.url.trim();
      if (!url) return;
      this.urlBusy = true;
      try {
        await api.post("/api/projects/from-url", { url, settings: this.overrides() });
        this.url = "";
        toast("Đang tải video từ liên kết. Dự án sẽ tự chạy khi tải xong.", "ok");
        await this.refresh(true);
        this.schedule();
      } catch (e) { toastError(e); } finally { this.urlBusy = false; }
    },
    open(p) { location.hash = `#/p/${p.id}`; },
    async remove(p) {
      const ok = await confirmDialog({
        title: "Xoá dự án?", danger: true, okText: "Xoá",
        message: `Xoá "${p.name}" cùng toàn bộ video, phụ đề và kết quả của dự án này. Không thể hoàn tác.`,
      });
      if (!ok) return;
      try { await api.del(`/api/projects/${p.id}`); toast("Đã xoá dự án.", "ok"); await this.refresh(true); }
      catch (e) { toastError(e); }
    },
    async stop(p) {
      try { await api.post(`/api/projects/${p.id}/cancel`); await this.refresh(true); } catch (e) { toastError(e); }
    },
    stepClass(p, s) {
      if (s === "dub" && p.mode && !p.mode.dub) return "skipped";
      return (p.steps[s] && p.steps[s].status) || "pending";
    },
    detail(p) {
      const st = this.state(p);
      if (st.key === "running") {
        const s = p.steps[st.step];
        return (s.message || "") + (s.progress ? ` · ${Math.round(s.progress * 100)}%` : "");
      }
      if (st.key === "error") return p.steps[st.step].error || "";
      if (p.counts && p.counts.segments) return `${p.counts.segments} câu · đã dịch ${p.counts.translated}`;
      return fmtDate(p.created_at);
    },
    thumb(p) { return p.has_thumb ? `url("/api/projects/${p.id}/thumb?u=${encodeURIComponent(p.updated_at)}")` : "none"; },
  },
  template: `
    <div class="page">
      <div class="page-head">
        <div class="grow">
          <h1 class="page-title">Dự án</h1>
          <div class="page-desc">Thả video tiếng Trung vào đây — ứng dụng tự nhận dạng lời thoại, dịch sang tiếng Việt, lồng tiếng và xuất video.</div>
        </div>
      </div>

      <div class="drop" :class="{ over }" @click="pick" @dragover.prevent="over = true" @dragleave.prevent="over = false" @drop.prevent="onDrop"
           role="button" tabindex="0" @keydown.enter="pick">
        <input ref="file" type="file" class="hidden" multiple :accept="accept" @change="onPick">
        <div class="drop-icon"><icon name="upload" :size="24"></icon></div>
        <h3>Kéo thả video vào đây hoặc bấm để chọn tệp</h3>
        <div class="muted small" style="margin-top: 4px">Hỗ trợ MP4, MKV, MOV, AVI, WEBM, FLV… và tệp âm thanh. Có thể chọn nhiều tệp cùng lúc.</div>
        <div class="url-row" @click.stop>
          <input class="input" v-model="url" placeholder="…hoặc dán liên kết video (YouTube, Bilibili, Douyin, liên kết tệp)" @keydown.enter="addUrl">
          <button class="btn" :disabled="!url.trim() || urlBusy" @click="addUrl"><icon :name="urlBusy ? 'loader-circle' : 'link'" :spin="urlBusy"></icon>Tải về</button>
        </div>
        <div class="quick" @click.stop>
          <select v-model="quick.source_lang" style="width: auto; height: 30px; font-size: 12.5px" title="Ngôn ngữ của video">
            <option v-for="l in langs" :key="l.id" :value="l.id">{{ l.name }}</option>
          </select>
          <select v-model="quick.engine" style="width: auto; height: 30px; font-size: 12.5px" title="Bộ dịch">
            <option v-for="e in engines" :key="e.id" :value="e.id">{{ e.name }}</option>
          </select>
          <button class="chip" :class="{ on: quick.burn }" @click="quick.burn = !quick.burn"><icon name="captions" :size="14"></icon>Gắn phụ đề Việt</button>
          <button class="chip" :class="{ on: quick.dub }" @click="quick.dub = !quick.dub"><icon name="mic" :size="14"></icon>Lồng tiếng Việt</button>
          <button class="chip" :class="{ on: quick.review }" @click="quick.review = !quick.review" title="Dừng sau khi dịch để bạn sửa phụ đề rồi mới lồng tiếng và xuất video">
            <icon name="eye" :size="14"></icon>Duyệt phụ đề trước khi xuất</button>
        </div>
      </div>

      <div class="card card-pad" v-if="uploads.length" style="margin-top: 16px">
        <div class="card-title" style="margin-bottom: 10px"><icon name="upload"></icon>Đang tải lên</div>
        <div v-for="u in uploads" :key="u.name" class="row" style="padding: 6px 0">
          <div class="grow">
            <div class="row"><span class="truncate" style="font-weight: 500">{{ u.name }}</span><span class="muted small nowrap">{{ fmtBytes(u.size) }} · {{ Math.round(u.progress * 100) }}%</span></div>
            <div class="progress" style="margin-top: 5px"><i :style="{ width: (u.progress * 100) + '%' }"></i></div>
          </div>
          <button class="btn btn-sm btn-ghost" v-if="u.abort" @click="u.abort()">Huỷ</button>
        </div>
      </div>

      <div style="margin-top: 26px">
        <div class="row" style="margin-bottom: 12px">
          <h2 style="font-size: 16px" class="grow">Dự án của bạn <span class="muted" v-if="projects">({{ projects.length }})</span></h2>
          <button class="btn btn-sm btn-ghost" @click="refresh()"><icon name="refresh-cw"></icon>Làm mới</button>
        </div>
        <div v-if="projects === null" class="empty"><icon name="loader-circle" :size="26" spin></icon></div>
        <div v-else-if="!projects.length" class="card empty">
          <icon name="film" :size="40"></icon>
          <div style="font-weight: 600; color: var(--text-2)">Chưa có dự án nào</div>
          <div class="small" style="margin-top: 4px">Thả một video vào khung phía trên để bắt đầu.</div>
        </div>
        <div v-else class="proj-grid">
          <div v-for="p in projects" :key="p.id" class="card proj" @click="open(p)" tabindex="0" @keydown.enter="open(p)">
            <div class="proj-thumb" :style="{ backgroundImage: thumb(p) }">
              <icon v-if="!p.has_thumb" name="film" :size="34"></icon>
              <span class="proj-dur" v-if="p.media && p.media.duration">{{ fmtDuration(p.media.duration) }}</span>
            </div>
            <div class="proj-body">
              <div class="row">
                <div class="proj-name truncate grow" :title="p.name">{{ p.name }}</div>
                <span class="badge" :class="state(p).cls">{{ state(p).label }}</span>
              </div>
              <div class="steps-mini" :title="'Chuẩn bị · Nhận dạng · Dịch · Lồng tiếng · Xuất video'">
                <i v-for="s in STEPS" :key="s" :class="stepClass(p, s)"></i>
              </div>
              <div class="row">
                <div class="muted small truncate grow" :title="detail(p)">{{ detail(p) }}</div>
                <button class="btn btn-sm btn-ghost btn-icon" v-if="['running', 'queued'].includes(state(p).key)" @click.stop="stop(p)" title="Dừng xử lý"><icon name="square"></icon></button>
                <button class="btn btn-sm btn-ghost btn-icon" @click.stop="remove(p)" title="Xoá dự án"><icon name="trash-2"></icon></button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>`,
};
