// Agents: the live end-to-end scenario, the agent graph, agent cards and self-tests.
import { get, post, esc, num, num1, time, pill, empty, toast, withBusy, icons, agentIco, traceHTML, drawer, loading, onLeave, can, modeTag } from "../core.js";

const AGENT_ORDER = ["orchestrator", "intake", "proposal", "planner", "team", "documents", "compliance", "security", "reporting"];

export async function render(el, _params, query) {
  const [agents, graph] = await Promise.all([get("/api/agents"), get("/api/agents/graph")]);
  let latest = null;
  try { latest = await get("/api/scenario/latest"); } catch { latest = null; }
  el.innerHTML = `
    <div class="card blueprint" style="color:#fff;margin-bottom:16px;overflow:hidden">
      <div class="card-b" style="display:flex;gap:20px;align-items:center;flex-wrap:wrap;padding:22px 24px">
        <div style="flex:1;min-width:280px">
          <div class="small" style="color:#99F6E4">نظام متعدد الوكلاء · منسّق + 8 وكلاء متخصصين</div>
          <h2 style="font-size:21px;margin:4px 0 6px">السيناريو الكامل: من طلب العميل إلى أول مخطط معتمد</h2>
          <p style="margin:0;color:#C7D6E4;font-size:13px">يرسل عميل طلبه بنص عربي حر، فيتسلّمه الوكلاء واحدًا تلو الآخر، ويعتمد الإنسان في نقاط القرار، ويمنع وكيل الأمن أي وصول غير مصرّح.</p>
        </div>
        ${can.manager() ? `<button class="btn gold lg" id="run-scn">${icons.play}<span>شغّل السيناريو الكامل</span></button>` : `<span class="small" style="color:#C7D6E4">يشغّل مدير المكتب السيناريو</span>`}
      </div></div>
    <div class="card" style="margin-bottom:16px"><div class="card-h"><h3>مراحل السيناريو</h3><span class="sub" id="scn-meta">${latest ? "" : "لم يُشغَّل بعد"}</span></div>
      <div class="card-b"><div class="stepper" id="stepper"></div><div id="stage-detail" style="margin-top:14px"></div></div></div>
    <div class="grid g2" style="margin-bottom:16px">
      <div class="card"><div class="card-h"><h3>خريطة الوكلاء</h3><span class="sub">كل حدث يمر عبر المنسّق، ووكيل الأمن أولًا لكل عملية بشرية</span></div>
        <div class="card-b graph">${graphSVG(graph)}</div></div>
      <div class="card"><div class="card-h"><h3>مسارات الأحداث</h3><span class="sub">${num(graph.routes.length)} حدثًا معرّفًا</span></div>
        <div class="card-b flush" style="max-height:430px;overflow:auto"><table class="t"><tbody>${graph.routes.map((r) => `<tr>
          <td class="small"><b>${esc(r.event_label_ar)}</b><div class="mono muted">${esc(r.event)}</div></td>
          <td class="small">${r.agents.map((a) => `<span class="tag">${esc(agents.items.find((x) => x.key === a)?.name_ar || a)}</span>`).join(" ← ")}
            ${r.emits.length ? `<div class="muted">يطلق: <span class="mono">${esc(r.emits.join(", "))}</span></div>` : ""}</td></tr>`).join("")}</tbody></table></div></div>
    </div>
    <div class="section-title"><h2>فريق الوكلاء</h2><span class="sub">كل وكيل له مهمة واحدة، ومدخلات ومخرجات محددة، واختبار ذاتي يثبت أنه يعمل</span>
      <span style="margin-inline-start:auto"><button class="btn primary" id="test-all">${icons.flask}<span>اختبر جميع الوكلاء</span></button></span></div>
    <div class="agents-grid" id="cards">${agents.items.map(card).join("")}</div>`;

  let selected = query && query.get("stage") ? Math.max(0, Math.min(8, +query.get("stage") - 1)) : null;
  let scn = latest;
  const drawScenario = () => {
    const stepper = el.querySelector("#stepper");
    const stages = scn ? scn.stages : [];
    const titles = ["استقبال طلب العميل", "مسودة عرض السعر", "اعتماد المدير وقبول العميل", "الجدول الزمني للمشروع", "تشكيل الفريق وإسناد المهام", "رفع الملفات وترميزها", "مراجعة الجودة والتوقيع والنشر", "منع وصول غير مصرّح", "تحديث العميل"];
    stepper.innerHTML = titles.map((t, i) => {
      const s = stages[i];
      const st = s ? s.status : "pending";
      return `<div class="stp ${st} ${selected === i ? "sel" : ""}" data-i="${i}"><span class="n">${st === "done" ? "✓" : i + 1}</span>
        <div class="t">${esc(t)}</div><div class="h">${esc(s && s.highlight_ar ? s.highlight_ar : st === "running" ? "جارٍ التنفيذ…" : "")}</div></div>`;
    }).join("");
    stepper.querySelectorAll(".stp").forEach((b) => b.addEventListener("click", () => { selected = +b.dataset.i; drawScenario(); }));
    const meta = el.querySelector("#scn-meta");
    if (scn) meta.innerHTML = `${pill(scn.status === "completed" ? "ok" : scn.status === "failed" ? "bad" : "teal", scn.status === "completed" ? "اكتمل" : scn.status === "failed" ? "تعذّر" : "قيد التشغيل")}
      <span class="ltr">${num1((scn.duration_ms || 0) / 1000)} s</span> · ${esc(time(scn.started_at))}`;
    const detail = el.querySelector("#stage-detail");
    if (!scn) { detail.innerHTML = empty("اضغط «شغّل السيناريو الكامل» لمشاهدة الوكلاء يعملون خطوة بخطوة"); return; }
    if (scn.error_ar) { detail.innerHTML = `<div class="notice">${esc(scn.error_ar)}</div>`; return; }
    const idx = selected !== null ? selected : Math.max(0, (scn.current_stage || 1) - 1);
    const s = scn.stages[idx];
    detail.innerHTML = `<div style="display:flex;gap:8px;align-items:center;margin-bottom:6px"><b>المرحلة ${idx + 1}: ${esc(s.title_ar)}</b>
      <span class="muted small">${esc(s.title_en)}</span>${pill(s.status === "done" ? "ok" : s.status, { pending: "لم تبدأ", running: "جارية", done: "اكتملت", failed: "تعذّرت" }[s.status])}</div>
      ${s.highlight_ar ? `<div class="notice info" style="margin-bottom:8px">${esc(s.highlight_ar)}</div>` : ""}
      ${s.steps.length ? traceHTML(s.steps) : empty(s.status === "pending" ? "لم تبدأ هذه المرحلة بعد" : "بانتظار الخطوات…")}`;
  };
  drawScenario();

  let timer = null;
  const poll = async (id) => {
    clearInterval(timer);
    timer = setInterval(async () => {
      try {
        scn = await get(`/api/scenario/${id}`);
        if (selected !== null && scn.status === "running") selected = null;
        drawScenario();
        if (scn.status !== "running") {
          clearInterval(timer);
          toast(scn.status === "completed" ? "اكتمل السيناريو: مرّ الطلب على الوكلاء التسعة بنجاح" : "تعذّر إكمال السيناريو", scn.status === "completed" ? "ok" : "error");
          refreshCards();
        }
      } catch { clearInterval(timer); }
    }, 500);
  };
  onLeave(() => clearInterval(timer));
  if (scn && scn.status === "running") poll(scn.scenario_id);

  el.querySelector("#run-scn")?.addEventListener("click", (e) => withBusy(e.currentTarget, async () => {
    const r = await post("/api/scenario/run");
    selected = null;
    scn = await get(`/api/scenario/${r.scenario_id}`);
    drawScenario();
    poll(r.scenario_id);
  }));

  const refreshCards = async () => {
    const a = await get("/api/agents");
    el.querySelector("#cards").innerHTML = a.items.map(card).join("");
    bindCards();
  };
  const bindCards = () => el.querySelectorAll("[data-test]").forEach((b) => b.addEventListener("click", () => withBusy(b, async () => {
    const r = await post(`/api/agents/${b.dataset.test}/self-test`);
    showChecks([r]);
    refreshCards();
  })));
  bindCards();
  el.querySelector("#test-all").addEventListener("click", (e) => withBusy(e.currentTarget, async () => {
    const r = await post("/api/agents/self-test");
    showChecks(r.results, r);
    refreshCards();
  }));
}

function card(a) {
  const h = a.health;
  return `<div class="card agent-card ${a.key === "orchestrator" ? "orch" : ""}">
    <div class="top">${agentIco(a.key)}<div style="flex:1"><div class="num">#${a.order}</div><h4>${esc(a.name_ar)}</h4><div class="en">${esc(a.name_en)}</div></div>
      ${pill(h === "healthy" ? "healthy" : h, a.health_label_ar)}</div>
    <div class="role">${esc(a.role_ar)}</div>
    <div class="small"><span class="muted">المخرجات:</span> ${esc(a.outputs_ar)}</div>
    <div class="small"><span class="muted">يخدم في التحدي:</span> «${esc(a.challenge_phrase_ar)}»</div>
    <div class="meta">${a.triggers_labels_ar.slice(0, 3).map((t) => `<span class="tag">${esc(t)}</span>`).join("")}</div>
    <div class="stats"><div><b>${num(a.stats.runs)}</b><span>تشغيل</span></div><div><b>${a.stats.avg_duration_ms !== null ? num1(a.stats.avg_duration_ms) : "—"}</b><span>ms متوسط</span></div>
      <div><b>${num(a.stats.denied + a.stats.errors)}</b><span>منع/خطأ</span></div></div>
    <div class="foot">${modeTag(a.mode)}${a.llm_capable ? `<span class="tag">يدعم Claude</span>` : ""}
      ${a.last_self_test ? `<span class="small muted">آخر اختبار: <span class="ltr">${num(a.last_self_test.checks_passed)}/${num(a.last_self_test.checks_total)}</span></span>` : ""}
      <button class="btn sm" style="margin-inline-start:auto" data-test="${a.key}">${icons.flask}<span>اختبر الوكيل</span></button></div>
  </div>`;
}

function showChecks(results, all) {
  const total = results.reduce((n, r) => n + r.checks.length, 0);
  const ok = results.reduce((n, r) => n + r.checks.filter((c) => c.passed).length, 0);
  drawer(all ? "نتيجة اختبار جميع الوكلاء" : `اختبار ${esc(results[0].name_ar)}`,
    `<span class="ltr">${num(ok)}/${num(total)}</span> فحص ناجح · بيانات معزولة ووضع دون اتصال`,
    results.map((r) => `<div class="card" style="margin-bottom:12px"><div class="card-h">${agentIco(r.key)}<div><h3>${esc(r.name_ar)}</h3><div class="sub">${esc(r.name_en)} · <span class="ltr">${num1(r.duration_ms)} ms</span></div></div>
      <div class="actions">${pill(r.passed ? "ok" : "bad", r.passed ? "ناجح" : "فشل")}</div></div>
      <div class="card-b">${r.checks.map((c) => `<div class="check-row"><span class="ic ${c.passed ? "ok" : "no"}">${c.passed ? "✓" : "✗"}</span>
        <div><div>${esc(c.name_ar)}</div><div class="d">${esc(c.name_en)}${c.detail ? " · " + esc(c.detail) : ""}</div></div></div>`).join("")}</div></div>`).join(""));
}

function graphSVG(g) {
  const W = 560, H = 430, cx = W / 2, cy = H / 2 + 6, R = 165;
  const agents = g.nodes.filter((n) => n.kind === "agent");
  const pos = {};
  agents.forEach((n, i) => {
    const ang = -Math.PI / 2 + (i * 2 * Math.PI) / agents.length;
    pos[n.id] = [cx + R * Math.cos(ang), cy + R * Math.sin(ang)];
  });
  const counts = {};
  g.edges.forEach((e) => { counts[e.to] = (counts[e.to] || 0) + 1; });
  const lines = agents.map((n) => {
    const [x, y] = pos[n.id];
    const w = Math.min(5, 1 + (counts[n.id] || 0) * 0.35);
    return `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="${n.id === "security" ? "#6366F1" : "#14B8A6"}" stroke-width="${w}" stroke-opacity=".45"/>`;
  }).join("");
  const nodes = agents.map((n) => {
    const [x, y] = pos[n.id];
    const label = n.label_ar.replace("وكيل ", "");
    return `<g><circle cx="${x}" cy="${y}" r="34" fill="#fff" stroke="${n.id === "security" ? "#6366F1" : "#0F766E"}" stroke-width="2"/>
      <text x="${x}" y="${y + 4}" text-anchor="middle" font-size="11.5" font-weight="600" fill="#0B1F33" font-family="IBM Plex Sans Arabic, Tahoma">${esc(label.length > 14 ? label.split(" ")[0] : label)}</text>
      <text x="${x}" y="${y + 50}" text-anchor="middle" font-size="9.5" fill="#64748B" font-family="Segoe UI, Arial">${esc(n.label_en)}</text></g>`;
  }).join("");
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="خريطة الوكلاء">
    <circle cx="${cx}" cy="${cy}" r="${R}" fill="none" stroke="#E2E8F0" stroke-dasharray="4 6"/>
    ${lines}
    <circle cx="${cx}" cy="${cy}" r="54" fill="#0B1F33"/><circle cx="${cx}" cy="${cy}" r="60" fill="none" stroke="#C8A24A" stroke-width="1.5" stroke-dasharray="3 4"/>
    <text x="${cx}" y="${cy - 2}" text-anchor="middle" font-size="16" font-weight="700" fill="#fff" font-family="IBM Plex Sans Arabic, Tahoma">المنسّق</text>
    <text x="${cx}" y="${cy + 16}" text-anchor="middle" font-size="10" fill="#99F6E4" font-family="Segoe UI, Arial">Orchestrator</text>
    ${nodes}</svg>`;
}
