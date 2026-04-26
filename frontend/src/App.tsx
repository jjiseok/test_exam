import { useEffect, useMemo, useState } from 'react';

const API = import.meta.env.VITE_API_BASE || 'http://localhost:8000';

type Teacher = {
  id: number;
  name: string;
  subject: string;
  is_homeroom: number;
  grade: string;
  class_no: string;
  department: string;
  can_supervise: number;
  exclude_chief: number;
  exclude_assistant: number;
  exclude_hallway: number;
  exclude_dates: string;
  exclude_periods: string;
  note: string;
};

type Exam = {
  id: number;
  school_year: number;
  semester: number;
  exam_round: number;
  title: string;
};

type Slot = {
  id: number;
  exam_id: number;
  exam_date: string;
  period_no: number;
  start_time: string;
  end_time: string;
  grade: string;
  subject: string;
  room_count: number;
};

type Assignment = {
  id: number;
  exam_id: number;
  slot_id: number;
  exam_date: string;
  period_no: number;
  time_label: string;
  grade: string;
  subject: string;
  room_name: string;
  role: string;
  teacher_id: number | null;
  teacher_name: string;
  teacher_subject: string;
};

const emptyTeacher = {
  name: '', subject: '', is_homeroom: 0, grade: '', class_no: '', department: '', can_supervise: 1,
  exclude_chief: 0, exclude_assistant: 0, exclude_hallway: 0, exclude_dates: '', exclude_periods: '', note: ''
};

function download(url: string) {
  window.open(`${API}${url}`, '_blank');
}

async function jsonFetch(url: string, options: RequestInit = {}) {
  const res = await fetch(`${API}${url}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || '요청을 처리하지 못했습니다.');
  }
  return res.json();
}

function App() {
  const [tab, setTab] = useState<'teachers' | 'exam' | 'assign' | 'stats' | 'print'>('teachers');
  const [teachers, setTeachers] = useState<Teacher[]>([]);
  const [exams, setExams] = useState<Exam[]>([]);
  const [selectedExamId, setSelectedExamId] = useState<number | ''>('');
  const [slots, setSlots] = useState<Slot[]>([]);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [stats, setStats] = useState<any[]>([]);
  const [message, setMessage] = useState('');
  const [warnings, setWarnings] = useState<string[]>([]);
  const [teacherForm, setTeacherForm] = useState<any>(emptyTeacher);
  const [examForm, setExamForm] = useState({ school_year: new Date().getFullYear(), semester: 1, exam_round: 1, title: '' });
  const [slotForm, setSlotForm] = useState({ exam_date: '', period_no: 1, start_time: '09:00', end_time: '09:45', grade: '1학년', subject: '', room_count: 1 });
  const [allocForm, setAllocForm] = useState({ chief_per_room: 1, assistant_per_room: 1, hallway_count_per_slot: 1, prefer_subject_hallway: true, minimize_consecutive: true, balance_counts: true, seed: '' });

  const selectedExam = useMemo(() => exams.find(e => e.id === selectedExamId), [exams, selectedExamId]);

  async function loadAll() {
    const [t, e] = await Promise.all([jsonFetch('/api/teachers'), jsonFetch('/api/exams')]);
    setTeachers(t);
    setExams(e);
    if (!selectedExamId && e.length > 0) setSelectedExamId(e[0].id);
  }

  async function loadExamData(id: number | '') {
    if (!id) return;
    const [s, a] = await Promise.all([
      jsonFetch(`/api/exams/${id}/slots`),
      jsonFetch(`/api/exams/${id}/assignments`)
    ]);
    setSlots(s);
    setAssignments(a);
  }

  async function loadStats() {
    const year = selectedExam?.school_year || new Date().getFullYear();
    const data = await jsonFetch(`/api/stats?school_year=${year}`);
    setStats(data);
  }

  useEffect(() => { loadAll().catch(err => setMessage(err.message)); }, []);
  useEffect(() => { loadExamData(selectedExamId).catch(err => setMessage(err.message)); }, [selectedExamId]);
  useEffect(() => { loadStats().catch(() => undefined); }, [selectedExamId, assignments.length, teachers.length]);

  async function uploadTeacherExcel(file?: File) {
    if (!file) return;
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(`${API}/api/teachers/upload`, { method: 'POST', body: formData });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    setMessage(`${data.count}명의 교사 명단을 업로드했습니다.`);
    await loadAll();
  }

  async function uploadScheduleExcel(file?: File) {
    if (!file || !selectedExamId) return;
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(`${API}/api/exams/${selectedExamId}/slots/upload`, { method: 'POST', body: formData });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    setMessage(`${data.count}개의 시험 시간표를 업로드했습니다.`);
    await loadExamData(selectedExamId);
  }

  async function createTeacher() {
    await jsonFetch('/api/teachers', { method: 'POST', body: JSON.stringify(teacherForm) });
    setTeacherForm(emptyTeacher);
    setMessage('교사를 추가했습니다.');
    await loadAll();
  }

  async function deleteTeacher(id: number) {
    if (!confirm('선택한 교사를 삭제할까요?')) return;
    await jsonFetch(`/api/teachers/${id}`, { method: 'DELETE' });
    await loadAll();
  }

  async function updateTeacherField(t: Teacher, key: string, value: any) {
    const next = { ...t, [key]: value };
    await jsonFetch(`/api/teachers/${t.id}`, { method: 'PUT', body: JSON.stringify(next) });
    await loadAll();
  }

  async function createExam() {
    const title = examForm.title || `${examForm.school_year}학년도 ${examForm.semester}학기 ${examForm.exam_round}차 지필평가`;
    const exam = await jsonFetch('/api/exams', { method: 'POST', body: JSON.stringify({ ...examForm, title }) });
    setSelectedExamId(exam.id);
    setMessage('시험 정보를 생성했습니다.');
    await loadAll();
  }

  async function createSample() {
    const data = await jsonFetch('/api/sample', { method: 'POST' });
    setMessage('예시 데이터를 생성했습니다. 자동 배정을 눌러 결과를 확인하세요.');
    await loadAll();
    setSelectedExamId(data.exam_id);
  }

  async function createSlot() {
    if (!selectedExamId) return setMessage('먼저 시험 정보를 선택하세요.');
    await jsonFetch(`/api/exams/${selectedExamId}/slots`, { method: 'POST', body: JSON.stringify(slotForm) });
    setSlotForm({ ...slotForm, subject: '' });
    await loadExamData(selectedExamId);
  }

  async function deleteSlot(id: number) {
    await jsonFetch(`/api/slots/${id}`, { method: 'DELETE' });
    await loadExamData(selectedExamId);
  }

  async function allocate() {
    if (!selectedExamId) return setMessage('먼저 시험 정보를 선택하세요.');
    setWarnings([]);
    const payload = { ...allocForm, seed: allocForm.seed === '' ? null : Number(allocForm.seed) };
    const data = await jsonFetch(`/api/exams/${selectedExamId}/allocate`, { method: 'POST', body: JSON.stringify(payload) });
    setMessage(data.message);
    setWarnings(data.warnings || []);
    await loadExamData(selectedExamId);
    await loadStats();
  }

  async function changeAssignmentTeacher(a: Assignment, teacherId: string) {
    try {
      await jsonFetch(`/api/assignments/${a.id}`, { method: 'PUT', body: JSON.stringify({ teacher_id: teacherId ? Number(teacherId) : null }) });
      await loadExamData(selectedExamId);
      await loadStats();
    } catch (err: any) {
      alert(err.message);
    }
  }

  return (
    <div className="app">
      <header className="hero no-print">
        <div>
          <p className="eyebrow">중학교 정기고사</p>
          <h1>시험감독 배정표 자동 생성 시스템</h1>
          <p>정감독·부감독·복도감독을 공정하게 배정하고 연간 4회 지필평가 감독 횟수를 누적 관리합니다.</p>
        </div>
        <button className="secondary" onClick={createSample}>예시 데이터 만들기</button>
      </header>

      <nav className="tabs no-print">
        <button className={tab === 'teachers' ? 'active' : ''} onClick={() => setTab('teachers')}>1. 교사 명단</button>
        <button className={tab === 'exam' ? 'active' : ''} onClick={() => setTab('exam')}>2. 시험 정보</button>
        <button className={tab === 'assign' ? 'active' : ''} onClick={() => setTab('assign')}>3. 자동 배정</button>
        <button className={tab === 'stats' ? 'active' : ''} onClick={() => setTab('stats')}>4. 누적 통계</button>
        <button className={tab === 'print' ? 'active' : ''} onClick={() => setTab('print')}>5. 인쇄/PDF</button>
      </nav>

      {message && <div className="message no-print">{message}</div>}
      {warnings.length > 0 && <div className="warning no-print"><b>확인 필요</b>{warnings.map((w, i) => <p key={i}>{w}</p>)}</div>}

      {tab === 'teachers' && (
        <section className="card">
          <div className="section-title">
            <h2>교사 명단 관리</h2>
            <div className="button-row">
              <button onClick={() => download('/api/templates/teachers')}>교사 엑셀 양식 다운로드</button>
              <label className="file-label">교사 엑셀 업로드<input type="file" accept=".xlsx,.xls" onChange={e => uploadTeacherExcel(e.target.files?.[0]).catch(err => setMessage(err.message))} /></label>
            </div>
          </div>

          <div className="grid form-grid">
            <input placeholder="교사명" value={teacherForm.name} onChange={e => setTeacherForm({ ...teacherForm, name: e.target.value })} />
            <input placeholder="교과" value={teacherForm.subject} onChange={e => setTeacherForm({ ...teacherForm, subject: e.target.value })} />
            <input placeholder="부서" value={teacherForm.department} onChange={e => setTeacherForm({ ...teacherForm, department: e.target.value })} />
            <input placeholder="제외 날짜 예: 2026-04-30" value={teacherForm.exclude_dates} onChange={e => setTeacherForm({ ...teacherForm, exclude_dates: e.target.value })} />
            <input placeholder="제외 교시 예: 1,3" value={teacherForm.exclude_periods} onChange={e => setTeacherForm({ ...teacherForm, exclude_periods: e.target.value })} />
            <button onClick={createTeacher}>교사 추가</button>
          </div>

          <div className="table-wrap">
            <table>
              <thead><tr><th>교사명</th><th>교과</th><th>부서</th><th>감독 가능</th><th>정 제외</th><th>부 제외</th><th>복도 제외</th><th>제외 날짜</th><th>제외 교시</th><th>삭제</th></tr></thead>
              <tbody>
                {teachers.map(t => (
                  <tr key={t.id}>
                    <td><input value={t.name} onChange={e => updateTeacherField(t, 'name', e.target.value)} /></td>
                    <td><input value={t.subject} onChange={e => updateTeacherField(t, 'subject', e.target.value)} /></td>
                    <td><input value={t.department} onChange={e => updateTeacherField(t, 'department', e.target.value)} /></td>
                    <td><input type="checkbox" checked={!!t.can_supervise} onChange={e => updateTeacherField(t, 'can_supervise', e.target.checked ? 1 : 0)} /></td>
                    <td><input type="checkbox" checked={!!t.exclude_chief} onChange={e => updateTeacherField(t, 'exclude_chief', e.target.checked ? 1 : 0)} /></td>
                    <td><input type="checkbox" checked={!!t.exclude_assistant} onChange={e => updateTeacherField(t, 'exclude_assistant', e.target.checked ? 1 : 0)} /></td>
                    <td><input type="checkbox" checked={!!t.exclude_hallway} onChange={e => updateTeacherField(t, 'exclude_hallway', e.target.checked ? 1 : 0)} /></td>
                    <td><input value={t.exclude_dates || ''} onChange={e => updateTeacherField(t, 'exclude_dates', e.target.value)} /></td>
                    <td><input value={t.exclude_periods || ''} onChange={e => updateTeacherField(t, 'exclude_periods', e.target.value)} /></td>
                    <td><button className="danger" onClick={() => deleteTeacher(t.id)}>삭제</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {tab === 'exam' && (
        <section className="card">
          <div className="section-title"><h2>시험 정보 입력</h2><button onClick={() => download('/api/templates/schedule')}>시험 시간표 양식 다운로드</button></div>
          <div className="grid form-grid">
            <input type="number" value={examForm.school_year} onChange={e => setExamForm({ ...examForm, school_year: Number(e.target.value) })} />
            <select value={examForm.semester} onChange={e => setExamForm({ ...examForm, semester: Number(e.target.value) })}><option value={1}>1학기</option><option value={2}>2학기</option></select>
            <select value={examForm.exam_round} onChange={e => setExamForm({ ...examForm, exam_round: Number(e.target.value) })}><option value={1}>1차</option><option value={2}>2차</option></select>
            <input placeholder="시험명" value={examForm.title} onChange={e => setExamForm({ ...examForm, title: e.target.value })} />
            <button onClick={createExam}>시험 생성</button>
          </div>

          <div className="select-row">
            <label>현재 시험 선택</label>
            <select value={selectedExamId} onChange={e => setSelectedExamId(e.target.value ? Number(e.target.value) : '')}>
              <option value="">선택</option>
              {exams.map(e => <option key={e.id} value={e.id}>{e.title}</option>)}
            </select>
            <label className="file-label">시험 시간표 엑셀 업로드<input type="file" accept=".xlsx,.xls" onChange={e => uploadScheduleExcel(e.target.files?.[0]).catch(err => setMessage(err.message))} /></label>
          </div>

          <h3>시험 시간표 직접 추가</h3>
          <div className="grid form-grid">
            <input type="date" value={slotForm.exam_date} onChange={e => setSlotForm({ ...slotForm, exam_date: e.target.value })} />
            <input type="number" min="1" value={slotForm.period_no} onChange={e => setSlotForm({ ...slotForm, period_no: Number(e.target.value) })} />
            <input type="time" value={slotForm.start_time} onChange={e => setSlotForm({ ...slotForm, start_time: e.target.value })} />
            <input type="time" value={slotForm.end_time} onChange={e => setSlotForm({ ...slotForm, end_time: e.target.value })} />
            <input placeholder="학년 예: 1학년" value={slotForm.grade} onChange={e => setSlotForm({ ...slotForm, grade: e.target.value })} />
            <input placeholder="교과" value={slotForm.subject} onChange={e => setSlotForm({ ...slotForm, subject: e.target.value })} />
            <input type="number" min="1" placeholder="시험실수" value={slotForm.room_count} onChange={e => setSlotForm({ ...slotForm, room_count: Number(e.target.value) })} />
            <button onClick={createSlot}>시간표 추가</button>
          </div>

          <div className="table-wrap">
            <table>
              <thead><tr><th>시험일자</th><th>교시</th><th>시간</th><th>학년</th><th>교과</th><th>시험실수</th><th>삭제</th></tr></thead>
              <tbody>{slots.map(s => <tr key={s.id}><td>{s.exam_date}</td><td>{s.period_no}교시</td><td>{s.start_time}~{s.end_time}</td><td>{s.grade}</td><td>{s.subject}</td><td>{s.room_count}</td><td><button className="danger" onClick={() => deleteSlot(s.id)}>삭제</button></td></tr>)}</tbody>
            </table>
          </div>
        </section>
      )}

      {tab === 'assign' && (
        <section className="card">
          <div className="section-title"><h2>감독 자동 배정</h2><button onClick={() => selectedExamId && download(`/api/exams/${selectedExamId}/export`)}>엑셀 다운로드</button></div>
          <div className="selected-exam">현재 시험: <b>{selectedExam?.title || '선택되지 않음'}</b></div>
          <div className="grid form-grid">
            <label>정감독/시험실<input type="number" min="0" value={allocForm.chief_per_room} onChange={e => setAllocForm({ ...allocForm, chief_per_room: Number(e.target.value) })} /></label>
            <label>부감독/시험실<input type="number" min="0" value={allocForm.assistant_per_room} onChange={e => setAllocForm({ ...allocForm, assistant_per_room: Number(e.target.value) })} /></label>
            <label>복도감독/교시·교과<input type="number" min="0" value={allocForm.hallway_count_per_slot} onChange={e => setAllocForm({ ...allocForm, hallway_count_per_slot: Number(e.target.value) })} /></label>
            <label className="check"><input type="checkbox" checked={allocForm.prefer_subject_hallway} onChange={e => setAllocForm({ ...allocForm, prefer_subject_hallway: e.target.checked })} /> 교과 담당 교사 복도감독 우선</label>
            <label className="check"><input type="checkbox" checked={allocForm.minimize_consecutive} onChange={e => setAllocForm({ ...allocForm, minimize_consecutive: e.target.checked })} /> 연속 감독 최소화</label>
            <label className="check"><input type="checkbox" checked={allocForm.balance_counts} onChange={e => setAllocForm({ ...allocForm, balance_counts: e.target.checked })} /> 누적 횟수 균등 배정</label>
            <input placeholder="랜덤 시드 선택 입력" value={allocForm.seed} onChange={e => setAllocForm({ ...allocForm, seed: e.target.value })} />
            <button className="primary" onClick={allocate}>랜덤 자동 배정 실행</button>
          </div>
          <AssignmentTable assignments={assignments} teachers={teachers} onChange={changeAssignmentTeacher} />
        </section>
      )}

      {tab === 'stats' && (
        <section className="card">
          <div className="section-title"><h2>교사별 연간 감독 누적 통계</h2><button onClick={loadStats}>새로고침</button></div>
          <div className="table-wrap wide"><table><thead><tr>{stats[0] && Object.keys(stats[0]).map(k => <th key={k}>{k}</th>)}</tr></thead><tbody>{stats.map((r, i) => <tr key={i}>{Object.keys(r).map(k => <td key={k}>{r[k]}</td>)}</tr>)}</tbody></table></div>
        </section>
      )}

      {tab === 'print' && (
        <section className="card print-area">
          <div className="section-title no-print"><h2>인쇄 / PDF 저장용 화면</h2><button onClick={() => window.print()}>인쇄 또는 PDF 저장</button></div>
          <h2 className="print-title">{selectedExam?.title || '시험감독 배정표'}</h2>
          <AssignmentTable assignments={assignments} teachers={teachers} readOnly />
        </section>
      )}
    </div>
  );
}

function AssignmentTable({ assignments, teachers, onChange, readOnly = false }: { assignments: Assignment[]; teachers: Teacher[]; onChange?: (a: Assignment, teacherId: string) => void; readOnly?: boolean }) {
  return (
    <div className="table-wrap">
      <table>
        <thead><tr><th>날짜</th><th>교시</th><th>시간</th><th>학년</th><th>교과</th><th>시험실</th><th>감독유형</th><th>교사</th><th>교사교과</th></tr></thead>
        <tbody>
          {assignments.map(a => (
            <tr key={a.id} className={a.teacher_name === '미배정' ? 'unassigned' : ''}>
              <td>{a.exam_date}</td><td>{a.period_no}교시</td><td>{a.time_label}</td><td>{a.grade}</td><td>{a.subject}</td><td>{a.room_name}</td><td>{a.role}</td>
              <td>{readOnly ? a.teacher_name : <select value={a.teacher_id || ''} onChange={e => onChange?.(a, e.target.value)}><option value="">미배정</option>{teachers.map(t => <option key={t.id} value={t.id}>{t.name}({t.subject})</option>)}</select>}</td>
              <td>{a.teacher_subject}</td>
            </tr>
          ))}
          {assignments.length === 0 && <tr><td colSpan={9} className="empty">아직 배정 결과가 없습니다.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

export default App;
