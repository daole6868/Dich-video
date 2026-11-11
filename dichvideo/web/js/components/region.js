// Khoanh vùng trên khung hình: kéo để vẽ, kéo thân để di chuyển, kéo góc để đổi cỡ.
import { Icon } from "../icons.js";
import { clamp } from "../util.js";

const MIN = 0.02;

export const RegionEditor = {
  name: "RegionEditor",
  components: { Icon },
  props: {
    modelValue: { type: Array, default: () => [] },   // [{x, y, w, h, ...}] theo tỉ lệ 0..1
    frameUrl: { type: String, required: true },
    single: Boolean,                                   // chỉ cho một vùng (vùng quét OCR)
    selected: { type: Number, default: -1 },
    template: { type: Object, default: () => ({ mode: "blur", strength: 60 }) },
    label: { type: Function, default: (r, i) => `Vùng ${i + 1}` },
    disabled: Boolean,
  },
  emits: ["update:modelValue", "update:selected"],
  data: () => ({ drag: null, loaded: false, failed: false }),
  methods: {
    point(e) {
      const r = this.$refs.layer.getBoundingClientRect();
      return { x: clamp((e.clientX - r.left) / r.width, 0, 1), y: clamp((e.clientY - r.top) / r.height, 0, 1) };
    },
    commit(list, sel) {
      this.$emit("update:modelValue", list);
      if (sel !== undefined) this.$emit("update:selected", sel);
    },
    startDraw(e) {
      if (this.disabled || e.button !== 0) return;
      const p = this.point(e);
      const list = this.single ? [] : this.modelValue.map((r) => ({ ...r }));
      list.push({ ...this.template, x: p.x, y: p.y, w: 0, h: 0 });
      this.drag = { kind: "draw", index: list.length - 1, origin: p };
      this.commit(list, list.length - 1);
      this.capture(e);
    },
    startMove(e, i) {
      if (this.disabled || e.button !== 0) return;
      const p = this.point(e), r = this.modelValue[i];
      this.drag = { kind: "move", index: i, dx: p.x - r.x, dy: p.y - r.y };
      this.$emit("update:selected", i);
      this.capture(e);
    },
    startResize(e, i, corner) {
      if (this.disabled || e.button !== 0) return;
      const r = this.modelValue[i];
      // Điểm neo là góc đối diện với góc đang kéo.
      const ax = corner.includes("w") ? r.x + r.w : r.x, ay = corner.includes("n") ? r.y + r.h : r.y;
      this.drag = { kind: "draw", index: i, origin: { x: ax, y: ay } };
      this.$emit("update:selected", i);
      this.capture(e);
    },
    capture(e) {
      e.preventDefault();
      window.addEventListener("pointermove", this.onMove);
      window.addEventListener("pointerup", this.onUp, { once: true });
    },
    onMove(e) {
      const d = this.drag;
      if (!d) return;
      const p = this.point(e);
      const list = this.modelValue.map((r) => ({ ...r }));
      const r = list[d.index];
      if (!r) return;
      if (d.kind === "move") {
        r.x = clamp(p.x - d.dx, 0, 1 - r.w);
        r.y = clamp(p.y - d.dy, 0, 1 - r.h);
      } else {
        r.x = Math.min(p.x, d.origin.x); r.y = Math.min(p.y, d.origin.y);
        r.w = Math.abs(p.x - d.origin.x); r.h = Math.abs(p.y - d.origin.y);
      }
      this.commit(list);
    },
    onUp() {
      window.removeEventListener("pointermove", this.onMove);
      const d = this.drag;
      this.drag = null;
      if (!d) return;
      // Bỏ vùng quá nhỏ (bấm nhầm mà không kéo), làm tròn số cho gọn.
      let list = this.modelValue.map((r) => ({ ...r, x: +r.x.toFixed(4), y: +r.y.toFixed(4), w: +r.w.toFixed(4), h: +r.h.toFixed(4) }));
      const r = list[d.index];
      if (r && (r.w < MIN || r.h < MIN)) {
        list = list.filter((_, i) => i !== d.index);
        this.commit(list, -1);
      } else {
        if (r) delete r.auto;
        this.commit(list);
      }
    },
    box(r) { return { left: r.x * 100 + "%", top: r.y * 100 + "%", width: r.w * 100 + "%", height: r.h * 100 + "%" }; },
  },
  template: `
    <div class="region-stage">
      <img :src="frameUrl" alt="Khung hình video" draggable="false" @load="loaded = true; failed = false" @error="failed = true">
      <div v-if="failed" style="position: absolute; inset: 0; display: grid; place-items: center; color: #cfd6de; line-height: 1.4; padding: 20px; text-align: center">Không lấy được khung hình tại vị trí này.</div>
      <div class="region-layer" ref="layer" :style="{ cursor: disabled ? 'default' : 'crosshair' }" @pointerdown.self="startDraw">
        <div v-for="(r, i) in modelValue" :key="i" class="region-box" :class="{ sel: i === selected }" :style="box(r)" @pointerdown.self="startMove($event, i)">
          <span class="tag">{{ label(r, i) }}</span>
          <template v-if="i === selected && !disabled">
            <i class="handle nw" @pointerdown.stop="startResize($event, i, 'nw')"></i>
            <i class="handle ne" @pointerdown.stop="startResize($event, i, 'ne')"></i>
            <i class="handle sw" @pointerdown.stop="startResize($event, i, 'sw')"></i>
            <i class="handle se" @pointerdown.stop="startResize($event, i, 'se')"></i>
          </template>
        </div>
      </div>
    </div>`,
};
