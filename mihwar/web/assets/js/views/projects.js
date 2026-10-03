// Projects list and project detail (Gantt, tasks, files, QA, reports, data & approvals).
import { get, post, patch, esc, num, num1, date, shortDate, time, pill, progress, ring, empty, toast, withBusy, avatar, can, state,
  icons, downloadDoc, bytes } from "../core.js";
import { openProposal, openReport, reportBody } from "./shared.js";
import { mountUpload } from "./upload.js";

export async function render(el, params) {
  if (params[0]) return renderDetail(el, +params[0]);
  const data = await get("/api/projects");
  el.innerHTML = `<div class="card"><div class="card-h"><h3>المشاريع</h3><span class="sub">${can.engineer() ? "المشاريع المسندة إليك فقط (صلاحيات وكيل الأمن)" : "كل مشاريع المكتب"}</span></div>
    <div class="card-b flush">${data.items.length ? `<table class="t"><thead><tr><th>المشروع</th><th>العميل</th><th>المرحلة</th><th>الحالة</th><th style="width:160px">الإنجاز</th><th>الفريق</th><th>ملاحظات الجودة</th><th>المعلم القادم</th></tr></thead><tbody>
      ${data.items.map((p) => `<tr class="click" data-id="${p.id}">
        <td><b>${esc(p.name_ar)}</b><div class="small muted"><span class="ltr">${esc(p.code)}</span> · ${esc(p.type_label_ar)} · ${esc(p.city)}</div></td>
        <td class="small">${esc(p.client.name_ar)}</td><td>${pill("teal", p.status_label_ar)}</td><td>${pill(p.health, p.health_label_ar)}</td>
        <td><div style="display:flex;gap:8px;align-items:center"><div style="flex:1">${progress(p.progress)}</div><span class="small ltr">${num(p.progress)}%</span></div></td>
        <td><span class="avatars">${p.team.slice(0, 5).map((m) => avatar(m.name_ar)).join("")}</span></td>
        <td>${p.open_issues ? pill("warn", num(p.open_issues)) : `<span class="muted small">—</span>`}</td>
        <td class="small">${p.next_milestone ? `${esc(p.next_milestone.name_ar)}<div class="muted">${date(p.next_milestone.date)}</div>` : "—"}</td></tr>`).join("")}
    </tbody></table>` : `${empty("لا توجد مشاريع مسندة")}`}</div></div>`;
  el.querySelectorAll("tr[data-id]").forEach((r) => r.addEventListener("click", () => { location.hash = `#/projects/${r.dataset.id}`; }));
}

const TABS = [["gantt", "الجدول الزمني"], ["tasks", "المهام"], ["files", "الملفات"], ["qa", "الجودة والامتثال"], ["reports", "التقارير"], ["data", "البيانات والاعتمادات"]];

async function renderDetail(el, id, tab = "gantt") {
  const d = await get(`/api/projects/${id}`);
  const p = d.project;
  el.innerHTML = `
    <div class="card" style="margin-bottom:16px"><div class="card-b" style="display:flex;gap:18px;align-items:center;flex-wrap:wrap">
      ${ring(p.progress)}
      <div style="flex:1;min-width:240px">
        <div class="small muted"><a href="#/projects">المشاريع</a> / <span class="ltr">${esc(p.code)}</span></div>
        <h2 style="font-size:20px">${esc(p.name_ar)}</h2>
        <div class="small muted">${esc(p.client.name_ar)} · ${esc(p.type_label_ar)} · ${esc(p.city)}${p.district ? " – " + esc(p.district) : ""} · ${date(p.start_date)} ← ${date(p.end_date)}</div>
      </div>
      <div style="display:flex;gap:6px;flex-wrap:wrap">${pill("teal", p.status_label_ar)} ${pill(p.health, p.health_label_ar)}
        ${p.open_issues ? pill("warn", "ملاحظات جودة: " + num(p.open_issues)) : ""}</div>
      <span class="avatars">${p.team.map((m) => avatar(m.name_ar)).join("")}</span>
    </div></div>
    <div class="tabs">${TABS.map(([k, l]) => `<button data-tab="${k}" class="${k === tab ? "on" : ""}">${l}</button>`).join("")}</div>
    <div id="tab"></div>`;
  const pane = el.querySelector("#tab");
  const show = (k) => {
    el.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === k));
    ({ gantt, tasks, files, qa, reports, data })[k](pane, d, () => renderDetail(el, id, k));
  };
  el.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => show(b.dataset.tab)));
  show(tab);
}

// ------------------------------------------------------------------ gantt (time flows right -> left)
function gantt(pane, d) {
  const tasks = d.tasks;
  if (!tasks.length) { pane.innerHTML = `<div class="card">${empty("لا توجد خطة بعد")}</div>`; return; }
  const day = (s) => Date.UTC(+s.slice(0, 4), +s.slice(5, 7) - 1, +s.slice(8, 10)) / 86400000;
  const min = Math.min(...tasks.map((t) => day(t.start)));
  const max = Math.max(...tasks.map((t) => day(t.end))) + 1;
  const span = max - min;
  const pos = (s) => ((day(s) - min) / span) * 100;
  const width = (s, e) => ((day(e) + 1 - day(s)) / span) * 100;
  const months = [];
  let cur = new Date(min * 86400000);
  cur = new Date(Date.UTC(cur.getUTCFullYear(), cur.getUTCMonth(), 1));
  while (cur.getTime() / 86400000 < max) {
    const next = new Date(Date.UTC(cur.getUTCFullYear(), cur.getUTCMonth() + 1, 1));
    const s = Math.max(min, cur.getTime() / 86400000), e = Math.min(max, next.getTime() / 86400000);
    months.push({ right: ((s - min) / span) * 100, w: ((e - s) / span) * 100, label: shortDate(cur.toISOString().slice(0, 10)).split(" ")[1] + " " + cur.getUTCFullYear() });
    cur = next;
  }
  const today = state.meta.today;
  const tpos = day(today) >= min && day(today) <= max ? ((day(today) - min) / span) * 100 : null;
  const rows = [];
  d.phases.forEach((ph) => {
    rows.push(`<div class="g-row g-phase"><div class="g-label">${esc(ph.name_ar)} <span class="muted small ltr">${num(ph.progress)}%</span></div>
      <div class="g-track"><div class="g-phasebar" style="right:${pos(ph.start)}%;width:${width(ph.start, ph.end)}%"></div></div></div>`);
    tasks.filter((t) => t.phase === ph.key).forEach((t) => {
      const tip = `${t.name_ar} · ${t.start} → ${t.end} · ${t.assignee ? t.assignee.name_ar : "—"} · ${t.progress}%`;
      rows.push(`<div class="g-row"><div class="g-label" title="${esc(tip)}">${t.assignee ? avatar(t.assignee.name_ar) : ""} ${esc(t.name_ar)}</div>
        <div class="g-track">${t.is_milestone ? `<div class="g-ms" style="right:${pos(t.start) + width(t.start, t.end) / 2}%" title="${esc(tip)}"></div>`
          : `<div class="g-bar d-${t.discipline}" style="right:${pos(t.start)}%;width:${width(t.start, t.end)}%" title="${esc(tip)}"><span style="width:${t.progress}%"></span></div>`}</div></div>`);
    });
  });
  pane.innerHTML = `<div class="notice">${esc(d.planner_notice_ar)} · أيام العمل ${esc(d.calendar.working_days_ar)}</div>
    <div class="card"><div class="gantt"><div class="gantt-inner">
      <div class="g-head"><div class="g-label">المرحلة / المهمة</div><div class="g-track g-months">${months.map((m) => `<div class="g-month" style="right:${m.right}%;width:${m.w}%">${esc(m.label)}</div>`).join("")}</div></div>
      <div style="position:relative">${rows.join("")}
        ${tpos !== null ? `<div style="position:absolute;top:0;bottom:0;left:0;right:260px;pointer-events:none"><div class="g-today" style="right:${tpos}%"></div></div>` : ""}</div>
    </div></div>
    <div class="g-legend"><span><i style="background:var(--primary-light)"></i>معماري</span><span><i style="background:#6366F1"></i>إنشائي</span>
      <span><i style="background:#F59E0B"></i>كهرباء</span><span><i style="background:#3B82F6"></i>ميكانيكا</span><span><i style="background:#06B6D4"></i>سباكة</span>
      <span><i style="background:#64748B"></i>عام</span><span><i style="background:var(--accent)"></i>معلم</span></div></div>`;
}

// ------------------------------------------------------------------ tasks
function tasks(pane, d, reload) {
  const editable = (t) => can.manager() || (t.assignee && t.assignee.id === state.user.id);
  pane.innerHTML = `<div class="card"><div class="card-b flush"><table class="t"><thead><tr><th>المهمة</th><th>التخصص</th><th>المسؤول</th><th>المدة</th><th>الساعات</th><th>الحالة</th><th>الإنجاز</th><th></th></tr></thead><tbody>
    ${d.tasks.map((t) => `<tr data-task="${t.id}"><td>${t.is_milestone ? "◆ " : ""}${esc(t.name_ar)}<div class="small muted">${esc(t.phase_name_ar)}</div></td>
      <td class="small">${esc(t.discipline_label_ar)}</td><td class="small">${t.assignee ? esc(t.assignee.name_ar) : "—"}</td>
      <td class="small nowrap">${shortDate(t.start)} – ${shortDate(t.end)}<div class="muted">${num(t.duration_days)} يوم عمل</div></td><td class="small ltr">${num1(t.hours)}</td>
      <td>${editable(t) && !t.is_milestone ? `<select class="input" data-f="status">${["todo", "in_progress", "review", "done"].map((s) => `<option value="${s}" ${s === t.status ? "selected" : ""}>${{ todo: "لم تبدأ", in_progress: "قيد التنفيذ", review: "قيد المراجعة", done: "منجزة" }[s]}</option>`).join("")}</select>` : pill(t.status, t.status_label_ar)}</td>
      <td style="width:150px">${editable(t) && !t.is_milestone ? `<input class="input" type="number" min="0" max="100" step="5" value="${t.progress}" data-f="progress" style="width:72px"> %` : `${progress(t.progress)}<span class="small ltr">${num(t.progress)}%</span>`}</td>
      <td>${editable(t) && !t.is_milestone ? `<button class="btn sm" data-save="${t.id}">حفظ</button>` : ""}</td></tr>`).join("")}
  </tbody></table></div></div>`;
  pane.querySelectorAll("[data-save]").forEach((b) => b.addEventListener("click", () => withBusy(b, async () => {
    const row = pane.querySelector(`tr[data-task="${b.dataset.save}"]`);
    const r = await patch(`/api/tasks/${b.dataset.save}`, { status: row.querySelector("[data-f=status]").value, progress: +row.querySelector("[data-f=progress]").value });
    toast(`حُدّثت المهمة · أعاد وكيل الفريق حساب الأحمال (متوسط ${num(r.team.summary.avg_utilisation_pct)}%)`, "ok", r.run.run_id);
    reload();
  })));
}

// ------------------------------------------------------------------ files
function files(pane, d, reload) {
  const canUpload = can.manager() || d.project.team.some((m) => m.id === state.user.id);
  pane.innerHTML = `<div class="grid ${canUpload ? "main-side" : ""}">
    <div class="card"><div class="card-h"><h3>ملفات المشروع</h3><span class="sub">أحدث الإصدارات أولًا</span></div>
      <div class="card-b flush">${d.documents.length ? `<table class="t"><thead><tr><th>الترميز</th><th>العنوان</th><th>الإصدار</th><th>الحالة</th><th>الجودة</th><th></th></tr></thead><tbody>
        ${d.documents.map((x) => `<tr style="${x.is_latest ? "" : "opacity:.55"}"><td class="code">${esc(x.code)}</td><td class="small">${esc(x.title)}<div class="muted">${esc(x.discipline_label_ar)} · ${esc(x.doc_type_label_ar)} · ${bytes(x.size_bytes)}</div></td>
          <td class="mono small">${esc(x.revision)}${x.is_latest ? "" : ' <span class="tag">مستبدَل</span>'}</td><td>${pill(x.state, x.state_label_ar)}</td><td>${pill(x.qa_status, x.qa_status_label_ar)}</td>
          <td><button class="btn sm" data-dl="${x.id}" data-fn="${esc(x.filename)}">${icons.download}</button></td></tr>`).join("")}</tbody></table>` : empty("لا توجد ملفات")}</div></div>
    ${canUpload ? `<div class="card"><div class="card-h"><h3>رفع ملف للمشروع</h3></div><div class="card-b" id="up"></div></div>` : ""}</div>`;
  pane.querySelectorAll("[data-dl]").forEach((b) => b.addEventListener("click", () => withBusy(b, () => downloadDoc(b.dataset.dl, b.dataset.fn))));
  if (canUpload) mountUpload(pane.querySelector("#up"), () => d.project.id, () => setTimeout(reload, 1800));
}

// ------------------------------------------------------------------ QA
export function qaReportCard(q, onChange) {
  return `<div class="card" data-qa="${q.id}" style="margin-bottom:14px">
    <div class="card-h"><div><h3>تقرير مراجعة #${q.id} ${q.document_code ? `· <span class="mono small">${esc(q.document_code)}</span>` : ""}</h3>
      <div class="sub">${esc(q.project_code)} · ${esc(q.phase_name_ar)} · ${esc(time(q.created_at))}</div></div>
      <div class="actions">${pill(q.status, q.status_label_ar)}
        ${q.can_sign_off ? `<button class="btn sm primary" data-sign="${q.id}">${icons.check}<span>توقيع المهندس المرخّص</span></button>` : ""}</div></div>
    <div class="card-b">
      <div style="display:flex;gap:16px;flex-wrap:wrap;align-items:center"><div><b class="ltr">${num(q.checks_passed)}/${num(q.checks_total)}</b> <span class="muted small">فحص ناجح</span></div>
        <div class="muted small">${esc(q.summary_ar)}</div></div>
      ${q.signed_off_by ? `<div class="notice info" style="margin:10px 0 0">وقّعه ${esc(q.signed_off_by.name_ar)} (${esc(q.signed_off_by.license_no || "—")}) ${q.signoff_note ? "· " + esc(q.signoff_note) : ""}</div>` : ""}
      ${q.blocking_reason_ar && !q.signed_off_by ? `<div class="small" style="color:var(--danger);margin-top:8px">⛔ ${esc(q.blocking_reason_ar)}</div>` : ""}
      ${q.issues.length ? `<table class="t" style="margin-top:10px"><thead><tr><th>الخطورة</th><th>القاعدة</th><th>القيمة الحالية</th><th>المطلوب</th><th>الحل المقترح</th></tr></thead><tbody>
        ${q.issues.map((i) => `<tr><td>${pill(i.severity, i.severity_label_ar)}</td><td class="small"><b>${esc(i.rule_name_ar)}</b><div class="muted mono">${esc(i.rule_id)}</div></td>
          <td class="small">${esc(i.actual)}</td><td class="small">${esc(i.limit)}</td><td class="small muted">${esc(i.fix_ar)}</td></tr>`).join("")}</tbody></table>` : `<div class="small" style="color:var(--success);margin-top:8px">✔ لا توجد ملاحظات</div>`}
      ${q.deliverables.map((ph) => `<div style="margin-top:12px"><div class="small"><b>اكتمال مخرجات ${esc(ph.phase_name_ar)}</b> <span class="ltr">${num(ph.complete_pct)}%</span></div>${progress(ph.complete_pct)}
        <div style="margin-top:6px">${ph.items.map((it) => `<span class="tag" style="${it.present ? "color:var(--success)" : "color:var(--warning)"}">${it.present ? "✔" : "○"} ${esc(it.label_ar)}</span>`).join("")}</div></div>`).join("")}
      <div class="small muted" style="margin-top:10px">${esc(q.notice_ar)}</div>
    </div></div>`;
}

export function bindQa(root, onChange) {
  root.querySelectorAll("[data-sign]").forEach((b) => b.addEventListener("click", () => withBusy(b, async () => {
    const note = prompt("ملاحظة التوقيع (اختياري):", "تمت المراجعة وفق الاشتراطات التوضيحية") ?? null;
    if (note === null) return;
    const r = await post(`/api/qa/${b.dataset.sign}/signoff`, { note });
    toast("وُقّع تقرير الجودة؛ أصبح الملف قابلًا للنشر", "ok", r.run.run_id);
    onChange();
  })));
}

function qa(pane, d, reload) {
  const canRun = can.manager() || d.project.team.some((m) => m.id === state.user.id);
  pane.innerHTML = `<div style="display:flex;gap:8px;margin-bottom:12px">${canRun ? `<button class="btn primary" id="run-qa">${icons.refresh}<span>تشغيل فحص الامتثال الآن</span></button>` : ""}
    <span class="muted small" style="align-self:center">يفحص وكيل المراجعة بيانات المشروع واكتمال المخرجات، ولا يُنشر ملف قبل توقيع مهندس مرخّص.</span></div>
    ${d.qa_reports.length ? d.qa_reports.slice(0, 4).map((q) => qaReportCard(q)).join("") : `<div class="card">${empty("لا توجد تقارير مراجعة بعد")}</div>`}`;
  pane.querySelector("#run-qa")?.addEventListener("click", (e) => withBusy(e.currentTarget, async () => {
    const r = await post(`/api/projects/${d.project.id}/qa`, {});
    toast(`اكتمل الفحص: ${r.qa_report.summary_ar}`, "ok", r.run.run_id);
    reload();
  }));
  bindQa(pane, reload);
}

// ------------------------------------------------------------------ reports
function reports(pane, d, reload) {
  const canMake = can.manager() || d.project.team.some((m) => m.id === state.user.id);
  pane.innerHTML = `${canMake ? `<div class="card" style="margin-bottom:14px"><div class="card-b" style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
      <button class="btn primary" id="mk">${icons.reporting}<span>إنشاء تقرير أسبوعي</span></button>
      <label class="small"><input type="checkbox" id="send" checked> إرساله للعميل عبر البوابة</label>
      <span class="muted small">يكتبه وكيل التقارير من بيانات المهام والجودة والفريق مباشرة.</span></div></div>` : ""}
    ${d.reports.length ? `<div class="card"><div class="card-b flush"><table class="t"><tbody>${d.reports.map((r) => `<tr class="click" data-r="${r.id}">
      <td><b>${esc(r.title_ar)}</b><div class="small muted">${date(r.period_start)} – ${date(r.period_end)}</div></td><td class="ltr">${num(r.progress_pct)}%</td>
      <td>${r.sent_to_client ? pill("ok", "أُرسل للعميل") : pill("grey", "داخلي")}</td></tr>`).join("")}</tbody></table></div></div>` : `<div class="card">${empty("لا توجد تقارير")}</div>`}`;
  pane.querySelectorAll("[data-r]").forEach((row) => row.addEventListener("click", () => openReport(d.reports.find((x) => x.id === +row.dataset.r))));
  pane.querySelector("#mk")?.addEventListener("click", (e) => withBusy(e.currentTarget, async () => {
    const r = await post(`/api/projects/${d.project.id}/reports/weekly`, { send_to_client: pane.querySelector("#send").checked });
    toast("أُنشئ التقرير الأسبوعي", "ok", r.run.run_id);
    openReport(r.report);
    reload();
  }));
}

// ------------------------------------------------------------------ data & approvals
function data(pane, d, reload) {
  const p = d.project;
  const canEdit = can.manager() || p.team.some((m) => m.id === state.user.id);
  const keys = ["coverage_ratio", "setback_front_m", "setback_side_m", "setback_rear_m", "height_m", "floors", "parking_spaces"];
  pane.innerHTML = `<div class="grid g2">
    <div class="card"><div class="card-h"><h3>بيانات المشروع للفحص</h3><span class="sub">تعديلها يعيد تشغيل وكيل المراجعة تلقائيًا</span></div>
      <div class="card-b"><div class="grid g2">${keys.map((k) => `<label class="small">${esc(p.params_labels_ar[k])}
        <input class="input" style="width:100%" type="number" step="${k === "coverage_ratio" ? "0.01" : "0.1"}" data-k="${k}" value="${p.params[k] ?? ""}" ${canEdit ? "" : "disabled"}></label>`).join("")}</div>
        ${canEdit ? `<button class="btn primary" style="margin-top:12px" id="save-params">حفظ وإعادة الفحص</button>` : ""}</div></div>
    <div class="card"><div class="card-h"><h3>معلومات المشروع</h3></div><div class="card-b"><div class="kv">
      <span class="k">العميل</span><span>${esc(p.client.name_ar)}</span>
      <span class="k">مساحة الأرض</span><span>${num(p.land_area_m2)} م²</span>
      <span class="k">مسطحات البناء</span><span>${num(p.bua_m2)} م² (تقديرية)</span>
      <span class="k">عدد الأدوار</span><span>${num(p.floors)}</span>
      <span class="k">الخدمات</span><span>${p.services.map((s) => `<span class="tag">${esc(s.name_ar)}</span>`).join("")}</span>
      <span class="k">الوصف</span><span class="small">${esc(p.description_ar)}</span>
    </div>${d.proposal ? `<button class="btn sm" style="margin-top:12px" id="open-prop">عرض السعر ${esc(d.proposal.code)}</button>` : ""}</div></div>
    <div class="card" style="grid-column:1/-1"><div class="card-h"><h3>الاعتمادات البشرية</h3><span class="sub">الوكلاء يجهّزون، والمسؤول البشري يعتمد</span></div>
      <div class="card-b flush">${d.approvals.length ? `<table class="t"><tbody>${d.approvals.map((a) => `<tr><td>${esc(a.label_ar)}</td><td>${pill(a.status, a.status_label_ar)}</td>
        <td class="small">${a.by ? esc(a.by.name_ar) : "—"}</td><td class="small muted">${a.at ? esc(time(a.at)) : "—"}</td></tr>`).join("")}</tbody></table>` : empty("لا اعتمادات")}</div></div></div>`;
  pane.querySelector("#open-prop")?.addEventListener("click", () => openProposal(d.proposal.id, reload));
  pane.querySelector("#save-params")?.addEventListener("click", (e) => withBusy(e.currentTarget, async () => {
    const body = {};
    pane.querySelectorAll("[data-k]").forEach((i) => { if (i.value !== "") body[i.dataset.k] = Number(i.value); });
    const r = await patch(`/api/projects/${p.id}/params`, body);
    toast(`حُفظت البيانات · ${r.qa_report.summary_ar}`, "ok", r.run.run_id);
    reload();
  }));
}
