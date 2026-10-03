// QA & compliance overview: latest report per project, rule pack.
import { get, esc, num, pill, empty } from "../core.js";
import { qaReportCard, bindQa } from "./projects.js";

export async function render(el) {
  const c = await get("/api/compliance");
  el.innerHTML = `
    <div class="notice">${esc(c.notice_ar)}</div>
    <div class="kpis" style="margin-bottom:16px">
      <div class="kpi"><div class="label">مشاريع مفحوصة</div><div class="value">${num(c.summary.projects_checked)}</div></div>
      <div class="kpi"><div class="label">ملاحظات عالية الخطورة</div><div class="value" style="color:var(--danger)">${num(c.summary.open_high)}</div></div>
      <div class="kpi"><div class="label">ملاحظات متوسطة</div><div class="value" style="color:var(--warning)">${num(c.summary.open_medium)}</div></div>
      <div class="kpi"><div class="label">بانتظار توقيع المهندس</div><div class="value">${num(c.summary.awaiting_signoff)}</div></div>
    </div>
    <div class="grid main-side">
      <div id="reports">${c.reports.length ? c.reports.map((q) => qaReportCard(q)).join("") : `<div class="card">${empty("لا توجد تقارير")}</div>`}</div>
      <div class="card" style="align-self:start"><div class="card-h"><h3>حزمة القواعد</h3><span class="sub ltr">${esc(c.rule_pack.version)}</span></div>
        <div class="card-b flush"><table class="t"><tbody>${c.rule_pack.rules.map((r) => `<tr><td class="small"><b>${esc(r.name_ar)}</b>
          <div class="muted"><span class="mono">${esc(r.id)}</span> · ${esc(r.applies_to_labels_ar.join("، "))}</div></td>
          <td class="small nowrap ltr">${esc(r.op.replace(">=per_unit", "≥ ×").replace(">=", "≥").replace("<=", "≤"))} ${r.unit_ar === "%" ? num(r.value * 100) + "%" : esc(r.value) + " " + esc(r.unit_ar)}</td>
          <td>${pill(r.severity, r.severity_label_ar)}</td></tr>`).join("")}</tbody></table>
          <div class="small muted" style="padding:10px 14px">${esc(c.rule_pack.name_ar)}</div></div></div>
    </div>`;
  bindQa(el, () => render(el));
}
