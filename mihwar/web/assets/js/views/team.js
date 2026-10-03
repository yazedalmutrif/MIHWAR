// Team & resources: weekly utilisation heatmap, alerts, rebalancing suggestions.
import { get, post, esc, num, shortDate, pill, empty, toast, withBusy, avatar, can } from "../core.js";

export async function render(el) {
  const t = await get("/api/team");
  const lvl = (p) => (p > 100 ? "ov" : p >= 85 ? "hi" : p >= 60 ? "l3" : p >= 30 ? "l2" : p > 0 ? "l1" : "");
  const weeks = t.engineers[0] ? t.engineers[0].weekly.map((w) => shortDate(w.week_start)) : [];
  el.innerHTML = `
    <div class="kpis" style="margin-bottom:16px">
      <div class="kpi"><div class="label">متوسط الاستغلال · 8 أسابيع</div><div class="value">${num(t.summary.avg_utilisation_pct)}%</div></div>
      <div class="kpi"><div class="label">مهندسون فوق الطاقة</div><div class="value">${num(t.summary.overloaded_count)}</div></div>
      <div class="kpi"><div class="label">أعضاء الفريق</div><div class="value">${num(t.summary.engineers_count)}</div></div>
      <div class="kpi"><div class="label">اقتراحات إعادة التوزيع</div><div class="value">${num(t.suggestions.length)}</div></div>
    </div>
    <div class="grid main-side">
      <div class="card"><div class="card-h"><h3>أحمال العمل الأسبوعية</h3><span class="sub">نسبة الساعات المتبقية المسندة إلى الطاقة الأسبوعية لكل مهندس</span></div>
        <div class="card-b flush"><table class="t"><thead><tr><th>المهندس</th><th>المتوسط / الذروة</th><th style="min-width:360px"><div class="heat-head">${weeks.map((w) => `<span>${esc(w)}</span>`).join("")}</div></th></tr></thead><tbody>
          ${t.engineers.map((e) => `<tr><td><div style="display:flex;gap:8px;align-items:center">${avatar(e.name_ar)}<div><b>${esc(e.name_ar)}</b>
              <div class="small muted">${esc(e.title_ar || e.discipline_label_ar)} · ${num(e.capacity_hours_week)} س/أسبوع${e.is_licensed ? " · مرخّص" : ""}</div></div></div></td>
            <td class="nowrap"><span class="ltr">${num(e.utilisation_pct)}% / ${num(e.peak_pct)}%</span><div>${pill(e.status === "high" ? "warn" : e.status, e.status_label_ar)}</div></td>
            <td><div class="heat">${e.weekly.map((w) => `<div class="c ${lvl(w.pct)}" title="${esc(shortDate(w.week_start))}: ${num(w.hours)} ساعة">${w.pct ? num(w.pct) + "%" : ""}</div>`).join("")}</div></td></tr>`).join("")}
        </tbody></table></div></div>
      <div class="grid" style="align-content:start">
        <div class="card"><div class="card-h"><h3>اقتراحات وكيل الفريق</h3></div><div class="card-b">${t.suggestions.length ? t.suggestions.map((s) => `
          <div style="border:1px solid var(--border);border-radius:10px;padding:12px;margin-bottom:10px">
            <div class="small muted">${esc(s.reason_ar)}</div>
            <div style="margin:4px 0">نقل «<b>${esc(s.task_name_ar)}</b>» <span class="ltr small muted">(${esc(s.project_code)})</span> من ${esc(s.from.name_ar)} إلى <b>${esc(s.to.name_ar)}</b></div>
            <div class="small" style="color:var(--primary)">${esc(s.effect_ar)}</div>
            ${can.manager() ? `<button class="btn sm primary" style="margin-top:8px" data-apply='${esc(JSON.stringify({ task_id: s.task_id, to_engineer_id: s.to.id }))}'>تطبيق الاقتراح</button>` : `<div class="small muted" style="margin-top:6px">يطبّقه مدير المكتب</div>`}
          </div>`).join("") : ""}
          ${(t.capacity_notes || []).map((c) => `<div class="notice" style="margin:0 0 10px">${esc(c.message_ar)}</div>`).join("")}
          ${!t.suggestions.length && !(t.capacity_notes || []).length ? empty("لا توجد اقتراحات؛ الأحمال متوازنة") : ""}</div></div>
        <div class="card"><div class="card-h"><h3>تنبيهات الضغط</h3></div><div class="card-b flush">${t.alerts.length ? `<table class="t"><tbody>${t.alerts.slice(0, 8).map((a) => `
          <tr><td>${pill(a.severity, a.severity === "high" ? "تجاوز" : "مرتفع")}</td><td class="small">${esc(a.message_ar)}</td></tr>`).join("")}</tbody></table>` : empty("لا تنبيهات")}</div></div>
      </div>
    </div>`;
  el.querySelectorAll("[data-apply]").forEach((b) => b.addEventListener("click", () => withBusy(b, async () => {
    const r = await post("/api/team/rebalance", JSON.parse(b.dataset.apply));
    toast(`أُعيد إسناد المهمة · متوسط الاستغلال الآن ${num(r.team.summary.avg_utilisation_pct)}%`, "ok", r.run.run_id);
    render(el);
  })));
}
