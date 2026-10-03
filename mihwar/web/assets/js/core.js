// Mihwar UI core: API client, formatting, icons, toasts, drawer, shared components.
export const state = { meta: null, users: [], user: null, leave: [] };

// ------------------------------------------------------------------ API
export class ApiError extends Error {
  constructor(status, detail) {
    super((detail && (detail.message_ar || detail.message_en)) || `HTTP ${status}`);
    this.status = status;
    this.code = detail && detail.code;
    this.runId = detail && detail.run_id;
    this.detail = detail || {};
  }
}

export async function api(method, path, body, { form = false } = {}) {
  const headers = {};
  if (state.user) headers["X-Demo-User"] = String(state.user.id);
  let payload;
  if (body !== undefined && body !== null) {
    if (form) payload = body;
    else { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
  }
  const res = await fetch(path, { method, headers, body: payload });
  let data = null;
  const text = await res.text();
  try { data = text ? JSON.parse(text) : null; } catch { data = null; }
  if (!res.ok) throw new ApiError(res.status, data && data.detail);
  return data;
}
export const get = (p) => api("GET", p);
export const post = (p, b = {}) => api("POST", p, b);
export const patch = (p, b = {}) => api("PATCH", p, b);

// ------------------------------------------------------------------ formatting (Western digits)
const NF = new Intl.NumberFormat("en-US");
const NF1 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });
export const num = (v) => (v === null || v === undefined || v === "" ? "—" : NF.format(Math.round(Number(v))));
export const num1 = (v) => (v === null || v === undefined ? "—" : NF1.format(Number(v)));
export const money = (v) => `${num(v)} ريال`;
const MONTHS = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"];
export function date(iso, withYear = true) {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return `${d} ${MONTHS[m - 1]}${withYear ? " " + y : ""}`;
}
export const shortDate = (iso) => date(iso, false);
export function time(iso) {
  if (!iso) return "";
  const t = iso.slice(11, 16);
  const today = (state.meta && state.meta.today) || "";
  return iso.slice(0, 10) === today ? t : `${shortDate(iso)} ${t}`;
}
export function bytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${num1(n / 1024)} KB`;
  return `${num1(n / 1024 / 1024)} MB`;
}
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const ltr = (s) => `<span class="ltr">${esc(s)}</span>`;

// ------------------------------------------------------------------ icons (simple line icons)
const svg = (d, extra = "") => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" ${extra}>${d}</svg>`;
export const icons = {
  dashboard: svg('<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>'),
  portal: svg('<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.5 5.6 12 3z"/>'),
  projects: svg('<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'),
  team: svg('<circle cx="9" cy="8" r="3.2"/><path d="M3.5 19c.6-3 2.8-4.8 5.5-4.8s4.9 1.8 5.5 4.8"/><circle cx="17" cy="9" r="2.4"/><path d="M15.5 14.4c2.4.1 4.2 1.7 4.8 4.6"/>'),
  files: svg('<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h4"/>'),
  compliance: svg('<path d="M9 4h6v3H9z"/><path d="M15 5h2a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h2"/><path d="m9 14 2 2 4-4"/>'),
  security: svg('<path d="M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6z"/><path d="M9.5 12l1.8 1.8L15 10"/>'),
  agents: svg('<rect x="7" y="7" width="10" height="10" rx="2"/><path d="M10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4"/>'),
  orchestrator: svg('<circle cx="12" cy="12" r="2.6"/><circle cx="5" cy="5" r="1.8"/><circle cx="19" cy="5" r="1.8"/><circle cx="5" cy="19" r="1.8"/><circle cx="19" cy="19" r="1.8"/><path d="M6.5 6.5l3.6 3.6M17.5 6.5l-3.6 3.6M6.5 17.5l3.6-3.6M17.5 17.5l-3.6-3.6"/>'),
  intake: svg('<path d="M4 5h16v10H9l-5 4z"/><path d="M8 9h8M8 12h5"/>'),
  proposal: svg('<path d="M6 3h12v18l-3-2-3 2-3-2-3 2z"/><path d="M9 8h6M9 12h6M9 16h3"/>'),
  planner: svg('<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4M7 14h5M10 17h7"/>'),
  documents: svg('<path d="M8 3h8l4 4v12a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M4 7v12a2 2 0 0 0 2 2"/><path d="M16 3v4h4"/>'),
  reporting: svg('<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>'),
  play: svg('<path d="M7 4.5v15l12-7.5z" fill="currentColor"/>'),
  check: svg('<path d="m5 12.5 4.5 4.5L19 7.5"/>'),
  upload: svg('<path d="M12 16V4M7 9l5-5 5 5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/>'),
  download: svg('<path d="M12 4v12M7 11l5 5 5-5M4 20h16"/>'),
  send: svg('<path d="M21 3 10 14M21 3l-7 18-4-7-7-4z"/>'),
  refresh: svg('<path d="M20 11a8 8 0 0 0-14.6-4.5L4 8M4 4v4h4M4 13a8 8 0 0 0 14.6 4.5L20 16M20 20v-4h-4"/>'),
  alert: svg('<path d="M12 3 2 20h20z"/><path d="M12 10v4M12 17.5v.01"/>'),
  eye: svg('<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>'),
  flask: svg('<path d="M9 3h6M10 3v6L4.5 18.5A1.7 1.7 0 0 0 6 21h12a1.7 1.7 0 0 0 1.5-2.5L14 9V3"/><path d="M7 15h10"/>'),
};
export const agentIconKey = { orchestrator: "orchestrator", intake: "intake", proposal: "proposal", planner: "planner", team: "team", documents: "documents", compliance: "compliance", security: "security", reporting: "reporting" };
export function agentIco(key, status) {
  const cls = status === "denied" ? "denied" : status === "error" ? "error" : key === "security" ? "security" : "";
  return `<div class="agent-ico ${cls}">${icons[agentIconKey[key]] || icons.agents}</div>`;
}

// The axis-bubble motif (محور = axis): grid lines with A/B/C and 1/2/3 bubbles, like engineering drawings.
export function axesSVG(cls = "axes", stroke = "currentColor") {
  return `<svg class="${cls}" viewBox="0 0 280 200" fill="none" stroke="${stroke}" stroke-width="1.2">
    <path d="M60 26v170M140 26v170M220 26v170M26 70h248M26 130h248" stroke-dasharray="6 5"/>
    <circle cx="60" cy="14" r="11"/><circle cx="140" cy="14" r="11"/><circle cx="220" cy="14" r="11"/>
    <circle cx="14" cy="70" r="11"/><circle cx="14" cy="130" r="11"/>
    <g fill="${stroke}" stroke="none" font-family="Consolas, monospace" font-size="11" text-anchor="middle">
      <text x="60" y="18">A</text><text x="140" y="18">B</text><text x="220" y="18">C</text><text x="14" y="74">1</text><text x="14" y="134">2</text>
    </g></svg>`;
}
export const brandSVG = `<svg class="brand-mark" viewBox="0 0 40 40" fill="none">
  <rect x="1" y="1" width="38" height="38" rx="10" fill="#0F766E"/>
  <path d="M13 8v24M27 8v24M8 15h24M8 25h24" stroke="#14B8A6" stroke-width="1.6" stroke-dasharray="3 2.5"/>
  <circle cx="20" cy="20" r="6.5" fill="#0B1F33" stroke="#C8A24A" stroke-width="1.8"/>
  <circle cx="20" cy="20" r="2" fill="#C8A24A"/></svg>`;

// ------------------------------------------------------------------ small components
export const pill = (cls, label) => `<span class="pill ${esc(cls)}">${esc(label)}</span>`;
export const modeTag = (mode) => mode === "llm" ? `<span class="mode llm">Claude</span>` : mode === "offline-fallback" ? `<span class="mode offline-fallback">رجوع للوضع دون اتصال</span>` : `<span class="mode">دون اتصال</span>`;
export const progress = (p, lg = false) => `<div class="progress ${lg ? "lg" : ""}"><span style="width:${Math.max(0, Math.min(100, p || 0))}%"></span></div>`;
export const ring = (p) => `<div class="ring" style="--p:${p || 0}"><span>${num(p)}%</span></div>`;
export function avatar(name, initials, sm = true) {
  const ini = initials || (name || "").replace(/^(م\.|أ\.)\s*/, "").split(/\s+/).slice(0, 2)
    .map((w) => (w.length > 3 && w.startsWith("ال") ? w[2] : w[0])).join(" ");
  return `<span class="avatar ${sm ? "sm" : ""}" title="${esc(name)}">${esc(ini)}</span>`;
}
export function empty(text, sub = "") {
  return `<div class="empty">${axesSVG("axes", "#94A3B8")}<div>${esc(text)}</div>${sub ? `<div class="small">${esc(sub)}</div>` : ""}</div>`;
}
export const loading = () => `<div class="loading-row"><span class="spinner"></span>&nbsp; جارٍ التحميل…</div>`;
export function kpiTile(k) {
  return `<div class="kpi ${k.estimate ? "estimate" : ""}" title="${esc(k.hint_ar || "")}">
    ${k.estimate ? `<span class="pill gold est">تقدير</span>` : ""}
    <div class="label">${esc(k.label_ar)}</div>
    <div class="value">${k.unit_ar === "%" ? num(k.value) + "%" : num1(k.value)}${k.unit_ar !== "%" ? `<span class="unit">${esc(k.unit_ar)}</span>` : ""}</div>
    ${k.hint_ar && !k.estimate ? `<div class="hint">${esc(k.hint_ar)}</div>` : ""}</div>`;
}

export function feedItem(s, isNew = false) {
  return `<div class="feed-item ${isNew ? "new" : ""}" data-run="${esc(s.run_id)}">
    ${agentIco(s.agent, s.status)}
    <div class="feed-main">
      <div class="feed-top"><span class="name">${esc(s.agent_name_ar)}</span><span class="ev">· ${esc(s.event_label_ar)}</span>
        ${s.status !== "ok" ? pill(s.status, s.status === "denied" ? "مرفوض" : "خطأ") : ""} ${modeTag(s.mode)}
        <span class="time">${esc(time(s.ts))}</span></div>
      <div class="feed-out">${esc(s.output_summary)}</div>
      <div class="feed-in">${esc(s.input_summary)}</div>
    </div></div>`;
}

export function traceHTML(steps) {
  if (!steps || !steps.length) return empty("لا توجد خطوات بعد");
  return `<div class="trace">${steps.map((s) => `
    <div class="trace-step">
      ${agentIco(s.agent, s.status)}
      <div class="body">
        <div class="head"><b>${esc(s.agent_name_ar)}</b><span class="muted small">${esc(s.agent_name_en)}</span>
          ${pill(s.status === "ok" ? "ok" : s.status, { ok: "نجح", denied: "مرفوض", error: "خطأ", skipped: "تخطٍّ" }[s.status] || s.status)}
          ${modeTag(s.mode)}<span class="muted small ltr">${num1(s.duration_ms)} ms</span></div>
        <div class="small muted">${esc(s.event_label_ar)} · ${esc(s.input_summary)}</div>
        <div>${esc(s.output_summary)}</div>
        ${s.input || s.output ? `<details><summary>المدخلات والمخرجات (JSON)</summary>
          <pre class="json">${esc(JSON.stringify({ input: s.input, output: s.output }, null, 2))}</pre></details>` : ""}
      </div></div>`).join("")}</div>`;
}

// ------------------------------------------------------------------ toast & drawer
export function toast(message, type = "", runId = null) {
  const root = document.getElementById("toast-root");
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.innerHTML = `<div>${esc(message)}${runId ? ` · <a href="#" data-run="${esc(runId)}">عرض سجل الوكلاء</a>` : ""}</div>`;
  root.appendChild(el);
  el.querySelector("a[data-run]")?.addEventListener("click", (e) => { e.preventDefault(); showRun(runId); });
  setTimeout(() => el.remove(), 6000);
}
export function errorToast(err) {
  if (err instanceof ApiError) toast(err.message, "error", err.runId);
  else { console.error(err); toast("حدث خطأ غير متوقع", "error"); }
}

export function drawer(title, subtitle, bodyHTML) {
  closeDrawer();
  const root = document.getElementById("drawer-root");
  root.innerHTML = `<div class="drawer-backdrop"></div><aside class="drawer" role="dialog">
    <div class="drawer-h"><div><h3>${title}</h3>${subtitle ? `<div class="muted small">${subtitle}</div>` : ""}</div><button class="x" aria-label="إغلاق">×</button></div>
    <div class="drawer-b">${bodyHTML}</div></aside>`;
  root.querySelector(".drawer-backdrop").onclick = closeDrawer;
  root.querySelector(".x").onclick = closeDrawer;
  return root.querySelector(".drawer-b");
}
export function closeDrawer() { const r = document.getElementById("drawer-root"); if (r) r.innerHTML = ""; }
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });

export async function showRun(runId) {
  const body = drawer("سجل الوكلاء لهذه العملية", ltr(runId), loading());
  try {
    const run = await get(`/api/runs/${encodeURIComponent(runId)}`);
    body.innerHTML = `<div class="kv" style="margin-bottom:12px">
        <span class="k">الحدث</span><span>${esc(run.event_label_ar)}</span>
        <span class="k">بواسطة</span><span>${esc(run.actor ? run.actor.name_ar + " (" + run.actor.role_label_ar + ")" : "النظام")}</span>
        <span class="k">النتيجة</span><span>${pill(run.status === "ok" ? "ok" : run.status, run.status_label_ar)}</span>
        <span class="k">المدة</span><span class="ltr">${num1(run.duration_ms)} ms</span>
        ${run.emitted && run.emitted.length ? `<span class="k">أحداث متسلسلة</span><span>${run.emitted.map((e) => `<span class="tag ltr">${esc(e)}</span>`).join("")}</span>` : ""}
      </div>${traceHTML(run.steps)}`;
  } catch (e) {
    body.innerHTML = empty("تعذّر تحميل السجل", e.message);
  }
}

export function onLeave(fn) { state.leave.push(fn); }
export function runLeave() { state.leave.splice(0).forEach((fn) => { try { fn(); } catch {} }); }

export function bindRuns(root) {
  root.querySelectorAll("[data-run]").forEach((el) => {
    if (el.dataset.bound) return;
    el.dataset.bound = "1";
    el.addEventListener("click", (e) => {
      if (e.target.closest("button, a:not([data-run])")) return;
      e.preventDefault(); showRun(el.dataset.run);
    });
  });
}

export async function downloadDoc(id, filename) {
  const headers = state.user ? { "X-Demo-User": String(state.user.id) } : {};
  const res = await fetch(`/api/files/${id}/download`, { headers });
  if (!res.ok) {
    let detail = null;
    try { detail = (await res.json()).detail; } catch {}
    throw new ApiError(res.status, detail);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename || "file";
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export async function withBusy(btn, fn) {
  if (btn) btn.classList.add("loading");
  try { return await fn(); } catch (e) { errorToast(e); } finally { if (btn) btn.classList.remove("loading"); }
}

export const can = {
  manager: () => state.user && state.user.role === "manager",
  engineer: () => state.user && state.user.role === "engineer",
  client: () => state.user && state.user.role === "client",
  staff: () => state.user && state.user.role !== "client",
};
