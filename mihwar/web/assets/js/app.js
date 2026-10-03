// Mihwar SPA shell: identity (demo role switcher), navigation, hash router.
import { state, get, esc, icons, brandSVG, runLeave, errorToast, closeDrawer } from "./core.js";
import * as portal from "./views/portal.js";
import * as dashboard from "./views/dashboard.js";
import * as projects from "./views/projects.js";
import * as team from "./views/team.js";
import * as files from "./views/files.js";
import * as compliance from "./views/compliance.js";
import * as security from "./views/security.js";
import * as agents from "./views/agents.js";

const ROUTES = {
  dashboard: { view: dashboard, title: "لوحة المكتب", sub: "مؤشرات الأداء ونشاط الوكلاء لحظة بلحظة", icon: "dashboard", roles: ["manager", "engineer"] },
  portal: { view: portal, title: "بوابة العملاء", sub: "خدمات المكتب عن بُعد على مدار الساعة", icon: "portal", roles: ["manager", "client"] },
  projects: { view: projects, title: "المشاريع", sub: "الخطط الزمنية والمهام والملفات والجودة", icon: "projects", roles: ["manager", "engineer"] },
  team: { view: team, title: "الفريق والموارد", sub: "أحمال العمل الأسبوعية وتنبيهات الضغط", icon: "team", roles: ["manager", "engineer"] },
  files: { view: files, title: "الملفات الهندسية", sub: "سجل الوثائق والإصدارات ومراحل الاعتماد (CDE)", icon: "files", roles: ["manager", "engineer"] },
  compliance: { view: compliance, title: "المراجعة والامتثال", sub: "فحص الاشتراطات واكتمال المخرجات وتوقيع المهندس المرخّص", icon: "compliance", roles: ["manager", "engineer"] },
  security: { view: security, title: "الأمن والصلاحيات", sub: "سجل التدقيق والتنبيهات ومصفوفة الصلاحيات", icon: "security", roles: ["manager"] },
  agents: { view: agents, title: "الوكلاء", sub: "فريق الوكلاء الأذكياء الذي يدير المنصة، واختباراتهم، والسيناريو الكامل", icon: "agents", roles: ["manager", "engineer"] },
};
const NAV_ORDER = ["dashboard", "portal", "projects", "team", "files", "compliance", "security", "agents"];
const ROLE_LABEL = { manager: "مدير المكتب", engineer: "مهندس", client: "عميل" };

function store(key, value) { try { if (value === undefined) return localStorage.getItem(key); localStorage.setItem(key, value); } catch { return null; } }

function pickIdentity() {
  const params = new URLSearchParams(location.search);
  const byId = (id) => state.users.find((u) => String(u.id) === String(id));
  const byRole = (r) => state.users.find((u) => u.role === r && u.default_for_role) || state.users.find((u) => u.role === r);
  return byId(params.get("user")) || (params.get("role") && byRole(params.get("role"))) || byId(store("mihwar.user")) || byRole("manager");
}

function defaultRoute() { return state.user.role === "client" ? "portal" : "dashboard"; }

function renderShell() {
  document.getElementById("brand").innerHTML = `${brandSVG}<div><div class="brand-name">محور</div><div class="brand-sub">المكتب الهندسي السحابي</div></div>`;
  const allowed = NAV_ORDER.filter((k) => ROUTES[k].roles.includes(state.user.role));
  const label = state.user.role === "client" ? "بوابتي" : "المنصة";
  document.getElementById("nav").innerHTML = `<div class="nav-label">${label}</div>` + allowed.map((k) =>
    `<a href="#/${k}" data-route="${k}">${icons[ROUTES[k].icon]}<span>${state.user.role === "client" && k === "portal" ? "بوابتي" : ROUTES[k].title}</span></a>`).join("");
  document.getElementById("sidebar-foot").innerHTML = `<div class="office">${esc(state.meta.office.name_ar)}</div>
    <div>مكتب افتراضي للعرض · v${esc(state.meta.app.version)}</div>`;
  const m = state.meta.mode;
  document.getElementById("mode-chip").innerHTML = m.llm_enabled
    ? `<span class="chip mode-llm" title="${esc(m.model || "")}"><span class="dot"></span>وضع Claude</span>`
    : `<span class="chip mode-offline" title="يعمل دون إنترنت بمنطق محدد؛ فعّل Claude عبر MIHWAR_LLM=on"><span class="dot"></span>دون اتصال · منطق محدد</span>`;
  const sameRole = state.users.filter((u) => u.role === state.user.role);
  document.getElementById("roles").innerHTML = `
    <div class="seg" role="tablist" aria-label="تبديل الدور">${["manager", "engineer", "client"].map((r) =>
      `<button data-role="${r}" class="${state.user.role === r ? "on" : ""}">${ROLE_LABEL[r]}</button>`).join("")}</div>
    <div class="who"><span class="avatar">${esc(state.user.initials)}</span>
      <select id="who-select" aria-label="الهوية التجريبية">${sameRole.map((u) =>
        `<option value="${u.id}" ${u.id === state.user.id ? "selected" : ""}>${esc(u.name_ar)}</option>`).join("")}</select></div>`;
  document.querySelectorAll("#roles [data-role]").forEach((b) => b.addEventListener("click", () => {
    const r = b.dataset.role;
    setUser(state.users.find((u) => u.role === r && u.default_for_role) || state.users.find((u) => u.role === r), true);
  }));
  document.getElementById("who-select").addEventListener("change", (e) => setUser(state.users.find((u) => String(u.id) === e.target.value), false));
}

function setUser(u, goHome) {
  if (!u) return;
  state.user = u;
  store("mihwar.user", String(u.id));
  renderShell();
  const route = (location.hash.replace(/^#\/?/, "").split("/")[0]) || "";
  if (goHome || !ROUTES[route] || !ROUTES[route].roles.includes(u.role)) location.hash = `#/${defaultRoute()}`;
  else route_();
}

async function route_() {
  runLeave();
  closeDrawer();
  const [path, query] = location.hash.replace(/^#\/?/, "").split("?");
  const parts = path.split("/").filter(Boolean);
  let key = parts[0] || defaultRoute();
  if (!ROUTES[key] || !ROUTES[key].roles.includes(state.user.role)) {
    location.replace(`#/${defaultRoute()}`);
    return;
  }
  const r = ROUTES[key];
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.route === key));
  document.getElementById("page-title").textContent = state.user.role === "client" && key === "portal" ? "بوابتي" : r.title;
  document.getElementById("page-sub").textContent = r.sub;
  const el = document.getElementById("view");
  el.innerHTML = `<div class="loading-row"><span class="spinner"></span>&nbsp; جارٍ التحميل…</div>`;
  try {
    await r.view.render(el, parts.slice(1), new URLSearchParams(query || ""));
  } catch (e) {
    errorToast(e);
    el.innerHTML = `<div class="card"><div class="card-b">تعذّر تحميل الصفحة: ${esc(e.message)}</div></div>`;
  }
  window.scrollTo(0, 0);
}

async function boot() {
  try {
    const [meta, users] = await Promise.all([get("/api/meta"), get("/api/demo/users")]);
    state.meta = meta;
    state.users = users.items;
    state.user = pickIdentity();
    renderShell();
    window.addEventListener("hashchange", route_);
    if (!location.hash || location.hash === "#" || location.hash === "#/") location.replace(`#/${defaultRoute()}`);
    else route_();
  } catch (e) {
    document.getElementById("view").innerHTML = `<div class="card"><div class="card-b">تعذّر الاتصال بالخادم. تأكد من تشغيل محور (run.bat).</div></div>`;
  }
}

boot();
