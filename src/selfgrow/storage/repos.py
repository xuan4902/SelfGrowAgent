"""各表仓库：学习闭环的数据读写（基于 Database）。"""

from __future__ import annotations

from typing import Any

from selfgrow.storage.db import Database


def save_learner(db: Database, learner_id: str, goal: str = "", xp: int = 0, level: int = 1) -> None:
    db.execute(
        "INSERT OR REPLACE INTO learners (id, goal, xp, level) VALUES (?, ?, ?, ?)",
        (learner_id, goal, xp, level),
    )


def get_learner(db: Database, learner_id: str) -> dict[str, Any] | None:
    return db.fetch_one("SELECT * FROM learners WHERE id = ?", (learner_id,))


def update_learner_progress(db: Database, learner_id: str, xp: int, level: int) -> None:
    db.execute(
        "UPDATE learners SET xp = ?, level = ? WHERE id = ?", (xp, level, learner_id)
    )


def save_assessment(
    db: Database,
    learner_id: str,
    kind: str,
    radar: dict[str, Any],
    gaps: list[str],
) -> int:
    return db.insert(
        "assessments",
        {
            "learner_id": learner_id,
            "kind": kind,
            "radar_json": db.dumps(radar),
            "gaps_json": db.dumps(gaps),
        },
    )


def get_assessments(db: Database, learner_id: str) -> list[dict[str, Any]]:
    rows = db.fetch_all(
        "SELECT * FROM assessments WHERE learner_id = ? ORDER BY id ASC", (learner_id,)
    )
    for r in rows:
        r["radar"] = db.loads(r.pop("radar_json"), {})
        r["gaps"] = db.loads(r.pop("gaps_json"), [])
    return rows


def save_plan(db: Database, learner_id: str, plan: dict[str, Any]) -> int:
    return db.insert(
        "plans",
        {
            "learner_id": learner_id,
            "plan_json": db.dumps(plan),
            "current_week": plan.get("current_week", 0),
        },
    )


def get_plan(db: Database, learner_id: str) -> dict[str, Any] | None:
    row = db.fetch_one(
        "SELECT * FROM plans WHERE learner_id = ? ORDER BY id DESC LIMIT 1", (learner_id,)
    )
    if not row:
        return None
    row["plan"] = db.loads(row.pop("plan_json"), {})
    return row


def update_plan_progress(
    db: Database, learner_id: str, current_week: int, status: str = "active"
) -> None:
    db.execute(
        "UPDATE plans SET current_week = ?, status = ? WHERE learner_id = ?",
        (current_week, status, learner_id),
    )


def save_learning_record(
    db: Database,
    learner_id: str,
    week: int,
    dimension: str,
    lesson: str,
    knowledge_hits: list[dict[str, Any]],
) -> int:
    return db.insert(
        "learning_records",
        {
            "learner_id": learner_id,
            "week": week,
            "dimension": dimension,
            "lesson": lesson,
            "knowledge_hits_json": db.dumps(knowledge_hits),
        },
    )


def save_spar_session(
    db: Database,
    learner_id: str,
    week: int,
    scenario_id: str,
    transcript: list[dict[str, Any]],
    feedback: dict[str, Any],
) -> int:
    return db.insert(
        "spar_sessions",
        {
            "learner_id": learner_id,
            "week": week,
            "scenario_id": scenario_id,
            "transcript_json": db.dumps(transcript),
            "feedback_json": db.dumps(feedback),
        },
    )


def save_review(db: Database, learner_id: str, week: int, kolb: dict[str, Any]) -> int:
    return db.insert(
        "reviews", {"learner_id": learner_id, "week": week, "kolb_json": db.dumps(kolb)}
    )


def save_knowledge_doc(
    db: Database, doc_id: str, title: str, path: str, chunk_index: int
) -> None:
    db.execute(
        "INSERT OR REPLACE INTO knowledge_docs (id, title, path, chunk_index) VALUES (?, ?, ?, ?)",
        (doc_id, title, path, chunk_index),
    )
