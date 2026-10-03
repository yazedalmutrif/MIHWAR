// Client portal (client view) and client-requests inbox (manager view).
import { get, post, esc, num, date, pill, progress, empty, toast, withBusy, errorToast, axesSVG, icons, can, state,
  downloadDoc, bytes, drawer, loading, avatar, showRun } from "../core.js";
import { openProposal, briefCard, openReport } from "./shared.js";

const EXAMPLES = [
  "السلام عليكم، أبغى تصميم فيلا في الرياض حي النرجس، مساحة الأرض ٦٢٥ م٢، دورين وملحق، مع رخصة البناء خلال ٤ أشهر",
  "نحتاج تصميم كامل لعمارة سكنية 4 أدوار في جدة على أرض 900 متر مربع",
  "I need a full design for a 2-floor villa in Riyadh, plot area 500 sqm, with building permit",
  "أبي أصمم استراحة",
];

export async function render(el) {
  if (can.manager()) return renderManager(el);
  return renderClient(el);
}

// ------------------------------------------------------------------ client
async function renderClient(el, keepActive) {
  const [office, reqs, props, projs] = await Promise.all([
    get("/api/portal/office"), get("/api/portal/requests"), get("/api/proposals"), get("/api/portal/projects"),
  ]);
  const requests = reqs.items;
  let active = keepActive !== undefined ? requests.find((r) => r.id === keepActive) || null
    : requests.find((r) => r.status === "needs_info")
      || requests.find((r) => ["brief_ready", "proposal_draft", "proposal_sent"].includes(r.status)) || null;

  el.innerHTML = `
    <section class="hero blueprint">
      ${axesSVG("axes-deco", "#14B8A6")}
      <div class="small" style="color:#99F6E4">${esc(office.office.name_ar)}</div>
      <h2>أهلًا ${esc(state.user.name_ar)}، كيف نخدمك اليوم؟</h2>
      <p>اكتب طلبك بأسلوبك وبالعربية أو الإنجليزية، ووكيل الاستقبال يفهمه فورًا ويسألك عن الناقص، ثم يجهّز وكيل العروض عرض السعر ليعتمده مدير المكتب.</p>
      <div class="hero-meta"><span>🕘 ${esc(office.office.hours_ar)}</span><span>📍 نخدم: ${esc(office.cities_served_ar.join("، "))}</span></div>
    </section>
    <div class="grid main-side" style="margin-top:18px">
      <div class="card chat" id="chat-card"></div>
      <div class="grid" style="align-content:start">
        <div class="card"><div class="card-h"><h3>طلباتي</h3><div class="actions"><button class="btn sm" id="new-req">+ طلب جديد</button></div></div>
          <div class="card-b flush">${requests.length ? `<table class="t"><tbody>${requests.map((r) => `
            <tr class="click ${active && active.id === r.id ? "sel" : ""}" data-req="${r.id}"><td><div class="small">${esc(r.original_text.slice(0, 60))}${r.original_text.length > 60 ? "…" : ""}</div>
            <div class="small muted">${date(r.created_at)}</div></td><td class="nowrap">${pill(r.status, r.status_label_ar)}</td></tr>`).join("")}</tbody></table>` : empty("لا توجد طلبات بعد")}</div></div>
        <div class="card"><div class="card-h"><h3>عروض الأسعار</h3><span class="sub">تظهر بعد اعتماد مدير المكتب</span></div>
          <div class="card-b flush">${props.items.length ? `<table class="t"><tbody>${props.items.map((p) => `
            <tr><td><div><b class="ltr">${esc(p.code)}</b> ${pill(p.status, p.status_label_ar)}</div><div class="small muted">${esc(p.title_ar)}</div></td>
            <td class="nowrap" style="text-align:left"><div><b>${num(p.total)}</b> <span class="small muted">ريال</span></div>
            <button class="btn sm ${p.status === "sent" ? "primary" : ""}" data-proposal="${p.id}">${p.status === "sent" ? "مراجعة وقبول" : "عرض"}</button></td></tr>`).join("")}</tbody></table>` : empty("لا توجد عروض بعد")}</div></div>
      </div>
    </div>
    <div class="section-title"><h2>مشاريعي</h2><span class="sub">التقدم، والملفات المعتمدة، والتحديثات، واسأل عن مشروعك</span></div>
    <div class="grid g2" id="my-projects">${projs.items.length ? projs.items.map(projectCard).join("") : `<div class="card">${empty("لا توجد مشاريع بعد", "يُنشأ مشروعك تلقائيًا عند قبول عرض السعر")}</div>`}</div>
    <div class="section-title"><h2>خدمات المكتب</h2><span class="sub">الأسعار المعروضة قيم توضيحية للعرض</span></div>
    <div class="services">${office.services.map((s) => `<div class="card service"><h4>${esc(s.name_ar)}</h4><p>${esc(s.description_ar)}</p><span class="small" style="color:var(--primary)">${esc(s.price_hint_ar)}</span></div>`).join("")}</div>`;

  const chat = el.querySelector("#chat-card");
  const drawChat = (req) => {
    active = req;
    const msgs = req ? req.messages : [];
    chat.innerHTML = `
      <div class="card-h">${avatar("وكيل الاستقبال", "و")}<div><h3>وكيل استقبال العملاء</h3><div class="sub">يرد فورًا على مدار الساعة · ${req ? pill(req.status, req.status_label_ar) : "طلب جديد"}</div></div></div>
      <div class="chat-log" id="chat-log">${msgs.length ? msgs.map((m) => `
        <div class="bubble ${m.sender === "client" ? "client" : "agent"}"><div class="who">${m.sender === "client" ? esc(state.user.name_ar) : "🤖 " + (m.agent === "proposal" ? "وكيل العروض" : "وكيل الاستقبال")}</div>${esc(m.text)}</div>`).join("")
        : `<div class="bubble agent"><div class="who">🤖 وكيل الاستقبال</div>مرحبًا بك! صف مشروعك بكلماتك: نوعه، ومدينته، ومساحة الأرض، وعدد الأدوار، والخدمات التي تحتاجها. وإذا نقص شيء سأسألك عنه.</div>`}</div>
      ${req ? `<div class="card-b" style="border-top:1px solid var(--border)"><div class="small muted" style="margin-bottom:6px">ما فهمه الوكيل من طلبك (مع النص الذي استُخرج منه كل حقل):</div>${briefCard(req)}
        ${req.proposal_id && req.status === "proposal_draft" ? `<div class="notice info" style="margin:10px 0 0">أعدّ وكيل العروض مسودة عرض السعر، وهي الآن بانتظار اعتماد مدير المكتب.</div>` : ""}</div>` : ""}
      ${!req || req.status === "needs_info" || req.status === "brief_ready" ? `
      <div class="chat-input"><textarea id="chat-text" placeholder="${req && req.status === "needs_info" ? "أجب عن أسئلة الوكيل هنا…" : "اكتب طلبك هنا…"}"></textarea>
        <button class="btn primary" id="chat-send">${icons.send}<span>إرسال</span></button></div>
      ${!req ? `<div class="examples">${EXAMPLES.map((x, i) => `<button data-ex="${i}">${esc(x.length > 46 ? x.slice(0, 46) + "…" : x)}</button>`).join("")}</div>` : ""}` : ""}`;
    const log = chat.querySelector("#chat-log");
    log.scrollTop = log.scrollHeight;
    chat.querySelectorAll("[data-ex]").forEach((b) => b.addEventListener("click", () => { chat.querySelector("#chat-text").value = EXAMPLES[+b.dataset.ex]; }));
    chat.querySelector("#chat-send")?.addEventListener("click", (e) => withBusy(e.currentTarget, async () => {
      const text = chat.querySelector("#chat-text").value.trim();
      if (!text) return;
      const r = active && active.status === "needs_info"
        ? await post(`/api/portal/requests/${active.id}/messages`, { text })
        : await post("/api/portal/requests", { text });
      toast(r.request.complete ? "اكتملت بيانات طلبك وأُعدّت مسودة العرض" : "استلم وكيل الاستقبال طلبك ويحتاج بعض التفاصيل", "ok", r.run.run_id);
      await renderClient(el, r.request.id);
    }));
  };
  drawChat(active);

  el.querySelector("#new-req").addEventListener("click", () => drawChat(null));
  el.querySelectorAll("[data-req]").forEach((row) => row.addEventListener("click", () => drawChat(requests.find((r) => r.id === +row.dataset.req))));
  el.querySelectorAll("[data-proposal]").forEach((b) => b.addEventListener("click", () => openProposal(b.dataset.proposal, () => renderClient(el))));
  bindProjects(el, projs.items);
}

function projectCard(item) {
  const p = item.project;
  return `<div class="card" data-project="${p.id}">
    <div class="card-h"><div><h3>${esc(p.name_ar)}</h3><div class="sub"><span class="ltr">${esc(p.code)}</span> · ${esc(p.type_label_ar)} · ${esc(p.city)}</div></div>
      <div class="actions">${pill(p.health, p.health_label_ar)}</div></div>
    <div class="card-b">
      <div style="display:flex;justify-content:space-between;font-size:12.5px"><span>${esc(p.status_label_ar)}</span><b class="ltr">${num(p.progress)}%</b></div>
      ${progress(p.progress, true)}
      <div class="small muted" style="margin-top:6px">${p.next_milestone ? `المعلم القادم: ${esc(p.next_milestone.name_ar)} — ${date(p.next_milestone.date)}` : "لا معالم قادمة"}</div>
      <div style="margin-top:12px"><b class="small">الملفات المعتمدة (${num(item.published_documents.length)})</b>
        ${item.published_documents.length ? `<table class="t" style="margin-top:4px"><tbody>${item.published_documents.slice(0, 4).map((d) => `
          <tr><td><div class="small">${esc(d.title)}</div><div class="small muted mono">${esc(d.code)} · ${esc(d.revision)}</div></td>
          <td class="nowrap small muted">${bytes(d.size_bytes)}</td>
          <td style="text-align:left"><button class="btn sm" data-dl="${d.id}" data-fn="${esc(d.filename)}">${icons.download}</button></td></tr>`).join("")}</tbody></table>` : `<div class="small muted">تظهر الملفات هنا بعد مراجعة الجودة وتوقيع المهندس المرخّص.</div>`}</div>
      <div style="margin-top:12px"><b class="small">تحديثات المشروع</b>
        ${item.updates.length ? item.updates.slice(0, 2).map((r) => `<div class="small" style="margin-top:4px"><a href="#" data-report="${r.id}">${esc(r.title_ar)}</a></div>`).join("") : `<div class="small muted">لا تحديثات بعد</div>`}</div>
      <div style="margin-top:14px;border-top:1px dashed var(--border);padding-top:12px">
        <b class="small">اسأل عن مشروعك</b>
        <div style="display:flex;gap:6px;margin-top:6px"><input class="input" style="flex:1" placeholder="مثال: وين وصل مشروعي؟ متى تطلع الرخصة؟" data-q="${p.id}">
          <button class="btn primary sm" data-ask="${p.id}">إرسال</button></div>
        <div class="answer" data-answer="${p.id}"></div>
      </div>
    </div></div>`;
}

function bindProjects(el, items) {
  el.querySelectorAll("[data-dl]").forEach((b) => b.addEventListener("click", () => withBusy(b, () => downloadDoc(b.dataset.dl, b.dataset.fn))));
  el.querySelectorAll("[data-report]").forEach((a) => a.addEventListener("click", (e) => {
    e.preventDefault();
    const r = items.flatMap((i) => i.updates).find((x) => String(x.id) === a.dataset.report);
    if (r) openReport(r);
  }));
  el.querySelectorAll("[data-ask]").forEach((b) => b.addEventListener("click", () => withBusy(b, async () => {
    const pid = b.dataset.ask;
    const input = el.querySelector(`[data-q="${pid}"]`);
    const text = input.value.trim() || "وين وصل مشروعي؟";
    const r = await post("/api/portal/questions", { project_id: +pid, text });
    const a = r.answer;
    el.querySelector(`[data-answer="${pid}"]`).innerHTML = `
      <div class="bubble agent" style="margin-top:10px;max-width:100%"><div class="who">🤖 وكيل التقارير والتواصل · ${pill(a.escalated ? "warn" : "teal", a.intent_label_ar)}</div>${esc(a.text_ar)}
      ${a.escalated ? `<div class="small" style="color:var(--warning);margin-top:4px">حُوّل السؤال لموظف المكتب للمتابعة</div>` : ""}
      <div class="small muted" style="margin-top:6px"><a href="#" data-run-link="${r.run.run_id}">كيف أُجيب هذا السؤال؟</a></div></div>`;
    el.querySelector(`[data-run-link="${r.run.run_id}"]`).addEventListener("click", (e) => { e.preventDefault(); showRun(r.run.run_id); });
  })));
}

// ------------------------------------------------------------------ manager
async function renderManager(el) {
  const [reqs, props, office] = await Promise.all([get("/api/portal/requests"), get("/api/proposals"), get("/api/portal/office")]);
  const drafts = props.items.filter((p) => p.status === "draft");
  el.innerHTML = `
    <div class="notice info">هذه واجهة المدير لطلبات البوابة. لتجربة البوابة كعميل اختر دور «عميل» من الشريط العلوي.</div>
    <div class="grid main-side">
      <div class="card"><div class="card-h"><h3>طلبات العملاء</h3><span class="sub">يستقبلها ويحللها وكيل الاستقبال على مدار الساعة</span></div>
        <div class="card-b flush">${reqs.items.length ? `<table class="t"><thead><tr><th>العميل</th><th>الطلب</th><th>ما فهمه الوكيل</th><th>الحالة</th></tr></thead><tbody>
          ${reqs.items.map((r) => `<tr class="click" data-req="${r.id}"><td class="nowrap">${esc(r.client.name_ar)}<div class="small muted">${date(r.created_at)}</div></td>
            <td class="small">${esc(r.original_text.slice(0, 80))}${r.original_text.length > 80 ? "…" : ""}</td>
            <td class="small">${esc([r.brief.project_type_label_ar, r.brief.city, r.brief.land_area_m2 ? num(r.brief.land_area_m2) + " م²" : null].filter(Boolean).join(" · ") || "—")}
              ${r.missing_fields.length ? `<div style="color:var(--warning)">ينقص: ${esc(r.missing_fields_labels_ar.join("، "))}</div>` : ""}</td>
            <td class="nowrap">${pill(r.status, r.status_label_ar)}</td></tr>`).join("")}</tbody></table>` : empty("لا توجد طلبات")}</div></div>
      <div class="grid" style="align-content:start">
        <div class="card"><div class="card-h"><h3>مسودات بانتظار اعتمادك</h3></div>
          <div class="card-b flush">${drafts.length ? `<table class="t"><tbody>${drafts.map((p) => `<tr><td><b class="ltr">${esc(p.code)}</b><div class="small muted">${esc(p.client.name_ar)} · ${num(p.total)} ريال</div></td>
            <td style="text-align:left"><button class="btn sm primary" data-proposal="${p.id}">مراجعة واعتماد</button></td></tr>`).join("")}</tbody></table>` : empty("لا توجد مسودات معلّقة")}</div></div>
        <div class="card"><div class="card-h"><h3>المدن المخدومة عن بُعد</h3></div><div class="card-b">${office.cities_served_ar.map((c) => `<span class="tag">${esc(c)}</span>`).join("")}</div></div>
      </div>
    </div>`;
  el.querySelectorAll("[data-proposal]").forEach((b) => b.addEventListener("click", () => openProposal(b.dataset.proposal, () => renderManager(el))));
  el.querySelectorAll("[data-req]").forEach((row) => row.addEventListener("click", () => {
    const r = reqs.items.find((x) => x.id === +row.dataset.req);
    drawer("طلب عميل", `${esc(r.client.name_ar)} · ${pill(r.status, r.status_label_ar)}`,
      `<div class="card" style="margin-bottom:12px"><div class="card-b">${briefCard(r)}</div></div>
       ${r.messages.map((m) => `<div class="bubble ${m.sender === "client" ? "client" : "agent"}" style="margin-bottom:8px;max-width:100%"><div class="who">${m.sender === "client" ? esc(r.client.name_ar) : "🤖 وكيل"}</div>${esc(m.text)}</div>`).join("")}`);
  }));
}
