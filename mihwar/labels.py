"""Arabic labels for every enum. The UI shows these and never hard-codes translations."""
from __future__ import annotations

ROLE = {"manager": "مدير المكتب", "engineer": "مهندس", "client": "عميل", "system": "النظام"}

DISCIPLINE = {
    "architectural": "معماري",
    "structural": "إنشائي",
    "mechanical": "ميكانيكي",
    "electrical": "كهربائي",
    "plumbing": "صحي (سباكة)",
    "general": "عام",
}
DISCIPLINE_CODE = {
    "architectural": "A",
    "structural": "S",
    "mechanical": "M",
    "electrical": "E",
    "plumbing": "P",
    "general": "Z",
}
CODE_DISCIPLINE = {v: k for k, v in DISCIPLINE_CODE.items()}

PROJECT_TYPE = {
    "villa": "فيلا سكنية",
    "residential_building": "عمارة سكنية",
    "commercial": "مبنى تجاري",
    "mixed_use": "مبنى متعدد الاستخدامات",
    "office": "مبنى مكاتب",
    "rest_house": "استراحة",
    "warehouse": "مستودع",
    "mosque": "مسجد",
    "renovation": "ترميم وتأهيل",
    "interior": "تصميم داخلي",
}

SERVICE = {
    "arch_design": "التصميم المعماري",
    "struct_design": "التصميم الإنشائي",
    "mep_design": "التصميم الكهروميكانيكي",
    "permit": "استخراج رخصة البناء",
    "supervision": "الإشراف على التنفيذ",
    "interior": "التصميم الداخلي",
    "landscape": "تنسيق الموقع",
    "bim": "نمذجة معلومات البناء (BIM)",
    "boq": "جداول الكميات والمواصفات",
}

REQUEST_STATUS = {
    "needs_info": "بانتظار معلومات من العميل",
    "brief_ready": "اكتملت البيانات",
    "proposal_draft": "مسودة عرض بانتظار الاعتماد",
    "proposal_sent": "أُرسل العرض للعميل",
    "accepted": "قبل العميل العرض",
}

PROPOSAL_STATUS = {
    "draft": "مسودة",
    "approved": "معتمد",
    "sent": "مُرسل للعميل",
    "accepted": "مقبول",
    "rejected": "مرفوض",
}

PROJECT_STATUS = {
    "planning": "تخطيط",
    "design": "تصميم",
    "permit": "رخصة البناء",
    "supervision": "إشراف",
    "completed": "مكتمل",
    "on_hold": "متوقف",
}

PROJECT_HEALTH = {"on_track": "ضمن الخطة", "at_risk": "معرّض للتأخر", "delayed": "متأخر"}

TASK_STATUS = {"todo": "لم تبدأ", "in_progress": "قيد التنفيذ", "review": "قيد المراجعة", "done": "منجزة"}

CDE_STATE = {
    "WIP": "قيد العمل (WIP)",
    "SHARED": "مشترك (Shared)",
    "PUBLISHED": "منشور (Published)",
    "ARCHIVED": "مؤرشف (Archived)",
}

DOC_TYPE = {
    "DR": "مخطط",
    "M3": "نموذج ثلاثي الأبعاد",
    "RP": "تقرير",
    "CA": "حسابات",
    "SP": "مواصفات",
    "SH": "جداول وكميات",
    "PP": "عرض تقديمي",
    "VS": "منظور",
}

QA_STATUS = {
    "not_requested": "لم تُطلب مراجعة",
    "issues": "توجد ملاحظات",
    "passed": "اجتاز الفحص",
    "signed_off": "معتمد بتوقيع مهندس",
}

SEVERITY = {"high": "عالية", "medium": "متوسطة", "low": "منخفضة"}

ALERT_TYPE = {
    "burst_download": "تنزيل جماعي غير معتاد",
    "unassigned_access": "محاولة وصول لمشروع غير مسند",
    "client_wip_request": "طلب عميل لملف غير منشور",
    "repeated_denials": "محاولات مرفوضة متكررة",
}
ALERT_STATUS = {"open": "مفتوح", "acknowledged": "تمت المعالجة"}

RUN_STATUS = {"ok": "نجح", "denied": "مرفوض أمنيًا", "error": "خطأ", "partial": "جزئي", "running": "قيد التنفيذ"}
STEP_STATUS = {"ok": "نجح", "denied": "مرفوض", "error": "خطأ", "skipped": "تخطٍّ"}

MODE = {
    "offline": "دون اتصال (منطق محدد)",
    "llm": "Claude",
    "offline-fallback": "رجوع تلقائي للوضع دون اتصال",
}

AGENT_HEALTH = {"healthy": "سليم", "degraded": "يعمل مع ملاحظات", "failing": "متعطل", "untested": "لم يُختبر بعد"}

TEAM_STATUS = {"ok": "طبيعي", "high": "حمل مرتفع", "overload": "تجاوز الطاقة"}

INTENT = {
    "status": "حالة المشروع ونسبة الإنجاز",
    "schedule": "المواعيد والمعالم",
    "files": "الملفات والمخططات",
    "payment": "الدفعات والفواتير",
    "team": "فريق العمل",
    "other": "استفسار عام",
}

EVENTS = {
    "client.request_submitted": "طلب خدمة جديد من عميل",
    "client.message": "رد العميل على أسئلة الطلب",
    "brief.ready": "اكتمال بيانات الطلب",
    "proposal.approved": "اعتماد عرض السعر",
    "proposal.accepted": "قبول العميل للعرض",
    "plan.created": "إنشاء خطة المشروع",
    "task.changed": "تحديث مهمة",
    "team.rebalance": "إعادة توزيع مهمة",
    "project.params_changed": "تعديل بيانات المشروع",
    "file.uploaded": "رفع ملف هندسي",
    "file.status_changed": "تغيير حالة ملف",
    "file.download": "تنزيل ملف",
    "qa.requested": "طلب مراجعة جودة",
    "qa.signed_off": "توقيع مراجعة الجودة",
    "report.weekly": "تقرير تقدم أسبوعي",
    "client.question": "سؤال من العميل",
    "security.alert_ack": "معالجة تنبيه أمني",
    "security.simulate": "محاكاة محاولة وصول",
}

ACTIONS = {
    "portal.request.create": "إرسال طلب خدمة",
    "portal.request.view": "عرض طلبات الخدمة",
    "portal.request.message": "الرد على أسئلة الطلب",
    "proposal.view": "عرض عروض الأسعار",
    "proposal.approve": "اعتماد عرض السعر",
    "proposal.accept": "قبول عرض السعر",
    "project.view": "عرض المشروع",
    "project.edit": "تعديل بيانات المشروع",
    "task.update": "تحديث المهام",
    "team.view": "عرض أحمال الفريق",
    "team.rebalance": "إعادة توزيع المهام",
    "file.view": "عرض الملفات",
    "file.upload": "رفع الملفات",
    "file.state": "تغيير حالة الملفات",
    "file.download": "تنزيل الملفات",
    "qa.run": "طلب مراجعة الجودة",
    "qa.signoff": "توقيع مراجعة الجودة",
    "report.create": "إصدار التقارير",
    "client.question": "سؤال عن المشروع",
    "dashboard.view": "لوحة المكتب",
    "agents.view": "الوكلاء والاختبارات",
    "scenario.run": "تشغيل السيناريو الكامل",
    "security.view": "سجل التدقيق والتنبيهات",
    "security.manage": "معالجة التنبيهات والمحاكاة",
    "compliance.view": "قواعد الاشتراطات والتقارير",
    "demo.reset": "إعادة ضبط بيانات العرض",
}

NOTICES = {
    "demo_ar": "بيانات افتراضية لأغراض العرض: المكتب والعملاء والمشاريع غير حقيقية.",
    "placeholder_ar": "قيم توضيحية للعرض — تُستبدل بالقيم الرسمية/الفعلية.",
    "auth_ar": "تبديل الأدوار هوية تجريبية للعرض فقط؛ تسجيل الدخول الحقيقي ضمن خطة التطوير.",
    "estimate_ar": "تقديرات مبنية على افتراضات قابلة للتعديل، وليست نتائج مقاسة.",
}


def label(table: dict, key) -> str | None:
    if key is None:
        return None
    return table.get(key, str(key))
