"""Authenticated student planning and counselor review endpoints."""
from contextlib import contextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import core, planning

router = APIRouter()
User = Annotated[dict, Depends(core.current_user)]


@contextmanager
def operation(user, student_id, write=False, reviewer=False):
    with core.connection() as conn:
        core.visible_student(conn, user, student_id)
        if write and not reviewer and user["role"] not in ("student", "admin"):
            raise HTTPException(403, "修读偏好与方案由学生本人填写，辅导员可查看和审核")
        if reviewer and user["role"] not in ("counselor", "admin"):
            raise HTTPException(403, "方案由负责辅导员或管理员审核")
        if write:
            conn.execute("BEGIN IMMEDIATE")
        try:
            if write:
                core.visible_student(conn, user, student_id)
            yield conn
            if write:
                conn.execute("COMMIT")
        except ValueError as exc:
            if write:
                conn.execute("ROLLBACK")
            raise HTTPException(422, str(exc)) from exc
        except Exception:
            if write:
                conn.execute("ROLLBACK")
            raise


class Preferences(BaseModel):
    language: str
    path: str
    advancedModules: list[str] = Field(max_length=2)
    allocations: dict[str, str] = Field(default_factory=dict)


@router.get("/api/students/{student_id}/curriculum-audit")
def audit(student_id: str, user: User):
    with operation(user, student_id) as conn:
        return planning.audit_curriculum(conn, student_id)


@router.put("/api/students/{student_id}/curriculum-preferences")
def preferences(student_id: str, body: Preferences, user: User):
    with operation(user, student_id, write=True) as conn:
        result = planning.save_preferences(conn, student_id, body.language, body.path, body.advancedModules, body.allocations)
        core.audit(conn, user["id"], "curriculum.preferences", body.model_dump())
        # Preference changes alter only this student's interpretation, not grades.
        from .academic import recompute
        recompute(conn)
        return result


@router.get("/api/students/{student_id}/planning")
def get_plan(student_id: str, user: User, term: str | None = None):
    with operation(user, student_id) as conn:
        return planning.get_planning(conn, student_id, term)


class Check(BaseModel):
    term: str
    courseIds: list[str] = Field(max_length=60)


class Save(Check):
    title: str = Field(default="", max_length=120)
    note: str = Field(default="", max_length=2000)


class Submit(BaseModel):
    term: str


class Review(Submit):
    status: str
    comment: str = Field(min_length=2, max_length=2000)


@router.post("/api/students/{student_id}/planning/check")
def check(student_id: str, body: Check, user: User):
    with operation(user, student_id) as conn:
        return planning.check_plan(conn, student_id, body.term, body.courseIds)


@router.put("/api/students/{student_id}/planning")
def save(student_id: str, body: Save, user: User):
    with operation(user, student_id, write=True) as conn:
        return planning.save_plan(conn, student_id, body.term, body.courseIds, body.title.strip(), body.note.strip(), user["id"])


@router.post("/api/students/{student_id}/planning/submit")
def submit(student_id: str, body: Submit, user: User):
    with operation(user, student_id, write=True) as conn:
        return planning.submit_plan(conn, student_id, body.term, user["id"])


@router.post("/api/students/{student_id}/planning/review")
def review(student_id: str, body: Review, user: User):
    with operation(user, student_id, write=True, reviewer=True) as conn:
        return planning.review_plan(conn, student_id, body.term, body.status, body.comment, user["id"])


@router.get("/api/counselor/plans")
def plans(user: User):
    if user["role"] not in ("counselor", "admin"):
        raise HTTPException(403, "仅辅导员可查看待审核方案")
    with core.connection() as conn:
        clause = "WHERE s.counselor_id=?" if user["role"] == "counselor" else ""
        rows = conn.execute(f"SELECT p.*,s.name AS student_name FROM course_plans p JOIN students s ON s.id=p.student_id {clause} ORDER BY CASE p.status WHEN 'submitted' THEN 0 ELSE 1 END,p.updated_at DESC", [user["id"]] if clause else []).fetchall()
        return {"items": [{**planning.plan_object(conn, r), "studentName": r["student_name"]} for r in rows]}
