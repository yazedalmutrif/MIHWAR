"""Document Control agent (وكيل التحكم بالوثائق).

On every upload it classifies the discipline and document type, applies a naming
convention inspired by ISO 19650, manages revisions and the common-data-environment
states WIP -> Shared -> Published -> Archived, detects duplicates and superseded files,
and issues transmittals when a file is published to the client.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .. import clock, labels, repo
from ..db import dumps, loads
from ..llm import LLMUnavailable
from .base import BaseAgent, Check, DomainError, StepResult
from .intake import norm

ALLOWED_EXT = {"pdf", "dwg", "dxf", "rvt", "ifc", "xlsx", "xls", "docx", "doc", "pptx", "png", "jpg", "jpeg", "txt", "csv", "zip"}
MAX_BYTES = 20 * 1024 * 1024
TRANSITIONS = {("WIP", "SHARED"), ("SHARED", "WIP"), ("SHARED", "PUBLISHED"), ("PUBLISHED", "ARCHIVED"), ("WIP", "ARCHIVED")}
CODE_RE = re.compile(r"^[A-Z]{2,5}\d{3}-[A-Z]{2,5}-ZZ-(?:\d{2}|RF|B\d|ZZ)-[A-Z0-9]{2}-[ASMEPZ]-\d{4}$")
NAMING_PATTERN = "<مشروع>-<الجهة المُعِدّة>-<المنطقة>-<المستوى>-<النوع>-<التخصص>-<الرقم>"

DISCIPLINE_RULES: list[tuple[str, list[str]]] = [
    ("structural", [r"struct", r"انشا", r"foundation", r"قواعد", r"اساسات", r"اعمده", r"column", r"beam", r"كمرات",
                    r"slab", r"بلاطات", r"تسليح", r"rebar", r"(?:^|\s)s\s?\d{2,3}"]),
    ("mechanical", [r"mech", r"hvac", r"تكييف", r"ميكانيك", r"duct", r"مجاري الهواء", r"(?:^|\s)m\s?\d{2,3}"]),
    ("electrical", [r"elec", r"كهرب", r"lighting", r"اناره", r"power", r"لوحات التوزيع", r"(?:^|\s)e\s?\d{2,3}"]),
    ("plumbing", [r"plumb", r"sanitary", r"سباك", r"صرف", r"drainage", r"water supply", r"تغذيه", r"(?:^|\s)صحي",
                  r"(?:^|\s)p\s?\d{2,3}"]),
    ("architectural", [r"arch", r"معماري", r"floor ?plan", r"(?:^|\s)plan", r"مسقط", r"مساقط", r"واجه", r"elevation",
                       r"section", r"قطاع", r"layout", r"render", r"منظور", r"(?:^|\s)a\s?\d{2,3}"]),
]
GENERAL_HINTS = [r"soil", r"تربه", r"survey", r"رفع مساحي", r"boq", r"كميات", r"spec", r"مواصفات", r"تقرير"]
LEVEL_RULES = [("00", r"ground|ارضي|(?:^|\s)gf(?:\s|$)"), ("01", r"first|(?:^|\s)اول|الاول|1st|(?:^|\s)1f"),
               ("02", r"second|ثاني|2nd|(?:^|\s)2f"), ("RF", r"roof|سطح|ملحق|(?:^|\s)rf(?:\s|$)"),
               ("B1", r"basement|قبو|(?:^|\s)b1")]
REV_MARKERS = re.compile(
    r"(?:\s*\b(?:v|rev|r|ver|version)\s?\d+\b|\s*(?:نسخة|نسخه|إصدار|اصدار)\s?\d+|\s*\(\d+\)"
    r"|\s*\b(?:final|copy|draft)\b|\s*(?:نهائي|نهايي|مسودة|مسوده)(?![؀-ۿ]))", re.I)

LLM_SCHEMA = {
    "type": "object",
    "properties": {
        "discipline": {"type": "string", "enum": list(labels.DISCIPLINE)},
        "doc_type": {"type": "string", "enum": list(labels.DOC_TYPE)},
        "reason_ar": {"type": "string"},
    },
    "required": ["discipline", "doc_type", "reason_ar"],
    "additionalProperties": False,
}


def _clean(filename: str) -> tuple[str, str]:
    stem, _, ext = filename.rpartition(".")
    if not stem:
        stem, ext = filename, ""
    return stem, ext.lower()


def classify(filename: str) -> dict:
    """Pure, deterministic classification from the file name."""
    stem, ext = _clean(filename)
    text = norm(re.sub(r"[_\-\.]+", " ", stem))
    reasons: list[str] = []
    scores = []
    for disc, pats in DISCIPLINE_RULES:
        hits = [p for p in pats if re.search(p, text)]
        if hits:
            scores.append((len(hits), -[d for d, _ in DISCIPLINE_RULES].index(disc), disc, hits))
    if scores:
        scores.sort(reverse=True)
        n, _, discipline, hits = scores[0]
        disc_conf = min(0.95, 0.55 + 0.2 * n)
        reasons.append(f"التخصص «{labels.DISCIPLINE[discipline]}» من كلمات في اسم الملف")
    else:
        discipline, disc_conf = "general", (0.7 if any(re.search(p, text) for p in GENERAL_HINTS) else 0.4)
        reasons.append("لا توجد دلالة تخصص واضحة؛ صُنّف «عام»")

    def has(*pats):
        return any(re.search(p, text) for p in pats)

    if ext in ("rvt", "ifc"):
        doc_type, type_conf, why = "M3", 0.9, f"امتداد .{ext} لنموذج ثلاثي الأبعاد"
    elif has(r"calc", r"حساب", r"calculation"):
        doc_type, type_conf, why = "CA", 0.9, "كلمة «حسابات» في الاسم"
    elif has(r"boq", r"كميات", r"bill of quant", r"quantit"):
        doc_type, type_conf, why = "SH", 0.9, "كلمة «كميات» في الاسم"
    elif has(r"spec", r"مواصفات"):
        doc_type, type_conf, why = "SP", 0.9, "كلمة «مواصفات» في الاسم"
    elif has(r"report", r"تقرير", r"soil", r"تربه", r"survey"):
        doc_type, type_conf, why = "RP", 0.9, "كلمة «تقرير» أو «تربة» في الاسم"
    elif has(r"render", r"منظور", r"3d", r"perspective", r"visual") or ext in ("png", "jpg", "jpeg"):
        doc_type, type_conf, why = "VS", 0.8, "منظور أو صورة"
    elif ext == "pptx":
        doc_type, type_conf, why = "PP", 0.9, "عرض تقديمي"
    elif ext in ("xlsx", "xls", "csv"):
        doc_type, type_conf, why = "SH", 0.7, f"جدول بامتداد .{ext}"
    elif ext in ("dwg", "dxf"):
        doc_type, type_conf, why = "DR", 0.9, f"امتداد .{ext} لملفات المخططات"
    elif ext in ("docx", "doc", "txt"):
        doc_type, type_conf, why = "RP", 0.6, "مستند نصي"
    else:
        doc_type, type_conf, why = "DR", 0.7 if has(r"plan", r"مسقط", r"مخطط", r"واجه", r"elevation", r"section", r"قطاع", r"layout", r"detail", r"تفاصيل") else 0.5, "مخطط PDF"
    reasons.append(f"النوع «{labels.DOC_TYPE[doc_type]}»: {why}")
    level = "ZZ"
    for code, pat in LEVEL_RULES:
        if re.search(pat, text):
            level = code
            reasons.append(f"المستوى {code} من اسم الملف")
            break
    title = REV_MARKERS.sub("", re.sub(r"[_]+", " ", stem)).strip(" -._") or stem
    return {"discipline": discipline, "doc_type": doc_type, "level": level, "confidence": round((disc_conf + type_conf) / 2, 2),
            "reasons_ar": reasons, "title": title, "ext": ext}


def lineage_key(title: str, discipline: str, doc_type: str) -> str:
    t = norm(REV_MARKERS.sub("", title))
    t = re.sub(r"[\s_\-\.]+", " ", t).strip()
    return f"{t}|{discipline}|{doc_type}"


class DocumentsAgent(BaseAgent):
    key = "documents"
    order = 5
    name_ar = "وكيل التحكم بالوثائق"
    name_en = "Document Control"
    role_ar = "يصنّف كل ملف مرفوع ويرمّزه وفق منهجية مستوحاة من ISO 19650، ويدير الإصدارات ومراحل الاعتماد ويصدر خطابات الإرسال."
    role_en = "Classifies uploads, applies an ISO 19650-inspired naming convention, manages revisions, CDE states and transmittals."
    triggers = ("file.uploaded", "file.status_changed")
    outputs_ar = "سجل الوثائق (الترميز، الإصدار، الحالة) + خطاب إرسال عند النشر"
    llm_capable = True
    challenge_phrase_ar = "وإدارة ملفاتها الهندسية عن بُعد"
    kpi_ar = "زمن الوصول لأحدث إصدار وتقليل الأخطاء بسبب النسخ القديمة"

    # ------------------------------------------------------------------ helpers
    def _classify(self, filename: str) -> tuple[dict, str]:
        c = classify(filename)
        mode = "offline"
        if self.ctx.llm.enabled and c["confidence"] < 0.6:
            try:
                data = self.ctx.llm.complete_json(
                    "You classify engineering document file names for a Saudi engineering office. Return the discipline "
                    "and document type using only the allowed values, and a short Arabic reason.",
                    f"File name: {filename}", LLM_SCHEMA, max_tokens=2048)
                if data.get("discipline") in labels.DISCIPLINE and data.get("doc_type") in labels.DOC_TYPE:
                    c.update(discipline=data["discipline"], doc_type=data["doc_type"], confidence=max(c["confidence"], 0.75))
                    c["reasons_ar"].append("Claude: " + str(data.get("reason_ar", ""))[:160])
                    mode = "llm"
                else:
                    raise LLMUnavailable("invalid enum")
            except LLMUnavailable:
                mode = "offline-fallback"
        return c, mode

    def _code(self, project: dict, c: dict, number: int) -> str:
        office = repo.office()
        return (f"{repo.compact_project_code(project['code'])}-{office['code']}-ZZ-{c['level']}-{c['doc_type']}-"
                f"{labels.DISCIPLINE_CODE[c['discipline']]}-{number:04d}")

    def _store_file(self, doc_id: int, project_id: int, filename: str, content: bytes) -> str:
        folder = Path(self.ctx.settings.uploads_dir) / str(project_id)
        folder.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w؀-ۿ.\- ]+", "_", filename)[:120]
        path = folder / f"{doc_id}_{safe}"
        path.write_bytes(content)
        return str(path)

    # ------------------------------------------------------------------ operations
    def op_register(self, project_id: int, filename: str, content: bytes, uploader: dict) -> StepResult:
        project = self.db.get("projects", project_id)
        if not project:
            raise DomainError("not_found", "المشروع غير موجود", "Project not found", 404)
        filename = Path(filename or "file").name
        stem, ext = _clean(filename)
        if ext not in ALLOWED_EXT:
            raise DomainError("validation_error", f"امتداد الملف .{ext} غير مسموح", f"File type .{ext} is not allowed", 422)
        if len(content) > MAX_BYTES:
            raise DomainError("validation_error", "حجم الملف يتجاوز 20 ميجابايت", "File exceeds 20 MB", 422)
        if not content:
            raise DomainError("validation_error", "الملف فارغ", "The file is empty", 422)
        sha = hashlib.sha256(content).hexdigest()
        c, mode = self._classify(filename)
        warnings: list[str] = []
        dup = self.db.one("SELECT * FROM documents WHERE project_id = ? AND sha256 = ?", (project_id, sha))
        if dup:
            warnings.append("الملف مطابق تمامًا لملف مسجّل مسبقًا؛ لم يُنشأ إصدار جديد.")
            return StepResult(
                output={"document_id": dup["id"], "duplicate_of": dup["id"], "classification": c, "warnings": warnings,
                        "is_new_revision": False, "previous": None},
                input_summary=f"{filename} ({len(content):,} بايت)",
                output_summary=f"ملف مكرر لـ {clock.ltr(dup['code'] + ' ' + dup['revision'])} — لم يُسجَّل",
                mode=mode, input={"project_id": project_id, "filename": filename},
            )
        key = lineage_key(c["title"], c["discipline"], c["doc_type"])
        prev = self.db.one("SELECT * FROM documents WHERE project_id = ? AND base_key = ? AND superseded_by IS NULL "
                           "ORDER BY id DESC LIMIT 1", (project_id, key))
        if prev:
            number = prev["number"]
            rev_seq = (self.db.scalar("SELECT COUNT(*) FROM documents WHERE project_id = ? AND base_key = ? AND revision LIKE 'P%'",
                                      (project_id, key)) or 0) + 1
            if prev["state"] == "PUBLISHED":
                warnings.append("الإصدار السابق منشور للعميل وسيبقى متاحًا حتى نشر الإصدار الجديد.")
        else:
            number = (self.db.scalar("SELECT MAX(number) FROM documents WHERE project_id = ? AND doc_type = ? AND discipline = ?",
                                     (project_id, c["doc_type"], c["discipline"])) or 0) + 1
            rev_seq = 1
        if c["confidence"] < 0.6:
            warnings.append("ثقة التصنيف منخفضة؛ يُنصح بمراجعة التخصص والنوع.")
        code = self._code(project, c, number)
        revision = f"P{rev_seq:02d}"
        doc_id = self.db.insert("documents", {
            "project_id": project_id, "code": code, "title": c["title"], "base_key": key, "filename": filename,
            "discipline": c["discipline"], "doc_type": c["doc_type"], "number": number, "level": c["level"],
            "revision": revision, "rev_seq": rev_seq, "state": "WIP", "size_bytes": len(content),
            "uploaded_by": uploader["id"] if uploader else None, "uploaded_at": clock.now_iso(),
            "qa_status": "not_requested", "superseded_by": None, "sha256": sha, "stored_path": None,
        })
        path = self._store_file(doc_id, project_id, filename, content)
        self.db.update("documents", doc_id, {"stored_path": path})
        if prev and prev["state"] != "PUBLISHED":
            self.db.update("documents", prev["id"], {"superseded_by": doc_id})
        return StepResult(
            output={"document_id": doc_id, "code": code, "revision": revision, "is_new_revision": bool(prev),
                    "previous": {"id": prev["id"], "revision": prev["revision"]} if prev else None, "duplicate_of": None,
                    "classification": c, "warnings": warnings},
            input_summary=f"{filename} ({len(content):,} بايت) · {project['code']}",
            output_summary=f"{labels.DISCIPLINE[c['discipline']]} · {labels.DOC_TYPE[c['doc_type']]} ← {clock.ltr(code)} · {revision}"
                           + (" (إصدار جديد)" if prev else ""),
            mode=mode, input={"project_id": project_id, "filename": filename, "size": len(content)},
        )

    def op_transition(self, document_id: int, to_state: str, actor: dict) -> StepResult:
        doc = self.db.get("documents", document_id)
        if not doc:
            raise DomainError("not_found", "الملف غير موجود", "Document not found", 404)
        frm = doc["state"]
        if to_state not in labels.CDE_STATE or (frm, to_state) not in TRANSITIONS:
            raise DomainError("invalid_state", f"لا يمكن نقل الملف من «{labels.CDE_STATE.get(frm, frm)}» إلى «{labels.CDE_STATE.get(to_state, to_state)}»",
                              f"Illegal transition {frm} -> {to_state}", 409)
        if to_state == "PUBLISHED" and doc["qa_status"] != "signed_off":
            raise DomainError("qa_signoff_required", "لا يُنشر الملف قبل توقيع مهندس مرخّص على مراجعة الجودة",
                              "Publishing requires a QA report signed off by a licensed engineer", 409)
        update: dict = {"state": to_state}
        transmittal_id = None
        if to_state == "PUBLISHED":
            n_pub = self.db.scalar("SELECT COUNT(*) FROM documents WHERE project_id = ? AND base_key = ? AND revision LIKE 'C%'",
                                   (doc["project_id"], doc["base_key"])) or 0
            update["revision"] = f"C{n_pub + 1:02d}"
            older = self.db.all("SELECT id FROM documents WHERE project_id = ? AND base_key = ? AND state = 'PUBLISHED' AND id != ?",
                                (doc["project_id"], doc["base_key"], document_id))
            for o in older:
                self.db.update("documents", o["id"], {"state": "ARCHIVED", "superseded_by": document_id})
            self.db.execute("UPDATE documents SET superseded_by = ? WHERE project_id = ? AND base_key = ? AND id != ? AND superseded_by IS NULL",
                            (document_id, doc["project_id"], doc["base_key"], document_id))
        self.db.update("documents", document_id, update)
        if to_state == "PUBLISHED":
            transmittal_id = self.issue_transmittal(doc["project_id"], [document_id], actor, "إصدار معتمد للعميل للعلم والاطلاع")
        doc = self.db.get("documents", document_id)
        return StepResult(
            output={"document_id": document_id, "from": frm, "to": to_state, "revision": doc["revision"],
                    "transmittal_id": transmittal_id},
            input_summary=f"{clock.ltr(doc['code'])} · {labels.CDE_STATE[frm]} ← {labels.CDE_STATE[to_state]}",
            output_summary=f"الحالة الآن {labels.CDE_STATE[to_state]} · الإصدار {doc['revision']}"
                           + (" · صدر خطاب إرسال للعميل" if transmittal_id else ""),
            input={"document_id": document_id, "to_state": to_state},
        )

    def issue_transmittal(self, project_id: int, doc_ids: list[int], actor: dict, purpose: str) -> int:
        project = self.db.get("projects", project_id)
        client_user = self.db.one("SELECT * FROM users WHERE role = 'client' AND client_id = ? ORDER BY id LIMIT 1", (project["client_id"],))
        seq = (self.db.scalar("SELECT COUNT(*) FROM transmittals WHERE project_id = ?", (project_id,)) or 0) + 1
        docs = [self.db.get("documents", i) for i in doc_ids]
        return self.db.insert("transmittals", {
            "code": f"TR-{repo.compact_project_code(project['code'])}-{seq:04d}", "project_id": project_id,
            "purpose_ar": purpose,
            "docs_json": [{"id": d["id"], "code": d["code"], "revision": d["revision"], "title": d["title"]} for d in docs],
            "issued_to": client_user["id"] if client_user else None, "created_by": actor["id"] if actor else None,
            "created_at": clock.now_iso(),
        })

    # ------------------------------------------------------------------ self-test
    def self_test(self) -> list[Check]:
        checks = []
        c1 = classify("S-101 Foundation Plan rev2.pdf")
        checks.append(self.check("Structural drawing from an English name", "تصنيف مخطط إنشائي من اسم إنجليزي",
                                 c1["discipline"] == "structural" and c1["doc_type"] == "DR", f"{c1['discipline']} / {c1['doc_type']}"))
        c2 = classify("مسقط الدور الأرضي - فيلا النرجس.pdf")
        checks.append(self.check("Arabic architectural plan with level", "مسقط معماري عربي مع المستوى",
                                 c2["discipline"] == "architectural" and c2["doc_type"] == "DR" and c2["level"] == "00",
                                 f"{c2['discipline']} / {c2['doc_type']} / {c2['level']}"))
        c3 = classify("حسابات التسليح للأعمدة.xlsx")
        checks.append(self.check("Structural calculations", "حسابات إنشائية", c3["discipline"] == "structural" and c3["doc_type"] == "CA",
                                 f"{c3['discipline']} / {c3['doc_type']}"))
        c4 = classify("HVAC layout first floor.dwg")
        checks.append(self.check("Mechanical drawing, first floor", "مخطط تكييف للدور الأول",
                                 c4["discipline"] == "mechanical" and c4["level"] == "01", f"{c4['discipline']} / {c4['level']}"))
        project = self.db.one("SELECT * FROM projects ORDER BY id LIMIT 1")
        uploader = self.db.one("SELECT * FROM users WHERE role='engineer' LIMIT 1")
        r1 = self.op_register(project["id"], "Selftest Electrical Lighting Plan.pdf", b"%PDF-1.4 selftest v1", uploader)
        checks.append(self.check("Naming code follows the convention", "الترميز يطابق المنهجية",
                                 bool(CODE_RE.match(r1.output["code"])) and r1.output["revision"] == "P01", r1.output["code"]))
        r2 = self.op_register(project["id"], "Selftest Electrical Lighting Plan v2.pdf", b"%PDF-1.4 selftest v2", uploader)
        old = self.db.get("documents", r1.output["document_id"])
        checks.append(self.check("New upload of the same drawing becomes P02 and supersedes P01", "إصدار جديد P02 يحل محل P01",
                                 r2.output["revision"] == "P02" and r2.output["code"] == r1.output["code"] and old["superseded_by"] == r2.output["document_id"],
                                 f"{r1.output['revision']} → {r2.output['revision']}"))
        r3 = self.op_register(project["id"], "copy of lighting.pdf", b"%PDF-1.4 selftest v2", uploader)
        checks.append(self.check("Identical content is detected as a duplicate", "كشف الملف المكرر",
                                 r3.output["duplicate_of"] == r2.output["document_id"], r3.output_summary))
        blocked = None
        try:
            self.op_transition(r2.output["document_id"], "PUBLISHED", uploader)
        except DomainError as e:
            blocked = e.code
        checks.append(self.check("Illegal jump WIP → Published is refused", "رفض القفز من WIP إلى النشر", blocked == "invalid_state", str(blocked)))
        self.op_transition(r2.output["document_id"], "SHARED", uploader)
        gate = None
        try:
            self.op_transition(r2.output["document_id"], "PUBLISHED", uploader)
        except DomainError as e:
            gate = e.code
        checks.append(self.check("Publishing requires a signed-off QA report", "النشر يتطلب توقيع مراجعة الجودة",
                                 gate == "qa_signoff_required", str(gate)))
        return checks
