// Office dashboard: KPIs, live agent activity, approvals, milestones.
import { get, esc, num, date, kpiTile, feedItem, empty, onLeave, bindRuns, icons, axesSVG, can } from "../core.js";
import { openProposal } from "./shared.js";

export async function render(el) {
  const d = await get("/api/dashboard");
  let lastId = d.recent_activity.length ? Math.max(...d.recent_activity.map((s) => s.id)) : 0;
  el.innerHTML = `
    <div class="kpis">${d.kpis.map(kpiTile).join("")}</div>
    <div class="small muted" style="margin-top:6px">المؤشرات الموسومة «تقدير»: ${esc(d.estimate_notice_ar)}</div>
    <div class="grid main-side" style="margin-top:18px">
      <div class="card">
        <div class="card-h"><h3>نشاط الوكلاء المباشر</h3><span class="sub">كل عملية تمر عبر المنسّق ثم الوكلاء المختصين</span>
          <div class="actions"><span class="pill teal">● مباشر</span><span class="muted small">عمليات اليوم: ${num(d.agent_runs_today)}</span></div></div>
        <div class="feed" id="feed">${d.recent_activity.length ? d.recent_activity.map((s) => feedItem(s)).join("") : empty("لا يوجد نشاط بعد")}</div>
      </div>
      <div class="grid" style="align-content:start">
        <div class="card blueprint" style="color:#fff;position:relative;overflow:hidden">
          <div class="card-b" style="position:relative">
            <div style="position:absolute;left:8px;top:6px;width:150px;opacity:.3">${axesSVG("axes", "#14B8A6")}</div>
            <div class="small" style="color:#99F6E4">عرض حي للمحكّمين</div>
            <h3 style="font-size:17px;margin:2px 0 6px">شاهد الوكلاء يديرون مشروعًا كاملًا</h3>
            <p style="color:#C7D6E4;margin:0 0 12px;font-size:12.5px">من طلب العميل حتى تسليم أول مخطط معتمد: 9 مراحل في أقل من دقيقة.</p>
            <a class="btn gold" href="#/agents">${icons.play}<span>شغّل السيناريو الكامل</span></a>
          </div>
        </div>
        <div class="card"><div class="card-h"><h3>بانتظار قرار بشري</h3><span class="sub">الوكلاء يجهّزون، والإنسان يعتمد</span></div>
          <div class="card-b flush">${d.pending_approvals.length ? `<table class="t"><tbody>${d.pending_approvals.map((p) => `
            <tr><td><div><b>${esc(p.title_ar)}</b></div><div class="small muted">${esc(p.subtitle_ar)}</div></td>
            <td class="nowrap" style="text-align:left">${p.kind === "proposal"
              ? `<button class="btn sm ${can.manager() ? "primary" : ""}" data-proposal="${p.id}">${can.manager() ? "مراجعة واعتماد" : "عرض"}</button>`
              : `<a class="btn sm" href="#/compliance">فتح المراجعة</a>`}</td></tr>`).join("")}</tbody></table>` : empty("لا توجد اعتمادات معلّقة")}</div></div>
        <div class="card"><div class="card-h"><h3>المعالم القادمة</h3></div>
          <div class="card-b flush">${d.upcoming_milestones.length ? `<table class="t"><tbody>${d.upcoming_milestones.map((m) => `
            <tr class="click" data-href="#/projects/${m.project_id}"><td><div>${esc(m.name_ar)}</div><div class="small muted ltr">${esc(m.project_code)}</div></td>
            <td class="nowrap muted small">${date(m.date)}</td></tr>`).join("")}</tbody></table>` : empty("لا معالم قريبة")}</div></div>
        <div class="card"><div class="card-h"><h3>المشاريع حسب المرحلة</h3></div>
          <div class="card-b" style="display:flex;gap:8px;flex-wrap:wrap">${d.projects_by_status.map((s) => `<span class="tag" style="font-size:12.5px">${esc(s.label_ar)}: <b>${num(s.count)}</b></span>`).join("")}</div></div>
      </div>
    </div>`;
  bindRuns(el.querySelector("#feed"));
  el.querySelectorAll("[data-proposal]").forEach((b) => b.addEventListener("click", () => openProposal(b.dataset.proposal, () => render(el))));
  el.querySelectorAll("[data-href]").forEach((r) => r.addEventListener("click", () => { location.hash = r.dataset.href; }));

  const feed = el.querySelector("#feed");
  const timer = setInterval(async () => {
    try {
      const a = await get(`/api/activity?after_id=${lastId}&limit=20`);
      if (a.items.length) {
        if (feed.querySelector(".empty")) feed.innerHTML = "";
        const html = a.items.map((s) => feedItem(s, true)).join("");
        feed.insertAdjacentHTML("afterbegin", html);
        lastId = Math.max(lastId, ...a.items.map((s) => s.id));
        while (feed.children.length > 40) feed.lastElementChild.remove();
        bindRuns(feed);
      }
    } catch { /* keep polling quietly */ }
  }, 3000);
  onLeave(() => clearInterval(timer));
}
