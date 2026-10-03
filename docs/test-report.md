# Mihwar test report

Generated on 2026-10-03 (Asia/Riyadh) on Windows 11, Python 3.10, offline mode. Sections 1–3 are the real outputs pasted unedited; section 4 is a condensed excerpt of a live scenario run (some stage highlights shortened).

| Check | Result |
|---|---|
| Automated tests (pytest) | **87 passed** |
| Agent self-tests (healthcheck) | **9/9 agents PASS, 65/65 checks PASS** |
| UI smoke test (16 page-and-role checks across manager, engineer and client, headless Edge) | **16/16 PASS** |
| End-to-end scenario (9 stages, live server) | **completed in ~16 s** (0.6 s animation delay between steps) |
| `run.bat` cold start on a spare port | server healthy (`/api/health` → ok) |

## 1) pytest

Test files: `test_agents.py` (39), `test_api.py` (33), `test_llm_mode.py` (7, Anthropic client mocked, no network), `test_orchestrator.py` (7), `test_scenario.py` (1).

```text
........................................................................ [ 82%]
...............                                                          [100%]
87 passed in 13.58s
```

## 2) Agent health check — `python -m mihwar.healthcheck -v`

```text
Mihwar agent health check (offline mode, isolated demo data)
==============================================================================
#  Agent                           Checks   Time (ms)   Result
------------------------------------------------------------------------------
0  Orchestrator                       5/5         4.0   PASS
       ok Every route has a handler and known agents  ->  18 مسارًا
       ok Every event has an Arabic label
       ok Chained event: request → intake → proposal draft  ->  security → intake → proposal
       ok Security denial stops the run  ->  denied
       ok Bad input fails cleanly without breaking the platform  ->  not_found
1  Client Intake                      8/8         3.8   PASS
       ok Arabic text with Arabic-Indic digits  ->  فيلا · الرياض · 625 م² · دوران + ملحق
       ok Services and timeline detected  ->  التصميم المعماري، استخراج رخصة البناء · 4 أشهر
       ok Complete brief has no missing fields  ->  []
       ok Missing fields produce follow-up questions  ->  المدينة، مساحة الأرض، عدد الأدوار، الخدمات المطلوبة
       ok English request  ->  عمارة · جدة · 900 م² · 3 أدوار
       ok Attached prefixes and thousands separator  ->  استراحة · الطائف · 1,200 م²
       ok Evidence links fields to the client's words  ->  ٦٢٥ م٢
       ok Follow-up answers merge into the brief  ->  فيلا · جدة · 500 م² · دوران
2  Proposal & Pricing                 8/8         3.6   PASS
       ok Built-up area estimate  ->  750 م²
       ok Per-m² fee line  ->  750 م² × 35 ريال × 1.00 = 26250.0
       ok Subtotal equals sum of lines  ->  47250.0
       ok VAT 15%  ->  7087.5
       ok Milestones add up to 100% of total  ->  30 + 40 + 30
       ok Minimum fee applied to small jobs  ->  80 م² × 35 ريال × 0.80 (الحد الأدنى للأتعاب)
       ok Client cannot accept before manager approval  ->  invalid_state
       ok Draft → approved → sent → accepted creates a project  ->  MST-2026-012
3  Project Planner                    7/7         3.4   PASS
       ok Tasks generated for every service  ->  15 مهمة
       ok No task starts or ends on Friday/Saturday  ->  الأحد–الخميس
       ok Every task starts after its dependencies end
       ok Structural design waits for concept approval  ->  2026-10-20
       ok Milestones are one-day, zero-hour items
       ok Durations scale with project size  ->  12 ← 24 يوم
       ok Plan is written to the project  ->  المهام: 13 · المراحل: 5 · المعالم: 2 · من 4 أكتوبر 2026 إلى 24 فبراير 2027
4  Team & Resources                   6/6         4.3   PASS
       ok Task hours are spread over working days  ->  1 أسبوع
       ok Discipline match  ->  م. نورة الحربي
       ok Least-loaded engineer is chosen  ->  م. فهد الدوسري
       ok Overload is detected  ->  م. سارة القحطاني، م. نورة الحربي
       ok A rebalancing suggestion is produced  ->  ينخفض حمل م. سارة القحطاني من 105% إلى 45%، ويصبح حمل م. فهد الدوسري 60%
       ok Every non-milestone task gets an engineer  ->  المهام المسندة: 9 (م. فهد الدوسري: 4، م. نورة الحربي: 2، أ. ليان المطيري: 3) · تنبيهات الضغط: 2
5  Document Control                   9/9         4.1   PASS
       ok Structural drawing from an English name  ->  structural / DR
       ok Arabic architectural plan with level  ->  architectural / DR / 00
       ok Structural calculations  ->  structural / CA
       ok Mechanical drawing, first floor  ->  mechanical / 01
       ok Naming code follows the convention  ->  MST004-MST-ZZ-ZZ-DR-E-0002
       ok New upload of the same drawing becomes P02 and supersedes P01  ->  P01 → P02
       ok Identical content is detected as a duplicate  ->  ملف مكرر لـ ⁦MST004-MST-ZZ-ZZ-DR-E-0002 P02⁩ — لم يُسجَّل
       ok Illegal jump WIP → Published is refused  ->  invalid_state
       ok Publishing requires a signed-off QA report  ->  qa_signoff_required
6  QA & Compliance                    8/8         3.1   PASS
       ok Compliant villa passes every zoning rule  ->  7/7
       ok Coverage violation is high severity  ->  نسبة التغطية القصوى (سكني): القيمة الحالية 68% والمطلوب ≤ 60%
       ok Side setback violation is medium severity  ->  الحد الأدنى للارتداد الجانبي: القيمة الحالية 1.5 م والمطلوب ≥ 2 م
       ok Parking per unit  ->  الحد الأدنى لمواقف السيارات: القيمة الحالية 5 والمطلوب ≥ 8 (موقف لكل وحدة)
       ok Report is stored with deliverables  ->  الفحوص الناجحة: 5 من 11 · الملاحظات: 6 (عالية الخطورة: 1)
       ok Sign-off is blocked while high-severity issues are open  ->  invalid_state
       ok Unlicensed engineers cannot sign off  ->  forbidden
       ok Licensed engineer signs off a clean report  ->  MST-2026-011
7  Security & Access                  8/8         3.3   PASS
       ok Unassigned engineer is denied  ->  مرفوض: المهندس غير مسند إلى هذا المشروع
       ok Assigned engineer is allowed  ->  مسموح: المهندس مسند إلى المشروع
       ok Client can download own published file  ->  مسموح: العميل مالك الطلب أو المشروع
       ok Client is blocked from WIP files and an alert is raised  ->  مرفوض: يطّلع العميل على الملفات المنشورة فقط
       ok Client cannot open another client's project  ->  مرفوض: لا يمكن الوصول إلى بيانات عميل آخر
       ok Only licensed engineers can sign off QA  ->  مرفوض: التوقيع مقصور على المهندسين المرخّصين / مسموح: مهندس مرخّص (DEMO-ENG-1042)
       ok Burst downloads raise an alert  ->  تنزيل 5 ملفات خلال دقيقة واحدة من م. سارة القحطاني — نمط غير معتاد
       ok Every decision is written to the audit log  ->  13 entries
8  Reporting & Client Comms           6/6         4.7   PASS
       ok Progress is weighted by hours  ->  88%
       ok Client questions are routed to the right intent  ->  كل الحالات صحيحة
       ok Status answer uses real project data  ->  مشروعك «فيلا السبيعي — حي النرجس» في مرحلة تصميم، ونسبة الإنجاز الحالية 87%. العمل الجاري الآن: المخططات الإنشائية (حتى 
       ok Unknown questions are escalated to a human  ->  النية: استفسار عام · حُوّل لمدير المشروع
       ok Weekly report has all sections and is sent  ->  نسبة الإنجاز 87% · الأعمال القادمة: 4 · المخاطر: 2 · أُرسل للعميل
       ok KPIs computed; savings flagged as estimates  ->  4 مشاريع نشطة
------------------------------------------------------------------------------
Agents: 9/9 PASS   Checks: 65/65 PASS   Total time: 1.2 s
```

## 3) UI smoke test — `python scripts/smoke_ui.py`

```text
PASS  user=1   #/dashboard      expects «نشاط الوكلاء المباشر»
PASS  user=1   #/portal         expects «طلبات العملاء»
PASS  user=1   #/projects       expects «كل مشاريع المكتب»
PASS  user=1   #/projects/2     expects «الجدول الزمني»
PASS  user=1   #/team           expects «أحمال العمل الأسبوعية»
PASS  user=1   #/files          expects «سجل الوثائق»
PASS  user=1   #/compliance     expects «حزمة القواعد»
PASS  user=1   #/security       expects «مصفوفة الصلاحيات»
PASS  user=1   #/agents         expects «فريق الوكلاء»
PASS  user=2   #/dashboard      expects «نشاط الوكلاء المباشر»
PASS  user=2   #/projects       expects «المشاريع المسندة إليك»
PASS  user=2   #/agents         expects «اختبر الوكيل»
PASS  user=4   #/files          expects «سجل الوثائق»
PASS  user=9   #/portal         expects «مشاريعي»
PASS  user=11  #/portal         expects «وكيل استقبال العملاء»
PASS  user=9   #/security       expects «مشاريعي»

UI smoke test: 16/16 pages PASS
```

## 4) End-to-end scenario on the live server (`scripts/make_screenshots.py`)

```text
1. Client intake                            done      steps=2 | فيلا · الرياض · 600 م² · دوران + ملحق
2. Proposal draft                           done      steps=1 | PR-2026-007 · الإجمالي 82,455 ريال شامل الضريبة
3. Manager approval & client acceptance     done      steps=4 | اعتمد م. خالد الشهري العرض وقبله العميل · المشروع MST-2026-012
4. Project plan                             done      steps=1
5. Team assignment                          done      steps=1
6. Document upload & control                done      steps=4 | MST012-MST-ZZ-00-DR-A-0001 · P01 + ملف حسابات إنشائية (قيد العمل)
7. QA, licensed sign-off & publish gate     done      steps=10 | نُشر MST012-MST-ZZ-00-DR-A-0001 بالإصدار C01 مع خطاب إرسال
8. Blocked unauthorised access              done      steps=1 | مُنع العميل من ملف قيد العمل وأُطلق تنبيه أمني
9. Client update                            done      steps=2
scenario: completed in 15.9 s
```

## What the tests cover

- **Every agent:** normal cases and edge cases. Examples: Arabic with Arabic-Indic digits, Saudi dialect, attached prefixes
  (بالرياض), «م2» not read as floors, «جامعة» not read as a mosque, «سمكة» not matched as Makkah, missing fields, English
  requests, minimum fees, VAT, payment milestones, weekend-aware scheduling, dependencies, discipline matching, overload
  detection and rebalancing, file classification, revisions, duplicates, illegal state transitions, the QA publish gate,
  zoning rule violations, licensed-only sign-off, RBAC for every role, burst/repeated-denial alerts, client intents and
  honest payment answers.
- **Orchestrator:** every event has a handler, Security runs first for human actions, chaining, denials, clean failures,
  a crashed agent contained without breaking the platform, live step callbacks.
- **API:** every route for manager / engineer / client, 401/403/404/409/422 error contracts with Arabic messages,
  multipart upload and download, the full proposal lifecycle, the scenario endpoint, demo reset.
- **LLM mode (mocked Claude client):** structured-output request shape (model, JSON schema, low effort, `fallbacks`),
  merge into the brief, automatic fallback on error, refusal and invalid schema, trace records the mode.
