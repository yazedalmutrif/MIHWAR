// Components shared by several views.
import { get, post, esc, num, money, date, time, pill, drawer, loading, empty, toast, withBusy, can } from "../core.js";

export async function openProposal(id, onChange) {
  const body = drawer("عرض السعر", "", loading());
  const render = (p) => {
    const actions = [];
    if (can.manager() && p.status === "draft") actions.push(`<button class="btn primary" id="pr-approve">اعتماد وإرسال للعميل</button>`);
    if (can.client() && p.status === "sent") actions.push(`<button class="btn primary" id="pr-accept">قبول العرض وبدء المشروع</button>`);
    body.innerHTML = `
      <div style="display:flex;gap:10px;align-items:center;margin-bottom:6px"><b class="ltr">${esc(p.code)}</b>${pill(p.status, p.status_label_ar)}</div>
      <h3 style="font-size:15px;margin-bottom:4px">${esc(p.title_ar)}</h3>
      <div class="muted small">العميل: ${esc(p.client.name_ar)} · مسطحات البناء التقديرية: ${num(p.bua_m2)} م² · ساري حتى ${date(p.valid_until)}</div>
      <div class="notice" style="margin:12px 0">${esc(p.notice_ar)}</div>
      <table class="t"><thead><tr><th>الخدمة</th><th>أساس الاحتساب</th><th>المبلغ</th></tr></thead><tbody>
        ${p.lines.map((l) => `<tr><td>${esc(l.name_ar)}</td><td class="small muted">${esc(l.basis_ar)}</td><td class="nowrap">${money(l.amount)}</td></tr>`).join("")}
        <tr><td colspan="2" class="muted">المجموع قبل الضريبة</td><td class="nowrap">${money(p.subtotal)}</td></tr>
        <tr><td colspan="2" class="muted">ضريبة القيمة المضافة (${num(p.vat_rate * 100)}%)</td><td class="nowrap">${money(p.vat)}</td></tr>
        <tr><td colspan="2"><b>الإجمالي</b></td><td class="nowrap"><b>${money(p.total)}</b></td></tr>
      </tbody></table>
      <h4 style="margin:16px 0 6px;font-size:13.5px">دفعات السداد</h4>
      <table class="t"><tbody>${p.milestones.map((m) => `<tr><td>${esc(m.name_ar)}</td><td class="muted small">${esc(m.trigger_ar)}</td><td class="nowrap">${num(m.pct)}%</td><td class="nowrap">${money(m.amount)}</td></tr>`).join("")}</tbody></table>
      <div class="grid g2" style="margin-top:14px">
        <div><h4 style="font-size:13px">لا يشمل العرض</h4><ul class="small muted">${p.exclusions_ar.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>
        <div><h4 style="font-size:13px">افتراضات</h4><ul class="small muted">${p.assumptions_ar.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>
      </div>
      <h4 style="margin:10px 0 6px;font-size:13px">سجل الحالة</h4>
      <div class="small">${p.history.map((h) => `<div>${pill(h.status, h.status_label_ar)} <span class="muted">${esc(h.by ? h.by.name_ar : "وكيل العروض")} · ${esc(time(h.at))}</span></div>`).join("")}</div>
      ${actions.length ? `<div style="display:flex;gap:8px;margin-top:18px">${actions.join("")}</div>` : ""}
      ${p.status === "draft" && !can.manager() ? `<div class="notice info" style="margin-top:14px">بانتظار اعتماد مدير المكتب قبل وصوله للعميل.</div>` : ""}`;
    body.querySelector("#pr-approve")?.addEventListener("click", (e) => withBusy(e.currentTarget, async () => {
      const r = await post(`/api/proposals/${p.id}/approve`);
      toast("اعتُمد العرض وأُرسل للعميل", "ok", r.run.run_id);
      render(r.proposal); onChange && onChange();
    }));
    body.querySelector("#pr-accept")?.addEventListener("click", (e) => withBusy(e.currentTarget, async () => {
      const r = await post(`/api/proposals/${p.id}/accept`);
      toast(`قُبل العرض وأُنشئ مشروعك ${r.project.code}؛ أعدّ الوكلاء الجدول الزمني وشكّلوا الفريق`, "ok", r.run.run_id);
      render(r.proposal); onChange && onChange();
    }));
  };
  try { render(await get(`/api/proposals/${id}`)); } catch (e) { body.innerHTML = empty("تعذّر تحميل العرض", e.message); }
}

const FIELDS = [
  ["project_type", "نوع المشروع", (b) => b.project_type_label_ar],
  ["city", "المدينة", (b) => b.city],
  ["district", "الحي", (b) => b.district],
  ["land_area_m2", "مساحة الأرض", (b) => (b.land_area_m2 ? `${num(b.land_area_m2)} م²` : null)],
  ["floors", "عدد الأدوار", (b) => (b.floors ? `${b.floors}${b.has_annex ? " + ملحق" : ""}` : null)],
  ["services", "الخدمات", (b) => (b.services_labels_ar && b.services_labels_ar.length ? b.services_labels_ar.join("، ") : null)],
  ["timeline_months", "المدة المطلوبة", (b) => (b.timeline_months ? `${b.timeline_months} شهر` : null)],
  ["budget_sar", "الميزانية", (b) => (b.budget_sar ? money(b.budget_sar) : null)],
];

export function briefCard(req) {
  const b = req.brief || {};
  const ev = {};
  (b.evidence || []).forEach((e) => { (ev[e.field] = ev[e.field] || []).push(e.source_text); });
  return `<div class="brief">${FIELDS.map(([k, label, fn]) => {
    const v = fn(b);
    const missing = (req.missing_fields || []).includes(k);
    const src = (ev[k] || []).filter(Boolean)[0];
    return `<div class="f"><div class="k">${label}</div>
      <div class="v ${v ? "" : "missing"}">${v ? esc(v) : missing ? "مطلوب" : "—"}</div>
      ${src ? `<div class="evidence">من نص العميل: <mark>${esc(src)}</mark></div>` : ""}</div>`;
  }).join("")}</div>`;
}

export function reportBody(r) {
  return `<div style="white-space:pre-wrap;font-size:13px;line-height:1.8">${esc(r.body_ar)}</div>`;
}

export function openReport(r) {
  drawer(esc(r.title_ar), `${esc(r.project_code)} · ${date(r.period_start)} – ${date(r.period_end)}${r.sent_to_client ? " · أُرسل للعميل" : ""}`,
    `<div class="card"><div class="card-b">${reportBody(r)}</div></div>`);
}
