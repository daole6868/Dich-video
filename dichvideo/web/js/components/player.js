// Trình phát video có lớp phủ xem trước: phụ đề theo đúng kiểu chữ đã chọn, vùng che, logo.
import { Icon } from "../icons.js";
import { store } from "../common.js";
import { clamp, fmtDuration } from "../util.js";

export const Player = {
  name: "Player",
  components: { Icon },
  props: {
    projectId: { type: String, required: true },
    media: { type: Object, required: true },
    segments: { type: Array, default: () => [] },
    settings: { type: Object, required: true },
    version: { type: [String, Number], default: "" },
    coverActive: { type: Function, default: null },
  },
  emits: ["time"],
  data: () => ({ time: 0, duration: 0, playing: false, box: { w: 0, h: 0, left: 0, top: 0 }, showSub: true, stopAt: null, failed: false }),
  computed: {
    isVideo() { return !!this.media.has_video; },
    src() { return `/api/projects/${this.projectId}/video?v=${encodeURIComponent(this.version)}`; },
    current() {
      const t = this.time;
      return this.segments.find((s) => t >= s.start && t <= s.end) || null;
    },
    // Tỉ lệ giữa kích thước hiển thị và kích thước video thật.
    scale() { return this.media.height ? this.box.h / this.media.height : 0; },
    sub() { return this.settings.subtitle; },
    family() { return (store.system.fonts || []).find((f) => f.family === this.sub.font) || null; },
    textStyle() {
      const sub = this.sub;
      const base = Math.min(this.media.width, this.media.height) / 1080;
      const px = Math.max(6, sub.size * base * this.scale);
      const outline = sub.box ? 0 : sub.outline * base * this.scale;
      const style = {
        fontFamily: `"sub:${sub.font}", "Be Vietnam Pro", sans-serif`,
        fontSize: px + "px",
        fontWeight: sub.bold ? 700 : 400,
        fontStyle: sub.italic ? "italic" : "normal",
        color: sub.color,
        textTransform: sub.uppercase ? "uppercase" : "none",
      };
      if (outline > 0.2) {
        style.webkitTextStroke = `${(outline * 2).toFixed(2)}px ${sub.outline_color}`;
        style.paintOrder = "stroke fill";
      }
      if (!sub.box && sub.shadow > 0) {
        const d = Math.max(0.5, sub.shadow * base * this.scale);
        style.textShadow = `${d}px ${d}px ${d}px rgba(0,0,0,.6)`;
      }
      return style;
    },
    spanStyle() {
      const sub = this.sub;
      if (!sub.box) return {};
      const a = Math.round(clamp(sub.box_opacity, 0, 100) * 2.55).toString(16).padStart(2, "0");
      return { background: sub.box_color + a, padding: "0.12em 0.4em" };
    },
    secondStyle() {
      return { ...this.textStyle, fontSize: `calc(${this.textStyle.fontSize} * ${this.sub.secondary_scale / 100})`,
               color: this.sub.secondary_color, fontWeight: 400, fontFamily: '"Be Vietnam Pro", sans-serif' };
    },
    lineStyle() {
      const sub = this.sub;
      const side = (sub.margin_h / 100) * this.box.w;
      const st = { left: side + "px", right: side + "px" };
      const v = (sub.margin_v / 100) * this.box.h;
      if (sub.align === "top") st.top = v + "px";
      else if (sub.align === "middle") { st.top = "50%"; st.transform = "translateY(-50%)"; }
      else st.bottom = v + "px";
      return st;
    },
    covers() {
      const on = !this.coverActive || this.coverActive(this.time);
      if (!on) return [];
      return (this.settings.cover || []).map((r) => ({
        cls: r.mode === "box" ? "box" : "blur",
        style: {
          left: r.x * this.box.w + "px", top: r.y * this.box.h + "px",
          width: r.w * this.box.w + "px", height: r.h * this.box.h + "px",
          ...(r.mode === "box" ? { background: r.color || "#000000", opacity: (r.opacity ?? 100) / 100 } : {}),
        },
      }));
    },
    logoStyle() {
      const logo = this.settings.logo;
      if (!logo || !logo.enabled || !logo.file) return null;
      const m = (Math.min(this.box.w, this.box.h) * logo.margin) / 100 + "px";
      const st = { position: "absolute", width: (this.box.w * logo.scale) / 100 + "px", opacity: logo.opacity / 100 };
      st[logo.position.includes("left") ? "left" : "right"] = m;
      st[logo.position.includes("top") ? "top" : "bottom"] = m;
      return st;
    },
    logoSrc() { return `/api/projects/${this.projectId}/logo?v=${encodeURIComponent(this.settings.logo.file || "")}`; },
  },
  mounted() {
    this._ro = new ResizeObserver(() => this.measure());
    this._ro.observe(this.$refs.stage);
    window.addEventListener("resize", this.measure);
    this.measure();
  },
  unmounted() {
    this._ro.disconnect();
    window.removeEventListener("resize", this.measure);
    cancelAnimationFrame(this._raf);
  },
  methods: {
    fmtDuration,
    el() { return this.$refs.media; },
    // Vùng hình ảnh thật bên trong thẻ video (video được co cho vừa khung nên có thể có viền đen).
    measure() {
      const el = this.el();
      if (!el || !this.isVideo) return;
      const rect = el.getBoundingClientRect();
      const stage = this.$refs.stage.getBoundingClientRect();
      const vw = this.media.width || el.videoWidth || 16, vh = this.media.height || el.videoHeight || 9;
      const k = Math.min(rect.width / vw, rect.height / vh);
      const w = vw * k, h = vh * k;
      this.box = { w, h, left: rect.left - stage.left + (rect.width - w) / 2, top: rect.top - stage.top + (rect.height - h) / 2 };
    },
    tick() {
      const el = this.el();
      if (!el) return;
      this.time = el.currentTime;
      if (this.stopAt !== null && el.currentTime >= this.stopAt) { el.pause(); this.stopAt = null; }
      this.$emit("time", this.time);
      if (!el.paused) this._raf = requestAnimationFrame(this.tick);
    },
    onPlay() { this.playing = true; cancelAnimationFrame(this._raf); this._raf = requestAnimationFrame(this.tick); },
    onPause() { this.playing = false; this.tick(); },
    onMeta() { this.duration = this.el().duration || this.media.duration || 0; this.measure(); },
    toggle() { const el = this.el(); if (!el) return; this.stopAt = null; if (el.paused) el.play().catch(() => {}); else el.pause(); },
    seek(t, play = false) {
      const el = this.el();
      if (!el) return;
      this.stopAt = null;
      el.currentTime = clamp(t, 0, (this.duration || this.media.duration || 0) - 0.01);
      this.time = el.currentTime;
      this.$emit("time", this.time);
      if (play) el.play().catch(() => {});
    },
    // Phát đúng một câu rồi dừng.
    playRange(a, b) {
      const el = this.el();
      if (!el) return;
      el.currentTime = Math.max(0, a);
      this.stopAt = b;
      el.play().catch(() => {});
    },
    step(d) { this.seek(this.time + d); },
    onScrub(e) { this.seek(Number(e.target.value)); },
    pause() { const el = this.el(); if (el) el.pause(); },
  },
  template: `
    <div class="player">
      <div class="stage" ref="stage">
        <video v-if="isVideo" ref="media" :src="src" preload="metadata" playsinline @click="toggle"
               @play="onPlay" @pause="onPause" @loadedmetadata="onMeta" @seeked="tick" @timeupdate="tick" @error="failed = true"></video>
        <div v-else style="width: 100%; padding: 46px 20px; color: #9aa6b4; text-align: center">
          <icon name="audio-lines" :size="40"></icon>
          <div style="margin-top: 8px">Tệp chỉ có âm thanh</div>
          <audio ref="media" :src="src" preload="metadata" @play="onPlay" @pause="onPause" @loadedmetadata="onMeta" @seeked="tick" @timeupdate="tick"></audio>
        </div>
        <div v-if="isVideo && box.w" class="overlay" :style="{ left: box.left + 'px', top: box.top + 'px', width: box.w + 'px', height: box.h + 'px' }">
          <div v-for="(c, i) in covers" :key="i" class="cover-prev" :class="c.cls" :style="c.style"></div>
          <img v-if="logoStyle" :src="logoSrc" :style="logoStyle" alt="">
          <div v-if="showSub && sub.burn && current && (current.translation || (sub.bilingual && current.text))" class="sub-line" :style="lineStyle">
            <div :style="textStyle" v-if="current.translation"><span :style="spanStyle">{{ current.translation }}</span></div>
            <div :style="secondStyle" v-if="sub.bilingual && current.text" lang="zh"><span :style="spanStyle">{{ current.text }}</span></div>
          </div>
        </div>
        <div v-if="failed" style="position: absolute; inset: 0; display: grid; place-items: center; color: #dfe5ec; background: rgba(0,0,0,.7); text-align: center; padding: 20px">
          Trình duyệt không phát được video này. Hãy chạy lại bước "Chuẩn bị" để tạo bản xem trước.
        </div>
      </div>
      <div class="transport">
        <button class="btn btn-icon btn-sm" @click="toggle" :title="playing ? 'Tạm dừng (phím cách)' : 'Phát (phím cách)'"><icon :name="playing ? 'pause' : 'play'"></icon></button>
        <button class="btn btn-icon btn-sm" @click="step(-3)" title="Lùi 3 giây"><icon name="skip-back"></icon></button>
        <button class="btn btn-icon btn-sm" @click="step(3)" title="Tới 3 giây"><icon name="skip-forward"></icon></button>
        <input type="range" min="0" :max="duration || media.duration || 0" step="0.05" :value="time" @input="onScrub" aria-label="Vị trí phát">
        <span class="time">{{ fmtDuration(time) }} / {{ fmtDuration(duration || media.duration) }}</span>
        <button class="btn btn-icon btn-sm" @click="showSub = !showSub" :title="showSub ? 'Ẩn phụ đề xem trước' : 'Hiện phụ đề xem trước'"><icon :name="showSub ? 'captions' : 'captions-off'"></icon></button>
      </div>
    </div>`,
};
