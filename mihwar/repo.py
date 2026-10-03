"""Small read helpers shared by agents, views and the orchestrator."""
from __future__ import annotations

from .config import load_config
from .db import loads


def office() -> dict:
    return load_config("office")


def get_user(db, user_id) -> dict | None:
    if user_id is None:
        return None
    return db.get("users", user_id)


def default_user(db, role: str) -> dict | None:
    return db.one("SELECT * FROM users WHERE role = ? ORDER BY default_for_role DESC, id LIMIT 1", (role,))


def engineers(db) -> list[dict]:
    return db.all("SELECT * FROM users WHERE role = 'engineer' ORDER BY id")


def member_ids(db, project_id) -> set[int]:
    return {r["user_id"] for r in db.all("SELECT user_id FROM project_members WHERE project_id = ?", (project_id,))}


def is_member(db, project_id, user_id) -> bool:
    return db.scalar(
        "SELECT 1 FROM project_members WHERE project_id = ? AND user_id = ?", (project_id, user_id)
    ) is not None


def add_member(db, project_id, user_id) -> None:
    db.execute("INSERT OR IGNORE INTO project_members (project_id, user_id) VALUES (?, ?)", (project_id, user_id))


def client_name(db, client_id) -> str:
    row = db.get("clients", client_id) if client_id else None
    return row["name_ar"] if row else "—"


def project_params(project: dict) -> dict:
    return loads(project.get("params_json"), {}) or {}


def project_services(project: dict) -> list[str]:
    return loads(project.get("services_json"), []) or []


def compact_project_code(code: str) -> str:
    """'MST-2026-011' -> 'MST011' (used in document codes)."""
    parts = (code or "").split("-")
    if len(parts) >= 3:
        return f"{parts[0]}{parts[-1]}"
    return (code or "PRJ").replace("-", "")


def user_ref(user: dict | None) -> dict | None:
    from . import labels

    if not user:
        return None
    return {
        "id": user["id"],
        "name_ar": user["name_ar"],
        "name_en": user.get("name_en"),
        "role": user["role"],
        "role_label_ar": labels.ROLE.get(user["role"], user["role"]),
    }
