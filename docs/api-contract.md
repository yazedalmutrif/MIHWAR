# Mihwar API contract (v1)

The single source of truth between the backend (`mihwar/` Python package) and the frontend (`mihwar/web/`).
If the implementation must deviate, update this file in the same change.

## 1. Conventions

- Base URL `http://127.0.0.1:8090` (env `MIHWAR_PORT`). API under `/api`. The SPA is served at `/` (index.html) and `/assets/...`.
- **Identity (demo only):** every request from the SPA sends header `X-Demo-User: <user_id>` (integer).
  - Missing header = anonymous. Anonymous may call only: `GET /api/health`, `GET /api/meta`, `GET /api/demo/users`, `GET /api/portal/office`.
  - Unknown user id = `401 unauthenticated`.
- JSON, UTF-8. Dates `YYYY-MM-DD`. Timestamps ISO-8601 with `+03:00` (Asia/Riyadh is fixed UTC+3; do not use zoneinfo/tzdata).
- Numbers are plain JSON numbers (the UI formats them with Western digits 0-9).
- Money is SAR, number, no currency symbol.
- **Labels come from the backend.** Every enum field `x` is accompanied by `x_label_ar` (professional MSA). The UI displays labels and never hard-codes enum translations (it may keep a fallback map).
- **Errors:** HTTP status + body
  ```json
  {"detail": {"code": "forbidden", "message_ar": "...", "message_en": "...", "run_id": "r_1a2b3c" }}
  ```
  Codes: `unauthenticated` 401 · `forbidden` 403 · `not_found` 404 · `invalid_state` 409 · `qa_signoff_required` 409 · `validation_error` 422 · `agent_error` 500. `run_id` is present when the error came out of an orchestrator run (e.g. a Security deny), otherwise `null`.
- **Every mutating endpoint (POST/PATCH) is an event** dispatched to the orchestrator, and returns its `run` (see `Run`) next to the result. GET endpoints are authorised by the Security agent and served from the read model (they do not create trace steps, except sensitive reads such as downloads, which are audited).

## 2. Enums (value → Arabic label is supplied by the backend)

| Enum | Values |
|---|---|
| `role` | `manager` مدير المكتب · `engineer` مهندس · `client` عميل |
| `discipline` | `architectural` (A) · `structural` (S) · `mechanical` (M) · `electrical` (E) · `plumbing` (P) · `general` (Z) |
| `project_type` | `villa` · `residential_building` · `commercial` · `mixed_use` · `office` · `rest_house` · `warehouse` · `mosque` · `renovation` · `interior` |
| `service_code` | `arch_design` · `struct_design` · `mep_design` · `permit` · `supervision` · `interior` · `landscape` · `bim` · `boq` |
| `request_status` | `needs_info` · `brief_ready` · `proposal_draft` · `proposal_sent` · `accepted` |
| `proposal_status` | `draft` · `approved` · `sent` · `accepted` · `rejected` |
| `project_status` | `planning` · `design` · `permit` · `supervision` · `completed` · `on_hold` |
| `project_health` | `on_track` · `at_risk` · `delayed` |
| `task_status` | `todo` · `in_progress` · `review` · `done` |
| `cde_state` | `WIP` · `SHARED` · `PUBLISHED` · `ARCHIVED` (labels e.g. «قيد العمل (WIP)», «مشترك (Shared)», «منشور (Published)», «مؤرشف (Archived)») |
| `doc_type` | `DR` مخطط · `M3` نموذج ثلاثي الأبعاد · `RP` تقرير · `CA` حسابات · `SP` مواصفات · `SH` جداول وكميات · `PP` عرض تقديمي · `VS` منظور |
| `qa_status` (document) | `not_requested` · `issues` · `passed` · `signed_off` |
| `qa_report_status` | `issues` · `passed` · `signed_off` |
| `severity` | `high` · `medium` · `low` |
| `alert_type` | `burst_download` · `unassigned_access` · `client_wip_request` · `repeated_denials` |
| `alert_status` | `open` · `acknowledged` |
| `run_status` | `ok` · `denied` · `error` · `partial` |
| `step_status` | `ok` · `denied` · `error` · `skipped` |
| `mode` | `offline` · `llm` · `offline-fallback` |
| `agent_health` | `healthy` · `degraded` · `failing` · `untested` |

Event names (each with `event_label_ar` in payloads): `client.request_submitted`, `client.message`, `brief.ready`, `proposal.approved`, `proposal.accepted`, `plan.created`, `task.changed`, `team.rebalance`, `project.params_changed`, `file.uploaded`, `file.status_changed`, `file.download`, `qa.requested`, `qa.signed_off`, `report.weekly`, `client.question`, `security.alert_ack`, `security.simulate`.

## 3. Shared types (TypeScript-like notation; `?` = may be null)

```ts
type UserRef = { id: number; name_ar: string; name_en: string; role: Role; role_label_ar: string }

type DemoUser = UserRef & {
  title_ar: string;               // e.g. "مهندس إنشائي أول"
  discipline: Discipline | null; discipline_label_ar: string | null;
  initials: string;               // two Arabic letters for the avatar, e.g. "ف د"
  is_licensed: boolean;           // may sign off QA
  license_no: string | null;      // fictional, e.g. "DEMO-ENG-1042"
  client_id: number | null;       // for client users
  default_for_role: boolean;      // the identity the role switcher uses
}

type TraceStep = {
  id: number; run_id: string; seq: number;
  agent: AgentKey; agent_name_ar: string; agent_name_en: string;
  event: string; event_label_ar: string;
  status: StepStatus; mode: Mode;
  duration_ms: number;            // float, 1 decimal
  input_summary: string;          // short Arabic summary
  output_summary: string;         // short Arabic summary
  ts: string;
  input?: object; output?: object // full payloads: present in GET /api/runs/{id} and scenario; null in lists
}

type Run = {
  run_id: string; event: string; event_label_ar: string;
  actor: UserRef | null; status: RunStatus;
  started_at: string; duration_ms: number;
  steps: TraceStep[];             // in order, including steps of chained events
  emitted: string[];              // follow-up events raised during the run, e.g. ["brief.ready"]
}

type ProjectBrief = {
  client_name: string | null;
  project_type: ProjectType | null; project_type_label_ar: string | null;
  city: string | null;            // Arabic city name, e.g. "الرياض"
  district: string | null;        // e.g. "النرجس"
  land_area_m2: number | null;
  floors: number | null;
  has_annex: boolean;             // ملحق
  services: ServiceCode[]; services_labels_ar: string[];
  timeline_months: number | null; // desired duration / start window in months
  budget_sar: number | null;
  notes: string | null;
  language: "ar" | "en";
  evidence: { field: string; label_ar: string; value: string; source_text: string }[]; // what text each field came from
}

type Message = { id: number; sender: "client" | "agent" | "staff"; agent: AgentKey | null; text: string; ts: string }

type IntakeRequest = {
  id: number; client: { id: number; name_ar: string };
  status: RequestStatus; status_label_ar: string; created_at: string;
  original_text: string;
  brief: ProjectBrief;
  missing_fields: string[]; missing_fields_labels_ar: string[];
  follow_up_questions_ar: string[];
  complete: boolean;
  messages: Message[];
  proposal_id: number | null;
}

type ProposalLine = { service_code: ServiceCode; name_ar: string; basis_ar: string; // e.g. "750 م² × 35 ريال × 1.00"
  qty: number; unit_ar: string; rate: number; multiplier: number; amount: number }

type Proposal = {
  id: number; code: string;       // "PR-2026-014"
  request_id: number | null; client: { id: number; name_ar: string }; project_id: number | null;
  status: ProposalStatus; status_label_ar: string;
  title_ar: string;
  brief: ProjectBrief;
  bua_m2: number;                 // estimated built-up area used for pricing
  lines: ProposalLine[];
  subtotal: number; vat_rate: number; vat: number; total: number; currency: "SAR";
  milestones: { name_ar: string; pct: number; amount: number; trigger_ar: string }[];
  validity_days: number; valid_until: string;
  exclusions_ar: string[]; assumptions_ar: string[];
  notice_ar: string;              // "قيم توضيحية للعرض — تُستبدل بالقيم الرسمية/الفعلية"
  history: { status: ProposalStatus; status_label_ar: string; at: string; by: UserRef | null }[];
  created_at: string; approved_by: UserRef | null; approved_at: string | null;
  sent_at: string | null; accepted_at: string | null;
}

type ProjectListItem = {
  id: number; code: string;       // "MST-2026-011"
  name_ar: string; name_en: string;
  client: { id: number; name_ar: string };
  type: ProjectType; type_label_ar: string;
  city: string; district: string | null;
  status: ProjectStatus; status_label_ar: string;
  health: ProjectHealth; health_label_ar: string;
  progress: number;               // 0..100 integer
  start_date: string; end_date: string;
  team: { id: number; name_ar: string; discipline: Discipline; discipline_label_ar: string }[];
  open_issues: number;            // open QA issues
  next_milestone: { name_ar: string; date: string } | null;
}

type Task = {
  id: number; project_id: number;
  phase: string; phase_name_ar: string;
  name_ar: string; discipline: Discipline; discipline_label_ar: string;
  start: string; end: string;     // working days only (Sun–Thu)
  duration_days: number;          // working days
  hours: number;
  depends_on: number[];
  assignee: { id: number; name_ar: string } | null;
  status: TaskStatus; status_label_ar: string;
  progress: number;               // 0..100
  is_milestone: boolean;
}

type Phase = { key: string; name_ar: string; start: string; end: string; progress: number }

type DocumentItem = {
  id: number; project_id: number; project_code: string;
  code: string;                   // "MST011-MST-ZZ-00-DR-A-0001"
  title: string;                  // human title derived from the file name
  filename: string;
  discipline: Discipline; discipline_code: string; discipline_label_ar: string;
  doc_type: DocType; doc_type_label_ar: string;
  revision: string;               // "P01", "P02" (preliminary) or "C01" (published)
  state: CdeState; state_label_ar: string;
  size_bytes: number;
  uploaded_by: { id: number; name_ar: string }; uploaded_at: string;
  qa_status: QaStatus; qa_status_label_ar: string;
  is_latest: boolean; superseded_by: number | null;
  sha256_short: string;           // first 8 hex chars
}

type Transmittal = {
  id: number; code: string;       // "TR-MST011-0002"
  project_id: number; project_code: string;
  purpose_ar: string;             // "للعلم والاطلاع"
  documents: { id: number; code: string; revision: string; title: string }[];
  issued_to: { id: number; name_ar: string };
  created_by: { id: number; name_ar: string }; created_at: string;
}

type QaIssue = {
  rule_id: string; rule_name_ar: string;
  category: "zoning" | "deliverables" | "document";
  severity: Severity; severity_label_ar: string;
  actual: string; limit: string;  // display strings, e.g. "65%" / "≤ 60%"
  message_ar: string; fix_ar: string;
}

type QaReport = {
  id: number; project_id: number; project_code: string;
  document_id: number | null; document_code: string | null;
  phase: string; phase_name_ar: string;
  status: QaReportStatus; status_label_ar: string;
  summary_ar: string;
  issues: QaIssue[];
  checks_total: number; checks_passed: number;
  deliverables: { phase: string; phase_name_ar: string; complete_pct: number;
                  items: { discipline: Discipline; doc_type: DocType; label_ar: string; present: boolean }[] }[];
  created_at: string;
  signed_off_by: (UserRef & { license_no: string | null }) | null; signed_off_at: string | null; signoff_note: string | null;
  can_sign_off: boolean;          // for the current viewer
  blocking_reason_ar: string | null; // e.g. "توجد ملاحظات عالية الخطورة مفتوحة"
  notice_ar: string;              // placeholder notice for rule values
}

type Report = {
  id: number; project_id: number; project_code: string;
  kind: "weekly" | "client_update"; title_ar: string;
  period_start: string; period_end: string;
  progress_pct: number;
  body_ar: string;                // plain text with line breaks; "- " bullets allowed
  sections: { done: string[]; next: string[]; milestones: string[]; risks: string[] };
  sent_to_client: boolean; sent_at: string | null; created_at: string;
}

type AuditEntry = { id: number; ts: string; actor: UserRef | null; action: string; action_label_ar: string;
  resource: string;               // "project:3", "document:33"
  decision: "allow" | "deny"; reason_ar: string; run_id: string | null }

type Alert = { id: number; ts: string; severity: Severity; severity_label_ar: string;
  type: AlertType; type_label_ar: string; message_ar: string;
  actor: UserRef | null; resource: string; status: AlertStatus; status_label_ar: string }
```

## 4. Endpoints

### Meta and demo identity
| Method & path | Who | Response |
|---|---|---|
| `GET /api/health` | anyone | `{status:"ok", mode: Mode, version: string}` |
| `GET /api/meta` | anyone | `{app:{name_ar:"محور", name_en:"Mihwar", version, tagline_ar}, mode:{llm_enabled:boolean, label_ar, model: string\|null}, office:{name_ar, name_en}, notices:{demo_ar, placeholder_ar, auth_ar, estimate_ar}, today: string, timezone:"Asia/Riyadh"}` |
| `GET /api/demo/users` | anyone | `{items: DemoUser[]}` |
| `GET /api/me` | any user | `DemoUser` |
| `POST /api/demo/reset` | manager | re-seeds the demo database → `{ok:true}` |

### Client portal
| Method & path | Who | Body | Response |
|---|---|---|---|
| `GET /api/portal/office` | anyone | | `{office:{name_ar, name_en, city_ar, about_ar, phone, email, hours_ar, fictional_notice_ar}, services:{code, name_ar, name_en, description_ar, price_hint_ar}[], cities_served_ar: string[]}` |
| `GET /api/portal/requests` | client (own), manager (all) | | `{items: IntakeRequest[]}` newest first |
| `GET /api/portal/requests/{id}` | owner, manager | | `IntakeRequest` |
| `POST /api/portal/requests` | client | `{text}` | `{request: IntakeRequest, proposal: Proposal\|null, run: Run}` (event `client.request_submitted`; when the brief is complete the run chains `brief.ready` → Proposal draft) |
| `POST /api/portal/requests/{id}/messages` | owner | `{text}` | same shape (event `client.message`; merges answers into the brief) |
| `GET /api/portal/projects` | client (own), manager (all) | | `{items: {project: ProjectListItem, published_documents: DocumentItem[], updates: Report[], proposal: Proposal\|null}[]}` |
| `POST /api/portal/questions` | client (own project), manager | `{project_id, text}` | `{answer:{text_ar, intent, intent_label_ar, escalated:boolean, facts:{label_ar, value}[]}, run: Run}` (event `client.question`) |

### Proposals
| Method & path | Who | Response |
|---|---|---|
| `GET /api/proposals?status=` | manager (all); client (own, only `sent`/`accepted`/`rejected`); engineer 403 | `{items: Proposal[]}` |
| `GET /api/proposals/{id}` | same rules | `Proposal` |
| `POST /api/proposals/{id}/approve` | manager | `{proposal: Proposal, run: Run}` — `draft → approved → sent` (both transitions in `history`); 409 if not draft |
| `POST /api/proposals/{id}/accept` | owning client | `{proposal: Proposal, project: ProjectListItem, run: Run}` — run chains Planner (`plan.created`) and Team; 409 if not sent |

### Dashboard and activity
| Method & path | Who | Response |
|---|---|---|
| `GET /api/dashboard` | manager, engineer (client 403) | see below |
| `GET /api/activity?after_id=&limit=30` | manager, engineer | `{items: TraceStep[] (newest first, no input/output), last_id: number}` |
| `GET /api/runs/{run_id}` | manager, engineer | `Run` with full `input`/`output` on each step |

`GET /api/dashboard`:
```ts
{
  kpis: { key: string; label_ar: string; value: number; unit_ar: string; estimate: boolean; hint_ar: string | null }[];
  // keys: active_projects, proposals_pending, avg_intake_to_proposal_s, team_utilisation_pct,
  //       docs_controlled, qa_open_issues, security_alerts_open, hours_saved_est, cost_saved_est
  estimate_notice_ar: string;
  pending_approvals: { kind: "proposal" | "qa_signoff"; id: number; title_ar: string; subtitle_ar: string; created_at: string }[];
  projects_by_status: { status: ProjectStatus; label_ar: string; count: number }[];
  upcoming_milestones: { project_id: number; project_code: string; name_ar: string; date: string }[];
  agent_runs_today: number;
  recent_activity: TraceStep[];   // 15 newest
}
```

### Projects, tasks, plans, reports
| Method & path | Who | Body | Response |
|---|---|---|---|
| `GET /api/projects` | manager (all), engineer (assigned), client (own) | | `{items: ProjectListItem[]}` |
| `GET /api/projects/{id}` | same; denied access is audited and may raise an alert | | see below |
| `PATCH /api/projects/{id}/params` | manager, assigned engineer | `{coverage_ratio?, setback_front_m?, setback_side_m?, setback_rear_m?, height_m?, floors?, parking_spaces?}` | `{project: ProjectDetail, qa_report: QaReport, run: Run}` (event `project.params_changed` → Compliance re-check) |
| `PATCH /api/tasks/{id}` | manager, assignee | `{status?, assignee_id?, progress?}` | `{task: Task, team: TeamView, run: Run}` (event `task.changed`) |
| `POST /api/projects/{id}/reports/weekly` | manager, assigned engineer | `{send_to_client?: boolean}` | `{report: Report, run: Run}` (event `report.weekly`) |
| `POST /api/projects/{id}/qa` | manager, assigned engineer | `{document_id?: number}` | `{qa_report: QaReport, run: Run}` (event `qa.requested`) |
| `POST /api/qa/{id}/signoff` | licensed engineer or licensed manager | `{note?: string}` | `{qa_report: QaReport, run: Run}` (event `qa.signed_off`); 403 if not licensed; 409 if high-severity issues are open |

`GET /api/projects/{id}` → `ProjectDetail`:
```ts
{
  project: ProjectListItem & {
    land_area_m2: number; floors: number; bua_m2: number; description_ar: string;
    params: { coverage_ratio: number; setback_front_m: number; setback_side_m: number; setback_rear_m: number;
              height_m: number; floors: number; parking_spaces: number; units: number };
    params_labels_ar: Record<string, string>;
    services: { code: ServiceCode; name_ar: string }[];
    proposal_id: number | null;
  };
  phases: Phase[];
  tasks: Task[];
  documents: DocumentItem[];      // latest revisions first
  qa_reports: QaReport[];         // newest first
  reports: Report[];              // newest first
  proposal: Proposal | null;
  approvals: { kind: "proposal" | "qa_signoff"; label_ar: string; status: string; status_label_ar: string;
               by: UserRef | null; at: string | null; ref_id: number }[];
  calendar: { working_days_ar: string; weekend_ar: string; today: string; holidays: string[] };
  planner_notice_ar: string;      // durations are illustrative placeholders
}
```

### Team
| Method & path | Who | Body | Response |
|---|---|---|---|
| `GET /api/team` | manager, engineer | | `TeamView` |
| `POST /api/team/rebalance` | manager | `{task_id, to_engineer_id}` | `{task: Task, team: TeamView, run: Run}` (event `team.rebalance`) |

```ts
type TeamView = {
  window: { start: string; weeks: number };
  engineers: {
    id: number; name_ar: string; name_en: string; title_ar: string;
    discipline: Discipline; discipline_label_ar: string; is_licensed: boolean;
    capacity_hours_week: number;
    utilisation_pct: number;      // average over the window
    peak_pct: number;             // highest week
    status: "ok" | "high" | "overload"; status_label_ar: string; // high >= 85, overload > 100
    weekly: { week_start: string; hours: number; pct: number }[];
    tasks_count: number; projects: { id: number; code: string }[];
  }[];
  alerts: { id: string; severity: Severity; engineer_id: number; week_start: string; message_ar: string }[];
  suggestions: { id: string; task_id: number; task_name_ar: string; project_code: string;
                 from: { id: number; name_ar: string }; to: { id: number; name_ar: string };
                 hours: number; reason_ar: string; effect_ar: string }[];
  summary: { avg_utilisation_pct: number; overloaded_count: number; engineers_count: number };
}
```

### Files (Document Control)
| Method & path | Who | Body | Response |
|---|---|---|---|
| `GET /api/files?project_id=&state=&latest_only=true` | manager (all), engineer (assigned projects), client (own, PUBLISHED only) | | `{items: DocumentItem[], counts: Record<CdeState, number>, naming: {pattern, example, fields:{key,label_ar}[], notice_ar}}` |
| `POST /api/files` | manager, assigned engineer | multipart: `project_id`, `file` | `UploadResult` (event `file.uploaded`) |
| `POST /api/files/{id}/state` | manager, assigned engineer | `{to_state: CdeState}` | `{document: DocumentItem, gate: {required:boolean, passed:boolean, reason_ar}, transmittal: Transmittal\|null, run: Run}` (event `file.status_changed`); 409 `invalid_state` for an illegal transition; 409 `qa_signoff_required` when publishing without a signed-off QA report |
| `GET /api/files/{id}/download` | per RBAC (clients: PUBLISHED of own projects only) | | the file bytes; 403 JSON on deny (audited, may raise an alert) |
| `GET /api/transmittals?project_id=` | manager, engineer (assigned), client (own) | | `{items: Transmittal[]}` |

```ts
type UploadResult = {
  document: DocumentItem;
  classification: { discipline: Discipline; discipline_label_ar: string; doc_type: DocType; doc_type_label_ar: string;
                    confidence: number; reasons_ar: string[] };
  naming: { code: string; fields: { key: string; label_ar: string; value: string }[] };
  revision: { value: string; is_new_revision: boolean; previous: { id: number; revision: string } | null };
  duplicate_of: { id: number; code: string; revision: string } | null;   // identical content already registered
  warnings_ar: string[];
  run: Run;
}
```
Allowed transitions: `WIP→SHARED`, `SHARED→WIP`, `SHARED→PUBLISHED` (QA gate), `PUBLISHED→ARCHIVED`, `WIP→ARCHIVED`. On publish the revision becomes `C0n` and a transmittal to the client is created.
Upload limits: 20 MB; extensions `pdf dwg dxf rvt ifc xlsx xls docx doc pptx png jpg jpeg txt csv zip`.

### QA and compliance
| Method & path | Who | Response |
|---|---|---|
| `GET /api/compliance` | manager, engineer | `{notice_ar, rule_pack:{name_ar, version, rules:{id, name_ar, param, param_label_ar, op, value, unit_ar, severity, severity_label_ar, applies_to: ProjectType[], fix_ar}[]}, reports: QaReport[] (latest per project), summary:{projects_checked, open_high, open_medium, open_low, awaiting_signoff}}` |

### Security
| Method & path | Who | Body | Response |
|---|---|---|---|
| `GET /api/security/audit?limit=100&decision=` | manager | | `{items: AuditEntry[], total: number}` newest first |
| `GET /api/security/alerts?status=` | manager | | `{items: Alert[]}` |
| `POST /api/security/alerts/{id}/ack` | manager | | `{alert: Alert, run: Run}` (event `security.alert_ack`) |
| `GET /api/security/roles` | manager, engineer | | `{roles:{key, label_ar}[], permissions:{key, label_ar, manager, engineer, client}[], legend_ar: Record<string,string>}`; cell values: `allow` · `deny` · `assigned` · `own` · `published` · `licensed` |
| `POST /api/security/simulate` | manager | `{kind: "client_wip" \| "unassigned_access" \| "burst_download"}` | `{attempt_ar: string, decision: "deny" \| "allow", alert: Alert\|null, run: Run}` — performs the attempt as the relevant demo identity (labelled «محاكاة») |

### Agents, self-tests, scenario
| Method & path | Who | Response |
|---|---|---|
| `GET /api/agents` | manager, engineer | `{items: AgentCard[]}` (9, orchestrator first) |
| `GET /api/agents/graph` | manager, engineer | `{nodes:{id, label_ar, label_en, kind:"orchestrator"\|"agent"}[], edges:{from, to, event, label_ar}[], routes:{event, event_label_ar, agents: AgentKey[]}[]}` |
| `POST /api/agents/{key}/self-test` | manager, engineer | `SelfTestResult` |
| `POST /api/agents/self-test` | manager, engineer | `{passed: boolean, duration_ms: number, results: SelfTestResult[]}` |
| `POST /api/scenario/run` | manager | `202 {scenario_id, status:"running", stages_total: 9}` |
| `GET /api/scenario/{scenario_id}` | manager, engineer | `Scenario` (poll every 500 ms while `running`) |
| `GET /api/scenario/latest` | manager, engineer | `Scenario` or `404 not_found` |

```ts
type AgentKey = "orchestrator" | "intake" | "proposal" | "planner" | "team" | "documents" | "compliance" | "security" | "reporting";

type AgentCard = {
  key: AgentKey; order: number;   // 0..8
  name_ar: string; name_en: string; role_ar: string; role_en: string;
  triggers: string[]; triggers_labels_ar: string[];
  outputs_ar: string;
  llm_capable: boolean; mode: Mode;         // effective mode now
  challenge_phrase_ar: string;              // which phrase of the challenge it serves
  kpi_ar: string;                           // which KPI it improves
  stats: { runs: number; errors: number; denied: number; fallbacks: number; last_run_at: string | null; avg_duration_ms: number | null };
  health: AgentHealth; health_label_ar: string;
  last_self_test: { passed: boolean; at: string; checks_passed: number; checks_total: number } | null;
}

type SelfTestResult = {
  key: AgentKey; name_ar: string; name_en: string; passed: boolean; duration_ms: number; ran_at: string;
  checks: { name_en: string; name_ar: string; passed: boolean; detail: string }[];
}

type Scenario = {
  scenario_id: string; status: "running" | "completed" | "failed";
  started_at: string; finished_at: string | null; duration_ms: number;
  current_stage: number;          // 1..9 (0 before start)
  stages: {
    n: number; key: string; title_ar: string; title_en: string; actor_role: Role | "system";
    status: "pending" | "running" | "done" | "failed";
    highlight_ar: string | null;  // one-line result, e.g. "فيلا · الرياض · 625 م² · دوران"
    steps: TraceStep[];           // with input/output
  }[];
  result: { request_id?: number; proposal_id?: number; project_id?: number; document_id?: number;
            qa_report_id?: number; alert_id?: number; report_id?: number } | null;
  error_ar: string | null;
}
```

Scenario stages (fixed order): 1 `intake` client request (free Arabic text with Arabic-Indic digits) · 2 `proposal` draft · 3 `approval` manager approves, client accepts · 4 `planner` · 5 `team` · 6 `documents` engineer uploads a drawing · 7 `compliance` QA report, licensed sign-off, publish gate · 8 `security` blocked unauthorised attempt + alert · 9 `reporting` client update sent.
Steps appear progressively (backend inserts `MIHWAR_SCENARIO_DELAY` seconds between steps, default 0.6; tests use 0).

## 5. Changes after v1 (implemented)

- `TeamView` adds `capacity_notes: {engineer_id, message_ar}[]`: overloaded engineers that no same-discipline colleague can relieve
  (recommend extending a duration or adding a resource). Rebalancing suggestions now accept a target that stays at or below 100%.
- 403 errors raised by the Security agent include `alert_id` (or `null`) next to `run_id`.
- Dashboard KPIs for counts return `unit_ar: ""` (the label already names the unit).
- `GET /api/security/roles` is readable by manager and engineer (permission `agents.view`).
- Scenario stage 6 uploads two files (the architect's ground-floor plan, published in stage 7, and the structural engineer's draft
  calculations, which stay WIP); stage 8 is the client trying to download that WIP file (alert `client_wip_request`).
- Human-facing Arabic sentences use dates like «4 أكتوبر 2026» (ISO dates get reordered inside right-to-left text) and wrap codes
  in Unicode LTR isolates; JSON date fields stay ISO.
