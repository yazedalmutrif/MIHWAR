"""Client Intake agent (وكيل استقبال العملاء).

Reads a client's free-text request (Arabic or English, including Arabic-Indic digits and
Saudi dialect words), extracts a structured project brief, records which text each field
came from, and asks follow-up questions for anything missing. Works 24/7 on the portal.
"""
from __future__ import annotations

import math
import re
from typing import Any

from pydantic import BaseModel, ValidationError, field_validator

from .. import clock, labels, repo
from ..db import dumps, loads
from ..llm import LLMUnavailable
from .base import BaseAgent, Check, DomainError, StepResult

# ---------------------------------------------------------------------------
# Normalisation (length-tracked so evidence can quote the client's original text)
# ---------------------------------------------------------------------------
_CHAR_MAP = {
    **{c: d for c, d in zip("٠١٢٣٤٥٦٧٨٩", "0123456789")},
    **{c: d for c, d in zip("۰۱۲۳۴۵۶۷۸۹", "0123456789")},
    "٫": ".", "٬": ",", "،": ",", "؛": ";", "؟": "?",
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ة": "ه", "ى": "ي", "ئ": "ي",
}
_DROP = re.compile(r"[ؗ-ًؚ-ْٰـ]")  # harakat + tatweel
AR = "؀-ۿ"


def normalize_with_map(text: str) -> tuple[str, list[int]]:
    out: list[str] = []
    idx: list[int] = []
    for i, ch in enumerate(text):
        if _DROP.match(ch):
            continue
        mapped = _CHAR_MAP.get(ch, ch).lower()
        for c in mapped:
            out.append(c)
            idx.append(i)
    return "".join(out), idx


def norm(text: str) -> str:
    return normalize_with_map(text)[0]


def P(pattern: str) -> re.Pattern:
    """Compile a pattern written in natural Arabic: map Arabic letters only (no lowercasing,
    which would corrupt regex escapes such as \\D or \\S)."""
    mapped = "".join(_CHAR_MAP.get(ch, ch) if "؀" <= ch <= "ۿ" else ch for ch in pattern)
    return re.compile(mapped)


NUM = r"(?<![\d.,])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
NUM_WORDS = {
    "واحد": 1, "واحده": 1, "اثنين": 2, "اثنان": 2, "ثنين": 2, "ثلاث": 3, "ثلاثه": 3, "اربع": 4, "اربعه": 4,
    "خمس": 5, "خمسه": 5, "ست": 6, "سته": 6, "سبع": 7, "سبعه": 7, "ثمان": 8, "ثمانيه": 8, "تسع": 9, "تسعه": 9,
    "عشر": 10, "عشره": 10, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10,
}
NUM_WORD_RE = "|".join(sorted(NUM_WORDS, key=len, reverse=True))


def to_number(s: str) -> float:
    return float(s.replace(",", ""))


FIELD_LABELS = {
    "client_name": "اسم العميل",
    "project_type": "نوع المشروع",
    "city": "المدينة",
    "district": "الحي",
    "land_area_m2": "مساحة الأرض",
    "floors": "عدد الأدوار",
    "has_annex": "ملحق علوي",
    "services": "الخدمات المطلوبة",
    "timeline_months": "المدة المطلوبة",
    "budget_sar": "الميزانية التقديرية",
}
FLOOR_TYPES = {"villa", "residential_building", "commercial", "mixed_use", "office"}
QUESTIONS_AR = {
    "project_type": "ما نوع المشروع؟ (فيلا سكنية، عمارة سكنية، مبنى تجاري، استراحة، ...)",
    "city": "في أي مدينة يقع المشروع؟ ويسعدنا معرفة الحي إن أمكن.",
    "land_area_m2": "كم تبلغ مساحة الأرض بالمتر المربع؟",
    "floors": "كم عدد الأدوار المطلوبة؟ وهل يوجد ملحق علوي؟",
    "services": "ما الخدمات التي تحتاجها؟ (تصميم معماري، إنشائي، كهروميكانيكي، رخصة بناء، إشراف)",
}
QUESTIONS_EN = {
    "project_type": "What type of project is it? (villa, residential building, commercial building, rest house, ...)",
    "city": "Which city is the project in? The district helps too.",
    "land_area_m2": "What is the land area in square metres?",
    "floors": "How many floors do you need? Is there a roof annex?",
    "services": "Which services do you need? (architectural, structural, MEP design, building permit, supervision)",
}

TYPE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("mixed_use", P(r"متعدد الاستخدام|سكني تجاري|تجاري سكني|mixed[\s-]?use")),
    ("residential_building", P(r"عمارة|عماير|عمائر|شقق|مبنى سكني|مبني سكني|apartment|residential building")),
    ("office", P(r"مبنى مكاتب|مبني مكاتب|مبنى إداري|مبني اداري|مكاتب إدارية|office building|offices")),
    ("commercial", P(r"مركز تجاري|محلات|محل تجاري|معرض تجاري|مبنى تجاري|مبني تجاري|(?<![" + AR + r"])(?:ال)?مول(?![" + AR + r"])|commercial|retail|showroom")),
    ("rest_house", P(r"استراحة|شاليه|rest ?house|chalet")),
    ("warehouse", P(r"مستودع|مستودعات|هنقر|warehouse")),
    ("mosque", P(r"مسجد|جامع(?![" + AR + r"])|mosque")),
    ("villa", P(r"فيلا|فيلة|فلة|فله|فلل|villa|(?<![" + AR + r"])[وبل]?(?:ال)?(?:منزل|بيت)(?:ي|نا)?(?![" + AR + r"])|house")),
    ("renovation", P(r"ترميم|تجديد|إعادة تأهيل|renovat")),
    ("interior", P(r"تصميم داخلي|ديكور|interior")),
]

CITY_VARIANTS = {
    "الرياض": ["الرياض", "riyadh"],
    "جدة": ["جدة", "جده", "jeddah", "jedda"],
    "مكة المكرمة": ["مكة", "مكه", "makkah", "mecca"],
    "المدينة المنورة": ["المدينة المنورة", "المدينه المنوره", "madinah", "medina"],
    "الدمام": ["الدمام", "dammam"],
    "الظهران": ["الظهران", "dhahran"],
    "الطائف": ["الطائف", "الطايف", "taif"],
    "أبها": ["أبها", "ابها", "abha"],
    "خميس مشيط": ["خميس مشيط", "khamis mushait"],
    "تبوك": ["تبوك", "tabuk"],
    "بريدة": ["بريدة", "buraidah", "buraydah"],
    "عنيزة": ["عنيزة", "unaizah"],
    "القصيم": ["القصيم", "qassim"],
    "حائل": ["حائل", "حايل", "hail"],
    "جازان": ["جازان", "جيزان", "jazan", "jizan"],
    "نجران": ["نجران", "najran"],
    "الجبيل": ["الجبيل", "jubail"],
    "ينبع": ["ينبع", "yanbu"],
    "الأحساء": ["الأحساء", "الاحساء", "الهفوف", "ahsa", "hofuf"],
    "القطيف": ["القطيف", "qatif"],
    "الباحة": ["الباحة", "baha"],
    "عرعر": ["عرعر", "arar"],
    "سكاكا": ["سكاكا", "sakaka"],
}
_KHOBAR = P(r"(?<![" + AR + r"])[وبلف]?الخبر(?![" + AR + r"])|\bkhobar\b")


def _city_pattern(variants: list[str]) -> re.Pattern:
    """Arabic names may carry an attached prefix (بالرياض، وجدة) but must not sit inside another
    word (سمكة must not match مكة); English names use word boundaries."""
    parts = []
    for v in variants:
        if re.search(r"[" + AR + r"]", v):
            parts.append(r"(?<![" + AR + r"])[وبلف]?" + re.escape(v) + r"(?![" + AR + r"])")
        else:
            parts.append(r"\b" + re.escape(v) + r"\b")
    return P("|".join(parts))


_CITY_RES = [(city, _city_pattern(variants)) for city, variants in CITY_VARIANTS.items()]

SERVICE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("arch_design", P(r"معماري|معمارية|architect")),
    ("struct_design", P(r"إنشائي|انشائي|إنشائية|انشائية|structur")),
    ("mep_design", P(r"كهروميكانيك|كهرباء|كهربائي|ميكانيك|تكييف|سباكة|(?<![" + AR + r"])صحي|\bmep\b|electrical|mechanical|plumbing|hvac")),
    ("permit", P(r"رخصة|رخص(?![" + AR + r"])|رخصه|تصريح|permit|licen[cs]e")),
    ("supervision", P(r"إشراف|اشراف|supervis")),
    ("interior", P(r"تصميم داخلي|ديكور|interior")),
    ("landscape", P(r"لاندسكيب|تنسيق حدائق|تنسيق الموقع|حديقة|landscap")),
    ("bim", P(r"\bbim\b|نمذجة معلومات|revit|ريفيت")),
    ("boq", P(r"كميات|\bboq\b|(?<![" + AR + r"])حصر|bill of quantit|quantit")),
]
FULL_DESIGN = P(r"تصميم كامل|تصميم شامل|مخططات كاملة|كامل المخططات|جميع المخططات|كل المخططات|full design|complete design|all (?:the )?drawings")
GENERIC_DESIGN = P(r"تصميم|مخطط|design|drawings?")
DESIGN_SERVICES = {"arch_design", "struct_design", "mep_design", "interior", "landscape"}

AREA_UNIT = r"(?:م2|م²|م ?2(?!\d)|متر ?مربع|مترمربع|أمتار|امتار|متر|م(?![" + AR + r"])|sq\.? ?m|sqm|m2|m²|square ?met(?:er|re)s?)"
AREA_WITH_UNIT = P(NUM + r"\s*" + AREA_UNIT)
AREA_AFTER_KEYWORD = P(r"(?:مساحة|مساحتها|بمساحة|المساحة|أرض|ارض|land|plot|area)[^\d]{0,20}" + NUM)
AREA_KEYWORD = P(r"مساحة|مساحتها|بمساحة|المساحة|أرض|ارض|land|plot|area")
NOT_AREA_AFTER = P(r"^\s*(?:مليون|ملايين|ألف|الف|آلاف|ريال|k\b|sar|million|thousand)")

FLOOR_WORD = r"(?:أدوار|ادوار|دور|طوابق|طابق|floors?|stor(?:e)?ys?|stories|levels?)"
FLOOR_PATTERNS: list[tuple[re.Pattern, Any]] = [
    (P(r"(?<![\w.,²])(\d{1,2})\s*" + FLOOR_WORD), lambda m: int(m.group(1))),
    (P(r"(" + NUM_WORD_RE + r")\s+(?:أدوار|ادوار|طوابق|floors|stor(?:e)?ys|stories|levels)"), lambda m: NUM_WORDS[m.group(1)]),
    (P(r"(" + NUM_WORD_RE + r")[\s-]+(?:floor|stor(?:e)?y|level)"), lambda m: NUM_WORDS[m.group(1)]),
    (P(r"دورين|دوران|طابقين|طابقان"), lambda m: 2),
    (P(r"(?:دور|طابق) واحد|single[\s-]stor(?:e)?y"), lambda m: 1),
    (P(r"g\s*\+\s*(\d)"), lambda m: int(m.group(1)) + 1),
    (P(r"أرضي\s*(?:\+|و)\s*أول\s*(?:\+|و)\s*ثاني"), lambda m: 3),
    (P(r"أرضي\s*(?:\+|و)\s*أول"), lambda m: 2),
]
ANNEX = P(r"ملحق|annex|roof extension")
NO_ANNEX = P(r"(?:بدون|بلا|من غير|without|no)\s+(?:ال)?(?:ملحق|annex)")

TIMELINE_PATTERNS: list[tuple[re.Pattern, Any]] = [
    (P(NUM + r"\s*(?:أشهر|اشهر|شهور|شهر|months?)"), lambda m: to_number(m.group(1))),
    (P(r"(" + NUM_WORD_RE + r")\s+(?:أشهر|اشهر|شهور|months)"), lambda m: NUM_WORDS[m.group(1)]),
    (P(r"(\d+)\s*(?:أسابيع|اسابيع|أسبوع|اسبوع|weeks?)"), lambda m: math.ceil(int(m.group(1)) / 4.345)),
    (P(r"شهرين"), lambda m: 2),
    (P(r"سنتين"), lambda m: 24),
    (P(r"(?:خلال|مدة|مده|في غضون|بحدود)\s+(?:شهر)(?![" + AR + r"])"), lambda m: 1),
    (P(r"(?:خلال|مدة|مده|في غضون|within)\s+(?:سنة|سنه|عام|a year|one year)"), lambda m: 12),
]
MULTIPLIERS = {"مليون": 1e6, "ملايين": 1e6, "million": 1e6, "m": 1e6, "الف": 1e3, "الاف": 1e3, "thousand": 1e3, "k": 1e3}
BUDGET_KEYWORD = P(r"(?:ميزانية|الميزانية|ميزانيتي|budget|تكلفة|بتكلفة)[^\d]{0,15}" + NUM + r"\s*(مليون|ملايين|ألف|الف|آلاف|الاف|million|thousand|k|m)?(?![a-z])")
BUDGET_MILLION = P(NUM + r"\s*(مليون|ملايين|million)")
NAME_RE = P(r"(?:اسمي|معك|my name is|this is)\s+([" + AR + r"a-z]+)(?:\s+([" + AR + r"a-z]+))?")
DISTRICT_RE = P(r"(?<![" + AR + r"])[بو]?حي\s+([" + AR + r"]+)(?:\s+([" + AR + r"]+))?")
DISTRICT_EN = P(r"([a-z][a-z\-]+)\s+district|district\s+(?:of\s+)?([a-z][a-z\-]+)")
COMPOUND_PREFIX = {norm(w) for w in ["الملك", "الأمير", "الإمام", "الشيخ", "أبو", "أم", "عبد"]}
STOP_WORDS = {norm(w) for w in [
    "في", "بمساحة", "مساحة", "مساحتها", "على", "و", "أرض", "ارض", "الأرض", "أبغى", "ابغى", "ابي", "أبي", "أريد", "اريد",
    "نبي", "وابي", "بمدينة", "مدينة", "دور", "دورين", "وملحق", "ملحق", "تصميم", "مع", "من", "إلى", "الى", "عن",
]}
NAME_STOP = {norm(w) for w in ["أبغى", "ابغى", "ابي", "أبي", "أريد", "اريد", "احتاج", "أحتاج", "عندي", "مهتم", "نبي", "و"]}


class _LLMBrief(BaseModel):
    client_name: str | None = None
    project_type: str | None = None
    city: str | None = None
    district: str | None = None
    land_area_m2: float | None = None
    floors: int | None = None
    has_annex: bool = False
    services: list[str] = []
    timeline_months: float | None = None
    budget_sar: float | None = None
    notes: str | None = None

    @field_validator("project_type")
    @classmethod
    def _type_ok(cls, v):
        if v is not None and v not in labels.PROJECT_TYPE:
            raise ValueError("unknown project_type")
        return v

    @field_validator("services")
    @classmethod
    def _services_ok(cls, v):
        bad = [s for s in v if s not in labels.SERVICE]
        if bad:
            raise ValueError(f"unknown services {bad}")
        return v

    @field_validator("land_area_m2")
    @classmethod
    def _area_ok(cls, v):
        if v is not None and not (10 <= v <= 2_000_000):
            raise ValueError("implausible area")
        return v

    @field_validator("floors")
    @classmethod
    def _floors_ok(cls, v):
        if v is not None and not (1 <= v <= 80):
            raise ValueError("implausible floors")
        return v


def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


LLM_SCHEMA = {
    "type": "object",
    "properties": {
        "client_name": _nullable({"type": "string"}),
        "project_type": _nullable({"type": "string", "enum": list(labels.PROJECT_TYPE)}),
        "city": _nullable({"type": "string"}),
        "district": _nullable({"type": "string"}),
        "land_area_m2": _nullable({"type": "number"}),
        "floors": _nullable({"type": "integer"}),
        "has_annex": {"type": "boolean"},
        "services": {"type": "array", "items": {"type": "string", "enum": list(labels.SERVICE)}},
        "timeline_months": _nullable({"type": "number"}),
        "budget_sar": _nullable({"type": "number"}),
        "notes": _nullable({"type": "string"}),
    },
    "required": ["client_name", "project_type", "city", "district", "land_area_m2", "floors", "has_annex",
                 "services", "timeline_months", "budget_sar", "notes"],
    "additionalProperties": False,
}
LLM_SYSTEM = (
    "You are the client-intake agent of a Saudi engineering consultancy. Extract the project brief from the "
    "client's message (Arabic, Saudi dialect or English). Never guess: if a value is not stated, return null "
    "(or false / an empty list). land_area_m2 is the plot area in square metres; floors is an integer (a roof "
    "annex is not a floor - set has_annex instead); timeline_months is the desired duration in months; budget_sar "
    "in Saudi riyals. project_type and services must use only the allowed enum values. Write city and district "
    "in Arabic. notes: one short Arabic sentence with any other requirement the client stated, or null."
)


def empty_brief() -> dict:
    return {
        "client_name": None, "project_type": None, "project_type_label_ar": None, "city": None, "district": None,
        "land_area_m2": None, "floors": None, "has_annex": False, "services": [], "services_labels_ar": [],
        "timeline_months": None, "budget_sar": None, "notes": None, "language": "ar", "evidence": [],
    }


def finalize_brief(brief: dict) -> dict:
    brief["project_type_label_ar"] = labels.label(labels.PROJECT_TYPE, brief.get("project_type"))
    order = list(labels.SERVICE)
    brief["services"] = sorted(set(brief.get("services") or []), key=order.index)
    brief["services_labels_ar"] = [labels.SERVICE[s] for s in brief["services"]]
    return brief


def missing_fields(brief: dict) -> list[str]:
    missing = []
    for f in ("project_type", "city", "land_area_m2"):
        if not brief.get(f):
            missing.append(f)
    if brief.get("project_type") in FLOOR_TYPES and not brief.get("floors"):
        missing.append("floors")
    if not brief.get("services"):
        missing.append("services")
    return missing


def brief_headline(brief: dict) -> str:
    parts = []
    if brief.get("project_type"):
        parts.append(labels.PROJECT_TYPE[brief["project_type"]].replace(" سكنية", ""))
    if brief.get("city"):
        parts.append(brief["city"])
    if brief.get("land_area_m2"):
        parts.append(f"{brief['land_area_m2']:,.0f} م²")
    if brief.get("floors"):
        f = brief["floors"]
        word = {1: "دور واحد", 2: "دوران"}.get(f, f"{f} أدوار")
        parts.append(word + (" + ملحق" if brief.get("has_annex") else ""))
    return " · ".join(parts) if parts else "—"


class IntakeAgent(BaseAgent):
    key = "intake"
    order = 1
    name_ar = "وكيل استقبال العملاء"
    name_en = "Client Intake"
    role_ar = "يفهم طلب العميل المكتوب بالعربية أو الإنجليزية على مدار الساعة، ويستخرج بيانات المشروع، ويسأل عن الناقص."
    role_en = "Reads free-text client requests 24/7 (Arabic or English), extracts a structured brief and asks for missing details."
    triggers = ("client.request_submitted", "client.message")
    outputs_ar = "ملخص المشروع (Project Brief) + أسئلة استكمال"
    llm_capable = True
    challenge_phrase_ar = "تمكّن المكاتب من تقديم خدماتها عن بُعد وتوسّع نطاق الوصول للعملاء"
    kpi_ar = "زمن الاستجابة الأولى للعميل (ثوانٍ بدل ساعات)"

    # ------------------------------------------------------------------ extraction
    def extract(self, text: str) -> dict:
        """Deterministic extraction. Returns a brief with evidence."""
        brief = empty_brief()
        n, idx = normalize_with_map(text)
        evidence: list[dict] = []

        def src(m: re.Match, group: int = 0) -> str:
            s, e = m.span(group)
            if s < 0 or e <= s:
                return ""
            return text[idx[s]: idx[e - 1] + 1]

        def add(field: str, value_display: str, m: re.Match | None, group: int = 0):
            evidence.append({"field": field, "label_ar": FIELD_LABELS[field], "value": value_display,
                             "source_text": src(m, group) if m else ""})

        arabic = len(re.findall(r"[" + AR + r"]", text))
        latin = len(re.findall(r"[A-Za-z]", text))
        brief["language"] = "en" if latin > arabic else "ar"

        # project type
        for ptype, rx in TYPE_PATTERNS:
            m = rx.search(n)
            if m:
                brief["project_type"] = ptype
                add("project_type", labels.PROJECT_TYPE[ptype], m)
                break

        # city (earliest mention wins)
        found = []
        for city, rx in _CITY_RES:
            m = rx.search(n)
            if m:
                found.append((m.start(), city, m))
        mk = _KHOBAR.search(n)
        if mk:
            found.append((mk.start(), "الخبر", mk))
        if found:
            found.sort(key=lambda x: x[0])
            _, city, m = found[0]
            brief["city"] = city
            add("city", city, m)

        # district
        md = DISTRICT_RE.search(n)
        if md:
            w1, w2 = md.group(1), md.group(2)
            if w1 not in STOP_WORDS:
                take_two = bool(w2) and (w1 in COMPOUND_PREFIX) and (w2 not in STOP_WORDS)
                g_end = md.end(2) if take_two else md.end(1)
                s = md.start(1)
                brief["district"] = text[idx[s]: idx[g_end - 1] + 1]
                evidence.append({"field": "district", "label_ar": FIELD_LABELS["district"], "value": brief["district"],
                                 "source_text": text[idx[md.start()]: idx[g_end - 1] + 1]})
        else:
            me = DISTRICT_EN.search(n)
            if me:
                g = 1 if me.group(1) else 2
                brief["district"] = src(me, g).title()
                add("district", brief["district"], me)

        # land area
        candidates = []
        for m in AREA_WITH_UNIT.finditer(n):
            v = to_number(m.group(1))
            if 30 <= v <= 1_000_000:
                score = 2 + (2 if AREA_KEYWORD.search(n[max(0, m.start() - 25): m.start()]) else 0)
                candidates.append((score, m.start(), v, m))
        for m in AREA_AFTER_KEYWORD.finditer(n):
            if NOT_AREA_AFTER.match(n[m.end():]):
                continue
            v = to_number(m.group(1))
            if 30 <= v <= 1_000_000:
                candidates.append((3, m.start(), v, m))
        if candidates:
            candidates.sort(key=lambda c: (-c[0], c[1]))
            _, _, v, m = candidates[0]
            brief["land_area_m2"] = v
            add("land_area_m2", f"{v:,.0f} م²", m)

        # floors
        best = None
        for rx, fn in FLOOR_PATTERNS:
            for m in rx.finditer(n):
                try:
                    v = int(fn(m))
                except (KeyError, ValueError):
                    continue
                if 1 <= v <= 80 and (best is None or m.start() < best[0]):
                    best = (m.start(), v, m)
        if best:
            brief["floors"] = best[1]
            add("floors", str(best[1]), best[2])

        # annex
        if ANNEX.search(n) and not NO_ANNEX.search(n):
            m = ANNEX.search(n)
            brief["has_annex"] = True
            add("has_annex", "نعم", m)

        # services
        services = []
        for code, rx in SERVICE_PATTERNS:
            m = rx.search(n)
            if m:
                services.append(code)
                add("services", labels.SERVICE[code], m)
        mf = FULL_DESIGN.search(n)
        if mf:
            for code in ("arch_design", "struct_design", "mep_design"):
                if code not in services:
                    services.append(code)
            add("services", "تصميم كامل (معماري + إنشائي + كهروميكانيكي)", mf)
        if not DESIGN_SERVICES.intersection(services):
            mg = GENERIC_DESIGN.search(n)
            if mg:
                services.append("arch_design")
                add("services", labels.SERVICE["arch_design"], mg)
        if brief["project_type"] == "interior" and "interior" not in services:
            services.append("interior")
        brief["services"] = services

        # timeline
        best = None
        for rx, fn in TIMELINE_PATTERNS:
            m = rx.search(n)
            if m and (best is None or m.start() < best[0]):
                try:
                    best = (m.start(), float(fn(m)), m)
                except (KeyError, ValueError):
                    pass
        if best and 0 < best[1] <= 60:
            v = best[1]
            brief["timeline_months"] = int(v) if float(v).is_integer() else round(v, 1)
            add("timeline_months", f"{brief['timeline_months']:g} شهر", best[2])

        # budget
        mb = BUDGET_KEYWORD.search(n) or BUDGET_MILLION.search(n)
        if mb:
            v = to_number(mb.group(1))
            mult_word = mb.group(2) if mb.lastindex and mb.lastindex >= 2 else None
            v *= MULTIPLIERS.get(norm(mult_word), 1) if mult_word else 1
            if v >= 1000:
                brief["budget_sar"] = round(v)
                add("budget_sar", f"{v:,.0f} ريال", mb)

        # client name
        mn = NAME_RE.search(n)
        if mn and mn.group(1) not in NAME_STOP:
            end_group = 2 if (mn.group(2) and mn.group(2) not in NAME_STOP and mn.group(2) not in STOP_WORDS) else 1
            s, e = mn.start(1), mn.end(end_group)
            brief["client_name"] = text[idx[s]: idx[e - 1] + 1]
            add("client_name", brief["client_name"], mn)

        brief["evidence"] = evidence
        return finalize_brief(brief)

    def extract_llm(self, text: str, existing: dict | None) -> dict:
        user = text if not existing else (
            "Existing brief (JSON): " + dumps({k: existing.get(k) for k in LLM_SCHEMA["properties"]}) +
            "\n\nNew client message:\n" + text)
        data = self.ctx.llm.complete_json(LLM_SYSTEM, user, LLM_SCHEMA, max_tokens=4096)
        try:
            parsed = _LLMBrief(**data)
        except ValidationError as exc:
            raise LLMUnavailable("schema validation failed") from exc
        return parsed.model_dump()

    def understand(self, text: str, existing: dict | None = None) -> tuple[dict, str]:
        offline = self.extract(text)
        mode = "offline"
        merged = offline
        if self.ctx.llm.enabled:
            try:
                llm = self.extract_llm(text, existing)
                merged = dict(offline)
                for k, v in llm.items():
                    if k == "services":
                        if v:
                            merged["services"] = sorted(set(v) | set(offline["services"]))
                    elif k == "has_annex":
                        merged["has_annex"] = bool(v) or offline["has_annex"]
                    elif v not in (None, ""):
                        if k == "city":
                            v = self._canonical_city(v) or v
                        merged[k] = v
                known = {e["field"] for e in offline["evidence"]}
                for k in ("project_type", "city", "district", "land_area_m2", "floors", "timeline_months", "budget_sar", "client_name"):
                    if merged.get(k) not in (None, "") and k not in known:
                        merged["evidence"].append({"field": k, "label_ar": FIELD_LABELS[k], "value": str(merged[k]),
                                                   "source_text": "استنتاج Claude من نص الرسالة"})
                merged = finalize_brief(merged)
                mode = "llm"
            except LLMUnavailable:
                mode = "offline-fallback"
        return merged, mode

    @staticmethod
    def _canonical_city(value: str) -> str | None:
        n = norm(value)
        for city, rx in _CITY_RES:
            if rx.search(n):
                return city
        return "الخبر" if _KHOBAR.search(n) else None

    @staticmethod
    def merge(existing: dict, new: dict) -> dict:
        out = dict(existing)
        for k, v in new.items():
            if k in ("evidence", "language", "project_type_label_ar", "services_labels_ar"):
                continue
            if k == "services":
                out["services"] = list(dict.fromkeys((existing.get("services") or []) + (v or [])))
            elif k == "has_annex":
                out["has_annex"] = bool(existing.get("has_annex")) or bool(v)
            elif v not in (None, "", []):
                out[k] = v
        out["evidence"] = (existing.get("evidence") or []) + (new.get("evidence") or [])
        out["language"] = existing.get("language") or new.get("language") or "ar"
        return finalize_brief(out)

    # ------------------------------------------------------------------ replies
    @staticmethod
    def compose_reply(brief: dict, missing: list[str]) -> tuple[str, list[str]]:
        en = brief.get("language") == "en"
        questions = [(QUESTIONS_EN if en else QUESTIONS_AR)[f] for f in missing]
        lines = []
        if en:
            lines.append("Thank you, your request was received. Here is what I understood:")
            if brief.get("project_type"):
                lines.append(f"• Project type: {brief['project_type'].replace('_', ' ')}")
            if brief.get("city"):
                lines.append(f"• Location: {brief['city']}" + (f" – {brief['district']}" if brief.get("district") else ""))
            if brief.get("land_area_m2"):
                lines.append(f"• Land area: {brief['land_area_m2']:,.0f} m²")
            if brief.get("floors"):
                lines.append(f"• Floors: {brief['floors']}" + (" + roof annex" if brief.get("has_annex") else ""))
            if brief.get("services"):
                lines.append("• Services: " + ", ".join(s.replace("_", " ") for s in brief["services"]))
            if brief.get("timeline_months"):
                lines.append(f"• Desired timeline: {brief['timeline_months']:g} months")
            if missing:
                lines.append("To complete your request, please tell me:")
                lines += [f"{i}) {q}" for i, q in enumerate(questions, 1)]
            else:
                lines.append("Your brief is complete. Our proposal agent is preparing a draft quotation; you will receive it once the office manager approves it.")
            return "\n".join(lines), questions
        lines.append("شكرًا لك، استلمنا طلبك. هذا ما فهمته:")
        if brief.get("project_type"):
            lines.append(f"• نوع المشروع: {labels.PROJECT_TYPE[brief['project_type']]}")
        if brief.get("city"):
            lines.append(f"• الموقع: {brief['city']}" + (f" – حي {brief['district']}" if brief.get("district") else ""))
        if brief.get("land_area_m2"):
            lines.append(f"• مساحة الأرض: {brief['land_area_m2']:,.0f} م²")
        if brief.get("floors"):
            lines.append(f"• عدد الأدوار: {brief['floors']}" + (" + ملحق علوي" if brief.get("has_annex") else ""))
        if brief.get("services"):
            lines.append("• الخدمات: " + "، ".join(brief["services_labels_ar"]))
        if brief.get("timeline_months"):
            lines.append(f"• المدة المطلوبة: {brief['timeline_months']:g} شهر")
        if brief.get("budget_sar"):
            lines.append(f"• الميزانية التقديرية: {brief['budget_sar']:,.0f} ريال")
        if missing:
            lines.append("لإكمال الطلب أحتاج منك:")
            lines += [f"{i}) {q}" for i, q in enumerate(questions, 1)]
        else:
            lines.append("اكتملت البيانات الأساسية. يُعدّ وكيل العروض الآن مسودة عرض السعر، وتصلك بعد اعتماد مدير المكتب.")
        return "\n".join(lines), questions

    # ------------------------------------------------------------------ operations
    def _store(self, request_id: int | None, client_id: int, text: str, brief: dict, mode: str) -> dict:
        missing = missing_fields(brief)
        reply, questions = self.compose_reply(brief, missing)
        complete = not missing
        now = clock.now_iso()
        data = {
            "status": "brief_ready" if complete else "needs_info",
            "brief_json": brief,
            "missing_json": missing,
            "questions_json": questions,
            "complete": complete,
        }
        if request_id is None:
            request_id = self.db.insert("requests", {"client_id": client_id, "created_at": now, "original_text": text, **data})
        else:
            self.db.update("requests", request_id, data)
        self.db.insert("messages", {"request_id": request_id, "sender": "client", "agent": None, "text": text, "ts": now})
        self.db.insert("messages", {"request_id": request_id, "sender": "agent", "agent": self.key, "text": reply, "ts": clock.now_iso()})
        return {"request_id": request_id, "complete": complete, "brief": brief, "missing_fields": missing,
                "missing_fields_labels_ar": [FIELD_LABELS[f] for f in missing], "questions": questions, "reply": reply,
                "mode": mode}

    def op_submit(self, client_id: int, text: str, client_name: str | None = None) -> StepResult:
        text = (text or "").strip()
        if len(text) < 5:
            raise DomainError("validation_error", "نص الطلب قصير جدًا", "Request text is too short", 422)
        brief, mode = self.understand(text)
        if not brief.get("client_name") and client_name:
            brief["client_name"] = client_name
        out = self._store(None, client_id, text, brief, mode)
        return self._result(text, out, mode)

    def op_message(self, request_id: int, text: str) -> StepResult:
        req = self.db.get("requests", request_id)
        if not req:
            raise DomainError("not_found", "الطلب غير موجود", "Request not found", 404)
        if req["status"] not in ("needs_info", "brief_ready"):
            raise DomainError("invalid_state", "تمت معالجة هذا الطلب بالفعل", "This request was already processed", 409)
        existing = loads(req["brief_json"], {}) or empty_brief()
        new, mode = self.understand(text, existing)
        brief = self.merge(existing, new)
        out = self._store(request_id, req["client_id"], text, brief, mode)
        return self._result(text, out, mode)

    @staticmethod
    def _result(text: str, out: dict, mode: str) -> StepResult:
        brief = out["brief"]
        if out["complete"]:
            summary = f"{brief_headline(brief)} — اكتملت البيانات"
        else:
            summary = f"{brief_headline(brief)} — ينقص: " + "، ".join(out["missing_fields_labels_ar"])
        short = text if len(text) <= 70 else text[:70] + "…"
        return StepResult(output=out, input_summary=f"نص العميل: «{short}»", output_summary=summary, mode=mode,
                          input={"text": text})

    # ------------------------------------------------------------------ self-test
    def self_test(self) -> list[Check]:
        checks = []
        t1 = "السلام عليكم، أبغى تصميم فيلا في الرياض حي النرجس، مساحة الأرض ٦٢٥ م٢، دورين وملحق، مع رخصة البناء خلال ٤ أشهر"
        b = self.extract(t1)
        checks.append(self.check("Arabic text with Arabic-Indic digits", "نص عربي بأرقام هندية",
                                 b["project_type"] == "villa" and b["city"] == "الرياض" and b["land_area_m2"] == 625
                                 and b["floors"] == 2 and b["has_annex"] and b["district"] == "النرجس",
                                 brief_headline(b)))
        checks.append(self.check("Services and timeline detected", "استخراج الخدمات والمدة",
                                 {"arch_design", "permit"} <= set(b["services"]) and b["timeline_months"] == 4,
                                 "، ".join(b["services_labels_ar"]) + f" · {b['timeline_months']} أشهر"))
        checks.append(self.check("Complete brief has no missing fields", "لا نواقص في الطلب المكتمل", missing_fields(b) == [], str(missing_fields(b))))
        b2 = self.extract("أبي أصمم بيت لأهلي")
        miss = missing_fields(b2)
        checks.append(self.check("Missing fields produce follow-up questions", "تحديد النواقص وتوليد أسئلة",
                                 "city" in miss and "land_area_m2" in miss and len(self.compose_reply(b2, miss)[1]) == len(miss),
                                 "، ".join(FIELD_LABELS[f] for f in miss)))
        b3 = self.extract("Hi, I need full design for a 3 floor residential building in Jeddah, plot area 900 sqm, budget 2 million SAR")
        checks.append(self.check("English request", "طلب باللغة الإنجليزية",
                                 b3["language"] == "en" and b3["project_type"] == "residential_building" and b3["city"] == "جدة"
                                 and b3["land_area_m2"] == 900 and b3["floors"] == 3 and b3["budget_sar"] == 2_000_000
                                 and {"arch_design", "struct_design", "mep_design"} <= set(b3["services"]), brief_headline(b3)))
        b4 = self.extract("استراحة بالطايف ارضها ١٬٢٠٠ متر مربع بدون ملحق، أحتاج إشراف وتصميم إنشائي")
        checks.append(self.check("Attached prefixes and thousands separator", "حروف الجر الملتصقة وفاصل الآلاف",
                                 b4["city"] == "الطائف" and b4["land_area_m2"] == 1200 and not b4["has_annex"]
                                 and {"supervision", "struct_design"} <= set(b4["services"]), brief_headline(b4)))
        checks.append(self.check("Evidence links fields to the client's words", "ربط كل حقل بنص العميل",
                                 any(e["field"] == "land_area_m2" and "٦٢٥" in e["source_text"] for e in b["evidence"]),
                                 next((e["source_text"] for e in b["evidence"] if e["field"] == "land_area_m2"), "")))
        merged = self.merge(b2, self.extract("في جدة، المساحة 500 متر، دورين، تصميم معماري"))
        checks.append(self.check("Follow-up answers merge into the brief", "دمج ردود العميل في الطلب",
                                 merged["city"] == "جدة" and merged["land_area_m2"] == 500 and missing_fields(merged) == [],
                                 brief_headline(merged)))
        return checks
