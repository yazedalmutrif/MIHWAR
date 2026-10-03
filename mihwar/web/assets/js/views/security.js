// Security: alerts, simulations, audit log, roles matrix.
import { get, post, esc, num, time, pill, empty, toast, withBusy, icons } from "../core.js";

export async function render(el) {
  const [alerts, audit, roles] = await Promise.all([get("/api/security/alerts"), get("/api/security/audit?limit=60"), get("/api/security/roles")]);
  const open = alerts.items.filter((a) => a.status === "open").length;
  const denies = audit.items.filter((a) => a.decision === "deny").length;
  const cell = (v) => ({ allow: pill("ok", "✓"), deny: pill("grey", "—"), assigned: pill("teal", "المسند"), own: pill("teal", "الخاص به"), published: pill("teal", "المنشور"), licensed: pill("gold", "المرخّص") }[v] || esc(v));
  el.innerHTML = `
    <div class="kpis" style="margin-bottom:16px">
      <div class="kpi"><div class="label">تنبيهات مفتوحة</div><div class="value" style="color:${open ? "var(--danger)" : "var(--ink)"}">${num(open)}</div></div>
      <div class="kpi"><div class="label">قرارات منع (آخر 60 عملية)</div><div class="value">${num(denies)}</div></div>
      <div class="kpi"><div class="label">سجلات التدقيق</div><div class="value">${num(audit.total)}</div></div>
      <div class="kpi"><div class="label">قواعد الصلاحيات</div><div class="value">${num(roles.permissions.length)}</div></div>
    </div>
    <div class="grid main-side">
      <div class="card"><div class="card-h"><h3>التنبيهات الأمنية</h3><span class="sub">يطلقها وكيل الأمن عند السلوك غير المعتاد</span></div>
        <div class="card-b flush">${alerts.items.length ? `<table class="t"><tbody>${alerts.items.map((a) => `<tr>
          <td>${pill(a.severity, a.severity_label_ar)}</td><td><b class="small">${esc(a.type_label_ar)}</b><div class="small">${esc(a.message_ar)}</div>
          <div class="small muted">${esc(time(a.ts))} · <span class="mono">${esc(a.resource)}</span></div></td>
          <td class="nowrap">${a.status === "open" ? `<button class="btn sm" data-ack="${a.id}">تمت المعالجة</button>` : pill("acknowledged", a.status_label_ar)}</td></tr>`).join("")}</tbody></table>` : empty("لا توجد تنبيهات")}</div></div>
      <div class="card" style="align-self:start"><div class="card-h"><h3>اختبر وكيل الأمن</h3></div><div class="card-b">
        <p class="small muted" style="margin-top:0">تنفّذ المحاكاة محاولة حقيقية بهوية تجريبية، ويقرر وكيل الأمن ويسجّل ويطلق التنبيه.</p>
        <div style="display:flex;flex-direction:column;gap:8px">
          <button class="btn" data-sim="client_wip">${icons.alert}<span>عميل يحاول تنزيل ملف غير منشور</span></button>
          <button class="btn" data-sim="unassigned_access">${icons.alert}<span>مهندس يفتح مشروعًا غير مسند إليه</span></button>
          <button class="btn" data-sim="burst_download">${icons.alert}<span>تنزيل جماعي سريع للملفات</span></button>
        </div><div id="sim-out" style="margin-top:12px"></div></div></div>
    </div>
    <div class="grid g2" style="margin-top:16px">
      <div class="card"><div class="card-h"><h3>سجل التدقيق</h3><span class="sub">كل قرار سماح أو منع</span>
        <div class="actions"><select class="input" id="dec"><option value="">الكل</option><option value="deny">المنع فقط</option><option value="allow">السماح فقط</option></select></div></div>
        <div class="card-b flush" style="max-height:520px;overflow:auto" id="audit"></div></div>
      <div class="card"><div class="card-h"><h3>مصفوفة الصلاحيات</h3><span class="sub">يطبقها وكيل الأمن على كل عملية</span></div>
        <div class="card-b flush" style="max-height:520px;overflow:auto"><table class="t"><thead><tr><th>العملية</th>${roles.roles.map((r) => `<th>${esc(r.label_ar)}</th>`).join("")}</tr></thead><tbody>
          ${roles.permissions.map((p) => `<tr><td class="small">${esc(p.label_ar)}</td><td>${cell(p.manager)}</td><td>${cell(p.engineer)}</td><td>${cell(p.client)}</td></tr>`).join("")}</tbody></table>
          <div class="small muted" style="padding:10px 14px">${Object.entries(roles.legend_ar).map(([k, v]) => `${cell(k)} ${esc(v)}`).join(" · ")}</div></div></div>
    </div>`;
  const drawAudit = (items) => {
    el.querySelector("#audit").innerHTML = items.length ? `<table class="t"><tbody>${items.map((a) => `<tr>
      <td>${pill(a.decision, a.decision === "allow" ? "سماح" : "منع")}</td>
      <td class="small"><b>${esc(a.action_label_ar)}</b> · <span class="mono">${esc(a.resource)}</span><div class="muted">${esc(a.reason_ar)}</div></td>
      <td class="small muted nowrap">${esc(a.actor ? a.actor.name_ar : "—")}<div>${esc(time(a.ts))}</div></td></tr>`).join("")}</tbody></table>` : empty("لا سجلات");
  };
  drawAudit(audit.items);
  el.querySelector("#dec").addEventListener("change", async (e) => drawAudit((await get(`/api/security/audit?limit=60${e.target.value ? "&decision=" + e.target.value : ""}`)).items));
  el.querySelectorAll("[data-ack]").forEach((b) => b.addEventListener("click", () => withBusy(b, async () => {
    const r = await post(`/api/security/alerts/${b.dataset.ack}/ack`);
    toast("أُغلق التنبيه وسُجّلت المعالجة", "ok", r.run.run_id);
    render(el);
  })));
  el.querySelectorAll("[data-sim]").forEach((b) => b.addEventListener("click", () => withBusy(b, async () => {
    const r = await post("/api/security/simulate", { kind: b.dataset.sim });
    toast(r.decision === "deny" ? "منع وكيل الأمن المحاولة" : "سُمح بالعمليات مع رصد النمط", r.alert ? "ok" : "", r.run.run_id);
    await render(el);
    el.querySelector("#sim-out").innerHTML = `<div class="notice ${r.decision === "deny" ? "" : "info"}" style="margin:0">${esc(r.attempt_ar)}<br>
      القرار: <b>${r.decision === "deny" ? "منع" : "سماح"}</b>${r.alert ? ` · تنبيه: ${esc(r.alert.message_ar)}` : ""}</div>`;
  })));
}
