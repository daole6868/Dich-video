// Trang Thuật ngữ: tên riêng, địa danh, thuật ngữ cần dịch thống nhất.
import { api } from "../api.js";
import { commonComponents, toast, toastError } from "../common.js";

export const GlossaryPage = {
  name: "GlossaryPage",
  components: commonComponents,
  data: () => ({ items: null, saved: "", filter: "", saving: false, bulk: false, bulkText: "" }),
  computed: {
    dirty() { return this.items !== null && JSON.stringify(this.clean()) !== this.saved; },
    shown() {
      const q = this.filter.trim().toLowerCase();
      if (!q) return this.items;
      return this.items.filter((t) => (t.source + " " + t.target + " " + (t.note || "")).toLowerCase().includes(q));
    },
  },
  async created() {
    try { const d = await api.get("/api/glossary"); this.set(d.items); } catch (e) { toastError(e); this.items = []; }
  },
  methods: {
    set(items) { this.items = items.map((t) => ({ ...t })); this.saved = JSON.stringify(this.clean()); },
    clean() {
      return (this.items || []).map((t) => ({ source: t.source.trim(), target: t.target.trim(), note: (t.note || "").trim() }))
        .filter((t) => t.source && t.target);
    },
    add() {
      this.filter = "";
      this.items.push({ source: "", target: "", note: "" });
      this.$nextTick(() => { const rows = this.$el.querySelectorAll("tbody tr"); const last = rows[rows.length - 1]; if (last) last.querySelector("input").focus(); });
    },
    remove(t) { this.items.splice(this.items.indexOf(t), 1); },
    async save() {
      this.saving = true;
      try { const d = await api.put("/api/glossary", { items: this.clean() }); this.set(d.items); toast("Đã lưu thuật ngữ.", "ok"); }
      catch (e) { toastError(e); } finally { this.saving = false; }
    },
    openBulk() { this.bulkText = this.clean().map((t) => `${t.source} = ${t.target}`).join("\n"); this.bulk = true; },
    async applyBulk() {
      try { const d = await api.put("/api/glossary", { text: this.bulkText }); this.set(d.items); this.bulk = false; toast(`Đã lưu ${d.items.length} thuật ngữ.`, "ok"); }
      catch (e) { toastError(e); }
    },
  },
  template: `
    <div class="page">
      <div class="page-head">
        <div class="grow">
          <h1 class="page-title">Thuật ngữ</h1>
          <div class="page-desc">Tên nhân vật, địa danh, chiêu thức… sẽ luôn được dịch đúng theo bảng này ở mọi dự án.</div>
        </div>
        <button class="btn" @click="openBulk"><icon name="file-text"></icon>Nhập nhanh từ văn bản</button>
        <button class="btn btn-primary" :disabled="!dirty || saving" @click="save"><icon :name="saving ? 'loader-circle' : 'save'" :spin="saving"></icon>Lưu</button>
      </div>

      <div class="note" style="margin-bottom: 16px"><icon name="info"></icon>
        <div>Ví dụ: <b>萧炎</b> → <b>Tiêu Viêm</b>, <b>乌坦城</b> → <b>Ô Thản Thành</b>. Bộ dịch AI nhận bảng này như chỉ dẫn bắt buộc;
          với Google Dịch, cụm gốc được thay bằng bản dịch đã chốt trước khi gửi đi.</div>
      </div>

      <div class="card">
        <div class="card-head">
          <input class="input" style="max-width: 280px" v-model="filter" placeholder="Tìm thuật ngữ…">
          <span class="muted small grow" v-if="items">{{ clean().length }} thuật ngữ<span v-if="dirty"> · có thay đổi chưa lưu</span></span>
          <button class="btn btn-sm" @click="add"><icon name="plus"></icon>Thêm dòng</button>
        </div>
        <div v-if="items === null" class="empty"><icon name="loader-circle" :size="24" spin></icon></div>
        <div v-else-if="!items.length" class="empty">
          <icon name="book-open" :size="36"></icon>
          <div>Chưa có thuật ngữ nào.</div>
          <button class="btn btn-sm" style="margin-top: 10px" @click="add"><icon name="plus"></icon>Thêm thuật ngữ đầu tiên</button>
        </div>
        <table v-else class="table">
          <thead><tr><th style="width: 30%">Từ gốc (tiếng Trung)</th><th style="width: 30%">Dịch thành</th><th>Ghi chú (tuỳ chọn)</th><th style="width: 44px"></th></tr></thead>
          <tbody>
            <tr v-for="(t, i) in shown" :key="i">
              <td><input class="input" v-model="t.source" placeholder="萧炎" lang="zh"></td>
              <td><input class="input" v-model="t.target" placeholder="Tiêu Viêm"></td>
              <td><input class="input" v-model="t.note" placeholder="nam chính"></td>
              <td><button class="btn btn-ghost btn-icon btn-sm" @click="remove(t)" title="Xoá dòng"><icon name="trash-2"></icon></button></td>
            </tr>
          </tbody>
        </table>
      </div>

      <modal v-if="bulk" title="Nhập nhanh thuật ngữ" icon="file-text" @close="bulk = false">
        <p class="muted small" style="margin-bottom: 8px">Mỗi dòng một thuật ngữ theo dạng <code class="mono">từ gốc = bản dịch</code>. Nội dung dưới đây sẽ thay toàn bộ bảng hiện tại.</p>
        <textarea v-model="bulkText" rows="14" class="mono" placeholder="萧炎 = Tiêu Viêm&#10;乌坦城 = Ô Thản Thành"></textarea>
        <template #foot>
          <button class="btn" @click="bulk = false">Huỷ</button>
          <button class="btn btn-primary" @click="applyBulk">Lưu bảng thuật ngữ</button>
        </template>
      </modal>
    </div>`,
};
