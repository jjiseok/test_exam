import random
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from .database import fetch_all, fetch_one, get_conn

ROLE_CHIEF = "정감독"
ROLE_ASSISTANT = "부감독"
ROLE_HALLWAY = "복도감독"


def norm(value: Any) -> str:
    return str(value or "").strip()


def split_tokens(value: str) -> set[str]:
    if not value:
        return set()
    raw = str(value).replace("，", ",").replace("/", ",").replace(";", ",")
    return {x.strip() for x in raw.split(",") if x.strip()}


def truthy(value: Any) -> int:
    if isinstance(value, bool):
        return 1 if value else 0
    text = str(value or "").strip().lower()
    return 1 if text in {"1", "y", "yes", "true", "예", "네", "가능", "o", "○", "사용", "함"} else 0


@dataclass
class AllocationOptions:
    chief_per_room: int = 1
    assistant_per_room: int = 1
    hallway_count_per_slot: int = 1
    prefer_subject_hallway: bool = True
    minimize_consecutive: bool = True
    balance_counts: bool = True
    seed: int | None = None


def is_teacher_available(teacher: dict, role: str, exam_date: str, period_no: int, used_ids: set[int]) -> bool:
    tid = teacher.get("id")
    if tid in used_ids:
        return False
    if int(teacher.get("can_supervise") or 0) != 1:
        return False
    if role == ROLE_CHIEF and int(teacher.get("exclude_chief") or 0) == 1:
        return False
    if role == ROLE_ASSISTANT and int(teacher.get("exclude_assistant") or 0) == 1:
        return False
    if role == ROLE_HALLWAY and int(teacher.get("exclude_hallway") or 0) == 1:
        return False
    excluded_dates = split_tokens(norm(teacher.get("exclude_dates")))
    if exam_date in excluded_dates:
        return False
    excluded_periods = split_tokens(norm(teacher.get("exclude_periods")))
    if str(period_no) in excluded_periods or f"{period_no}교시" in excluded_periods:
        return False
    return True


def grade_room_name(grade: str, index: int) -> str:
    g = norm(grade).replace("학년", "").strip()
    return f"{g}-{index}" if g else str(index)


def load_year_counts(school_year: int, exclude_exam_id: int | None = None) -> dict[int, dict[str, int]]:
    params: list[Any] = [school_year]
    where = "e.school_year = ? AND a.teacher_id IS NOT NULL"
    if exclude_exam_id:
        where += " AND a.exam_id != ?"
        params.append(exclude_exam_id)
    rows = fetch_all(
        f"""
        SELECT a.teacher_id, a.role, COUNT(*) AS cnt
        FROM assignments a
        JOIN exams e ON e.id = a.exam_id
        WHERE {where}
        GROUP BY a.teacher_id, a.role
        """,
        params,
    )
    counts: dict[int, dict[str, int]] = defaultdict(lambda: {ROLE_CHIEF: 0, ROLE_ASSISTANT: 0, ROLE_HALLWAY: 0, "전체": 0})
    for row in rows:
        tid = int(row["teacher_id"])
        role = row["role"]
        cnt = int(row["cnt"])
        counts[tid][role] += cnt
        counts[tid]["전체"] += cnt
    return counts


def choose_teacher(
    candidates: list[dict],
    role: str,
    date_key: str,
    period_no: int,
    subject: str,
    used_ids: set[int],
    year_counts: dict[int, dict[str, int]],
    current_counts: dict[int, dict[str, int]],
    day_counts: dict[tuple[int, str], int],
    previous_period_teacher_ids: set[int],
    prefer_non_subject_for_room: bool,
    rng: random.Random,
    options: AllocationOptions,
) -> dict | None:
    available = [t for t in candidates if is_teacher_available(t, role, date_key, period_no, used_ids)]
    if not available:
        return None

    exam_subject = norm(subject)
    if role in {ROLE_CHIEF, ROLE_ASSISTANT} and prefer_non_subject_for_room:
        non_subject = [t for t in available if norm(t.get("subject")) != exam_subject]
        if non_subject:
            available = non_subject

    def score(t: dict) -> tuple:
        tid = int(t["id"])
        annual_total = year_counts[tid]["전체"] + current_counts[tid]["전체"]
        role_total = year_counts[tid][role] + current_counts[tid][role]
        same_day = day_counts[(tid, date_key)]
        consecutive_penalty = 1 if tid in previous_period_teacher_ids and options.minimize_consecutive else 0
        # 낮은 점수 우선, 마지막 값은 완전 동률일 때 무작위
        return (
            annual_total if options.balance_counts else 0,
            role_total if options.balance_counts else 0,
            same_day,
            consecutive_penalty,
            rng.random(),
        )

    available.sort(key=score)
    return available[0]


def insert_assignment(conn, slot: dict, room_name: str, role: str, teacher: dict | None) -> None:
    time_label = f"{slot['start_time']}~{slot['end_time']}"
    if teacher:
        teacher_id = int(teacher["id"])
        teacher_name = norm(teacher["name"])
        teacher_subject = norm(teacher.get("subject"))
    else:
        teacher_id = None
        teacher_name = "미배정"
        teacher_subject = ""
    conn.execute(
        """
        INSERT INTO assignments
        (exam_id, slot_id, exam_date, period_no, time_label, grade, subject, room_name, role, teacher_id, teacher_name, teacher_subject)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            slot["exam_id"],
            slot["id"],
            slot["exam_date"],
            slot["period_no"],
            time_label,
            slot["grade"],
            slot["subject"],
            room_name,
            role,
            teacher_id,
            teacher_name,
            teacher_subject,
        ),
    )


def allocate_exam(exam_id: int, options: AllocationOptions) -> dict:
    exam = fetch_one("SELECT * FROM exams WHERE id = ?", [exam_id])
    if not exam:
        raise ValueError("시험 정보가 없습니다.")
    teachers = fetch_all("SELECT * FROM teachers ORDER BY name")
    if not teachers:
        raise ValueError("교사 명단이 없습니다. 먼저 교사 명단을 업로드하거나 입력하세요.")
    slots = fetch_all(
        """
        SELECT * FROM exam_slots
        WHERE exam_id = ?
        ORDER BY exam_date, period_no, grade, subject, id
        """,
        [exam_id],
    )
    if not slots:
        raise ValueError("시험 시간표가 없습니다. 먼저 시험일자, 교시, 교과를 입력하세요.")

    rng = random.Random(options.seed)
    warnings: list[str] = []
    year_counts = load_year_counts(int(exam["school_year"]), exclude_exam_id=exam_id)
    current_counts: dict[int, dict[str, int]] = defaultdict(lambda: {ROLE_CHIEF: 0, ROLE_ASSISTANT: 0, ROLE_HALLWAY: 0, "전체": 0})
    day_counts: dict[tuple[int, str], int] = defaultdict(int)
    assigned_by_time: dict[tuple[str, int], set[int]] = defaultdict(set)
    assigned_by_date_period_room_role: list[tuple] = []

    with get_conn() as conn:
        conn.execute("DELETE FROM assignments WHERE exam_id = ?", [exam_id])

        for slot in slots:
            date_key = norm(slot["exam_date"])
            period_no = int(slot["period_no"])
            time_key = (date_key, period_no)
            used_ids = assigned_by_time[time_key]
            subject = norm(slot["subject"])
            subject_teachers = [t for t in teachers if norm(t.get("subject")) == subject]
            other_teachers = [t for t in teachers if norm(t.get("subject")) != subject]

            previous_ids = assigned_by_time.get((date_key, period_no - 1), set())

            # 1) 복도감독: 해당 교과 담당 교사 우선
            hallway_candidates = subject_teachers + other_teachers if options.prefer_subject_hallway else teachers[:]
            for i in range(max(0, int(options.hallway_count_per_slot))):
                teacher = choose_teacher(
                    hallway_candidates,
                    ROLE_HALLWAY,
                    date_key,
                    period_no,
                    subject,
                    used_ids,
                    year_counts,
                    current_counts,
                    day_counts,
                    previous_ids,
                    prefer_non_subject_for_room=False,
                    rng=rng,
                    options=options,
                )
                if not teacher:
                    warnings.append(f"{date_key} {period_no}교시 {slot['grade']} {subject}: 복도감독 배정 가능 교사가 부족합니다.")
                    insert_assignment(conn, slot, "복도", ROLE_HALLWAY, None)
                else:
                    insert_assignment(conn, slot, "복도", ROLE_HALLWAY, teacher)
                    tid = int(teacher["id"])
                    used_ids.add(tid)
                    current_counts[tid][ROLE_HALLWAY] += 1
                    current_counts[tid]["전체"] += 1
                    day_counts[(tid, date_key)] += 1

            # 2) 시험실별 정감독/부감독
            room_count = max(1, int(slot.get("room_count") or 1))
            for room_index in range(1, room_count + 1):
                room = grade_room_name(slot["grade"], room_index)
                for _ in range(max(0, int(options.chief_per_room))):
                    teacher = choose_teacher(
                        teachers,
                        ROLE_CHIEF,
                        date_key,
                        period_no,
                        subject,
                        used_ids,
                        year_counts,
                        current_counts,
                        day_counts,
                        previous_ids,
                        prefer_non_subject_for_room=options.prefer_subject_hallway,
                        rng=rng,
                        options=options,
                    )
                    if not teacher:
                        warnings.append(f"{date_key} {period_no}교시 {room}: 정감독 배정 가능 교사가 부족합니다.")
                        insert_assignment(conn, slot, room, ROLE_CHIEF, None)
                    else:
                        insert_assignment(conn, slot, room, ROLE_CHIEF, teacher)
                        tid = int(teacher["id"])
                        used_ids.add(tid)
                        current_counts[tid][ROLE_CHIEF] += 1
                        current_counts[tid]["전체"] += 1
                        day_counts[(tid, date_key)] += 1

                for _ in range(max(0, int(options.assistant_per_room))):
                    teacher = choose_teacher(
                        teachers,
                        ROLE_ASSISTANT,
                        date_key,
                        period_no,
                        subject,
                        used_ids,
                        year_counts,
                        current_counts,
                        day_counts,
                        previous_ids,
                        prefer_non_subject_for_room=options.prefer_subject_hallway,
                        rng=rng,
                        options=options,
                    )
                    if not teacher:
                        warnings.append(f"{date_key} {period_no}교시 {room}: 부감독 배정 가능 교사가 부족합니다.")
                        insert_assignment(conn, slot, room, ROLE_ASSISTANT, None)
                    else:
                        insert_assignment(conn, slot, room, ROLE_ASSISTANT, teacher)
                        tid = int(teacher["id"])
                        used_ids.add(tid)
                        current_counts[tid][ROLE_ASSISTANT] += 1
                        current_counts[tid]["전체"] += 1
                        day_counts[(tid, date_key)] += 1

        conn.commit()

    return {"message": "자동 배정이 완료되었습니다.", "warnings": warnings, "assignment_count": len(fetch_all("SELECT id FROM assignments WHERE exam_id = ?", [exam_id]))}
