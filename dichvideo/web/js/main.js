// Khung ứng dụng: thanh bên, điều hướng theo #hash, nạp thông tin hệ thống.
import { commonComponents, ConfirmHost, Toasts, injectSubtitleFonts, loadSettings, loadSystem, setTheme, store, toastError } from "./common.js";
import { ProjectsPage } from "./pages/projects.js";
import { WorkspacePage } from "./pages/workspace.js";
import { SettingsPage } from "./pages/settings.js";
import { GlossaryPage } from "./pages/glossary.js";
import { HelpPage } from "./pages/help.js";

const { createApp } = Vue;

function parseRoute() {
  const hash = (location.hash || "#/").replace(/^#/, "");
  const parts = hash.split("/").filter(Boolean);
  if (parts[0] === "p" && parts[1]) return { name: "workspace", id: parts[1], tab: parts[2] || "" };
  if (parts[0] === "settings") return { name: "settings" };
  if (parts[0] === "glossary") return { name: "glossary" };
  if (parts[0] === "help") return { name: "help" };
  return { name: "projects" };
}

const App = {
  components: { ...commonComponents, Toasts, ConfirmHost, ProjectsPage, WorkspacePage, SettingsPage, GlossaryPage, HelpPage },
  data: () => ({ store, route: parseRoute(), ready: false, bootError: "" }),
  computed: {
    nav() {
      return [
        { name: "projects", href: "#/", icon: "clapperboard", label: "Dự án" },
        { name: "glossary", href: "#/glossary", icon: "book-open", label: "Thuật ngữ" },
        { name: "settings", href: "#/settings", icon: "settings", label: "Cài đặt" },
        { name: "help", href: "#/help", icon: "circle-help", label: "Hướng dẫn" },
      ];
    },
    activeNav() { return this.route.name === "workspace" ? "projects" : this.route.name; },
    sys() { return store.system; },
  },
  async created() {
    window.addEventListener("hashchange", () => { this.route = parseRoute(); window.scrollTo(0, 0); });
    try {
      await Promise.all([loadSystem(), loadSettings()]);
      injectSubtitleFonts(store.system.fonts);
      this.ready = true;
    } catch (e) {
      this.bootError = e.message || String(e);
    }
  },
  methods: {
    toggleTheme() { setTheme(store.theme === "dark" ? "light" : "dark"); },
    async retry() {
      this.bootError = "";
      try { await Promise.all([loadSystem(), loadSettings()]); injectSubtitleFonts(store.system.fonts); this.ready = true; }
      catch (e) { this.bootError = e.message || String(e); toastError(e); }
    },
  },
  template: `
    <div class="app">
      <aside class="sidebar">
        <a class="brand" href="#/" style="text-decoration: none; color: inherit">
          <div class="brand-mark"><icon name="play" :size="18"></icon></div>
          <div>
            <div class="brand-name">Dịch Video Studio</div>
            <div class="brand-sub">Tiếng Trung → Tiếng Việt</div>
          </div>
        </a>
        <nav class="nav">
          <a v-for="n in nav" :key="n.name" :href="n.href" :class="{ active: activeNav === n.name }">
            <icon :name="n.icon" :size="18"></icon><span>{{ n.label }}</span>
          </a>
        </nav>
        <div class="sidebar-foot">
          <div class="sys-card" v-if="sys">
            <div class="line"><i class="dot" :class="sys.ffmpeg.ok ? 'ok' : 'bad'"></i>
              <span>{{ sys.ffmpeg.ok ? 'Bộ xử lý video sẵn sàng' : 'Thiếu ffmpeg' }}</span></div>
            <div class="line"><i class="dot" :class="sys.gpu ? 'ok' : 'warn'"></i>
              <span>{{ sys.gpu ? 'Tăng tốc bằng card NVIDIA' : 'Chạy bằng CPU (' + sys.cpu_count + ' luồng)' }}</span></div>
            <div class="line muted" style="margin-top: 4px">Phiên bản {{ sys.version }}</div>
          </div>
          <button class="btn btn-ghost btn-sm" @click="toggleTheme" :title="store.theme === 'dark' ? 'Chuyển giao diện sáng' : 'Chuyển giao diện tối'">
            <icon :name="store.theme === 'dark' ? 'sun' : 'moon'"></icon>
            <span>{{ store.theme === 'dark' ? 'Giao diện sáng' : 'Giao diện tối' }}</span>
          </button>
        </div>
      </aside>
      <main class="main">
        <div class="page" v-if="bootError">
          <div class="note err"><icon name="circle-alert"></icon>
            <div><b>Không nạp được ứng dụng.</b><br>{{ bootError }}<br>
              <button class="btn btn-sm" style="margin-top: 10px" @click="retry"><icon name="refresh-cw"></icon>Thử lại</button></div>
          </div>
        </div>
        <template v-else-if="ready">
          <workspace-page v-if="route.name === 'workspace'" :key="route.id" :project-id="route.id" :initial-tab="route.tab"></workspace-page>
          <settings-page v-else-if="route.name === 'settings'"></settings-page>
          <glossary-page v-else-if="route.name === 'glossary'"></glossary-page>
          <help-page v-else-if="route.name === 'help'"></help-page>
          <projects-page v-else></projects-page>
        </template>
        <div class="page" v-else><div class="empty"><icon name="loader-circle" :size="28" spin></icon><div>Đang khởi động…</div></div></div>
      </main>
      <toasts></toasts>
      <confirm-host></confirm-host>
    </div>`,
};

createApp(App).mount("#app");
