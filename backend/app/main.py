from __future__ import annotations

from io import BytesIO
from typing import Any

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .allocator import AllocationOptions, allocate_exam
from .database import execute, executemany, fetch_all, fetch_one, get_conn, init_db

app = FastAPI(title="중학교 시험감독 배정표 자동 생성 시스템", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


def yes_no(value: Any, default: int = 0) -> int:
    if pd.isna(value):
        return default
    text = str(value).strip().lower()
    if text == "":
        return default
    return 1 if text in {"1", "true", "y", "yes", "예", "네", "가능", "o", "○", "사용", "함", "담임"} else 0


def cell_text(value: Any) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, pd.Timestamp):
        if value.hour == 0 and value.minute == 0 and value.second == 0:
            return value.strftime("%Y-%m-%d")
        return value.strftime("%H:%M")
    return str(value).strip()


class TeacherIn(BaseModel):
    name: str
    subject: str = ""
    is_homeroom: int = 0
    grade: str = ""
    class_no: str = ""
    department: str = ""
    can_supervise: int = 1
    exclude_chief: int = 0
    exclude_assistant: int = 0
    exclude_hallway: int = 0
    exclude_dates: str = ""
    exclude_periods: str = ""
    note: str = ""


class ExamIn(BaseModel):
    school_year: int
    semester: int = Field(ge=1, le=2)
    exam_round: int = Field(ge=1, le=2)
    title: str


class SlotIn(BaseModel):
    exam_date: str
    period_no: int
    start_time: str
    end_time: str
    grade: str
    subject: str
    room_count: int = 1


class AllocateIn(BaseModel):
    chief_per_room: int = 1
    assistant_per_room: int = 1
    hallway_count_per_slot: int = 1
    prefer_subject_hallway: bool = True
    minimize_consecutive: bool = True
    balance_counts: bool = True
    seed: int | None = None


class AssignmentUpdateIn(BaseModel):
    teacher_id: int | None = None


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/teachers")
def list_teachers() -> list[dict]:
    return fetch_all("SELECT * FROM teachers ORDER BY name")


@app.post("/api/teachers")
def create_teacher(item: TeacherIn) -> dict:
    if not item.name.strip():
        raise HTTPException(400, "교사명은 필수입니다.")
    new_id = execute(
        """
        INSERT INTO teachers
        (name, subject, is_homeroom, grade, class_no, department, can_supervise,
         exclude_chief, exclude_assistant, exclude_hallway, exclude_dates, exclude_periods, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item.name.strip(), item.subject.strip(), item.is_homeroom, item.grade, item.class_no,
            item.department, item.can_supervise, item.exclude_chief, item.exclude_assistant,
            item.exclude_hallway, item.exclude_dates, item.exclude_periods, item.note,
        ),
    )
    return fetch_one("SELECT * FROM teachers WHERE id = ?", [new_id])


@app.put("/api/teachers/{teacher_id}")
def update_teacher(teacher_id: int, item: TeacherIn) -> dict:
    teacher = fetch_one("SELECT * FROM teachers WHERE id = ?", [teacher_id])
    if not teacher:
        raise HTTPException(404, "교사를 찾을 수 없습니다.")
    execute(
        """
        UPDATE teachers
        SET name=?, subject=?, is_homeroom=?, grade=?, class_no=?, department=?, can_supervise=?,
            exclude_chief=?, exclude_assistant=?, exclude_hallway=?, exclude_dates=?, exclude_periods=?, note=?
        WHERE id=?
        """,
        (
            item.name.strip(), item.subject.strip(), item.is_homeroom, item.grade, item.class_no,
            item.department, item.can_supervise, item.exclude_chief, item.exclude_assistant,
            item.exclude_hallway, item.exclude_dates, item.exclude_periods, item.note, teacher_id,
        ),
    )
    return fetch_one("SELECT * FROM teachers WHERE id = ?", [teacher_id])


@app.delete("/api/teachers/{teacher_id}")
def delete_teacher(teacher_id: int) -> dict:
    execute("DELETE FROM teachers WHERE id = ?", [teacher_id])
    return {"message": "삭제되었습니다."}


@app.post("/api/teachers/upload")
async def upload_teachers(file: UploadFile = File(...)) -> dict:
    if not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(400, "엑셀 파일(.xlsx, .xls)만 업로드할 수 있습니다.")
    content = await file.read()
    try:
        df = pd.read_excel(BytesIO(content))
    except Exception as exc:
        raise HTTPException(400, f"엑셀 파일을 읽을 수 없습니다: {exc}")

    required = "교사명"
    if required not in df.columns:
        raise HTTPException(400, "엑셀 파일에 '교사명' 열이 필요합니다.")

    rows = []
    for _, r in df.iterrows():
        name = cell_text(r.get("교사명"))
        if not name:
            continue
        rows.append(
            (
                name,
                cell_text(r.get("교과")),
                yes_no(r.get("담임 여부")),
                cell_text(r.get("담당 학년")),
                cell_text(r.get("담당 반")),
                cell_text(r.get("부서")),
                yes_no(r.get("감독 가능 여부"), 1),
                yes_no(r.get("정감독 제외 여부")),
                yes_no(r.get("부감독 제외 여부")),
                yes_no(r.get("복도감독 제외 여부")),
                cell_text(r.get("특정 날짜 제외")),
                cell_text(r.get("특정 교시 제외")),
                cell_text(r.get("비고")),
            )
        )

    if not rows:
        raise HTTPException(400, "업로드할 교사 정보가 없습니다.")

    with get_conn() as conn:
        conn.execute("DELETE FROM teachers")
        conn.executemany(
            """
            INSERT INTO teachers
            (name, subject, is_homeroom, grade, class_no, department, can_supervise,
             exclude_chief, exclude_assistant, exclude_hallway, exclude_dates, exclude_periods, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
    return {"message": "교사 명단을 업로드했습니다.", "count": len(rows)}


@app.get("/api/templates/teachers")
def teacher_template() -> StreamingResponse:
    df = pd.DataFrame([
        {"교사명": "김가람", "교과": "국어", "담임 여부": "예", "담당 학년": "1", "담당 반": "1", "부서": "교무기획부", "감독 가능 여부": "예", "정감독 제외 여부": "", "부감독 제외 여부": "", "복도감독 제외 여부": "", "특정 날짜 제외": "", "특정 교시 제외": "", "비고": ""},
        {"교사명": "박나래", "교과": "수학", "담임 여부": "아니오", "담당 학년": "", "담당 반": "", "부서": "교육연구부", "감독 가능 여부": "예", "정감독 제외 여부": "", "부감독 제외 여부": "", "복도감독 제외 여부": "", "특정 날짜 제외": "2026-04-30", "특정 교시 제외": "", "비고": "예시"},
    ])
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="교사명단")
    bio.seek(0)
    return StreamingResponse(
        bio,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=teacher_template.xlsx"},
    )


@app.get("/api/templates/schedule")
def schedule_template() -> StreamingResponse:
    df = pd.DataFrame([
        {"시험일자": "2026-04-30", "교시": 1, "시작시간": "09:00", "종료시간": "09:45", "학년": "1학년", "교과": "국어", "시험실수": 4},
        {"시험일자": "2026-04-30", "교시": 2, "시작시간": "10:00", "종료시간": "10:45", "학년": "2학년", "교과": "수학", "시험실수": 4},
    ])
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="시험시간표")
    bio.seek(0)
    return StreamingResponse(
        bio,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=schedule_template.xlsx"},
    )


@app.get("/api/exams")
def list_exams() -> list[dict]:
    return fetch_all("SELECT * FROM exams ORDER BY school_year DESC, semester, exam_round, id DESC")


@app.post("/api/exams")
def create_exam(item: ExamIn) -> dict:
    title = item.title.strip() or f"{item.school_year}학년도 {item.semester}학기 {item.exam_round}차 지필평가"
    new_id = execute(
        "INSERT INTO exams (school_year, semester, exam_round, title) VALUES (?, ?, ?, ?)",
        [item.school_year, item.semester, item.exam_round, title],
    )
    return fetch_one("SELECT * FROM exams WHERE id = ?", [new_id])


@app.delete("/api/exams/{exam_id}")
def delete_exam(exam_id: int) -> dict:
    execute("DELETE FROM exams WHERE id = ?", [exam_id])
    return {"message": "시험 정보가 삭제되었습니다."}


@app.get("/api/exams/{exam_id}/slots")
def list_slots(exam_id: int) -> list[dict]:
    return fetch_all(
        "SELECT * FROM exam_slots WHERE exam_id = ? ORDER BY exam_date, period_no, grade, id",
        [exam_id],
    )


@app.post("/api/exams/{exam_id}/slots")
def create_slot(exam_id: int, item: SlotIn) -> dict:
    if not fetch_one("SELECT * FROM exams WHERE id = ?", [exam_id]):
        raise HTTPException(404, "시험 정보를 찾을 수 없습니다.")
    if not item.subject.strip():
        raise HTTPException(400, "시험 교과는 필수입니다.")
    new_id = execute(
        """
        INSERT INTO exam_slots
        (exam_id, exam_date, period_no, start_time, end_time, grade, subject, room_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [exam_id, item.exam_date, item.period_no, item.start_time, item.end_time, item.grade, item.subject, item.room_count],
    )
    return fetch_one("SELECT * FROM exam_slots WHERE id = ?", [new_id])


@app.post("/api/exams/{exam_id}/slots/upload")
async def upload_slots(exam_id: int, file: UploadFile = File(...)) -> dict:
    if not fetch_one("SELECT * FROM exams WHERE id = ?", [exam_id]):
        raise HTTPException(404, "시험 정보를 찾을 수 없습니다.")
    content = await file.read()
    try:
        df = pd.read_excel(BytesIO(content))
    except Exception as exc:
        raise HTTPException(400, f"엑셀 파일을 읽을 수 없습니다: {exc}")
    required = ["시험일자", "교시", "시작시간", "종료시간", "학년", "교과", "시험실수"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise HTTPException(400, f"필수 열이 없습니다: {', '.join(missing)}")
    rows = []
    for _, r in df.iterrows():
        if not cell_text(r.get("시험일자")) or not cell_text(r.get("교과")):
            continue
        rows.append((exam_id, cell_text(r["시험일자"])[:10], int(r["교시"]), cell_text(r["시작시간"]), cell_text(r["종료시간"]), cell_text(r["학년"]), cell_text(r["교과"]), int(r["시험실수"])))
    if not rows:
        raise HTTPException(400, "업로드할 시험 시간표가 없습니다.")
    executemany(
        """
        INSERT INTO exam_slots
        (exam_id, exam_date, period_no, start_time, end_time, grade, subject, room_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return {"message": "시험 시간표를 업로드했습니다.", "count": len(rows)}


@app.delete("/api/slots/{slot_id}")
def delete_slot(slot_id: int) -> dict:
    execute("DELETE FROM exam_slots WHERE id = ?", [slot_id])
    return {"message": "삭제되었습니다."}


@app.post("/api/exams/{exam_id}/allocate")
def allocate(exam_id: int, item: AllocateIn) -> dict:
    try:
        return allocate_exam(exam_id, AllocationOptions(**item.model_dump()))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/exams/{exam_id}/assignments")
def list_assignments(exam_id: int) -> list[dict]:
    return fetch_all(
        """
        SELECT * FROM assignments
        WHERE exam_id = ?
        ORDER BY exam_date, period_no, grade, room_name, CASE role WHEN '복도감독' THEN 0 WHEN '정감독' THEN 1 ELSE 2 END, id
        """,
        [exam_id],
    )


@app.put("/api/assignments/{assignment_id}")
def update_assignment(assignment_id: int, item: AssignmentUpdateIn) -> dict:
    assignment = fetch_one("SELECT * FROM assignments WHERE id = ?", [assignment_id])
    if not assignment:
        raise HTTPException(404, "배정 정보를 찾을 수 없습니다.")
    if item.teacher_id is None:
        execute("UPDATE assignments SET teacher_id=NULL, teacher_name='미배정', teacher_subject='' WHERE id=?", [assignment_id])
        return fetch_one("SELECT * FROM assignments WHERE id = ?", [assignment_id])
    teacher = fetch_one("SELECT * FROM teachers WHERE id = ?", [item.teacher_id])
    if not teacher:
        raise HTTPException(404, "교사를 찾을 수 없습니다.")
    duplicate = fetch_one(
        """
        SELECT id FROM assignments
        WHERE id != ? AND exam_id = ? AND exam_date = ? AND period_no = ? AND teacher_id = ?
        """,
        [assignment_id, assignment["exam_id"], assignment["exam_date"], assignment["period_no"], item.teacher_id],
    )
    if duplicate:
        raise HTTPException(400, "같은 날짜·교시에 이미 배정된 교사입니다.")
    execute(
        "UPDATE assignments SET teacher_id=?, teacher_name=?, teacher_subject=? WHERE id=?",
        [teacher["id"], teacher["name"], teacher["subject"], assignment_id],
    )
    return fetch_one("SELECT * FROM assignments WHERE id = ?", [assignment_id])


@app.get("/api/stats")
def stats(school_year: int | None = None) -> list[dict]:
    if school_year is None:
        latest = fetch_one("SELECT MAX(school_year) AS y FROM exams")
        school_year = latest["y"] if latest and latest["y"] else None
    teachers = fetch_all("SELECT id, name, subject FROM teachers ORDER BY name")
    if school_year is None:
        return [{"교사명": t["name"], "교과": t["subject"], "연간 정감독": 0, "연간 부감독": 0, "연간 복도감독": 0, "연간 총계": 0} for t in teachers]

    rows = fetch_all(
        """
        SELECT a.teacher_id, e.semester, e.exam_round, a.role, COUNT(*) AS cnt
        FROM assignments a
        JOIN exams e ON e.id = a.exam_id
        WHERE e.school_year = ? AND a.teacher_id IS NOT NULL
        GROUP BY a.teacher_id, e.semester, e.exam_round, a.role
        """,
        [school_year],
    )
    stat_map: dict[int, dict[str, int]] = {}
    labels = []
    for sem in [1, 2]:
        for rnd in [1, 2]:
            for role in ["정감독", "부감독", "복도감독"]:
                labels.append(f"{sem}학기 {rnd}차 {role}")
    for t in teachers:
        stat_map[t["id"]] = {label: 0 for label in labels}
        stat_map[t["id"]].update({"연간 정감독": 0, "연간 부감독": 0, "연간 복도감독": 0, "연간 총계": 0})
    for r in rows:
        tid = r["teacher_id"]
        key = f"{r['semester']}학기 {r['exam_round']}차 {r['role']}"
        cnt = int(r["cnt"])
        if tid in stat_map:
            stat_map[tid][key] = cnt
            stat_map[tid][f"연간 {r['role']}"] += cnt
            stat_map[tid]["연간 총계"] += cnt
    result = []
    for t in teachers:
        result.append({"교사명": t["name"], "교과": t["subject"], **stat_map[t["id"]]})
    return result


@app.get("/api/exams/{exam_id}/export")
def export_exam(exam_id: int) -> StreamingResponse:
    exam = fetch_one("SELECT * FROM exams WHERE id = ?", [exam_id])
    if not exam:
        raise HTTPException(404, "시험 정보를 찾을 수 없습니다.")
    assignments = fetch_all(
        """
        SELECT exam_date AS 날짜, period_no AS 교시, time_label AS 시간, grade AS 학년, subject AS 교과,
               room_name AS 시험실, role AS 감독유형, teacher_name AS 교사명, teacher_subject AS 교사교과
        FROM assignments
        WHERE exam_id = ?
        ORDER BY exam_date, period_no, grade, room_name, 감독유형
        """,
        [exam_id],
    )
    stat_rows = stats(exam["school_year"])
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        pd.DataFrame(assignments).to_excel(writer, index=False, sheet_name="감독배정표")
        pd.DataFrame(stat_rows).to_excel(writer, index=False, sheet_name="교사별통계")
    bio.seek(0)
    filename = f"exam_supervision_{exam['school_year']}_{exam['semester']}_{exam['exam_round']}.xlsx"
    return StreamingResponse(
        bio,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.post("/api/sample")
def create_sample() -> dict:
    teachers = [
        ("김가람", "국어", 1, "1", "1", "교무기획부", 1, 0, 0, 0, "", "", ""),
        ("박나래", "수학", 0, "", "", "교육연구부", 1, 0, 0, 0, "", "", ""),
        ("이도윤", "영어", 1, "2", "1", "학생생활안전부", 1, 0, 0, 0, "", "", ""),
        ("최서연", "과학", 0, "", "", "정보과학부", 1, 0, 0, 0, "", "", ""),
        ("정민수", "사회", 1, "3", "1", "진로상담부", 1, 0, 0, 0, "", "", ""),
        ("한지우", "정보", 0, "", "", "정보과학부", 1, 0, 0, 0, "", "", ""),
        ("오하늘", "도덕", 0, "", "", "인문사회부", 1, 0, 0, 0, "", "", ""),
        ("문채원", "기술가정", 0, "", "", "예체능부", 1, 0, 0, 0, "", "", ""),
        ("강유찬", "체육", 0, "", "", "예체능부", 1, 0, 1, 0, "", "", "부감독 제외 예시"),
        ("서은호", "음악", 0, "", "", "예체능부", 1, 0, 0, 0, "", "", ""),
        ("윤다인", "미술", 0, "", "", "예체능부", 1, 0, 0, 0, "", "", ""),
        ("임준서", "중국어", 0, "", "", "외국어부", 1, 0, 0, 0, "", "", ""),
        ("배수아", "진로", 0, "", "", "진로상담부", 1, 0, 0, 0, "", "", ""),
        ("조현우", "보건", 0, "", "", "보건실", 1, 1, 0, 0, "", "", "정감독 제외 예시"),
        ("유세린", "상담", 0, "", "", "상담실", 1, 0, 0, 0, "", "", ""),
    ]
    with get_conn() as conn:
        conn.execute("DELETE FROM assignments")
        conn.execute("DELETE FROM exam_slots")
        conn.execute("DELETE FROM exams")
        conn.execute("DELETE FROM teachers")
        conn.executemany(
            """
            INSERT INTO teachers
            (name, subject, is_homeroom, grade, class_no, department, can_supervise, exclude_chief,
             exclude_assistant, exclude_hallway, exclude_dates, exclude_periods, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            teachers,
        )
        cur = conn.execute("INSERT INTO exams (school_year, semester, exam_round, title) VALUES (2026, 1, 1, '2026학년도 1학기 1차 지필평가')")
        exam_id = cur.lastrowid
        slots = [
            (exam_id, "2026-04-30", 1, "09:00", "09:45", "1학년", "국어", 3),
            (exam_id, "2026-04-30", 1, "09:00", "09:45", "2학년", "수학", 3),
            (exam_id, "2026-04-30", 2, "10:00", "10:45", "1학년", "영어", 3),
            (exam_id, "2026-04-30", 2, "10:00", "10:45", "2학년", "과학", 3),
            (exam_id, "2026-05-01", 1, "09:00", "09:45", "3학년", "사회", 3),
            (exam_id, "2026-05-01", 2, "10:00", "10:45", "3학년", "정보", 3),
        ]
        conn.executemany(
            """
            INSERT INTO exam_slots
            (exam_id, exam_date, period_no, start_time, end_time, grade, subject, room_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            slots,
        )
        conn.commit()
    return {"message": "예시 데이터를 생성했습니다.", "exam_id": exam_id}
