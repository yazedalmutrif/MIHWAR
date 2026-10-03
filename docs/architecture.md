# Mihwar architecture

## Agent graph

Every website action becomes an event. The orchestrator routes it through the agents declared in `ROUTES`
(`mihwar/orchestrator.py`); the Security agent always runs first for actions a person takes.

```mermaid
flowchart TB
    UI["Arabic web app<br/>(client portal · office · agents)"] -->|"REST /api (X-Demo-User)"| API["FastAPI routes<br/>mihwar/app.py"]
    API -->|"POST/PATCH = event"| ORCH(("Orchestrator<br/>المنسّق"))
    API -->|"GET = authorised read"| SEC
    ORCH --> SEC["7 · Security & Access"]
    ORCH --> INT["1 · Client Intake"]
    ORCH --> PRO["2 · Proposal & Pricing"]
    ORCH --> PLN["3 · Project Planner"]
    ORCH --> TEAM["4 · Team & Resources"]
    ORCH --> DOC["5 · Document Control"]
    ORCH --> QA["6 · QA & Compliance"]
    ORCH --> REP["8 · Reporting & Comms"]
    INT -. "brief.ready" .-> PRO
    PRO -. "proposal.accepted" .-> PLN
    PLN -. "plan.created" .-> TEAM
    QA -. "publish gate" .-> DOC
    ORCH --> TRACE[("runs · steps<br/>trace")]
    SEC --> AUDIT[("audit · alerts")]
    INT & PRO & PLN & TEAM & DOC & QA & REP --> DB[("SQLite<br/>projects · tasks · documents …")]
    INT & DOC & REP -. "optional" .-> LLM{{"Claude claude-opus-5-5<br/>JSON schema · fallbacks"}}
```

## Request flow (example: a client submits a request)

```mermaid
sequenceDiagram
    participant C as Client (portal)
    participant O as Orchestrator
    participant S as Security
    participant I as Intake
    participant P as Proposal
    participant M as Manager
    C->>O: client.request_submitted {text}
    O->>S: authorize(portal.request.create)
    S-->>O: allow (audited)
    O->>I: submit(text)
    I-->>O: brief complete
    O->>P: brief.ready -> draft()
    P-->>O: PR-2026-0xx (draft)
    O-->>C: reply + "awaiting manager approval"
    M->>O: proposal.approved
    O->>S: authorize(proposal.approve)
    O->>P: approve() -> sent
    C->>O: proposal.accepted
    O->>P: accept() -> project created
    O->>O: planner.plan -> plan.created -> team.assign
```

## Human in the loop

| Decision | Who | Enforced by |
|---|---|---|
| Send a proposal to the client | Office manager | Proposal agent state machine + Security (`proposal.approve`) |
| Publish a file to the client | Licensed engineer signs the QA report | Compliance gate + Document Control (`qa_signoff_required`) |
| Reassign a task | Office manager | Security (`team.rebalance`) |
| Any engineering approval/stamp | Licensed engineer, outside the platform | The platform never approves designs on its own |

## Modes

| | Offline (default) | Claude (optional) |
|---|---|---|
| Intake | regex + keyword extraction with evidence | structured JSON extraction, merged and validated |
| Document Control | filename rules | consulted only when confidence < 0.6 |
| Reporting | templates from project data | rewording of the same facts; rejected if a figure is lost |
| On error | n/a | automatic fallback, traced as `offline-fallback` |

## Main data

`users`, `clients`, `requests`, `messages`, `proposals`, `projects`, `project_members`, `tasks`, `documents`,
`transmittals`, `qa_reports`, `reports`, `audit`, `alerts`, `runs`, `steps`, `selftests` (SQLite, `var/mihwar.db`).

Editable configuration (illustrative values): `mihwar/data/price_list.json`, `rule_pack.json`, `phase_templates.json`,
`assumptions.json`, `office.json`.

## Path to production (after the hackathon)

PostgreSQL + object storage for files · real authentication (SSO / national identity provider) and per-office tenancy ·
hosting inside Saudi Arabia · rule packs authored with licensed engineers from the official Saudi Building Code and
municipal requirements · a drawing viewer (PDF/IFC) · integrations with the office's existing tools.
