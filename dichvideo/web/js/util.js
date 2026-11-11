// Hàm tiện ích dùng chung cho giao diện.

export const STEPS = ["prepare", "transcribe", "translate", "dub", "render"];
export const STEP_NAMES = {
  prepare: "Chuẩn bị", transcribe: "Nhận dạng", translate: "Dịch", dub: "Lồng tiếng", render: "Xuất video",
};
export const STATUS_NAMES = {
  pending: "Chưa chạy", queued: "Đang chờ", running: "Đang chạy", done: "Xong",
  error: "Lỗi", stale: "Cần chạy lại", skipped: "Bỏ qua",
};

export function clamp(v, lo, hi) { return Math.min(hi, Math.max(lo, v)); }

export function pad(n, w = 2) { return String(n).padStart(w, "0"); }

// 83.4 -> "1:23"; 3723 -> "1:02:03"
export function fmtDuration(sec) {
  sec = Math.max(0, Math.round(Number(sec) || 0));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

// 83.456 -> "01:23.456" (thêm giờ khi cần)
export function fmtTime(sec) {
  const ms = Math.max(0, Math.round((Number(sec) || 0) * 1000));
  const h = Math.floor(ms / 3600000), m = Math.floor((ms % 3600000) / 60000);
  const s = Math.floor((ms % 60000) / 1000), f = ms % 1000;
  return (h ? `${pad(h)}:` : "") + `${pad(m)}:${pad(s)}.${pad(f, 3)}`;
}

// Chấp nhận "83.4", "1:23.4", "01:02:03,456". Trả về null nếu không đọc được.
export function parseTime(str) {
  const s = String(str || "").trim().replace(",", ".");
  if (!s) return null;
  const parts = s.split(":");
  if (parts.length > 3 || parts.some((p) => p === "" || isNaN(Number(p)))) return null;
  let total = 0;
  for (const p of parts) total = total * 60 + Number(p);
  return total >= 0 ? Math.round(total * 1000) / 1000 : null;
}

export function fmtBytes(n) {
  n = Number(n) || 0;
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let i = -1;
  do { n /= 1024; i++; } while (n >= 1024 && i < units.length - 1);
  return `${n >= 100 ? n.toFixed(0) : n.toFixed(1)} ${units[i]}`;
}

export function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return "";
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function debounce(fn, ms) {
  let t = null;
  const wrapped = (...args) => { clearTimeout(t); t = setTimeout(() => { t = null; fn(...args); }, ms); };
  wrapped.flush = (...args) => { if (t) { clearTimeout(t); t = null; fn(...args); } };
  wrapped.cancel = () => { clearTimeout(t); t = null; };
  wrapped.pending = () => t !== null;
  return wrapped;
}

export function clone(obj) { return JSON.parse(JSON.stringify(obj)); }

export function same(a, b) { return JSON.stringify(a) === JSON.stringify(b); }

// Số ký tự "đọc được" của một câu (bỏ khoảng trắng thừa).
export function textLen(s) { return (s || "").replace(/\s+/g, " ").trim().length; }

// Trạng thái tổng quát của dự án để hiện nhãn trên thẻ.
export function projectState(p) {
  const steps = p.steps || {};
  if (p.source && !p.source.ready) return { key: "wait", label: "Đang nhận video", cls: "run" };
  const order = STEPS.filter((s) => s !== "dub" || !p.mode || p.mode.dub !== false);
  const running = order.find((s) => steps[s] && steps[s].status === "running");
  if (running) return { key: "running", label: `${STEP_NAMES[running]}…`, cls: "run", step: running };
  if (order.some((s) => steps[s] && steps[s].status === "queued")) return { key: "queued", label: "Đang chờ", cls: "run" };
  const failed = order.find((s) => steps[s] && steps[s].status === "error");
  if (failed) return { key: "error", label: `Lỗi ở bước ${STEP_NAMES[failed]}`, cls: "err", step: failed };
  if (order.every((s) => steps[s] && steps[s].status === "done")) return { key: "done", label: "Hoàn tất", cls: "ok" };
  if (order.some((s) => steps[s] && steps[s].status === "stale")) return { key: "stale", label: "Cần chạy lại", cls: "warn" };
  if (order.some((s) => steps[s] && steps[s].status === "done")) return { key: "partial", label: "Đang làm dở", cls: "pri" };
  return { key: "new", label: "Chưa xử lý", cls: "" };
}

export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
