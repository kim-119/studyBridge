import React, { useState, useEffect, useRef } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  FileText, File as FileIcon, Plus, X, AlignLeft, MessageSquare, CalendarDays,
  Folder as FolderIcon, FolderPlus, MoreVertical, ChevronRight, ArrowLeft, Upload, Check,
} from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import { materialService, folderService } from '../services/api';
import { sanitizeMarkdownText, sanitizeList } from '../utils/markdown';

// 의미 없는 제목 차단 — 저장 요청을 보내기 전에 막는다.
const BLOCKED_TITLES = ['', ' ', 'ㅇㅇ', 'ㅎㅎ', 'test', 'sample', 'planner', '플래너', '무제', '제목 없음'];
const TITLE_GUIDE = '제목은 핵심 키워드가 드러나게 입력해 주세요. 예: ViewModel·StateFlow 피드백 수렴 플래너';
function isMeaninglessTitle(raw) {
  const t = (raw || '').trim();
  if (!t) return true;
  const low = t.toLowerCase();
  return BLOCKED_TITLES.some((b) => b.trim().toLowerCase() === low);
}

// 업로드 전 AI 유형 판별(classify-before-save) 사용 여부 — 기본 OFF.
const CLASSIFY_BEFORE_SAVE_ENABLED =
  String(import.meta.env.VITE_MATERIAL_CLASSIFY_ENABLED || '').toLowerCase() === 'true';

// ── 플래너/PDF 표시 제목 유틸 (프론트 표시 전용, DB title 은 변경하지 않음) ───────────────
const UUID_PREFIX = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}_/;
const MEANINGLESS_PLANNER_TITLES = new Set(
  ['공부 플래너', '플래너', 'ㅇㅇ', 'ㅎㅎ', '무제', '제목 없음', '이름 없음', 'planner', 'sample', 'test']
);

function cleanText(s) {
  return String(s || '').replace(UUID_PREFIX, '').trim();
}

function toKeywordArray(kw) {
  if (Array.isArray(kw)) return kw.map((k) => String(k).trim()).filter(Boolean);
  if (typeof kw === 'string') return kw.split(',').map((k) => k.trim()).filter(Boolean);
  return [];
}

function getPlannerWeekNumber(material) {
  if (material == null) return null;
  const direct = material.weekNumber;
  if (direct != null && !Number.isNaN(Number(direct))) return Number(direct);
  let meta = material.metadata ?? material.plannerMetadataJson ?? null;
  if (typeof meta === 'string') { try { meta = JSON.parse(meta); } catch { meta = null; } }
  if (meta && meta.weekNumber != null && !Number.isNaN(Number(meta.weekNumber))) {
    return Number(meta.weekNumber);
  }
  const title = cleanText(material.rawTitle || material.title);
  const w = title.match(/(\d+)\s*주차/);
  if (w) return Number(w[1]);
  const d = title.match(/(\d+)\s*일차/);
  if (d) return Number(d[1]);
  return null;
}

function getPlannerKeywordTitle(material) {
  if (material == null) return '핵심 키워드 미설정';
  const kws = toKeywordArray(material.keywords);
  if (kws.length) return kws.slice(0, 4).join(' ');
  const title = cleanText(material.rawTitle || material.title);
  const stripped = title.replace(/^\s*\d+\s*(주차|일차)\s*[:\-–~]?\s*/, '').trim();
  if (stripped && !MEANINGLESS_PLANNER_TITLES.has(stripped) && !MEANINGLESS_PLANNER_TITLES.has(stripped.toLowerCase())) {
    return stripped;
  }
  const fname = cleanText(material.originalFileName).replace(/\.[^.]+$/, '').trim();
  if (fname && !MEANINGLESS_PLANNER_TITLES.has(fname) && !MEANINGLESS_PLANNER_TITLES.has(fname.toLowerCase())) {
    return fname;
  }
  return '핵심 키워드 미설정';
}

function getPlannerDisplayTitle(material) {
  const week = getPlannerWeekNumber(material);
  const kw = getPlannerKeywordTitle(material);
  return week != null ? `${week}주차 - ${kw}` : kw;
}

// 자료 카드 표시 제목 (타입별)
function getMaterialDisplayTitle(m) {
  if (m.materialType === 'PLANNER') return getPlannerDisplayTitle(m);
  const t = cleanText(m.title || m.originalFileName || '이름 없음');
  return t || '이름 없음';
}

// 타입별 배지/썸네일 메타
const TYPE_META = {
  STUDY_LOG: { label: '학습일지', Icon: FileText, badge: 'doc-badge-journal' },
  PDF: { label: 'PDF', Icon: FileIcon, badge: 'doc-badge-pdf' },
  PLANNER: { label: '플래너', Icon: CalendarDays, badge: 'doc-badge-planner' },
};

function materialDate(m) {
  if (m.uploadedAt) return String(m.uploadedAt).split('T')[0];
  if (m.studyDate) return String(m.studyDate);
  return '';
}

// 상단 유형 필터 탭 (폴더는 모든 탭에서 표시, 자료만 유형별 필터)
// '전체' 탭 제거 — 학습자료 / 플래너 / 학습일지 3개만 유지. 기본 진입 = 학습자료.
const ARCHIVE_TABS = [
  { key: 'LEARNING_PDF', label: '학습자료' },
  { key: 'PLANNER', label: '플래너' },
  { key: 'STUDY_LOG', label: '학습일지' },
];
const ARCHIVE_TAB_KEYS = ARCHIVE_TABS.map((t) => t.key);
const DEFAULT_ARCHIVE_TAB = 'LEARNING_PDF';
// 레거시 값('ALL'/'all' 등)이나 알 수 없는 값은 학습자료로 폴백.
function normalizeArchiveTab(value) {
  return ARCHIVE_TAB_KEYS.includes(value) ? value : DEFAULT_ARCHIVE_TAB;
}

// 탭 키 → 백엔드 문서 도메인(canonical). 폴더/자료/조회/생성에 모두 같은 기준 사용.
const TAB_TO_DOMAIN = {
  LEARNING_PDF: 'LEARNING_MATERIAL',
  PLANNER: 'PLANNER',
  STUDY_LOG: 'STUDY_JOURNAL',
};
function domainForTab(tabKey) {
  return TAB_TO_DOMAIN[normalizeArchiveTab(tabKey)] || 'LEARNING_MATERIAL';
}

// 자료(material)의 유형을 탭 키로 매핑. materialType 우선, 없으면 제목/파일명 보조 판별.
function materialTabKind(m) {
  const raw = String(m.materialType ?? m.type ?? m.sourceType ?? m.category ?? '').toUpperCase();
  if (raw.includes('PLANNER') || raw.includes('PLAN') || raw.includes('SCHEDULE')) return 'PLANNER';
  if (raw.includes('STUDY_LOG') || raw.includes('LEARNING_LOG') || raw.includes('JOURNAL') || raw.includes('DIARY')) return 'STUDY_LOG';
  if (raw.includes('PDF') || raw.includes('MATERIAL') || raw.includes('DOCUMENT')) return 'LEARNING_PDF';
  const title = String(m.title ?? m.originalFileName ?? '').toLowerCase();
  if (title.endsWith('.pdf')) return 'LEARNING_PDF';
  return 'LEARNING_PDF'; // 알 수 없는 파일 자료는 학습PDF 탭에 노출(누락 방지)
}

// 폴더 전체 목록에서 특정 폴더의 자기+하위 id 집합 (이동 시 순환 후보 제외용)
function descendantIds(allFolders, rootId) {
  const childrenMap = {};
  allFolders.forEach((f) => {
    const p = f.parentId == null ? 'root' : f.parentId;
    (childrenMap[p] = childrenMap[p] || []).push(f);
  });
  const result = new Set([rootId]);
  const stack = [rootId];
  while (stack.length) {
    const cur = stack.pop();
    (childrenMap[cur] || []).forEach((c) => {
      if (!result.has(c.folderId)) { result.add(c.folderId); stack.push(c.folderId); }
    });
  }
  return result;
}

// 폴더 경로 라벨 ("홈 > a > b") — 이동 대상 select 표시용
function folderPathLabel(allFolders, folderId) {
  const byId = {};
  allFolders.forEach((f) => { byId[f.folderId] = f; });
  const parts = [];
  let cursor = folderId;
  let guard = 0;
  while (cursor != null && guard++ < 1000) {
    const f = byId[cursor];
    if (!f) break;
    parts.unshift(f.name);
    cursor = f.parentId;
  }
  return ['홈', ...parts].join(' > ');
}

export default function Archive() {
  const { userId } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const folderIdParam = searchParams.get('folderId');
  const currentFolderId = folderIdParam != null && folderIdParam !== '' ? Number(folderIdParam) : null;

  // 폴더 뷰 상태
  const [folders, setFolders] = useState([]);
  const [materials, setMaterials] = useState([]);
  const [breadcrumb, setBreadcrumb] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState('');

  // UI 상태
  const [activeArchiveTab, setActiveArchiveTab] = useState(DEFAULT_ARCHIVE_TAB); // LEARNING_PDF | PLANNER | STUDY_LOG
  const [sortMode, setSortMode] = useState('recent'); // 'recent' | 'name'
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedKeys, setSelectedKeys] = useState(new Set());
  const [openMenuKey, setOpenMenuKey] = useState(null); // ⋮ / 신규 메뉴

  // 모달 상태
  const [openedModalType, setOpenedModalType] = useState(null); // 'addMaterial'
  const [createFolderOpen, setCreateFolderOpen] = useState(false);
  const [createFolderName, setCreateFolderName] = useState('');
  const [renameState, setRenameState] = useState(null); // {kind, id, name}
  const [moveState, setMoveState] = useState(null); // {kind, id, name, targetId, options}

  // 자료 추가(업로드) 폼 상태
  const [addMaterialType, setAddMaterialType] = useState('pdf');
  const [classifyInfo, setClassifyInfo] = useState(null);
  const [formTitle, setFormTitle] = useState('');
  const [formDate, setFormDate] = useState(new Date().toISOString().split('T')[0]);
  const [formKeywords, setFormKeywords] = useState('');
  const [formContent, setFormContent] = useState('');
  const [formNextPlan, setFormNextPlan] = useState('');
  const [formFile, setFormFile] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const addFileInputRef = useRef(null);

  // 학습일지 모달 상태
  const [selectedJournal, setSelectedJournal] = useState(null);
  const [isJournalEditMode, setIsJournalEditMode] = useState(false);
  const [editTitle, setEditTitle] = useState('');
  const [editDate, setEditDate] = useState('');
  const [editKeywords, setEditKeywords] = useState('');
  const [editContent, setEditContent] = useState('');
  const [editNextPlan, setEditNextPlan] = useState('');
  const [journalSummary, setJournalSummary] = useState('');
  const [journalFeedback, setJournalFeedback] = useState([]);
  const [journalFeedbackStruct, setJournalFeedbackStruct] = useState(null);
  const [regeneratingFeedback, setRegeneratingFeedback] = useState(false);

  const checkAuth = () => {
    if (!userId) {
      alert('로그인이 필요한 기능입니다. 로그인 페이지로 이동합니다.');
      navigate('/login');
      return false;
    }
    return true;
  };

  // 현재 탭의 canonical 문서 도메인(학습자료/플래너/학습일지). 모든 조회/생성에 동일 기준 사용.
  const activeDocumentDomain = domainForTab(activeArchiveTab);

  // ── 폴더 뷰 데이터 로드 ─────────────────────────────────────────────
  const fetchItems = async () => {
    if (!userId) return;
    try {
      setIsLoading(true);
      setLoadError('');
      const data = await materialService.getArchiveItems(currentFolderId, activeDocumentDomain);
      // 방어: 서버가 도메인 필터링하지만, 혹시 섞여오면 현재 도메인 외 항목은 렌더 제외(+개발 경고).
      const okFolders = (Array.isArray(data?.folders) ? data.folders : []).filter((f) => {
        if (f?.domain && f.domain !== activeDocumentDomain) {
          if (import.meta.env.DEV) console.warn('[Archive] 도메인 불일치 폴더 제외', f.domain, activeDocumentDomain, f);
          return false;
        }
        return true;
      });
      setFolders(okFolders);
      setMaterials(Array.isArray(data?.materials) ? data.materials : []);
      setBreadcrumb(Array.isArray(data?.breadcrumb) ? data.breadcrumb : []);
    } catch (error) {
      console.error('자료보관함 조회 실패:', error);
      setLoadError(error.response?.data?.message || '자료 목록을 불러오지 못했습니다. 다시 시도해주세요.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (userId) {
      setSelectionMode(false);
      setSelectedKeys(new Set());
      setOpenMenuKey(null);
      fetchItems();
    } else {
      setFolders([]);
      setMaterials([]);
      setBreadcrumb([]);
    }
    // activeArchiveTab 포함 → 탭 전환 시(루트에 머물러도) 해당 도메인으로 재조회.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId, currentFolderId, activeArchiveTab]);

  // 다른 화면 갔다가 돌아오면 서버 기준 재조회
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === 'visible' && userId) fetchItems();
    };
    document.addEventListener('visibilitychange', onVisible);
    window.addEventListener('focus', onVisible);
    return () => {
      document.removeEventListener('visibilitychange', onVisible);
      window.removeEventListener('focus', onVisible);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId, currentFolderId]);

  // 메뉴 바깥 클릭 시 닫기 — 풀스크린 오버레이 대신 document 리스너(오버레이가 메뉴 클릭을 가로채는 문제 방지)
  useEffect(() => {
    if (!openMenuKey) return;
    const onDocMouseDown = (e) => {
      if (e.target.closest('.doc-menu') || e.target.closest('.doc-more') || e.target.closest('.doc-new')) return;
      setOpenMenuKey(null);
    };
    document.addEventListener('mousedown', onDocMouseDown);
    return () => document.removeEventListener('mousedown', onDocMouseDown);
  }, [openMenuKey]);

  // ── 네비게이션 ─────────────────────────────────────────────────────
  const openFolder = (folderId) => {
    setOpenMenuKey(null);
    setSelectionMode(false);
    setSelectedKeys(new Set());
    if (folderId == null) setSearchParams({});
    else setSearchParams({ folderId: String(folderId) });
  };

  const goBack = () => {
    if (breadcrumb.length <= 1) openFolder(null);
    else openFolder(breadcrumb[breadcrumb.length - 2].folderId);
  };

  // ── 자료 클릭: 타입별 분기 (폴더는 절대 자료 상세/AI 로 가지 않음) ─────
  //  라우팅을 이 한 함수로 단일화한다(타입별 분기 분산 금지).
  //   - STUDY_LOG → 학습일지 모달
  //   - PLANNER / PDF → /archive/pdf/:materialId 분할뷰 상세
  //  플래너/PDF 모두 같은 상세 라우트로 들어가고, 좌측 PDF 뷰어 + 우측 패널(요약·체크리스트 등)은
  //  ArchiveDetail 이 서버 응답의 materialType(PLANNER 여부)로 결정한다. 따라서 state.item 은 첫 페인트
  //  최적화일 뿐이며, 새 PC·시크릿·캐시 없는 환경에서도 서버 기준으로 동일하게 열린다.
  const openMaterial = (m) => {
    if (!checkAuth()) return;
    const kind = String(m.materialType || '').toUpperCase();
    if (kind === 'STUDY_LOG') {
      const journal = {
        id: m.materialId,
        title: m.title || '제목 없음',
        date: materialDate(m),
        tag: '학습일지',
        keywords: m.keywords ? m.keywords.split(',').map((k) => k.trim()).filter(Boolean) : [],
        content: m.learningContent || '',
        nextPlan: m.nextPlan || '',
      };
      setSelectedJournal(journal);
      setEditTitle(journal.title);
      setEditDate(journal.date);
      setEditKeywords(journal.keywords.join(', '));
      setEditContent(journal.content);
      setEditNextPlan(journal.nextPlan);
      setIsJournalEditMode(false);
      fetchJournalAiData(journal.id);
      return;
    }
    // PLANNER 와 PDF → 분할뷰 상세(서버 materialType 으로 우측 패널 결정). materialId 를 canonical id 로 사용.
    navigate(`/archive/pdf/${m.materialId}`, { state: { item: m } });
  };

  // ── 학습일지 AI 데이터 (모달) ────────────────────────────────────────
  const normalizeFeedback = (raw) => {
    if (!raw) return { struct: null, lines: [] };
    let obj = null;
    try { obj = JSON.parse(raw); } catch { obj = null; }
    if (obj && typeof obj === 'object' && !Array.isArray(obj) &&
        (obj.strengths || obj.recommendations || obj.concerns || obj.summary || obj.feedback_balance)) {
      return {
        struct: {
          title: sanitizeMarkdownText(obj.feedback_title || 'AI 학습 피드백'),
          summary: sanitizeMarkdownText(obj.summary || obj.feedbackData || ''),
          strengths: sanitizeList(obj.strengths),
          recommendations: sanitizeList(obj.recommendations),
          concerns: sanitizeList(obj.concerns),
          nextActions: sanitizeList(obj.next_actions),
          balance: obj.feedback_balance || null,
        },
        lines: [],
      };
    }
    const text = Array.isArray(obj) ? obj.map(String).join('\n') : String(raw);
    const lines = sanitizeMarkdownText(text)
      .split(/\n+/).map((l) => l.replace(/^\s*\d+[.)]\s*/, '').trim()).filter(Boolean);
    return { struct: null, lines: lines.length ? lines : ['아직 등록된 AI 피드백이 없습니다. 잠시 후 다시 확인해주세요.'] };
  };

  const fetchJournalAiData = async (materialId) => {
    try {
      setJournalSummary('AI가 학습일지를 분석 중입니다...');
      setJournalFeedback([]);
      setJournalFeedbackStruct(null);

      const summaryRes = await materialService.getSummary(materialId);
      if (summaryRes && summaryRes.overview) {
        setJournalSummary(sanitizeMarkdownText(summaryRes.overview));
      } else {
        setJournalSummary('작성된 학습일지를 바탕으로 분석된 AI 요약이 아직 생성되지 않았습니다.');
      }

      const feedbackRes = await materialService.getFeedback(materialId);
      const norm = normalizeFeedback(feedbackRes?.feedbackData);
      setJournalFeedbackStruct(norm.struct);
      setJournalFeedback(norm.lines);
    } catch (error) {
      console.error('AI 분석 정보 조회 실패:', error);
      setJournalSummary('AI 요약을 가져오는 도중 오류가 발생했습니다.');
      setJournalFeedbackStruct(null);
      setJournalFeedback(['AI 피드백 정보를 불러오지 못했습니다.']);
    }
  };

  const handleRegenerateFeedback = async () => {
    if (regeneratingFeedback || !selectedJournal?.id) return;
    try {
      setRegeneratingFeedback(true);
      const feedbackRes = await materialService.regenerateFeedback(selectedJournal.id);
      const norm = normalizeFeedback(feedbackRes?.feedbackData);
      setJournalFeedbackStruct(norm.struct);
      setJournalFeedback(norm.lines);
    } catch (e) {
      // 진단을 위해 status / 요청 URL / 응답 본문을 함께 남긴다(기존 피드백 화면은 유지).
      console.error('피드백 재생성 실패:', {
        status: e.response?.status,
        url: e.config?.url,
        data: e.response?.data,
        message: e.message,
      });
      alert(e.response?.data?.message || '피드백 재생성 중 오류가 발생했습니다.');
    } finally {
      setRegeneratingFeedback(false);
    }
  };

  const FB_SECTIONS = [
    { key: 'strengths', label: '장점', color: '#10B981' },
    { key: 'recommendations', label: '권장사항', color: '#3B82F6' },
    { key: 'concerns', label: '우려사항 / 비판적 개선점', color: '#F59E0B' },
    { key: 'nextActions', label: '다음 행동', color: '#8B5CF6' },
  ];
  const fbWarn = (msg) => (
    <div style={{ padding: '12px 14px', borderRadius: '8px', backgroundColor: '#FFFBEB', border: '1px solid #FDE68A', color: '#92400E', fontSize: '13.5px', lineHeight: 1.6 }}>{msg}</div>
  );
  const renderFeedbackBody = () => {
    const s = journalFeedbackStruct;
    if (s) {
      const insufficient = s.strengths.length < 8 || s.recommendations.length < 8 || s.concerns.length < 8;
      const strengthOnly = s.strengths.length > 0 && s.recommendations.length === 0 && s.concerns.length === 0;
      return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {strengthOnly && fbWarn('AI 피드백이 장점 위주로 생성되었습니다. 권장사항과 우려사항을 포함해 다시 생성해 주세요.')}
          {!strengthOnly && insufficient && fbWarn('AI 피드백이 충분하지 않습니다. 다시 생성해 주세요.')}
          {s.summary && (
            <div style={{ padding: '14px 16px', borderRadius: '10px', backgroundColor: '#F9FAFB', borderLeft: '4px solid var(--color-primary)' }}>
              <div style={{ fontWeight: 700, fontSize: '14px', marginBottom: '6px', color: 'var(--color-text-main)' }}>전체 요약</div>
              <p style={{ margin: 0, fontSize: '14px', lineHeight: 1.6, color: 'var(--color-text-main)' }}>{s.summary}</p>
            </div>
          )}
          {FB_SECTIONS.map((sec) => {
            const list = s[sec.key] || [];
            if (!list.length) return null;
            return (
              <div key={sec.key}>
                <h4 style={{ margin: '0 0 8px', fontSize: '14.5px', color: 'var(--color-text-main)', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: sec.color }} /> {sec.label} <span style={{ fontSize: '12px', color: 'var(--color-text-muted)', fontWeight: 400 }}>({list.length}개)</span>
                </h4>
                <ul style={{ margin: 0, paddingLeft: '18px', display: 'flex', flexDirection: 'column', gap: '6px', borderLeft: `3px solid ${sec.color}22` }}>
                  {list.map((t, i) => <li key={i} style={{ fontSize: '13.5px', lineHeight: 1.6, color: 'var(--color-text-main)' }}>{t}</li>)}
                </ul>
              </div>
            );
          })}
        </div>
      );
    }
    const joined = journalFeedback.join(' ');
    const hasNeg = /(개선|아쉬|부족|권장|주의|우려|보완|위험|문제|보강|한계)/.test(joined);
    const strengthOnly = journalFeedback.length > 1 && !hasNeg;
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        {strengthOnly && fbWarn('AI 피드백이 장점 위주로 생성되었습니다. 권장사항과 우려사항을 포함해 “균형 잡힌 피드백 다시 생성”을 눌러주세요.')}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          {journalFeedback.map((fb, idx) => (
            <div key={idx} style={{ display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
              <div style={{ width: '24px', height: '24px', borderRadius: '50%', backgroundColor: 'var(--color-primary)', color: 'white', display: 'flex', justifyContent: 'center', alignItems: 'center', fontSize: '12px', fontWeight: 'bold', flexShrink: 0 }}>{idx + 1}</div>
              <p style={{ margin: 0, fontSize: '14px', lineHeight: '1.5', color: 'var(--color-text-main)' }}>{fb}</p>
            </div>
          ))}
        </div>
      </div>
    );
  };

  const handleUpdateJournal = async () => {
    if (!checkAuth()) return;
    if (!editTitle.trim()) { alert('제목을 입력해주세요.'); return; }
    try {
      await materialService.updateMaterial(selectedJournal.id, { title: editTitle, keywords: editKeywords });
      alert('학습일지가 수정되었습니다.');
      setIsJournalEditMode(false);
      fetchItems();
      setSelectedJournal((prev) => ({
        ...prev,
        title: editTitle,
        keywords: editKeywords.split(',').map((k) => k.trim()).filter(Boolean),
      }));
    } catch (error) {
      console.error('학습일지 수정 실패:', error);
      alert('수정 도중 오류가 발생했습니다.');
    }
  };

  // ── 자료 추가(업로드) ───────────────────────────────────────────────
  const resetFormState = () => {
    setFormTitle('');
    setFormDate(new Date().toISOString().split('T')[0]);
    setFormKeywords('');
    setFormContent('');
    setFormNextPlan('');
    setFormFile(null);
  };

  const openAddMaterial = () => {
    if (!checkAuth()) return;
    setOpenMenuKey(null);
    setAddMaterialType('pdf');
    resetFormState();
    setOpenedModalType('addMaterial');
  };

  const closeModal = () => {
    setOpenedModalType(null);
    resetFormState();
  };

  const handlePickUploadFile = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const name = (file.name || '').toLowerCase();
    if (name.endsWith('.doc') && !name.endsWith('.docx')) {
      alert('현재는 .docx 형식만 지원합니다. .doc 파일은 .docx로 변환 후 업로드해주세요.');
      e.target.value = ''; setFormFile(null); return;
    }
    if (!name.endsWith('.pdf') && !name.endsWith('.docx')) {
      alert('지원하지 않는 파일 형식입니다. PDF 또는 DOCX 파일만 업로드할 수 있습니다.');
      e.target.value = ''; setFormFile(null); return;
    }
    setFormFile(file);
  };

  const AI_TO_ENUM = { STUDY_PDF: 'PDF', PLANNER: 'PLANNER', WRONG_NOTE: 'REVIEW_NOTE', STUDY_LOG: 'STUDY_LOG' };

  // 실제 업로드 — 현재 폴더(currentFolderId)에 저장. 루트면 null.
  const doUpload = async (enumType) => {
    try {
      setIsSubmitting(true);
      await materialService.uploadMaterial(formTitle, enumType, formKeywords, formFile, currentFolderId);
      alert(enumType === 'PLANNER' ? '플래너 PDF가 등록되었습니다.'
        : '자료 업로드가 시작되었습니다. AI가 문서를 분석하는 데 수 분이 걸릴 수 있습니다.');
      setClassifyInfo(null);
      closeModal();
      await fetchItems();
    } catch (error) {
      console.error('자료 업로드 실패:', error);
      alert(error.response?.data?.message || '자료 업로드 중 오류가 발생했습니다.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSubmitMaterial = async () => {
    if (!checkAuth()) return;
    if (isMeaninglessTitle(formTitle)) { alert(TITLE_GUIDE); return; }

    // 학습일지 — 파일 없음. 현재 폴더에 저장.
    if (addMaterialType === 'journal') {
      setIsSubmitting(true);
      try {
        await materialService.createStudyLog({
          title: formTitle,
          keywords: formKeywords,
          studyDate: formDate || new Date().toISOString().split('T')[0],
          learningContent: formContent,
          nextPlan: formNextPlan,
          folderId: currentFolderId,
        });
        alert('학습일지가 등록되었습니다.');
        closeModal();
        await fetchItems();
      } catch (error) {
        console.error('학습일지 등록 실패:', error);
        alert(error.response?.data?.message || '학습일지 등록 중 오류가 발생했습니다.');
      } finally {
        setIsSubmitting(false);
      }
      return;
    }

    if (!formFile) { alert('업로드할 파일을 선택해주세요.'); return; }

    const selectedAi = addMaterialType === 'planner' ? 'PLANNER' : 'STUDY_PDF';
    setIsSubmitting(true);
    try {
      if (CLASSIFY_BEFORE_SAVE_ENABLED) {
        let cls = null;
        try {
          cls = await materialService.classifyBeforeSave(selectedAi, formTitle, formKeywords, formFile);
        } catch (e) {
          console.warn('유형 판별 호출 실패, 선택 유형으로 진행:', e);
        }
        const recommended = cls?.recommendedType;
        if (cls?.isMismatch && recommended && recommended !== selectedAi) {
          setClassifyInfo({ ...cls, selectedAi });
          return;
        }
      }
      const UPLOAD_ENUM = { planner: 'PLANNER' };
      await doUpload(UPLOAD_ENUM[addMaterialType] || 'PDF');
    } finally {
      setIsSubmitting(false);
    }
  };

  const confirmClassifySave = (aiType) => {
    if (aiType === 'CANCEL') { setClassifyInfo(null); return; }
    doUpload(AI_TO_ENUM[aiType] || 'PDF');
  };

  // ── 폴더 생성 / 이름변경 / 삭제 / 이동 ────────────────────────────────
  const openCreateFolder = () => {
    if (!checkAuth()) return;
    setOpenMenuKey(null);
    setCreateFolderName('');
    setCreateFolderOpen(true);
  };

  const handleCreateFolder = async () => {
    const name = createFolderName.trim();
    if (!name) { alert('폴더 이름을 입력해주세요.'); return; }
    try {
      setIsSubmitting(true);
      // 현재 탭 도메인을 명시 전달 → 학습자료/플래너/학습일지 폴더가 각자 탭에만 보이도록.
      await folderService.createFolder(name, currentFolderId, activeDocumentDomain);
      setCreateFolderOpen(false);
      setCreateFolderName('');
      await fetchItems();
    } catch (error) {
      console.error('폴더 생성 실패:', error);
      alert(error.response?.data?.message || '폴더 생성 중 오류가 발생했습니다.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDeleteFolder = async (folder) => {
    setOpenMenuKey(null);
    if (!window.confirm(`'${folder.name}' 폴더를 삭제하시겠습니까?`)) return;
    try {
      await folderService.deleteFolder(folder.folderId);
      await fetchItems();
    } catch (error) {
      console.error('폴더 삭제 실패:', error);
      alert(error.response?.data?.message || '폴더 삭제 중 오류가 발생했습니다.');
    }
  };

  const handleDeleteMaterial = async (m) => {
    setOpenMenuKey(null);
    if (!window.confirm('정말로 이 자료를 삭제하시겠습니까? 삭제 후에는 복구할 수 없습니다.')) return;
    try {
      await materialService.deleteMaterial(m.materialId);
      await fetchItems();
    } catch (error) {
      console.error('자료 삭제 실패:', error);
      alert(error.response?.data?.message || '자료 삭제 중 오류가 발생했습니다.');
    }
  };

  const openRename = (kind, item) => {
    setOpenMenuKey(null);
    if (kind === 'folder') setRenameState({ kind, id: item.folderId, name: item.name });
    else setRenameState({ kind, id: item.materialId, name: getMaterialDisplayTitle(item) });
  };

  const handleRenameSubmit = async () => {
    const name = (renameState?.name || '').trim();
    if (!name) { alert('이름을 입력해주세요.'); return; }
    try {
      setIsSubmitting(true);
      if (renameState.kind === 'folder') {
        await folderService.renameFolder(renameState.id, name);
      } else {
        await materialService.updateMaterial(renameState.id, { title: name });
      }
      setRenameState(null);
      await fetchItems();
    } catch (error) {
      console.error('이름 변경 실패:', error);
      alert(error.response?.data?.message || '이름 변경 중 오류가 발생했습니다.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const openMove = async (kind, item) => {
    setOpenMenuKey(null);
    try {
      const all = await folderService.listFolders();
      // 같은 도메인(현재 탭) 폴더로만 이동 가능 — 탭 간 자료 혼입 방지. 레거시(null)=학습자료.
      const allFolders = (Array.isArray(all) ? all : [])
        .filter((f) => (f?.domain || 'LEARNING_MATERIAL') === activeDocumentDomain);
      let candidates = allFolders;
      if (kind === 'folder') {
        const excluded = descendantIds(allFolders, item.folderId); // 자기+하위 제외(순환 방지)
        candidates = allFolders.filter((f) => !excluded.has(f.folderId));
      }
      const options = [
        { value: '', label: '홈 (최상위)' },
        ...candidates.map((f) => ({ value: String(f.folderId), label: folderPathLabel(allFolders, f.folderId) })),
      ];
      setMoveState({
        kind,
        id: kind === 'folder' ? item.folderId : item.materialId,
        name: kind === 'folder' ? item.name : getMaterialDisplayTitle(item),
        targetId: '',
        options,
      });
    } catch (error) {
      console.error('폴더 목록 조회 실패:', error);
      alert('폴더 목록을 불러오지 못했습니다.');
    }
  };

  const handleMoveSubmit = async () => {
    if (!moveState) return;
    const target = moveState.targetId === '' ? null : Number(moveState.targetId);
    try {
      setIsSubmitting(true);
      if (moveState.kind === 'folder') {
        await folderService.moveFolder(moveState.id, target);
      } else {
        await materialService.moveMaterial(moveState.id, target);
      }
      setMoveState(null);
      await fetchItems();
    } catch (error) {
      console.error('이동 실패:', error);
      alert(error.response?.data?.message || '이동 중 오류가 발생했습니다.');
    } finally {
      setIsSubmitting(false);
    }
  };

  // ── 선택 모드 ───────────────────────────────────────────────────────
  const toggleSelectionMode = () => {
    setOpenMenuKey(null);
    setSelectionMode((prev) => {
      if (prev) setSelectedKeys(new Set());
      return !prev;
    });
  };

  const toggleSelect = (key) => {
    setSelectedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };

  const handleBulkDelete = async () => {
    if (selectedKeys.size === 0) return;
    if (!window.confirm(`선택한 ${selectedKeys.size}개 항목을 삭제하시겠습니까?`)) return;
    let blocked = 0;
    for (const key of selectedKeys) {
      const [kind, idStr] = key.split('-');
      const id = Number(idStr);
      try {
        if (kind === 'folder') await folderService.deleteFolder(id);
        else await materialService.deleteMaterial(id);
      } catch (e) {
        if (kind === 'folder' && e.response?.status === 409) blocked++;
        else console.error('삭제 실패:', e);
      }
    }
    setSelectedKeys(new Set());
    setSelectionMode(false);
    await fetchItems();
    if (blocked > 0) alert('폴더 안에 자료가 있어 삭제할 수 없습니다. (비어 있지 않은 폴더는 건너뛰었습니다.)');
  };

  // ── 정렬 + 탭 필터 ──────────────────────────────────────────────────
  const sortedFolders = [...folders].sort((a, b) =>
    sortMode === 'name'
      ? a.name.localeCompare(b.name, 'ko')
      : String(b.createdAt || '').localeCompare(String(a.createdAt || '')));

  const sortedMaterials = [...materials].sort((a, b) =>
    sortMode === 'name'
      ? getMaterialDisplayTitle(a).localeCompare(getMaterialDisplayTitle(b), 'ko')
      : String(b.uploadedAt || '').localeCompare(String(a.uploadedAt || '')));

  // 상단 탭 필터: 선택 탭 유형만 표시(레거시/오류 값은 학습자료로 폴백). 폴더는 탭과 무관하게 항상 표시.
  const effectiveTab = normalizeArchiveTab(activeArchiveTab);
  const visibleMaterials = sortedMaterials.filter((m) => materialTabKind(m) === effectiveTab);

  const isEmpty = !isLoading && !loadError && sortedFolders.length === 0 && visibleMaterials.length === 0;

  return (
    <div className="container-main archive-page">
      {/* 상단 헤더: 제목 + 도구(선택/정렬) */}
      <div className="doc-header">
        <h2 className="doc-title">문서</h2>
        <div className="doc-toolbar">
          {selectionMode && (
            <button className="doc-tool-btn danger" onClick={handleBulkDelete} disabled={selectedKeys.size === 0}>
              삭제 ({selectedKeys.size})
            </button>
          )}
          <button className={`doc-tool-btn ${selectionMode ? 'active' : ''}`} onClick={toggleSelectionMode}>
            {selectionMode ? '선택 취소' : '선택'}
          </button>
          <select className="doc-sort" value={sortMode} onChange={(e) => setSortMode(e.target.value)}>
            <option value="recent">정렬: 최신순</option>
            <option value="name">정렬: 이름순</option>
          </select>
        </div>
      </div>

      {/* 상단 유형 필터 탭 (currentFolderId/breadcrumb 유지, 폴더는 모든 탭에서 표시) */}
      <div className="archive-tabs" style={{ marginBottom: '16px' }}>
        {ARCHIVE_TABS.map((t) => (
          <button
            key={t.key}
            className={`archive-tab ${effectiveTab === t.key ? 'active' : ''}`}
            onClick={() => {
              if (t.key === effectiveTab) return;
              setActiveArchiveTab(t.key);
              setOpenMenuKey(null);
              // 다른 탭의 folderId/breadcrumb 재사용 금지 → 탭 전환 시 항상 루트로.
              if (currentFolderId != null) setSearchParams({});
              setBreadcrumb([]);
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* breadcrumb + 뒤로가기 */}
      <div className="doc-breadcrumb">
        {currentFolderId != null && (
          <button className="doc-back" onClick={goBack} title="뒤로가기"><ArrowLeft size={18} /></button>
        )}
        <button className={`doc-crumb ${currentFolderId == null ? 'current' : ''}`} onClick={() => openFolder(null)}>홈</button>
        {breadcrumb.map((c, idx) => (
          <React.Fragment key={c.folderId}>
            <ChevronRight size={14} style={{ opacity: 0.5 }} />
            <button className={`doc-crumb ${idx === breadcrumb.length - 1 ? 'current' : ''}`} onClick={() => openFolder(c.folderId)}>{c.name}</button>
          </React.Fragment>
        ))}
      </div>

      {/* 카드 그리드 */}
      <div className="doc-grid">
        {/* 신규 카드 */}
        <div
          className="doc-card doc-new"
          style={openMenuKey === 'new' ? { position: 'relative', zIndex: 40 } : undefined}
          onClick={() => setOpenMenuKey(openMenuKey === 'new' ? null : 'new')}
        >
          <div className="doc-thumb"><Plus size={36} /></div>
          <div className="doc-card-body">
            <span className="doc-name">신규</span>
            <span className="doc-date">폴더 또는 자료 추가</span>
          </div>
          {openMenuKey === 'new' && (
            <div className="doc-menu" onClick={(e) => e.stopPropagation()}>
              <button onClick={openCreateFolder}><FolderPlus size={14} style={{ marginRight: 6, verticalAlign: 'middle' }} />폴더 만들기</button>
              <button onClick={openAddMaterial}><Upload size={14} style={{ marginRight: 6, verticalAlign: 'middle' }} />자료 업로드</button>
            </div>
          )}
        </div>

        {isLoading && (
          <div className="doc-state" style={{ gridColumn: '1 / -1' }}>자료를 불러오는 중입니다.</div>
        )}

        {!isLoading && loadError && (
          <div className="doc-state error" style={{ gridColumn: '1 / -1' }}>
            <p style={{ margin: '0 0 12px' }}>{loadError}</p>
            <button className="btn-primary" style={{ width: 'auto', padding: '8px 16px', borderRadius: '20px' }} onClick={fetchItems}>다시 시도</button>
          </div>
        )}

        {/* 폴더 카드 (모든 탭에서 표시) */}
        {!isLoading && !loadError && sortedFolders.map((folder) => {
          const key = `folder-${folder.folderId}`;
          return (
            <div
              key={key}
              className="doc-card"
              style={openMenuKey === key ? { position: 'relative', zIndex: 40 } : undefined}
              onClick={() => (selectionMode ? toggleSelect(key) : openFolder(folder.folderId))}
            >
              {selectionMode && (
                <span className={`doc-check ${selectedKeys.has(key) ? 'on' : ''}`}>
                  {selectedKeys.has(key) && <Check size={14} />}
                </span>
              )}
              <div className="doc-thumb"><FolderIcon size={40} /></div>
              <div className="doc-card-body">
                <span className="doc-name">{folder.name}</span>
                <div className="doc-meta">
                  <span className="doc-badge doc-badge-folder">폴더</span>
                  <span className="doc-date">{String(folder.createdAt || '').split('T')[0]}</span>
                </div>
              </div>
              {!selectionMode && (
                <>
                  <button className="doc-more" onClick={(e) => { e.stopPropagation(); setOpenMenuKey(openMenuKey === key ? null : key); }}>
                    <MoreVertical size={16} />
                  </button>
                  {openMenuKey === key && (
                    <div className="doc-menu" onClick={(e) => e.stopPropagation()}>
                      <button onClick={() => openRename('folder', folder)}>이름 변경</button>
                      <button onClick={() => openMove('folder', folder)}>이동</button>
                      <button className="danger" onClick={() => handleDeleteFolder(folder)}>삭제</button>
                    </div>
                  )}
                </>
              )}
            </div>
          );
        })}

        {/* 자료(파일) 카드 — 상단 탭 필터 적용 */}
        {!isLoading && !loadError && visibleMaterials.map((m) => {
          const key = `material-${m.materialId}`;
          const meta = TYPE_META[m.materialType] || TYPE_META.PDF;
          const Icon = meta.Icon;
          return (
            <div
              key={key}
              className="doc-card"
              style={openMenuKey === key ? { position: 'relative', zIndex: 40 } : undefined}
              onClick={() => (selectionMode ? toggleSelect(key) : openMaterial(m))}
            >
              {selectionMode && (
                <span className={`doc-check ${selectedKeys.has(key) ? 'on' : ''}`}>
                  {selectedKeys.has(key) && <Check size={14} />}
                </span>
              )}
              <div className="doc-thumb"><Icon size={40} /></div>
              <div className="doc-card-body">
                <span className="doc-name">{getMaterialDisplayTitle(m)}</span>
                <div className="doc-meta">
                  <span className={`doc-badge ${meta.badge}`}>{meta.label}</span>
                  <span className="doc-date">{materialDate(m)}</span>
                </div>
              </div>
              {!selectionMode && (
                <>
                  <button className="doc-more" onClick={(e) => { e.stopPropagation(); setOpenMenuKey(openMenuKey === key ? null : key); }}>
                    <MoreVertical size={16} />
                  </button>
                  {openMenuKey === key && (
                    <div className="doc-menu" onClick={(e) => e.stopPropagation()}>
                      <button onClick={() => openRename('material', m)}>이름 변경</button>
                      <button onClick={() => openMove('material', m)}>이동</button>
                      <button className="danger" onClick={() => handleDeleteMaterial(m)}>삭제</button>
                    </div>
                  )}
                </>
              )}
            </div>
          );
        })}

        {isEmpty && (
          <div className="doc-state" style={{ gridColumn: '1 / -1' }}>
            <FolderIcon size={44} style={{ opacity: 0.3, marginBottom: 12 }} />
            <p style={{ margin: 0 }}>이 위치에 표시할 항목이 없습니다. “신규”로 폴더를 만들거나 자료를 업로드하세요.</p>
          </div>
        )}
      </div>

      {/* 폴더 만들기 모달 */}
      {createFolderOpen && (
        <div className="modal-overlay">
          <div className="glass-panel modal-content" style={{ maxWidth: '420px', width: '100%', padding: '28px' }}>
            <h3 style={{ margin: '0 0 16px', fontSize: '18px' }}>폴더 만들기</h3>
            <input
              type="text" autoFocus className="input-field" placeholder="폴더 이름"
              value={createFolderName}
              onChange={(e) => setCreateFolderName(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleCreateFolder(); }}
              style={{ width: '100%', padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', backgroundColor: '#F9FAFB', marginBottom: '20px' }}
            />
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
              <button className="btn-outline" style={{ padding: '10px 20px', width: 'auto' }} onClick={() => setCreateFolderOpen(false)} disabled={isSubmitting}>취소</button>
              <button className="btn-primary" style={{ padding: '10px 20px', width: 'auto' }} onClick={handleCreateFolder} disabled={isSubmitting}>{isSubmitting ? '생성 중...' : '생성'}</button>
            </div>
          </div>
        </div>
      )}

      {/* 이름 변경 모달 */}
      {renameState && (
        <div className="modal-overlay">
          <div className="glass-panel modal-content" style={{ maxWidth: '420px', width: '100%', padding: '28px' }}>
            <h3 style={{ margin: '0 0 16px', fontSize: '18px' }}>{renameState.kind === 'folder' ? '폴더 이름 변경' : '자료 이름 변경'}</h3>
            <input
              type="text" autoFocus className="input-field"
              value={renameState.name}
              onChange={(e) => setRenameState((s) => ({ ...s, name: e.target.value }))}
              onKeyDown={(e) => { if (e.key === 'Enter') handleRenameSubmit(); }}
              style={{ width: '100%', padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', backgroundColor: '#F9FAFB', marginBottom: '20px' }}
            />
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
              <button className="btn-outline" style={{ padding: '10px 20px', width: 'auto' }} onClick={() => setRenameState(null)} disabled={isSubmitting}>취소</button>
              <button className="btn-primary" style={{ padding: '10px 20px', width: 'auto' }} onClick={handleRenameSubmit} disabled={isSubmitting}>{isSubmitting ? '저장 중...' : '저장'}</button>
            </div>
          </div>
        </div>
      )}

      {/* 이동 모달 */}
      {moveState && (
        <div className="modal-overlay">
          <div className="glass-panel modal-content" style={{ maxWidth: '460px', width: '100%', padding: '28px' }}>
            <h3 style={{ margin: '0 0 8px', fontSize: '18px' }}>이동</h3>
            <p style={{ margin: '0 0 16px', fontSize: '13.5px', color: 'var(--color-text-muted)' }}>
              '{moveState.name}' 을(를) 옮길 위치를 선택하세요.
            </p>
            <select
              className="doc-sort" value={moveState.targetId}
              onChange={(e) => setMoveState((s) => ({ ...s, targetId: e.target.value }))}
              style={{ width: '100%', marginBottom: '20px' }}
            >
              {moveState.options.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
              <button className="btn-outline" style={{ padding: '10px 20px', width: 'auto' }} onClick={() => setMoveState(null)} disabled={isSubmitting}>취소</button>
              <button className="btn-primary" style={{ padding: '10px 20px', width: 'auto' }} onClick={handleMoveSubmit} disabled={isSubmitting}>{isSubmitting ? '이동 중...' : '이동'}</button>
            </div>
          </div>
        </div>
      )}

      {/* 업로드 전 유형 판별 불일치 확인 모달 */}
      {classifyInfo && (
        <div className="modal-overlay">
          <div className="glass-panel modal-content" style={{ maxWidth: '460px', width: '100%', padding: '28px' }}>
            <h3 style={{ margin: '0 0 12px', fontSize: '18px' }}>업로드 유형 확인</h3>
            <p style={{ margin: '0 0 8px', fontSize: '14px', lineHeight: 1.6, color: 'var(--color-text-main)' }}>
              {classifyInfo.userMessage || '선택한 유형과 파일 내용이 다를 수 있습니다. 알맞은 곳에 넣으세요.'}
            </p>
            {classifyInfo.reason && (
              <p style={{ margin: '0 0 16px', fontSize: '12.5px', color: 'var(--color-text-muted)', lineHeight: 1.5 }}>{classifyInfo.reason}</p>
            )}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {(Array.isArray(classifyInfo.allowedActions) && classifyInfo.allowedActions.length
                ? classifyInfo.allowedActions
                : [
                    { label: '추천 유형으로 저장', type: classifyInfo.recommendedType, recommended: true },
                    { label: '그래도 선택한 유형으로 저장', type: classifyInfo.selectedAi, recommended: false },
                    { label: '취소', type: 'CANCEL', recommended: false },
                  ]
              ).map((act, i) => (
                <button
                  key={i}
                  className={act.recommended ? 'btn-primary' : 'btn-outline'}
                  disabled={isSubmitting}
                  style={{ width: '100%', padding: '10px', borderRadius: '10px', fontWeight: 600 }}
                  onClick={() => confirmClassifySave(act.type)}
                >
                  {act.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* 자료 추가 모달 */}
      {openedModalType === 'addMaterial' && (
        <div className="modal-overlay">
          <div className="glass-panel modal-content" style={{ maxWidth: '800px', width: '100%', maxHeight: 'calc(100vh - 48px)', padding: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
            <div className="modal-header" style={{ flexShrink: 0, padding: '28px 32px 20px', borderBottom: '1px solid var(--color-border)' }}>
              <h3 style={{ margin: 0, fontSize: '22px' }}>자료 추가{currentFolderId != null && breadcrumb.length ? ` — ${breadcrumb[breadcrumb.length - 1].name}` : ''}</h3>
              <button className="btn-close" onClick={closeModal}><X size={24} /></button>
            </div>
            <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '24px', flex: 1, minHeight: 0, overflowY: 'auto', padding: '24px 32px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '16px', fontWeight: 'bold', marginBottom: '12px' }}>자료 유형</label>
                <div style={{ display: 'flex', gap: '20px' }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '16px', cursor: 'pointer' }}>
                    <input type="radio" name="materialType" checked={addMaterialType === 'journal'} onChange={() => setAddMaterialType('journal')} style={{ transform: 'scale(1.2)' }} /> 학습일지
                  </label>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '16px', cursor: 'pointer' }}>
                    <input type="radio" name="materialType" checked={addMaterialType === 'pdf'} onChange={() => setAddMaterialType('pdf')} style={{ transform: 'scale(1.2)' }} /> 학습자료
                  </label>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '16px', cursor: 'pointer' }}>
                    <input type="radio" name="materialType" checked={addMaterialType === 'planner'} onChange={() => setAddMaterialType('planner')} style={{ transform: 'scale(1.2)' }} /> 플래너
                  </label>
                </div>
              </div>

              <hr style={{ border: 'none', borderTop: '1px solid var(--color-border)', margin: '0' }} />

              {addMaterialType === 'journal' ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
                    <div>
                      <label style={{ display: 'block', marginBottom: '8px', fontWeight: '600', fontSize: '14px' }}>제목</label>
                      <input type="text" className="input-field" placeholder="학습일지 제목" value={formTitle} onChange={(e) => setFormTitle(e.target.value)} style={{ width: '100%', padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', backgroundColor: '#F9FAFB' }} />
                    </div>
                    <div>
                      <label style={{ display: 'block', marginBottom: '8px', fontWeight: '600', fontSize: '14px' }}>날짜</label>
                      <input type="date" className="input-field" value={formDate} onChange={(e) => setFormDate(e.target.value)} style={{ width: '100%', padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', backgroundColor: '#F9FAFB' }} />
                    </div>
                  </div>
                  <div>
                    <label style={{ display: 'block', marginBottom: '8px', fontWeight: '600', fontSize: '14px' }}>핵심 키워드 (쉼표로 구분)</label>
                    <input type="text" className="input-field" placeholder="키워드 입력 (예: React, 상태관리)" value={formKeywords} onChange={(e) => setFormKeywords(e.target.value)} style={{ width: '100%', padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', backgroundColor: '#F9FAFB' }} />
                  </div>
                  <div>
                    <label style={{ display: 'block', marginBottom: '8px', fontWeight: '600', fontSize: '14px' }}>학습 내용</label>
                    <textarea className="input-field" placeholder="학습한 내용을 상세히 작성하세요." value={formContent} onChange={(e) => setFormContent(e.target.value)} style={{ width: '100%', minHeight: '120px', padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', resize: 'vertical', backgroundColor: '#F9FAFB', fontFamily: 'inherit', lineHeight: '1.5' }} />
                  </div>
                  <div>
                    <label style={{ display: 'block', marginBottom: '8px', fontWeight: '600', fontSize: '14px' }}>다음 학습 계획</label>
                    <textarea className="input-field" placeholder="다음에 학습할 내용을 작성하세요." value={formNextPlan} onChange={(e) => setFormNextPlan(e.target.value)} style={{ width: '100%', minHeight: '80px', padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', resize: 'vertical', backgroundColor: '#F9FAFB', fontFamily: 'inherit', lineHeight: '1.5' }} />
                  </div>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', flex: 1 }}>
                  <div>
                    <label style={{ display: 'block', fontSize: '16px', fontWeight: 'bold', marginBottom: '12px' }}>제목</label>
                    <input type="text" className="input-field" placeholder="자료의 제목을 입력하세요" value={formTitle} onChange={(e) => setFormTitle(e.target.value)} style={{ width: '100%', fontSize: '16px', padding: '16px', borderRadius: '8px', border: '1px solid var(--color-border)', backgroundColor: '#F9FAFB' }} />
                  </div>
                  <div>
                    <label style={{ display: 'block', fontSize: '16px', fontWeight: 'bold', marginBottom: '12px' }}>핵심 키워드 (쉼표로 구분)</label>
                    <input type="text" className="input-field" placeholder="키워드 입력" value={formKeywords} onChange={(e) => setFormKeywords(e.target.value)} style={{ width: '100%', fontSize: '16px', padding: '16px', borderRadius: '8px', border: '1px solid var(--color-border)', backgroundColor: '#F9FAFB' }} />
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', flex: 1 }}>
                    <label style={{ display: 'block', fontSize: '16px', fontWeight: 'bold', marginBottom: '12px' }}>파일 업로드</label>
                    <input type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" ref={addFileInputRef} onChange={handlePickUploadFile} style={{ display: 'none' }} />
                    <div
                      onClick={() => addFileInputRef.current?.click()}
                      style={{ flex: 1, border: '2px dashed var(--color-border)', borderRadius: '12px', padding: '28px', display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', textAlign: 'center', color: 'var(--color-text-muted)', backgroundColor: '#F9FAFB', cursor: 'pointer', minHeight: '160px', maxHeight: '220px' }}
                    >
                      <FileIcon size={48} style={{ margin: '0 auto 16px', opacity: 0.5 }} />
                      <p style={{ margin: '0 0 12px', fontSize: '16px', fontWeight: 'bold' }}>
                        {formFile ? `선택된 파일: ${formFile.name}` : '클릭하거나 파일을 드래그하여 업로드하세요'}
                      </p>
                      <p style={{ margin: 0, fontSize: '14px' }}>지원 형식: PDF, DOCX</p>
                    </div>
                  </div>
                </div>
              )}
            </div>
            <div className="modal-footer" style={{ justifyContent: 'flex-end', display: 'flex', gap: '12px', flexShrink: 0, padding: '20px 32px', borderTop: '1px solid var(--color-border)', background: 'white' }}>
              <button className="btn-outline" style={{ padding: '12px 32px', fontSize: '16px' }} onClick={closeModal} disabled={isSubmitting}>취소</button>
              <button className="btn-primary" style={{ padding: '12px 32px', fontSize: '16px' }} onClick={handleSubmitMaterial} disabled={isSubmitting}>
                {isSubmitting ? '저장 중...' : '저장'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 학습일지 모달 */}
      {selectedJournal && (
        <div className="modal-overlay">
          <div className="glass-panel modal-content" style={{ maxWidth: '1100px', width: '90%', height: '85vh', padding: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
            <div className="modal-header" style={{ padding: '24px 32px', borderBottom: '1px solid var(--color-border)', margin: 0, flexShrink: 0 }}>
              <h3 style={{ margin: 0, fontSize: '22px' }}>{selectedJournal.title}</h3>
              <button className="btn-close" onClick={() => setSelectedJournal(null)}><X size={24} /></button>
            </div>
            <div className="modal-body" style={{ flex: 1, display: 'flex', overflow: 'hidden', padding: 0 }}>
              <div style={{ flex: 1, padding: '32px', overflowY: 'auto', borderRight: '1px solid var(--color-border)' }}>
                {isJournalEditMode ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', height: '100%' }}>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
                      <div>
                        <label style={{ display: 'block', marginBottom: '8px', fontWeight: '600', fontSize: '14px' }}>제목</label>
                        <input type="text" className="input-field" value={editTitle} onChange={(e) => setEditTitle(e.target.value)} style={{ width: '100%', padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', backgroundColor: '#F9FAFB' }} />
                      </div>
                      <div>
                        <label style={{ display: 'block', marginBottom: '8px', fontWeight: '600', fontSize: '14px' }}>날짜</label>
                        <input type="text" className="input-field" value={editDate} disabled style={{ width: '100%', padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', backgroundColor: '#F3F4F6', color: '#9CA3AF' }} />
                      </div>
                    </div>
                    <div>
                      <label style={{ display: 'block', marginBottom: '8px', fontWeight: '600', fontSize: '14px' }}>키워드</label>
                      <input type="text" className="input-field" value={editKeywords} onChange={(e) => setEditKeywords(e.target.value)} style={{ width: '100%', padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', backgroundColor: '#F9FAFB' }} />
                    </div>
                    <div>
                      <label style={{ display: 'block', marginBottom: '8px', fontWeight: '600', fontSize: '14px' }}>학습 내용</label>
                      <textarea className="input-field" value={editContent} disabled style={{ width: '100%', minHeight: '120px', padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', resize: 'vertical', backgroundColor: '#F3F4F6', color: '#9CA3AF', fontFamily: 'inherit', lineHeight: '1.5' }} />
                    </div>
                    <div>
                      <label style={{ display: 'block', marginBottom: '8px', fontWeight: '600', fontSize: '14px' }}>다음 학습 계획</label>
                      <textarea className="input-field" value={editNextPlan} disabled style={{ width: '100%', minHeight: '80px', padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', resize: 'vertical', backgroundColor: '#F3F4F6', color: '#9CA3AF', fontFamily: 'inherit', lineHeight: '1.5' }} />
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px', marginTop: 'auto', paddingTop: '12px' }}>
                      <button className="btn-outline" style={{ padding: '10px 24px', width: 'auto' }} onClick={() => setIsJournalEditMode(false)}>취소</button>
                      <button className="btn-primary" style={{ padding: '10px 24px', width: 'auto' }} onClick={handleUpdateJournal}>저장하기</button>
                    </div>
                  </div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '24px', height: '100%' }}>
                    <div><span style={{ color: 'var(--color-text-muted)', fontSize: '14px' }}>{selectedJournal.date} • {selectedJournal.tag}</span></div>
                    <div>
                      <h4 style={{ margin: '0 0 8px', fontSize: '15px', color: 'var(--color-text-muted)' }}>키워드</h4>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                        {selectedJournal.keywords.map(kw => <span key={kw} className="tag">#{kw}</span>)}
                      </div>
                    </div>
                    <div>
                      <h4 style={{ margin: '0 0 8px', fontSize: '15px', color: 'var(--color-text-muted)' }}>학습 내용</h4>
                      <p style={{ margin: 0, lineHeight: 1.6, whiteSpace: 'pre-wrap', color: 'var(--color-text-main)' }}>{selectedJournal.content}</p>
                    </div>
                    <div>
                      <h4 style={{ margin: '0 0 8px', fontSize: '15px', color: 'var(--color-text-muted)' }}>다음 학습 계획</h4>
                      <p style={{ margin: 0, lineHeight: 1.6, whiteSpace: 'pre-wrap', color: 'var(--color-text-main)' }}>{selectedJournal.nextPlan}</p>
                    </div>
                    <div style={{ marginTop: 'auto', paddingTop: '16px' }}>
                      <button className="btn-outline" style={{ width: '100%', padding: '12px', fontWeight: 'bold' }} onClick={() => setIsJournalEditMode(true)}>수정하기</button>
                    </div>
                  </div>
                )}
              </div>
              <div style={{ flex: 1, padding: '32px', overflowY: 'auto', backgroundColor: 'var(--color-bg-base)' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                  <div className="glass-panel" style={{ padding: '24px' }}>
                    <h3 style={{ margin: '0 0 16px', fontSize: '18px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <AlignLeft size={18} color="var(--color-primary)" /> AI 요약
                    </h3>
                    <p style={{ margin: 0, fontSize: '15px', lineHeight: '1.6', color: 'var(--color-text-main)' }}>{journalSummary}</p>
                  </div>
                  <div className="glass-panel" style={{ padding: '24px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', marginBottom: '16px', flexWrap: 'wrap' }}>
                      <h3 style={{ margin: 0, fontSize: '18px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <MessageSquare size={18} color="var(--color-primary)" /> AI 피드백
                      </h3>
                      <button
                        onClick={handleRegenerateFeedback}
                        disabled={regeneratingFeedback}
                        style={{ padding: '7px 16px', borderRadius: '20px', fontSize: '13px', border: '1px solid var(--color-border)', background: 'white', cursor: regeneratingFeedback ? 'default' : 'pointer', opacity: regeneratingFeedback ? 0.6 : 1, whiteSpace: 'nowrap' }}
                      >
                        {regeneratingFeedback ? '재생성 중…' : '균형 잡힌 피드백 다시 생성'}
                      </button>
                    </div>
                    {renderFeedbackBody()}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
