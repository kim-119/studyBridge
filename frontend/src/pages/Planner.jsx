import React, { useEffect, useMemo, useState } from 'react';
import {
  Plus, Save, Download, Archive, Trash2, NotebookPen, FileText, Clock,
} from 'lucide-react';
import { plannerService } from '../services/api';

const DOW = ['일', '월', '화', '수', '목', '금', '토'];
const HOURS = Array.from({ length: 18 }, (_, i) => i + 6); // 6시 ~ 23시
const SLOTS = ['00', '10', '20', '30', '40', '50'];

const GREEN = '#69CB5B';
const GREEN_DARK = '#15803D';
const GREEN_SOFT = '#F4FBF2';
const GREEN_BORDER = '#E7F1E4';

const blankForm = () => {
  const today = new Date();
  return {
    title: '공부 플래너',
    year: today.getFullYear(),
    month: today.getMonth() + 1,
    day: today.getDate(),
    dayOfWeek: DOW[today.getDay()],
    goalTime: '',
    netStudyTime: '',
    wakeUpTime: '',
    dDay: '',
    subject: '',
    content: '',
    tmi: '',
  };
};

const parseTimeTable = (json) => {
  if (!json) return {};
  try { return JSON.parse(json) || {}; } catch { return {}; }
};

// .lucide 전역 색상(muted)을 덮어쓰기 위해 인라인 color 사용
const inputCls =
  'w-full h-12 box-border rounded-xl border border-[#D1D5DB] px-3.5 text-[14px] text-[#111827] outline-none transition focus:border-[#69CB5B]';
const labelCls = 'mb-1.5 block text-[13px] font-bold text-[#374151]';

export default function Planner() {
  const [form, setForm] = useState(blankForm);
  const [timeTable, setTimeTable] = useState({}); // { hour: [bool x6] }
  const [plannerId, setPlannerId] = useState(null); // null = 새 플래너
  const [saved, setSaved] = useState([]);
  const [busy, setBusy] = useState('');
  const [loadingList, setLoadingList] = useState(true);

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
        goalTime: d.goalTime ?? '',
        netStudyTime: d.netStudyTime ?? '',
        wakeUpTime: d.wakeUpTime ?? '',
        dDay: d.dDay ?? '',
        subject: d.subject ?? '',
        content: d.content ?? '',
        tmi: d.tmi ?? '',
      });
      setTimeTable(parseTimeTable(d.timeTableJson));
      setPlannerId(d.id);
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

  return (
    <div className="min-h-screen bg-[#F6F7F8]">
      <div className="mx-auto max-w-[1200px] px-4 py-6 sm:px-5 lg:px-6">
        {/* 헤더 */}
        <div className="mb-5">
          <h1 className="m-0 text-[24px] font-black text-[#111827]">공부 플래너</h1>
          <p className="mt-1.5 text-[14px] text-[#6B7280]">
            저장본을 불러와 수정하거나 새 플래너를 작성하세요. PDF로 저장하면 자료보관함 &gt; 플래너 탭에서 확인할 수 있습니다.
          </p>
        </div>

        {/* 데스크탑: 좌(목록+폼) / 우(미리보기) · 모바일: 목록 → 폼 → 미리보기 */}
        <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(360px,1.05fr)]">
          {/* ===== 좌측 컬럼: 저장본 목록 + 입력 폼 ===== */}
          <div className="flex flex-col gap-6">
            {/* 저장본 목록 */}
            <section className="rounded-[20px] border border-[#E5E7EB] bg-white p-6 shadow-[0_2px_8px_rgba(0,0,0,0.04)]">
              <div className="mb-4 flex items-center justify-between gap-3">
                <h2 className="m-0 flex items-center gap-2 text-[16px] font-extrabold text-[#111827]">
                  <NotebookPen size={18} strokeWidth={2.2} style={{ color: GREEN_DARK }} />
                  저장된 플래너
                  {saved.length > 0 && (
                    <span className="rounded-full bg-[#F4FBF2] px-2 py-0.5 text-[12px] font-bold text-[#15803D]">{saved.length}</span>
                  )}
                </h2>
                <button
                  onClick={handleNew}
                  className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-[#69CB5B] px-3.5 text-[13px] font-bold text-white transition hover:bg-[#5cb84f]"
                >
                  <Plus size={16} strokeWidth={2.6} style={{ color: '#fff' }} />
                  새 플래너
                </button>
              </div>

              {loadingList ? (
                <div className="py-8 text-center text-[13px] text-[#9CA3AF]">불러오는 중…</div>
              ) : saved.length === 0 ? (
                <div className="flex flex-col items-center gap-2 py-8 text-center">
                  <FileText size={28} strokeWidth={1.8} style={{ color: '#D1D5DB' }} />
                  <p className="m-0 text-[13px] font-semibold text-[#6B7280]">저장된 플래너가 없습니다</p>
                  <p className="m-0 text-[12px] text-[#9CA3AF]">아래에서 플래너를 작성하고 저장해 보세요.</p>
                </div>
              ) : (
                <div className="flex flex-col gap-2">
                  {saved.map((p) => {
                    const active = p.id === plannerId;
                    return (
                      <div
                        key={p.id}
                        onClick={() => handleSelect(p.id)}
                        className={`group flex cursor-pointer items-center gap-3 rounded-xl border px-3.5 py-3 transition ${
                          active
                            ? 'border-[#69CB5B] bg-[#F4FBF2]'
                            : 'border-[#E5E7EB] bg-white hover:border-[#BBF7D0] hover:bg-[#F9FEF8]'
                        }`}
                      >
                        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[#F4FBF2]">
                          <NotebookPen size={16} strokeWidth={2.2} style={{ color: GREEN }} />
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-[14px] font-bold text-[#111827]">{p.title || '공부 플래너'}</div>
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
            <section className="rounded-[20px] border border-[#E5E7EB] bg-white p-6 shadow-[0_2px_8px_rgba(0,0,0,0.04)]">
              <div className="mb-4 flex items-center gap-2">
                <span className={`rounded-full px-2.5 py-1 text-[12px] font-bold ${isEditing ? 'bg-[#FEF3C7] text-[#92400E]' : 'bg-[#F4FBF2] text-[#15803D]'}`}>
                  {isEditing ? `수정 중 · #${plannerId}` : '새 플래너'}
                </span>
              </div>

              <div className="mb-3">
                <label className={labelCls}>플래너 제목</label>
                <input className={inputCls} value={form.title} onChange={(e) => set('title', e.target.value)} />
              </div>

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

              <div className="mb-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
                <div><label className={labelCls}>목표 시간</label><input className={inputCls} placeholder="예: 8시간" value={form.goalTime} onChange={(e) => set('goalTime', e.target.value)} /></div>
                <div><label className={labelCls}>순공부 시간</label><input className={inputCls} placeholder="예: 6시간 30분" value={form.netStudyTime} onChange={(e) => set('netStudyTime', e.target.value)} /></div>
                <div><label className={labelCls}>기상 시간</label><input className={inputCls} placeholder="예: 07:00" value={form.wakeUpTime} onChange={(e) => set('wakeUpTime', e.target.value)} /></div>
                <div><label className={labelCls}>디데이</label><input className={inputCls} placeholder="예: D-30" value={form.dDay} onChange={(e) => set('dDay', e.target.value)} /></div>
              </div>

              <div className="mb-3">
                <label className={labelCls}>과목</label>
                <input className={inputCls} value={form.subject} onChange={(e) => set('subject', e.target.value)} />
              </div>
              <div className="mb-3">
                <label className={labelCls}>내용</label>
                <textarea className={`${inputCls} h-auto min-h-[70px] resize-y py-2.5`} value={form.content} onChange={(e) => set('content', e.target.value)} />
              </div>

              {/* 10분 단위 시간 체크표 */}
              <div className="mb-3">
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

              <div className="mb-4">
                <label className={labelCls}>오늘의 TMI</label>
                <textarea className={`${inputCls} h-auto min-h-[60px] resize-y py-2.5`} value={form.tmi} onChange={(e) => set('tmi', e.target.value)} />
              </div>

              <div className="flex flex-wrap gap-2.5">
                <button onClick={handleSave} disabled={!!busy}
                  className="inline-flex h-12 items-center gap-2 rounded-xl bg-[#69CB5B] px-5 text-[14px] font-extrabold text-white transition hover:bg-[#5cb84f] disabled:cursor-not-allowed disabled:opacity-60">
                  <Save size={17} strokeWidth={2.2} style={{ color: '#fff' }} />
                  {busy === 'save' ? '저장 중…' : (isEditing ? '수정 저장' : '플래너 생성')}
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
              </div>
            </section>
          </div>

          {/* ===== 우측 컬럼: A4 세로 미리보기 ===== */}
          <div className="lg:sticky lg:top-[96px]">
            <section className="rounded-[20px] border border-[#E5E7EB] bg-white p-6 shadow-[0_2px_8px_rgba(0,0,0,0.04)]">
              <div className="mb-3 text-[13px] font-bold text-[#6B7280]">A4 미리보기</div>
              <div className="flex justify-center">
                <div
                  className="w-full max-w-[480px] overflow-auto rounded-md border border-[#E5E7EB] bg-white p-6"
                  style={{ aspectRatio: '210 / 297', boxShadow: '0 10px 30px rgba(0,0,0,0.10)' }}
                >
                  <div className="text-[20px] font-black text-[#15803D]">{form.title || '공부 플래너'}</div>
                  <div className="mb-3.5 mt-1 text-[12px] text-[#4B5563]">
                    {form.year || '____'}년 {form.month || '__'}월 {form.day || '__'}일 ({form.dayOfWeek})
                  </div>

                  <div className="mb-3.5 grid grid-cols-4 gap-1.5">
                    {[['목표 시간', form.goalTime], ['순공부', form.netStudyTime], ['기상', form.wakeUpTime], ['디데이', form.dDay]].map(([l, v]) => (
                      <div key={l} className="rounded-md border border-[#E7F1E4] p-1.5">
                        <div className="text-[9px] font-bold text-[#15803D]">{l}</div>
                        <div className="text-[12px] font-extrabold">{v || '-'}</div>
                      </div>
                    ))}
                  </div>

                  <PreviewRow label="과목" value={form.subject} />
                  <PreviewRow label="내용" value={form.content} multi />

                  <div className="my-3 text-[12px] font-extrabold text-[#15803D]">시간 체크표</div>
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

                  <div className="my-3 text-[12px] font-extrabold text-[#15803D]">오늘의 TMI</div>
                  <div className="min-h-[50px] whitespace-pre-wrap rounded-md border border-[#D1D5DB] p-1.5 text-[11px]">{form.tmi}</div>
                </div>
              </div>
            </section>
          </div>
        </div>
      </div>
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
