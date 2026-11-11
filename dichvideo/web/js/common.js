// Kho trạng thái chung và các thành phần nhỏ dùng ở mọi trang.
import { api } from "./api.js";
import { Icon } from "./icons.js";

const { reactive } = Vue;

export const store = reactive({
  system: null,
  settings: null,
  theme: document.documentElement.getAttribute("data-theme") || "light",
  toasts: [],
  dialog: null,
});

let toastSeq = 0;
export function toast(message, type = "info", ms = 4500) {
  const id = ++toastSeq;
  store.toasts.push({ id, message: String(message), type });
  if (ms) setTimeout(() => closeToast(id), type === "err" ? Math.max(ms, 7000) : ms);
}
export function closeToast(id) {
  const i = store.toasts.findIndex((t) => t.id === id);
  if (i >= 0) store.toasts.splice(i, 1);
}
export function toastError(e) { toast(e && e.message ? e.message : String(e), "err"); }

// Hộp thoại xác nhận trả về Promise<boolean>.
export function confirmDialog({ title, message, okText = "Đồng ý", cancelText = "Huỷ", danger = false }) {
  return new Promise((resolve) => { store.dialog = { title, message, okText, cancelText, danger, resolve }; });
}

export function setTheme(theme) {
  store.theme = theme;
  document.documentElement.setAttribute("data-theme", theme);
  try { localStorage.setItem("dvs-theme", theme); } catch (e) { /* trình duyệt chặn lưu trữ */ }
}

export async function loadSystem() {
  store.system = await api.get("/api/system");
  return store.system;
}
export async function loadSettings() {
  store.settings = await api.get("/api/settings");
  return store.settings;
}

// Nạp các phông phụ đề vào trang để xem trước đúng kiểu chữ.
let fontsInjected = false;
export function injectSubtitleFonts(families) {
  if (fontsInjected || !families) return;
  fontsInjected = true;
  let css = "";
  for (const fam of families) {
    for (const face of fam.faces) {
      css += `@font-face{font-family:${JSON.stringify("sub:" + fam.family)};font-weight:${face.bold ? 700 : 400};` +
        `font-style:${face.italic ? "italic" : "normal"};font-display:swap;src:url(${JSON.stringify(face.url)});}\n`;
    }
  }
  const el = document.createElement("style");
  el.textContent = css;
  document.head.appendChild(el);
}

export const Modal = {
  name: "Modal",
  components: { Icon },
  props: { title: String, wide: Boolean, icon: String },
  emits: ["close"],
  mounted() { this._key = (e) => { if (e.key === "Escape") this.$emit("close"); }; window.addEventListener("keydown", this._key); },
  unmounted() { window.removeEventListener("keydown", this._key); },
  template: `
    <div class="modal-back" @mousedown.self="$emit('close')">
      <div class="modal" :class="{ wide }" role="dialog" aria-modal="true">
        <div class="modal-head">
          <icon v-if="icon" :name="icon" :size="18"></icon>
          <span class="grow">{{ title }}</span>
          <button class="btn btn-ghost btn-icon" @click="$emit('close')" title="Đóng"><icon name="x"></icon></button>
        </div>
        <div class="modal-body"><slot></slot></div>
        <div class="modal-foot" v-if="$slots.foot"><slot name="foot"></slot></div>
      </div>
    </div>`,
};

export const Toasts = {
  name: "Toasts",
  components: { Icon },
  data: () => ({ store }),
  methods: { closeToast },
  template: `
    <div class="toasts" aria-live="polite">
      <div v-for="t in store.toasts" :key="t.id" class="toast" :class="t.type">
        <icon :name="t.type === 'err' ? 'circle-alert' : t.type === 'ok' ? 'circle-check' : 'info'" :size="17"></icon>
        <span>{{ t.message }}</span>
        <button @click="closeToast(t.id)" title="Đóng"><icon name="x" :size="15"></icon></button>
      </div>
    </div>`,
};

export const ConfirmHost = {
  name: "ConfirmHost",
  components: { Modal },
  data: () => ({ store }),
  methods: {
    answer(v) { const d = store.dialog; store.dialog = null; if (d) d.resolve(v); },
  },
  template: `
    <modal v-if="store.dialog" :title="store.dialog.title" @close="answer(false)">
      <p style="white-space: pre-line; line-height: 1.6">{{ store.dialog.message }}</p>
      <template #foot>
        <button class="btn" @click="answer(false)">{{ store.dialog.cancelText }}</button>
        <button class="btn" :class="store.dialog.danger ? 'btn-danger-solid' : 'btn-primary'" @click="answer(true)">{{ store.dialog.okText }}</button>
      </template>
    </modal>`,
};

// Thanh trượt có nhãn và giá trị: <slider label="Cỡ chữ" v-model="x" :min="20" :max="90" unit="px">
export const Slider = {
  name: "Slider",
  props: {
    modelValue: Number, label: String, min: { type: Number, default: 0 }, max: { type: Number, default: 100 },
    step: { type: Number, default: 1 }, unit: { type: String, default: "" }, hint: String, disabled: Boolean,
    format: Function,
  },
  emits: ["update:modelValue"],
  computed: {
    shown() { return this.format ? this.format(this.modelValue) : `${this.modelValue}${this.unit}`; },
  },
  template: `
    <div class="field">
      <label class="row" style="justify-content: space-between"><span>{{ label }}</span><span class="value">{{ shown }}</span></label>
      <input type="range" :min="min" :max="max" :step="step" :value="modelValue" :disabled="disabled"
             @input="$emit('update:modelValue', Number($event.target.value))">
      <div class="hint" v-if="hint">{{ hint }}</div>
    </div>`,
};

export const Toggle = {
  name: "Toggle",
  props: { modelValue: Boolean, label: String, hint: String, disabled: Boolean },
  emits: ["update:modelValue"],
  template: `
    <label class="switch">
      <input type="checkbox" :checked="modelValue" :disabled="disabled" @change="$emit('update:modelValue', $event.target.checked)">
      <i></i>
      <span>{{ label }}<small v-if="hint">{{ hint }}</small></span>
    </label>`,
};

export const commonComponents = { Icon, Modal, Slider, Toggle };
