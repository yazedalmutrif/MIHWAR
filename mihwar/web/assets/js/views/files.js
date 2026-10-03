// Files register: CDE pipeline, filters, state transitions, upload with the Document Control result.
import { get, post, esc, num, date, pill, empty, toast, withBusy, icons, downloadDoc, bytes } from "../core.js";
import { mountUpload } from "./upload.js";

const NEXT = { WIP: [["SHARED", "مشاركة"], ["ARCHIVED", "أرشفة"]], SHARED: [["PUBLISHED", "نشر للعميل"], ["WIP", "إعادة للعمل"]], PUBLISHED: [["ARCHIVED", "أرشفة"]], ARCHIVED: [] };

export async function render(el, _params, query) {
  const [list, projs] = await Promise.all([get("/api/files"), get("/api/projects")]);
  const filter = { project: query && query.get("project_id") ? query.get("project_id") : "", state: "" };
  el.innerHTML = `
    <div class="card" style="margin-bottom:16px"><div class="pipeline">
      ${[["WIP", "قيد العمل"], ["SHARED", "مشترك مع الفريق"], ["PUBLISHED", "منشور للعميل"], ["ARCHIVED", "مؤرشف"]].map(([k, l]) => `
        <div class="stage-box"><div class="n ltr">${num(list.counts[k] || 0)}</div><div class="l">${l} <span class="mono">(${k})</span></div></div>`).join("")}
    </div></div>
    <div class="grid g2" style="margin-bottom:16px">
      <div class="card"><div class="card-h"><h3>رفع ملف</h3><span class="sub">يصنّفه وكيل التحكم بالوثائق ويرمّزه ويحدد إصداره</span>
        <div class="actions"><select class="input" id="up-project">${projs.items.map((p) => `<option value="${p.id}">${esc(p.code)} · ${esc(p.name_ar)}</option>`).join("")}</select></div></div>
        <div class="card-b" id="up"></div></div>
      <div class="card"><div class="card-h"><h3>منهجية الترميز</h3><span class="sub">مستوحاة من ISO 19650</span></div><div class="card-b">
        <div class="small">${esc(list.naming.pattern)}</div>
        <div class="naming" style="margin:10px 0">${list.naming.example.split("-").map((v, i) => `<span class="seg-part"><b>${esc(v)}</b><span>${esc(list.naming.fields[i] ? list.naming.fields[i].label_ar : "")}</span></span>`).join('<span class="sep">-</span>')}</div>
        <div class="small muted">${esc(list.naming.notice_ar)}</div>
        <div class="small" style="margin-top:8px">المراحل: قيد العمل ← مشترك ← منشور ← مؤرشف. <b>النشر للعميل مشروط بتوقيع مهندس مرخّص على مراجعة الجودة.</b></div></div></div>
    </div>
    <div class="card">
      <div class="card-h"><h3>سجل الوثائق</h3><span class="sub">أحدث الإصدارات</span>
        <div class="actions filters">
          <select class="input" id="f-project"><option value="">كل المشاريع</option>${projs.items.map((p) => `<option value="${p.id}">${esc(p.code)} · ${esc(p.name_ar)}</option>`).join("")}</select>
          <select class="input" id="f-state"><option value="">كل الحالات</option><option value="WIP">قيد العمل</option><option value="SHARED">مشترك</option><option value="PUBLISHED">منشور</option><option value="ARCHIVED">مؤرشف</option></select>
        </div></div>
      <div class="card-b flush" id="rows" style="overflow-x:auto"></div>
    </div>`;
  const rows = el.querySelector("#rows");
  let items = list.items;
  const draw = () => {
    const shown = items.filter((d) => (!filter.project || String(d.project_id) === String(filter.project)) && (!filter.state || d.state === filter.state));
    rows.innerHTML = shown.length ? `<table class="t"><thead><tr><th>الترميز</th><th>العنوان</th><th>التخصص / النوع</th><th>الإصدار</th><th>الحالة</th><th>مراجعة الجودة</th><th>رفعه</th><th>إجراءات</th></tr></thead><tbody>
      ${shown.map((d) => `<tr><td class="code">${esc(d.code)}</td>
        <td class="small"><b>${esc(d.title)}</b><div class="muted">${bytes(d.size_bytes)}</div></td>
        <td class="small">${esc(d.discipline_label_ar)}<div class="muted">${esc(d.doc_type_label_ar)}</div></td>
        <td class="mono small">${esc(d.revision)}</td><td>${pill(d.state, d.state_label_ar)}</td><td>${pill(d.qa_status, d.qa_status_label_ar)}</td>
        <td class="small muted nowrap">${esc(d.uploaded_by ? d.uploaded_by.name_ar : "—")}<div>${date(d.uploaded_at)}</div></td>
        <td class="nowrap"><button class="btn sm" data-dl="${d.id}" data-fn="${esc(d.filename)}" title="تنزيل">${icons.download}</button>
          ${(NEXT[d.state] || []).map(([to, l]) => `<button class="btn sm ${to === "PUBLISHED" ? "primary" : ""}" data-move="${d.id}" data-to="${to}">${l}</button>`).join(" ")}</td></tr>`).join("")}
    </tbody></table>` : empty("لا توجد ملفات مطابقة");
    rows.querySelectorAll("[data-dl]").forEach((b) => b.addEventListener("click", () => withBusy(b, () => downloadDoc(b.dataset.dl, b.dataset.fn))));
    rows.querySelectorAll("[data-move]").forEach((b) => b.addEventListener("click", () => withBusy(b, async () => {
      const r = await post(`/api/files/${b.dataset.move}/state`, { to_state: b.dataset.to });
      toast(r.transmittal ? `نُشر الملف بالإصدار ${r.document.revision} وصدر خطاب الإرسال ${r.transmittal.code}` : `الحالة الآن: ${r.document.state_label_ar}`, "ok", r.run.run_id);
      await refresh();
    })));
  };
  const refresh = async () => { items = (await get("/api/files")).items; draw(); };
  el.querySelector("#f-project").value = filter.project;
  el.querySelector("#f-project").addEventListener("change", (e) => { filter.project = e.target.value; draw(); });
  el.querySelector("#f-state").addEventListener("change", (e) => { filter.state = e.target.value; draw(); });
  draw();
  mountUpload(el.querySelector("#up"), () => el.querySelector("#up-project").value, () => refresh());
}
