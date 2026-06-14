import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Plus, Save, Download, Archive, Trash2, NotebookPen, FileText, Clock,
  CalendarDays, Layers, ChevronDown, ChevronUp, CalendarPlus, ExternalLink,
} from 'lucide-react';
import { plannerService, todoService } from '../services/api';
import PlannerAiPanel from '../components/PlannerAiPanel';

const DOW = ['일', '월', '화', '수', '목', '금', '토'];
const HOURS = Array.from({ length: 18 }, (_, i) => i + 6); // 6시 ~ 23시
const SLOTS = ['00', '10', '20', '30', '40', '50'];

// 대학생 학습 유형 / 우선순위 (pill 선택)
const STUDY_TYPES = ['강의 복습', '과제', '시험 준비', '팀플', '프로젝트', '발표 준비', '개인 공부'];
const PRIORITIES = [
  { value: '낮음', cls: 'bg-[#F3F4F6] text-[#6B7280] border-[#E5E7EB]', activeCls: 'bg-[#E5E7EB] text-[#374151] border-[#D1D5DB]' },
  { value: '보통', cls: 'bg-[#F4FBF2] text-[#15803D] border-[#E7F1E4]', activeCls: 'bg-[#69CB5B] text-white border-[#69CB5B]' },
  { value: '높음', cls: 'bg-[#FFF7ED] text-[#C2410C] border-[#FED7AA]', activeCls: 'bg-[#F97316] text-white border-[#F97316]' },
  { value: '긴급', cls: 'bg-[#FEF2F2] text-[#B91C1C] border-[#FECACA]', activeCls: 'bg-[#EF4444] text-white border-[#EF4444]' },
];

const GREEN = '#69CB5B';
const GREEN_DARK = '#15803D';

// 로드맵 기반 플래너 제목("[로드맵 N주차 M일] topic")을 prefix/topic으로 분리한다.
// 일반 플래너(prefix 없음)는 prefix=null로 반환되어 기존 표시가 그대로 유지된다.
const splitRoadmapTitle = (title) => {
  const m = typeof title === 'string' ? title.match(/^\s*(\[로드맵\s*\d+\s*주차\s*\d+\s*일\])\s*(.*)$/) : null;
  if (m) return { prefix: m[1], topic: m[2].trim() || '학습 계획' };
  return { prefix: null, topic: title };
};

const blankForm = () => {
  const today = new Date();
  return {
    title: '공부 플래너',
    year: today.getFullYear(),
    month: today.getMonth() + 1,
    day: today.getDate(),
    dayOfWeek: DOW[today.getDay()],
    term: '',
    subject: '',
    studyType: '',
    priority: '',
    goalTime: '',
    netStudyTime: '',
    wakeUpTime: '',
    dDay: '',
    content: '',
    tmi: '',
  };
};

const parseTimeTable = (json) => {
  if (!json) return {};
  try { return JSON.parse(json) || {}; } catch { return {}; }
};

const toDateStr = (d) => {
  const tz = new Date(d.getTime() - d.getTimezoneOffset() * 60000);
  return tz.toISOString().split('T')[0];
};

// .lucide 전역 색상(muted)을 덮어쓰기 위해 인라인 color 사용
const inputCls =
  'w-full h-11 box-border rounded-xl border border-[#D1D5DB] px-3.5 text-[14px] text-[#111827] outline-none transition focus:border-[#69CB5B]';
const labelCls = 'mb-1 block text-[12.5px] font-bold text-[#374151]';

export default function Planner() {
  const navigate = useNavigate();
  const [form, setForm] = useState(blankForm);
  const [timeTable, setTimeTable] = useState({}); // { hour: [bool x6] }
  const [plannerId, setPlannerId] = useState(null); // null = 새 플래너
  const [saved, setSaved] = useState([]);
  const [busy, setBusy] = useState('');
  const [loadingList, setLoadingList] = useState(true);
  const [showOptional, setShowOptional] = useState(false); // 기상시간 + 10분 체크표(선택 항목)
  const [addedToSchedule, setAddedToSchedule] = useState(false); // 주간일정 추가 성공 후 '보기' 버튼 노출
  const [showBulkModal, setShowBulkModal] = useState(false); // 자료 기반 플래너 전체삭제 확인 모달
  const [isDeleting, setIsDeleting] = useState(false); // 전체삭제 진행 중(중복 클릭 방지)
  const [selectedIds, setSelectedIds] = useState([]); // 체크박스 선택 삭제 대상 id
  const [showSelectModal, setShowSelectModal] = useState(false); // 선택삭제 확인 모달
  const [isSelectDeleting, setIsSelectDeleting] = useState(false); // 선택삭제 진행 중(중복 클릭 방지)

  const isEditing = plannerId != null;

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const refreshList = async () => {
    try {
      setLoadingList(true);
      const list = await plannerService.getPlanners();
      setSaved(Array.isArray(list) ? list : []);
    } catch (e) {
      console.warn('플래너 목록 로드 실패:', e?.message || e);
    } finally {
      setLoadingList(false);
    }
  };

  useEffect(() => { refreshList(); }, []);

  const toggleSlot = (hour, slot) => {
    setTimeTable((prev) => {
      const row = prev[hour] ? [...prev[hour]] : new Array(6).fill(false);
      row[slot] = !row[slot];
      return { ...prev, [hour]: row };
    });
  };

  const isChecked = (hour, slot) => !!(timeTable[hour] && timeTable[hour][slot]);

  const buildPayload = () => ({
    ...form,
    year: Number(form.year) || null,
    month: Number(form.month) || null,
    day: Number(form.day) || null,
    plannerDate: (form.year && form.month && form.day)
      ? `${form.year}-${String(form.month).padStart(2, '0')}-${String(form.day).padStart(2, '0')}`
      : null,
    timeTableJson: JSON.stringify(timeTable),
  });

  // 새 플래너 작성 시작
  const handleNew = () => {
    setForm(blankForm());
    setTimeTable({});
    setPlannerId(null);
    setAddedToSchedule(false);
  };

  // 저장본을 폼으로 불러오기 (reopen / edit)
  const handleSelect = async (id) => {
    try {
      setBusy('load');
      const d = await plannerService.getPlanner(id);
      setForm({
        title: d.title ?? '공부 플래너',
        year: d.year ?? '',
        month: d.month ?? '',
        day: d.day ?? '',
        dayOfWeek: d.dayOfWeek ?? DOW[0],
        term: d.term ?? '',
        subject: d.subject ?? '',
        studyType: d.studyType ?? '',
        priority: d.priority ?? '',
        goalTime: d.goalTime ?? '',
        netStudyTime: d.netStudyTime ?? '',
        wakeUpTime: d.wakeUpTime ?? '',
        dDay: d.dDay ?? '',
        content: d.content ?? '',
        tmi: d.tmi ?? '',
      });
      setTimeTable(parseTimeTable(d.timeTableJson));
      setPlannerId(d.id);
      setAddedToSchedule(false);
      // 저장본에 기상시간/체크표가 있으면 선택 항목을 펼쳐서 보여준다.
      setShowOptional(Boolean(d.wakeUpTime) || Boolean(d.timeTableJson && d.timeTableJson !== '{}'));
      if (typeof window !== 'undefined') window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (e) {
      alert(e.response?.data?.message || e.message || '플래너를 불러오지 못했습니다.');
    } finally { setBusy(''); }
  };

  // 현재 폼 상태를 저장(수정 or 생성)하고 id 반환
  const persist = async () => {
    const payload = buildPayload();
    if (plannerId) {
      await plannerService.updatePlanner(plannerId, payload);
      return plannerId;
    }
    const created = await plannerService.createPlanner(payload);
    setPlannerId(created.id);
    return created.id;
  };

  const handleSave = async () => {
    try {
      setBusy('save');
      const id = await persist();
      await refreshList();
      alert(isEditing ? `플래너가 수정되었습니다. (#${id})` : `플래너가 저장되었습니다. (#${id})`);
    } catch (e) {
      alert(e.response?.data?.message || e.message || '플래너 저장에 실패했습니다.');
    } finally { setBusy(''); }
  };

  const handlePdf = async () => {
    try {
      setBusy('pdf');
      const id = await persist();
      const res = await plannerService.generatePdf(id);
      await refreshList();
      if (res.downloadUrl) window.open(res.downloadUrl, '_blank', 'noopener');
      alert('PDF가 생성되어 자료보관함에 저장되었습니다.');
    } catch (e) {
      alert(e.response?.data?.message || e.message || 'PDF 생성에 실패했습니다.');
    } finally { setBusy(''); }
  };

  const handleArchive = async () => {
    try {
      setBusy('archive');
      const id = await persist();
      await plannerService.archive(id);
      await refreshList();
      alert('자료보관함 > 플래너 탭에 저장되었습니다.');
    } catch (e) {
      alert(e.response?.data?.message || e.message || '자료보관함 저장에 실패했습니다.');
    } finally { setBusy(''); }
  };

  // ===== 플래너 → 주간일정(기존 /api/todos) 연동 (새 컬럼/엔드포인트 없음) =====
  const buildScheduleDate = () =>
    (form.year && form.month && form.day)
      ? `${form.year}-${String(form.month).padStart(2, '0')}-${String(form.day).padStart(2, '0')}`
      : '';

  // Todo 모델이 text 한 필드뿐이라, 출처/과목/학습목표를 text 에 담는다. ('[플래너]' 접두어로 주간일정에서 badge 표시)
  const buildScheduleText = () => {
    const goal = (form.content || '').trim() || (form.title || '').trim();
    const subject = (form.subject || '').trim();
    const core = subject ? `${subject} - ${goal}` : goal;
    return `[플래너] ${core}`.slice(0, 250);
  };

  const handleAddToSchedule = async () => {
    const date = buildScheduleDate();
    if (!date) { alert('날짜(년/월/일)를 먼저 입력하세요.'); return; }
    const goal = (form.content || '').trim() || (form.title || '').trim();
    if (!goal) { alert('제목 또는 학습 목표를 입력하세요.'); return; }

    const text = buildScheduleText();
    try {
      setBusy('schedule');
      const savedUserId = localStorage.getItem('userId');
      // 중복 방지: 같은 날짜 + 같은 제목이 이미 등록돼 있으면 막는다.
      const existing = await todoService.getTodos(savedUserId);
      const dup = Array.isArray(existing) && existing.some(
        (t) => (t.startDate ? String(t.startDate).split('T')[0] : '') === date && t.text === text
      );
      if (dup) { alert('이미 주간일정에 추가된 플래너입니다.'); setBusy(''); return; }

      // 기존 createTodo 그대로 사용 (text/startDate/endDate/completed)
      await todoService.createTodo(savedUserId, {
        text,
        startDate: `${date}T00:00:00`,
        endDate: `${date}T23:59:59`,
        completed: false,
      });
      setAddedToSchedule(true);
      alert('주간일정에 추가되었습니다.');
    } catch (e) {
      console.error('주간일정 추가 실패:', e);
      alert('주간일정 추가에 실패했습니다. 다시 시도해 주세요.');
    } finally { setBusy(''); }
  };

  const handleDelete = async (id, e) => {
    e?.stopPropagation();
    if (!window.confirm('이 플래너를 삭제할까요? (연결된 PDF도 함께 삭제됩니다)')) return;
    try {
      setBusy('delete');
      await plannerService.deletePlanner(id);
      if (id === plannerId) handleNew();
      await refreshList();
    } catch (err) {
      alert(err.response?.data?.message || err.message || '삭제에 실패했습니다.');
    } finally { setBusy(''); }
  };

  // 현재 화면에 표시 중인 '자료 기반(ROADMAP_AUTO)' 플래너만 전체삭제 대상으로 삼는다.
  // 수동으로 작성한 플래너(sourceType 없음)는 대상에서 제외 → 절대 삭제되지 않는다.
  const roadmapPlanners = useMemo(
    () => (Array.isArray(saved) ? saved.filter((p) => p.sourceType === 'ROADMAP_AUTO') : []),
    [saved]
  );
  const hasManualMixed = useMemo(
    () => (Array.isArray(saved) ? saved.some((p) => p.sourceType !== 'ROADMAP_AUTO') : false),
    [saved]
  );
  // 전체삭제 버튼 비활성화 조건: 대상 0개 / 삭제 중 / 다른 작업 진행 중
  const bulkDisabled = roadmapPlanners.length === 0 || isDeleting || !!busy;

  // 자료 기반 플래너 전체삭제 (현재 화면에 보이는 ROADMAP_AUTO id 만 전송 → 백엔드 재검증)
  const handleBulkDelete = async () => {
    if (isDeleting) return; // 중복 클릭 방지
    const targetIds = roadmapPlanners.map((p) => p.id);
    if (targetIds.length === 0) { setShowBulkModal(false); return; }
    try {
      setIsDeleting(true);
      const res = await plannerService.bulkDeletePlanners({
        scope: 'VISIBLE_ROADMAP_AUTO',
        sourceType: 'ROADMAP_AUTO',
        plannerIds: targetIds,
      });
      if (res && res.success === false) {
        alert(res.message || '전체삭제에 실패했습니다.');
        return; // 목록 유지
      }
      setShowBulkModal(false);
      // 현재 편집 중 플래너가 삭제 대상이면 폼 초기화
      if (plannerId != null && targetIds.includes(plannerId)) handleNew();
      await refreshList(); // 목록/badge 갱신
      alert(res?.message || `${res?.deletedCount ?? targetIds.length}개의 플래너를 삭제했습니다.`);
    } catch (err) {
      alert(err.response?.data?.message || err.message || '전체삭제에 실패했습니다.');
    } finally {
      setIsDeleting(false);
    }
  };

  // ===== 체크박스 선택 삭제 =====
  const toggleSelect = (id, e) => {
    e?.stopPropagation();
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };
  const allVisibleIds = useMemo(() => (Array.isArray(saved) ? saved.map((p) => p.id) : []), [saved]);
  const allSelected = allVisibleIds.length > 0 && selectedIds.length === allVisibleIds.length;
  const toggleSelectAll = (e) => {
    e?.stopPropagation();
    setSelectedIds(allSelected ? [] : allVisibleIds);
  };
  // 목록이 바뀌면 더 이상 존재하지 않는 선택 id 정리
  useEffect(() => {
    setSelectedIds((prev) => prev.filter((id) => allVisibleIds.includes(id)));
  }, [allVisibleIds]);

  const handleSelectDelete = async () => {
    if (isSelectDeleting) return; // 중복 클릭 방지
    const ids = selectedIds.filter((id) => allVisibleIds.includes(id));
    if (ids.length === 0) { setShowSelectModal(false); return; }
    try {
      setIsSelectDeleting(true);
      const res = await plannerService.bulkDeleteSelectedPlanners(ids);
      if (res && res.success === false) {
        alert(res.message || '선택삭제에 실패했습니다.');
        return; // 목록 유지
      }
      setShowSelectModal(false);
      if (plannerId != null && ids.includes(plannerId)) handleNew();
      setSelectedIds([]);
      await refreshList(); // 목록/badge 갱신
      alert(res?.message || `${res?.deletedCount ?? ids.length}개의 플래너를 삭제했습니다.`);
    } catch (err) {
      alert(err.response?.data?.message || err.message || '선택삭제에 실패했습니다.');
    } finally {
      setIsSelectDeleting(false);
    }
  };

  const checkedCount = useMemo(
    () => Object.values(timeTable).reduce((acc, row) => acc + (row ? row.filter(Boolean).length : 0), 0),
    [timeTable]
  );

  const dateLabel = (p) => {
    if (p.year && p.month && p.day) {
      return `${p.year}.${String(p.month).padStart(2, '0')}.${String(p.day).padStart(2, '0')}${p.dayOfWeek ? ` (${p.dayOfWeek})` : ''}`;
    }
    if (p.plannerDate) return p.plannerDate;
    return '날짜 미입력';
  };

  // ===== 요약 카드: 기존 저장 데이터(saved)에서 파생 (더미 없음) =====
  const summary = useMemo(() => {
    const list = Array.isArray(saved) ? saved : [];
    const todayStr = toDateStr(new Date());
    const withDate = list.filter((p) => p.plannerDate);
    const upcoming = withDate
      .filter((p) => p.plannerDate >= todayStr)
      .sort((a, b) => String(a.plannerDate).localeCompare(String(b.plannerDate)));
    const subjects = [...new Set(list.map((p) => (p.subject || '').trim()).filter(Boolean))];
    return {
      total: list.length,
      upcomingCount: upcoming.length,
      upcoming: upcoming.slice(0, 3),
      subjectCount: subjects.length,
    };
  }, [saved]);

  return (
    <div className="min-h-screen bg-[#F6F7F8]">
      <div className="mx-auto max-w-[1240px] px-4 py-6 sm:px-5 lg:px-6">
        {/* 헤더 */}
        <div className="mb-5">
          <h1 className="m-0 text-[24px] font-black text-[#111827]">공부 플래너</h1>
          <p className="mt-1.5 text-[14px] text-[#6B7280]">강의, 과제, 시험, 팀플 일정을 한 번에 정리하세요.</p>
          <p className="mt-0.5 text-[13px] text-[#9CA3AF]">강의, 과제, 시험, 복습 계획을 하나의 학습 흐름으로 관리하세요.</p>
        </div>

        {/* 좌(목록+폼) / 우(요약 + 미리보기) */}
        <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(360px,1fr)]">
          {/* ===== 좌측 컬럼 ===== */}
          <div className="flex flex-col gap-6">
            {/* 저장본 목록 */}
            <section className="rounded-[20px] border border-[#E5E7EB] bg-white p-5 shadow-[0_2px_8px_rgba(0,0,0,0.04)]">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <h2 className="m-0 flex items-center gap-2 text-[15px] font-extrabold text-[#111827]">
                  <NotebookPen size={17} strokeWidth={2.2} style={{ color: GREEN_DARK }} />
                  저장된 플래너
                  {saved.length > 0 && (
                    <span className="rounded-full bg-[#F4FBF2] px-2 py-0.5 text-[12px] font-bold text-[#15803D]">{saved.length}</span>
                  )}
                </h2>
                <div className="flex flex-wrap items-center gap-2">
                  {/* 체크박스 선택 삭제 — 선택된 항목이 없으면 disabled */}
                  <button
                    onClick={() => setShowSelectModal(true)}
                    disabled={selectedIds.length === 0 || isSelectDeleting || !!busy}
                    title={selectedIds.length === 0 ? '삭제할 플래너를 선택하세요' : '선택한 플래너 삭제'}
                    className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-[#FDBA74] bg-white px-3.5 text-[13px] font-bold text-[#C2410C] transition hover:bg-[#FFF7ED] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <Trash2 size={15} strokeWidth={2.2} style={{ color: '#C2410C' }} />
                    {isSelectDeleting ? '삭제 중…' : `선택삭제${selectedIds.length > 0 ? ` (${selectedIds.length})` : ''}`}
                  </button>
                  {/* 자료 기반(ROADMAP_AUTO) 플래너 전체삭제 — 위험 액션(빨간색 outline) */}
                  <button
                    onClick={() => setShowBulkModal(true)}
                    disabled={bulkDisabled}
                    title={roadmapPlanners.length === 0 ? '삭제할 자료 기반 플래너가 없습니다' : '자료 기반 플래너 전체삭제'}
                    className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-[#FECACA] bg-white px-3.5 text-[13px] font-bold text-[#DC2626] transition hover:bg-[#FEF2F2] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <Trash2 size={15} strokeWidth={2.2} style={{ color: '#DC2626' }} />
                    {isDeleting ? '삭제 중…' : `전체삭제${roadmapPlanners.length > 0 ? ` (${roadmapPlanners.length})` : ''}`}
                  </button>
                  <button
                    onClick={handleNew}
                    className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-[#69CB5B] px-3.5 text-[13px] font-bold text-white transition hover:bg-[#5cb84f]"
                  >
                    <Plus size={16} strokeWidth={2.6} style={{ color: '#fff' }} />
                    새 플래너
                  </button>
                </div>
              </div>

              {loadingList ? (
                <div className="py-6 text-center text-[13px] text-[#9CA3AF]">불러오는 중…</div>
              ) : saved.length === 0 ? (
                <div className="flex flex-col items-center gap-2 py-6 text-center">
                  <FileText size={26} strokeWidth={1.8} style={{ color: '#D1D5DB' }} />
                  <p className="m-0 text-[13px] font-semibold text-[#6B7280]">저장된 플래너가 없습니다</p>
                  <p className="m-0 text-[12px] text-[#9CA3AF]">아래에서 플래너를 작성하고 저장해 보세요.</p>
                </div>
              ) : (
                <div className="flex max-h-[280px] flex-col gap-2 overflow-y-auto pr-1">
                  {/* 전체선택 + 선택 개수 */}
                  <div className="flex items-center justify-between px-1 pb-1">
                    <label className="flex cursor-pointer items-center gap-2 text-[12px] font-semibold text-[#6B7280]" onClick={(e) => e.stopPropagation()}>
                      <input type="checkbox" checked={allSelected} onChange={toggleSelectAll} className="h-4 w-4 cursor-pointer accent-[#69CB5B]" />
                      전체선택
                    </label>
                    {selectedIds.length > 0 && (
                      <span className="text-[12px] font-bold text-[#C2410C]">{selectedIds.length}개 선택됨</span>
                    )}
                  </div>
                  {saved.map((p) => {
                    const active = p.id === plannerId;
                    const checked = selectedIds.includes(p.id);
                    return (
                      <div
                        key={p.id}
                        onClick={() => handleSelect(p.id)}
                        className={`group flex cursor-pointer items-center gap-3 rounded-xl border px-3.5 py-2.5 transition ${
                          active
                            ? 'border-[#69CB5B] bg-[#F4FBF2]'
                            : checked
                            ? 'border-[#FDBA74] bg-[#FFF7ED]'
                            : 'border-[#E5E7EB] bg-white hover:border-[#BBF7D0] hover:bg-[#F9FEF8]'
                        }`}
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          onClick={(e) => e.stopPropagation()}
                          onChange={(e) => toggleSelect(p.id, e)}
                          title="선택"
                          className="h-4 w-4 shrink-0 cursor-pointer accent-[#69CB5B]"
                        />
                        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#F4FBF2]">
                          <NotebookPen size={15} strokeWidth={2.2} style={{ color: GREEN }} />
                        </div>
                        <div className="min-w-0 flex-1" title={p.title || '공부 플래너'}>
                          {(() => {
                            const { prefix, topic } = splitRoadmapTitle(p.title || '공부 플래너');
                            return (
                              <>
                                {prefix && (
                                  <span className="mb-0.5 inline-block rounded-md bg-[#EEF8EB] px-1.5 py-0.5 text-[10px] font-bold text-[#15803D]">
                                    {prefix.replace(/^\[|\]$/g, '')}
                                  </span>
                                )}
                                <div className="flex items-center gap-1.5">
                                  <span className="truncate text-[14px] font-bold text-[#111827]">{topic || '공부 플래너'}</span>
                                  {p.studyType && <span className="shrink-0 rounded-full bg-[#F4FBF2] px-1.5 py-0.5 text-[10px] font-bold text-[#15803D]">{p.studyType}</span>}
                                </div>
                              </>
                            );
                          })()}
                          <div className="flex items-center gap-1 text-[12px] text-[#6B7280]">
                            <Clock size={12} strokeWidth={2} style={{ color: '#9CA3AF' }} />
                            {dateLabel(p)}
                            {p.s3Key && <span className="ml-1 rounded bg-[#EEF8EB] px-1.5 py-0.5 text-[10px] font-bold text-[#15803D]">PDF</span>}
                          </div>
                        </div>
                        <button
                          onClick={(e) => handleDelete(p.id, e)}
                          disabled={!!busy}
                          title="삭제"
                          className="shrink-0 rounded-lg p-1.5 opacity-0 transition hover:bg-red-50 group-hover:opacity-100"
                        >
                          <Trash2 size={15} strokeWidth={2} style={{ color: '#EF4444' }} />
                        </button>
                      </div>
                    );
                  })}
                </div>
              )}
            </section>

            {/* 입력 폼 */}
            <section className="rounded-[20px] border border-[#E5E7EB] bg-white p-5 shadow-[0_2px_8px_rgba(0,0,0,0.04)]">
              <div className="mb-4 flex items-center gap-2">
                <span className={`rounded-full px-2.5 py-1 text-[12px] font-bold ${isEditing ? 'bg-[#FEF3C7] text-[#92400E]' : 'bg-[#F4FBF2] text-[#15803D]'}`}>
                  {isEditing ? `수정 중 · #${plannerId}` : '새 플래너'}
                </span>
                <span className="text-[12px] text-[#9CA3AF]">강의자료에서 뽑은 핵심 내용과 개인 일정을 연결해 오늘 할 일을 정리하세요.</span>
              </div>

              <div className="mb-3">
                <label className={labelCls}>플래너 제목</label>
                <input className={inputCls} value={form.title} onChange={(e) => set('title', e.target.value)} />
              </div>

              {/* 날짜 + 요일 */}
              <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
                <div><label className={labelCls}>년</label><input type="number" className={inputCls} value={form.year} onChange={(e) => set('year', e.target.value)} /></div>
                <div><label className={labelCls}>월</label><input type="number" className={inputCls} value={form.month} onChange={(e) => set('month', e.target.value)} /></div>
                <div><label className={labelCls}>일</label><input type="number" className={inputCls} value={form.day} onChange={(e) => set('day', e.target.value)} /></div>
                <div>
                  <label className={labelCls}>요일</label>
                  <select className={inputCls} value={form.dayOfWeek} onChange={(e) => set('dayOfWeek', e.target.value)}>
                    {DOW.map((d) => <option key={d} value={d}>{d}</option>)}
                  </select>
                </div>
              </div>

              {/* 학기/주차 + 과목명 */}
              <div className="mb-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
                <div><label className={labelCls}>학기 / 주차</label><input className={inputCls} placeholder="예: 2026-1학기 · 3주차" value={form.term} onChange={(e) => set('term', e.target.value)} /></div>
                <div><label className={labelCls}>과목명</label><input className={inputCls} placeholder="예: 모바일 앱 개발" value={form.subject} onChange={(e) => set('subject', e.target.value)} /></div>
              </div>

              {/* 학습 유형 (pill) */}
              <div className="mb-3">
                <label className={labelCls}>학습 유형</label>
                <div className="flex flex-wrap gap-1.5">
                  {STUDY_TYPES.map((t) => {
                    const on = form.studyType === t;
                    return (
                      <button
                        key={t}
                        type="button"
                        onClick={() => set('studyType', on ? '' : t)}
                        className={`rounded-full border px-3 py-1.5 text-[12.5px] font-semibold transition ${
                          on ? 'border-[#69CB5B] bg-[#69CB5B] text-white' : 'border-[#E7F1E4] bg-[#F4FBF2] text-[#15803D] hover:bg-[#EAF8E5]'
                        }`}
                      >
                        {t}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* 우선순위 (pill) */}
              <div className="mb-3">
                <label className={labelCls}>우선순위</label>
                <div className="flex flex-wrap gap-1.5">
                  {PRIORITIES.map((p) => {
                    const on = form.priority === p.value;
                    return (
                      <button
                        key={p.value}
                        type="button"
                        onClick={() => set('priority', on ? '' : p.value)}
                        className={`rounded-full border px-3 py-1.5 text-[12.5px] font-bold transition ${on ? p.activeCls : p.cls}`}
                      >
                        {p.value}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* 시간 + 마감/시험일 */}
              <div className="mb-3 grid grid-cols-1 gap-2 sm:grid-cols-3">
                <div><label className={labelCls}>목표 학습 시간</label><input className={inputCls} placeholder="예: 2시간" value={form.goalTime} onChange={(e) => set('goalTime', e.target.value)} /></div>
                <div><label className={labelCls}>실제 학습 시간</label><input className={inputCls} placeholder="예: 1시간 30분" value={form.netStudyTime} onChange={(e) => set('netStudyTime', e.target.value)} /></div>
                <div><label className={labelCls}>마감일 / 시험일</label><input className={inputCls} placeholder="예: 2026-06-20" value={form.dDay} onChange={(e) => set('dDay', e.target.value)} /></div>
              </div>

              {/* 학습 목표 */}
              <div className="mb-3">
                <label className={labelCls}>학습 목표</label>
                <textarea className={`${inputCls} h-auto min-h-[60px] resize-y py-2.5`} placeholder="예: Retrofit2 개념 정리 및 실습 코드 완성" value={form.content} onChange={(e) => set('content', e.target.value)} />
              </div>

              {/* 세부 할 일 */}
              <div className="mb-3">
                <label className={labelCls}>세부 할 일</label>
                <textarea className={`${inputCls} h-auto min-h-[70px] resize-y py-2.5`} placeholder="예: 강의자료 1~5p 복습, 실습 코드 실행, 오류 메모" value={form.tmi} onChange={(e) => set('tmi', e.target.value)} />
              </div>

              {/* 선택 항목 (기상 시간 + 10분 체크표) — 기본 접힘 */}
              <div className="mb-4 rounded-xl border border-[#E5E7EB] bg-[#FAFBFA]">
                <button
                  type="button"
                  onClick={() => setShowOptional((v) => !v)}
                  className="flex w-full items-center justify-between px-3.5 py-2.5 text-[13px] font-bold text-[#374151]"
                >
                  <span className="flex items-center gap-1.5">
                    <Clock size={14} strokeWidth={2.2} style={{ color: '#9CA3AF' }} />
                    집중 세션 기록 (선택) · 기상 시간 · 10분 체크표
                    {checkedCount > 0 && <span className="rounded-full bg-[#F4FBF2] px-1.5 py-0.5 text-[11px] font-bold text-[#15803D]">{checkedCount}칸</span>}
                  </span>
                  {showOptional ? <ChevronUp size={16} style={{ color: '#6B7280' }} /> : <ChevronDown size={16} style={{ color: '#6B7280' }} />}
                </button>

                {showOptional && (
                  <div className="border-t border-[#E5E7EB] px-3.5 py-3">
                    <div className="mb-3 max-w-[200px]">
                      <label className={labelCls}>기상 시간 (선택)</label>
                      <input className={inputCls} placeholder="예: 07:00" value={form.wakeUpTime} onChange={(e) => set('wakeUpTime', e.target.value)} />
                    </div>
                    <label className={labelCls}>시간 체크표 (10분 단위, 클릭해서 체크) · 체크 {checkedCount}칸</label>
                    <div className="overflow-x-auto rounded-lg border border-[#E7F1E4]">
                      <table className="w-full border-collapse text-[11px]">
                        <thead>
                          <tr>
                            <th className="border border-[#E5E7EB] bg-[#F4FBF2] p-1 text-[#15803D]">시</th>
                            {SLOTS.map((s) => <th key={s} className="border border-[#E5E7EB] bg-[#F4FBF2] p-1 text-[#15803D]">{s}</th>)}
                          </tr>
                        </thead>
                        <tbody>
                          {HOURS.map((h) => (
                            <tr key={h}>
                              <td className="border border-[#E5E7EB] p-1 text-center text-[#374151]">{String(h).padStart(2, '0')}</td>
                              {SLOTS.map((s, slot) => (
                                <td
                                  key={s}
                                  onClick={() => toggleSlot(h, slot)}
                                  className="h-[18px] min-w-[26px] cursor-pointer border border-[#E5E7EB] p-0.5 text-center"
                                  style={{ backgroundColor: isChecked(h, slot) ? GREEN : '#fff' }}
                                />
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </div>

              <div className="flex flex-wrap gap-2.5">
                <button onClick={handleSave} disabled={!!busy}
                  className="inline-flex h-12 items-center gap-2 rounded-xl bg-[#69CB5B] px-5 text-[14px] font-extrabold text-white transition hover:bg-[#5cb84f] disabled:cursor-not-allowed disabled:opacity-60">
                  <Save size={17} strokeWidth={2.2} style={{ color: '#fff' }} />
                  {busy === 'save' ? '저장 중…' : (isEditing ? '수정 저장' : '플래너 생성')}
                </button>
                <button onClick={handleAddToSchedule} disabled={!!busy}
                  className="inline-flex h-12 items-center gap-2 rounded-xl border border-[#E7F1E4] bg-[#F4FBF2] px-5 text-[14px] font-extrabold text-[#15803D] transition hover:bg-[#EAF8E5] disabled:cursor-not-allowed disabled:opacity-60">
                  <CalendarPlus size={17} strokeWidth={2.2} style={{ color: GREEN_DARK }} />
                  {busy === 'schedule' ? '추가 중…' : '주간일정에 추가'}
                </button>
                <button onClick={handlePdf} disabled={!!busy}
                  className="inline-flex h-12 items-center gap-2 rounded-xl border border-[#E7F1E4] bg-[#F4FBF2] px-5 text-[14px] font-extrabold text-[#15803D] transition hover:bg-[#EAF8E5] disabled:cursor-not-allowed disabled:opacity-60">
                  <Download size={17} strokeWidth={2.2} style={{ color: GREEN_DARK }} />
                  {busy === 'pdf' ? 'PDF 생성 중…' : 'PDF 저장'}
                </button>
                <button onClick={handleArchive} disabled={!!busy}
                  className="inline-flex h-12 items-center gap-2 rounded-xl border border-[#E7F1E4] bg-[#F4FBF2] px-5 text-[14px] font-extrabold text-[#15803D] transition hover:bg-[#EAF8E5] disabled:cursor-not-allowed disabled:opacity-60">
                  <Archive size={17} strokeWidth={2.2} style={{ color: GREEN_DARK }} />
                  {busy === 'archive' ? '저장 중…' : '자료보관함에 저장'}
                </button>
                {addedToSchedule && (
                  <button onClick={() => navigate('/weekly-schedule')}
                    className="inline-flex h-12 items-center gap-2 rounded-xl border border-[#69CB5B] bg-white px-5 text-[14px] font-extrabold text-[#15803D] transition hover:bg-[#F4FBF2]">
                    <ExternalLink size={17} strokeWidth={2.2} style={{ color: GREEN_DARK }} />
                    주간일정에서 보기
                  </button>
                )}
              </div>
            </section>

            {/* 공부 플래너 전용 AI (학습 실행 관리: 피드백 및 다음 학습 추천) */}
            <PlannerAiPanel plannerId={plannerId} />
          </div>

          {/* ===== 우측 컬럼: 요약 카드 + A4 미리보기 ===== */}
          <div className="flex flex-col gap-6 lg:sticky lg:top-[96px]">
            {/* 요약 카드 (기존 저장 데이터 기반) */}
            <section className="rounded-[20px] border border-[#E5E7EB] bg-white p-5 shadow-[0_2px_8px_rgba(0,0,0,0.04)]">
              <div className="mb-3 flex items-center gap-2 text-[14px] font-extrabold text-[#111827]">
                <Layers size={16} strokeWidth={2.2} style={{ color: GREEN_DARK }} /> 내 학습 요약
              </div>
              <div className="grid grid-cols-3 gap-2.5">
                <SummaryStat label="저장된 플래너" value={`${summary.total}개`} />
                <SummaryStat label="다가오는 일정" value={`${summary.upcomingCount}개`} />
                <SummaryStat label="과목 수" value={`${summary.subjectCount}개`} />
              </div>

              <div className="mt-3.5">
                <div className="mb-1.5 flex items-center gap-1.5 text-[12.5px] font-bold text-[#374151]">
                  <CalendarDays size={14} strokeWidth={2.2} style={{ color: '#9CA3AF' }} /> 마감 임박 일정
                </div>
                {summary.upcoming.length === 0 ? (
                  <p className="m-0 rounded-lg bg-[#F9FAFB] px-3 py-2.5 text-[12.5px] text-[#9CA3AF]">예정된 일정이 없습니다. 날짜를 입력해 플래너를 저장해 보세요.</p>
                ) : (
                  <div className="flex flex-col gap-1.5">
                    {summary.upcoming.map((p) => (
                      <div key={p.id} className="flex items-center justify-between gap-2 rounded-lg border border-[#E7F1E4] bg-[#F4FBF2] px-3 py-2">
                        <span className="truncate text-[12.5px] font-semibold text-[#111827]">{p.subject || p.title || '플래너'}</span>
                        <span className="shrink-0 text-[12px] font-bold text-[#15803D]">{p.plannerDate}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </section>

            {/* A4 세로 미리보기 */}
            <section className="rounded-[20px] border border-[#E5E7EB] bg-white p-5 shadow-[0_2px_8px_rgba(0,0,0,0.04)]">
              <div className="mb-3 text-[13px] font-bold text-[#6B7280]">A4 미리보기</div>
              <div className="flex justify-center">
                <div
                  className="w-full max-w-[480px] overflow-auto rounded-md border border-[#E5E7EB] bg-white p-6"
                  style={{ aspectRatio: '210 / 297', boxShadow: '0 10px 30px rgba(0,0,0,0.10)' }}
                >
                  <div className="text-[20px] font-black text-[#15803D]">{form.title || '공부 플래너'}</div>
                  <div className="mb-3.5 mt-1 text-[12px] text-[#4B5563]">
                    {form.year || '____'}년 {form.month || '__'}월 {form.day || '__'}일 ({form.dayOfWeek})
                    {form.term ? `  ·  ${form.term}` : ''}
                  </div>

                  <div className="mb-3.5 grid grid-cols-4 gap-1.5">
                    {[['학습 유형', form.studyType], ['우선순위', form.priority], ['목표 시간', form.goalTime], ['마감/시험', form.dDay]].map(([l, v]) => (
                      <div key={l} className="rounded-md border border-[#E7F1E4] p-1.5">
                        <div className="text-[9px] font-bold text-[#15803D]">{l}</div>
                        <div className="text-[12px] font-extrabold">{v || '-'}</div>
                      </div>
                    ))}
                  </div>

                  <PreviewRow label="과목명" value={form.subject} />
                  <PreviewRow label="학습 목표" value={form.content} multi />
                  <PreviewRow label="세부 할 일" value={form.tmi} multi />

                  {(form.wakeUpTime || checkedCount > 0) && (
                    <>
                      <div className="my-3 text-[12px] font-extrabold text-[#15803D]">집중 세션 기록</div>
                      {form.wakeUpTime && <div className="mb-2 text-[11px] text-[#4B5563]">기상 시간: <span className="font-bold">{form.wakeUpTime}</span></div>}
                      <table className="w-full border-collapse text-[8px]">
                        <thead>
                          <tr>
                            <th className="border border-[#E5E7EB] bg-[#F4FBF2] p-px">시</th>
                            {SLOTS.map((s) => <th key={s} className="border border-[#E5E7EB] bg-[#F4FBF2] p-px">{s}</th>)}
                          </tr>
                        </thead>
                        <tbody>
                          {HOURS.map((h) => (
                            <tr key={h}>
                              <td className="border border-[#E5E7EB] text-center">{String(h).padStart(2, '0')}</td>
                              {SLOTS.map((s, slot) => (
                                <td key={s} className="h-[9px] border border-[#E5E7EB]" style={{ backgroundColor: isChecked(h, slot) ? GREEN : '#fff' }} />
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </>
                  )}
                </div>
              </div>
            </section>
          </div>
        </div>
      </div>

      {/* ===== 선택삭제 확인 모달 ===== */}
      {showSelectModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
          onClick={() => { if (!isSelectDeleting) setShowSelectModal(false); }}
        >
          <div
            className="w-full max-w-[420px] rounded-2xl bg-white p-6 shadow-[0_20px_60px_rgba(0,0,0,0.25)]"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-3 flex items-center gap-2">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-[#FFF7ED]">
                <Trash2 size={20} strokeWidth={2.2} style={{ color: '#C2410C' }} />
              </div>
              <h3 className="m-0 text-[17px] font-extrabold text-[#111827]">선택한 플래너 삭제</h3>
            </div>
            <p className="m-0 text-[14px] leading-relaxed text-[#374151]">
              선택한 플래너를 삭제합니다. 이 작업은 되돌릴 수 없습니다.
            </p>
            <p className="mt-2 text-[13px] leading-relaxed text-[#6B7280]">
              선택하지 않은 플래너와 주간일정은 삭제되지 않습니다.
            </p>
            <div className="mt-3 rounded-xl border border-[#FDBA74] bg-[#FFF7ED] px-3.5 py-2.5 text-[13px] font-bold text-[#C2410C]">
              삭제 대상: {selectedIds.length}개
            </div>
            <div className="mt-5 flex justify-end gap-2.5">
              <button
                onClick={() => setShowSelectModal(false)}
                disabled={isSelectDeleting}
                className="inline-flex h-11 items-center rounded-xl border border-[#E5E7EB] bg-white px-5 text-[14px] font-bold text-[#374151] transition hover:bg-[#F9FAFB] disabled:cursor-not-allowed disabled:opacity-60"
              >
                취소
              </button>
              <button
                onClick={handleSelectDelete}
                disabled={isSelectDeleting || selectedIds.length === 0}
                className="inline-flex h-11 items-center gap-2 rounded-xl bg-[#C2410C] px-5 text-[14px] font-extrabold text-white transition hover:bg-[#9A3412] disabled:cursor-not-allowed disabled:opacity-60"
              >
                <Trash2 size={16} strokeWidth={2.2} style={{ color: '#fff' }} />
                {isSelectDeleting ? '삭제 중…' : '선택삭제'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ===== 전체삭제 확인 모달 (위험 액션) ===== */}
      {showBulkModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
          onClick={() => { if (!isDeleting) setShowBulkModal(false); }}
        >
          <div
            className="w-full max-w-[420px] rounded-2xl bg-white p-6 shadow-[0_20px_60px_rgba(0,0,0,0.25)]"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-3 flex items-center gap-2">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-[#FEF2F2]">
                <Trash2 size={20} strokeWidth={2.2} style={{ color: '#DC2626' }} />
              </div>
              <h3 className="m-0 text-[17px] font-extrabold text-[#111827]">플래너 전체삭제</h3>
            </div>
            <p className="m-0 text-[14px] leading-relaxed text-[#374151]">
              현재 화면에 표시된 자료 기반 플래너를 모두 삭제합니다. 이 작업은 되돌릴 수 없습니다.
            </p>
            <p className="mt-2 text-[13px] leading-relaxed text-[#6B7280]">
              수동으로 작성한 플래너와 주간일정은 삭제되지 않습니다.
            </p>
            <div className="mt-3 rounded-xl border border-[#FECACA] bg-[#FEF2F2] px-3.5 py-2.5 text-[13px] font-bold text-[#B91C1C]">
              삭제 대상: {roadmapPlanners.length}개
              {hasManualMixed && (
                <span className="ml-1 font-semibold text-[#9CA3AF]">· 수동 플래너는 제외</span>
              )}
            </div>
            <div className="mt-5 flex justify-end gap-2.5">
              <button
                onClick={() => setShowBulkModal(false)}
                disabled={isDeleting}
                className="inline-flex h-11 items-center rounded-xl border border-[#E5E7EB] bg-white px-5 text-[14px] font-bold text-[#374151] transition hover:bg-[#F9FAFB] disabled:cursor-not-allowed disabled:opacity-60"
              >
                취소
              </button>
              <button
                onClick={handleBulkDelete}
                disabled={isDeleting || roadmapPlanners.length === 0}
                className="inline-flex h-11 items-center gap-2 rounded-xl bg-[#DC2626] px-5 text-[14px] font-extrabold text-white transition hover:bg-[#B91C1C] disabled:cursor-not-allowed disabled:opacity-60"
              >
                <Trash2 size={16} strokeWidth={2.2} style={{ color: '#fff' }} />
                {isDeleting ? '삭제 중…' : '전체삭제'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function SummaryStat({ label, value }) {
  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-[#FAFBFA] px-2.5 py-3 text-center">
      <div className="text-[19px] font-black text-[#15803D]">{value}</div>
      <div className="mt-0.5 text-[11.5px] font-semibold text-[#6B7280]">{label}</div>
    </div>
  );
}

function PreviewRow({ label, value, multi }) {
  return (
    <div className="mb-1.5 grid grid-cols-[60px_1fr] gap-1.5">
      <div className="flex items-center justify-center rounded-md border border-[#E7F1E4] bg-[#F4FBF2] p-1 text-[11px] font-bold text-[#15803D]">{label}</div>
      <div className={`whitespace-pre-wrap rounded-md border border-[#D1D5DB] p-1.5 text-[11px] ${multi ? 'min-h-[40px]' : ''}`}>{value}</div>
    </div>
  );
}
