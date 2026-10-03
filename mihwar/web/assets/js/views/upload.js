// Upload widget + the Document Control agent's result card.
import { api, esc, pill, toast, errorToast, icons, num } from "../core.js";

export function resultHTML(r) {
  const c = r.classification;
  const parts = r.naming.fields.map((f) => `<span class="seg-part"><b>${esc(f.value)}</b><span>${esc(f.label_ar)}</span></span>`).join('<span class="sep">-</span>');
  return `<div class="card" style="margin-top:12px;border-color:var(--primary-100)">
    <div class="card-h"><div class="agent-ico">${icons.documents}</div><div><h3>نتيجة وكيل التحكم بالوثائق</h3>
      <div class="sub">${esc(r.document.title)} · <span class="mono">${esc(r.document.filename)}</span></div></div>
      <div class="actions">${r.duplicate_of ? pill("warn", "ملف مكرر") : pill("WIP", r.document.state_label_ar)} ${pill("teal", "الإصدار " + r.revision.value)}</div></div>
    <div class="card-b">
      <div class="small muted" style="margin-bottom:6px">الترميز الذي طبّقه الوكيل:</div>
      <div class="naming">${parts}</div>
      <div class="grid g2" style="margin-top:12px">
        <div><div class="small muted">التصنيف</div><div><b>${esc(c.discipline_label_ar)}</b> · ${esc(c.doc_type_label_ar)} <span class="tag">الثقة ${num(c.confidence * 100)}%</span></div>
          <ul class="small" style="margin:6px 0 0;padding-inline-start:18px">${c.reasons_ar.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>
        <div><div class="small muted">الإصدار</div><div>${r.revision.is_new_revision ? `إصدار جديد يحل محل <b>${esc(r.revision.previous.revision)}</b>` : r.duplicate_of ? "لم يُنشأ إصدار جديد" : "أول إصدار لهذه الوثيقة"}</div>
          ${r.warnings_ar.length ? `<div style="margin-top:6px">${r.warnings_ar.map((w) => `<div class="small" style="color:var(--warning)">⚠ ${esc(w)}</div>`).join("")}</div>` : ""}</div>
      </div>
    </div></div>`;
}

export function mountUpload(container, getProjectId, onDone) {
  container.innerHTML = `<div class="dropzone" tabindex="0">${icons.upload}<div><b>اسحب الملف هنا أو اضغط للاختيار</b></div>
    <div class="small">PDF, DWG, DXF, IFC, RVT, XLSX, DOCX, صور… حتى 20 ميجابايت · يصنّفه الوكيل ويرمّزه تلقائيًا</div>
    <input type="file" hidden></div><div class="upload-result"></div>`;
  const dz = container.querySelector(".dropzone");
  const input = container.querySelector("input[type=file]");
  const out = container.querySelector(".upload-result");
  const send = async (file) => {
    const pid = getProjectId();
    if (!pid) { toast("اختر المشروع أولًا", "error"); return; }
    const fd = new FormData();
    fd.append("project_id", String(pid));
    fd.append("file", file);
    dz.classList.add("over");
    dz.querySelector("b").textContent = `جارٍ رفع «${file.name}» ومعالجته…`;
    try {
      const r = await api("POST", "/api/files", fd, { form: true });
      out.innerHTML = resultHTML(r);
      toast(r.duplicate_of ? "الملف مكرر؛ لم يُسجَّل إصدار جديد" : `سُجّل الملف ${r.document.code}`, r.duplicate_of ? "" : "ok", r.run.run_id);
      onDone && onDone(r);
    } catch (e) { errorToast(e); }
    finally { dz.classList.remove("over"); dz.querySelector("b").textContent = "اسحب الملف هنا أو اضغط للاختيار"; input.value = ""; }
  };
  dz.addEventListener("click", () => input.click());
  dz.addEventListener("keydown", (e) => { if (e.key === "Enter") input.click(); });
  input.addEventListener("change", () => input.files[0] && send(input.files[0]));
  dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("over"); });
  dz.addEventListener("dragleave", () => dz.classList.remove("over"));
  dz.addEventListener("drop", (e) => { e.preventDefault(); dz.classList.remove("over"); if (e.dataTransfer.files[0]) send(e.dataTransfer.files[0]); });
}
