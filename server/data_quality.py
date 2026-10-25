"""Explicit source coverage declarations; row presence never proves completeness."""
import re
from . import core


def initialize(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS data_coverage(student_id TEXT NOT NULL REFERENCES students(id),kind TEXT NOT NULL CHECK(kind IN ('grades','enrollment')),through_term TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN ('complete','partial')),source TEXT NOT NULL,confirmed_by TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(student_id,kind))")


def previous_term(term):
    year = int(term[:4])
    return f"{year}-{year + 1}-1" if term.endswith("2") else f"{year - 1}-{year}-2"


def set_coverage(conn, student_id, kind, through_term, status, source, confirmed_by):
    if kind not in ("grades", "enrollment") or status not in ("complete", "partial"):
        raise ValueError("覆盖类型或状态无效")
    match = re.fullmatch(r"(20\d{2})-(20\d{2})-([12])", str(through_term))
    if not match or int(match[2]) != int(match[1]) + 1:
        raise ValueError("覆盖学期格式应为2026-2027-1")
    if not str(source).strip() or not str(confirmed_by).strip():
        raise ValueError("覆盖声明须填写数据来源及确认人")
    conn.execute("INSERT INTO data_coverage VALUES (?,?,?,?,?,?,?) ON CONFLICT(student_id,kind) DO UPDATE SET through_term=excluded.through_term,status=excluded.status,source=excluded.source,confirmed_by=excluded.confirmed_by,updated_at=excluded.updated_at", (student_id, kind, through_term, status, str(source).strip(), str(confirmed_by).strip(), core.now()))


def coverage(conn, student_id, term=None):
    term = term or core.TERM
    rows = [dict(r) for r in conn.execute("SELECT * FROM data_coverage WHERE student_id=? ORDER BY kind", (student_id,))]
    by_kind = {r["kind"]: r for r in rows}
    grades = by_kind.get("grades", {})
    enrollment = by_kind.get("enrollment", {})
    student = conn.execute("SELECT cohort FROM students WHERE id=?", (student_id,)).fetchone()
    first_semester = bool(student and 2 * (int(term[:4]) - student["cohort"]) + int(term[-1]) <= 1)
    return {"historyComplete": first_semester or (grades.get("status") == "complete" and grades.get("through_term", "") >= previous_term(term)),
            "enrollmentComplete": enrollment.get("status") == "complete" and enrollment.get("through_term") == term,
            "gradesThrough": grades.get("through_term") if grades.get("status") == "complete" else None,
            "coverage": [{"kind": r["kind"], "throughTerm": r["through_term"], "status": r["status"], "source": r["source"], "confirmedBy": r["confirmed_by"], "updatedAt": r["updated_at"]} for r in rows]}


def grades_complete_through(conn, student_id, term):
    row = conn.execute("SELECT * FROM data_coverage WHERE student_id=? AND kind='grades'", (student_id,)).fetchone()
    return bool(row and row["status"] == "complete" and row["through_term"] >= term)
