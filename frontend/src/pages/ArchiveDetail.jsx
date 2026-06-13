import React, { useState, useEffect, useRef } from 'react';
import { useLocation, useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, AlignLeft, HelpCircle, Map, MessageSquare, Edit3, Image, Download, Send, CheckCircle2, Circle, Settings, ChevronRight, X, Trash2 } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import { AI_TIMEOUT_MS, materialService, reviewNoteService, plannerService } from '../services/api';
import SummarySectionCard from '../components/SummarySectionCard';
import KeywordDefineModal from '../components/KeywordDefineModal';
import { sanitizeMarkdownText, sanitizeList } from '../utils/markdown';

// F. 빠른 체감 — 실제 streaming 전, 단계별 진행 문구 + skeleton (멀티에이전트 SSE와 무관, 자료보관함 전용)
const ANALYZE_STEPS = ['텍스트 추출 중', '요약 생성 중', '핵심 내용 생성 중', '세부 핵심 내용 생성 중', '키워드 생성 중', '로드맵 생성 중', '마무리 중'];
function AnalyzingProgress() {
  const [step, setStep] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setStep((s) => (s + 1) % ANALYZE_STEPS.length), 1300);
    return () => clearInterval(t);
  }, []);
  return (
    <div className="glass-panel" style={{ padding: '24px', borderLeft: '4px solid var(--color-primary)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px' }}>
        <div style={{ width: '16px', height: '16px', border: '2px solid var(--color-primary)', borderTopColor: 'transparent', borderRadius: '50%', animation: 'spin 0.8s linear infinite' }} />
        <span style={{ fontWeight: 700, color: 'var(--color-text-main)' }}>AI가 문서를 분석하고 있습니다 — {ANALYZE_STEPS[step]}…</span>
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '18px' }}>
        {ANALYZE_STEPS.map((label, i) => (
          <span key={i} style={{ fontSize: '11.5px', padding: '3px 10px', borderRadius: '12px', fontWeight: 600,
            backgroundColor: i <= step ? '#ECFDF5' : '#F3F4F6', color: i <= step ? '#15803D' : '#9CA3AF' }}>{label}</span>
        ))}
      </div>
      {[88, 70, 94, 60].map((w, i) => (
        <div key={i} style={{ height: '12px', width: `${w}%`, borderRadius: '6px', background: 'linear-gradient(90deg,#EEF2F7,#F8FAFC,#EEF2F7)', backgroundSize: '200% 100%', animation: 'shimmer 1.4s ease-in-out infinite', marginBottom: '10px' }} />
      ))}
      <style>{`@keyframes spin{to{transform:rotate(360deg)}}@keyframes shimmer{0%{background-position:200% 0}100%{background-position:-200% 0}}`}</style>
    </div>
  );
}

export default function ArchiveDetail() {
  const { type, id } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const { userId } = useAuth();

  // 기본 상태 정보
  const [material, setMaterial] = useState(location.state?.item || null);
  const [isLoadingDetail, setIsLoadingDetail] = useState(!location.state?.item);
  const [activePdfTool, setActivePdfTool] = useState('summary');

  // 각 탭별 실 API 데이터 상태
  const [summaryData, setSummaryData] = useState(null);
  const [quizzes, setQuizzes] = useState([]);
  const [selectedQuizId, setSelectedQuizId] = useState(null);
  const [roadmapSteps, setRoadmapSteps] = useState([]);
  const [isRegeneratingRoadmap, setIsRegeneratingRoadmap] = useState(false);
  const [roadmapLevel, setRoadmapLevel] = useState('intermediate'); // beginner | intermediate | advanced
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [isAddingStudyLog, setIsAddingStudyLog] = useState(false);
  const [showAllDetailed, setShowAllDetailed] = useState(false);
  const [memoText, setMemoText] = useState('');
  const [chatMessages, setChatMessages] = useState([
    { sender: 'ai', text: '이 AI는 자료보관함에 업로드된 PDF 기반 채팅만 가능합니다.\n현재 선택한 자료의 내용 안에서만 질문에 답변합니다.\n자료에 없는 내용은 임의로 생성하지 않습니다.\n일반적인 학습 질문이나 자료와 무관한 질문은 학습메이트 기능을 이용해주세요.' }
  ]);
  const [chatInput, setChatInput] = useState('');

  const [roadmapData, setRoadmapData] = useState(null);
  const [roadmapError, setRoadmapError] = useState(null);
  const [quizError, setQuizError] = useState(null);
  const [isAskingQuestion, setIsAskingQuestion] = useState(false);


  // UI 상호작용 상태
  const [isQuizSettingsOpen, setIsQuizSettingsOpen] = useState(false);
  const [quizSettings, setQuizSettings] = useState({ difficulty: '보통', count: 10, range: '전체' }); // R. 기본 10문항
  const [isGeneratingQuiz, setIsGeneratingQuiz] = useState(false);
  const [isSavingMemo, setIsSavingMemo] = useState(false);
  const [userAnswers, setUserAnswers] = useState({});
  // 오답노트
  const [isCreatingReviewNote, setIsCreatingReviewNote] = useState(false);
  const [reviewNotesByQuiz, setReviewNotesByQuiz] = useState({}); // quizId -> 생성된 오답노트
  const [reviewNoteResult, setReviewNoteResult] = useState(null); // 생성 성공/실패 모달
  // 로드맵 → 플래너 생성 (플래너 도메인 전용, 주간일정과 무관)
  const [isCreatingPlanner, setIsCreatingPlanner] = useState(false);
  const [isPlannerModalOpen, setIsPlannerModalOpen] = useState(false);
  const [plannerStartDate, setPlannerStartDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [plannerResult, setPlannerResult] = useState(null);
  const [plannerError, setPlannerError] = useState(null);

  const chatEndRef = useRef(null);

  // ✅ 패널 너비 조절 관련 상태
  const [leftWidth, setLeftWidth] = useState(50); // 기본값 50%

  // 핵심 키워드 클릭 → 개념 정의 패널
  const [activeKeyword, setActiveKeyword] = useState(null);


  const AI_ERROR_MESSAGES = {
    PDF_TEXT_EMPTY: 'PDF에서 추출된 텍스트가 없습니다. 다시 분석을 시도해주세요.',
    PDF_TEXT_TOO_SHORT: '문서 텍스트가 너무 짧아 요약 품질이 낮을 수 있습니다.',
    PDF_EXTRACTION_FAILED: 'PDF 텍스트 추출에 실패했습니다.',
    PDF_OCR_REQUIRED: '이미지 기반 PDF라 텍스트 추출이 필요합니다. OCR 설정을 켠 뒤 다시 시도해주세요.',
    AI_TIMEOUT: 'AI 응답 시간이 초과되었습니다. 잠시 후 다시 시도해주세요.',
    OLLAMA_UNAVAILABLE: '로컬 AI 모델 연결에 실패했습니다.',
    OPENAI_UNAVAILABLE: 'GPT 모델 연결에 실패했습니다.',
    AI_RESPONSE_PARSE_FAILED: 'AI 응답 형식 처리에 실패했습니다. 다시 생성해주세요.',
    QUIZ_VALIDATE_FAILED: '요청한 난이도가 충분히 반영되지 않았습니다. 같은 PDF 자료를 기준으로 다시 생성해주세요.',
    PDF_CONTEXT_REQUIRED: 'PDF 기반 퀴즈를 생성하려면 자료에서 추출된 텍스트나 요약이 필요합니다.',
    ROADMAP_VALIDATE_FAILED: '로드맵 형식 검증에 실패했습니다. 다시 생성해주세요.',
    SUMMARY_VALIDATE_FAILED: '요약 형식 검증에 실패했습니다. 다시 생성해주세요.',
    QA_VALIDATE_FAILED: '답변 검증에 실패했습니다. 다시 질문해주세요.',
    UNKNOWN_ERROR: 'AI 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.',
  };

  const normalizeAiResponse = (response) => {
    if (!response) return { success: null };
    if (response.success === false) {
      return {
        ...response,
        success: false,
        errorCode: response.errorCode || 'UNKNOWN_ERROR',
        message: getAiErrorMessage(response.errorCode, response.textStatus, response.message),
        retryable: response.retryable !== false,
      };
    }
    return { ...response, success: response.success !== false };
  };

  const normalizeAiException = (error) => {
    const isTimeout = error?.code === 'ECONNABORTED' || /timeout|timed out/i.test(error?.message || '');
    const data = error?.response?.data || {};
    const errorCode = isTimeout ? 'AI_TIMEOUT' : (data.errorCode || 'UNKNOWN_ERROR');
    return normalizeAiResponse({
      success: false,
      errorCode,
      message: data.message,
      retryable: true,
      textStatus: data.textStatus,
      metadata: { timeoutMs: AI_TIMEOUT_MS },
    });
  };

  const getAiErrorMessage = (errorCode, textStatus, fallback) => {
    if (fallback) return fallback;
    if (errorCode && AI_ERROR_MESSAGES[errorCode]) return AI_ERROR_MESSAGES[errorCode];
    if (textStatus?.hasText === false) return AI_ERROR_MESSAGES.PDF_TEXT_EMPTY;
    if (textStatus?.status === 'TOO_SHORT') return AI_ERROR_MESSAGES.PDF_TEXT_TOO_SHORT;
    return AI_ERROR_MESSAGES.UNKNOWN_ERROR;
  };

  const isRetryableAiError = (response) => normalizeAiResponse(response).retryable === true;

  const getTextStatusMessage = (textStatus) => {
    if (!textStatus) return null;
    if (textStatus.hasText === false || textStatus.status === 'EMPTY') return AI_ERROR_MESSAGES.PDF_TEXT_EMPTY;
    if (textStatus.status === 'TOO_SHORT') return AI_ERROR_MESSAGES.PDF_TEXT_TOO_SHORT;
    return null;
  };

  const removeDummyKeywords = (keywords) => {
    const list = Array.isArray(keywords) ? keywords : String(keywords || '').split(',');
    const junk = new Set(['ㅇㅇ', '#ㅇㅇ', 'ㅎㅎ', 'ㅋㅋ', 'test', 'keyword', 'keywords', '테스트', 'null', 'undefined']);
    const seen = new Set();
    return list
      .map((kw) => String(kw || '').trim().replace(/^#+/, '').trim())
      .filter((kw) => kw.length > 1 && !junk.has(kw.toLowerCase()) && /[가-힣A-Za-z0-9]/.test(kw))
      .filter((kw) => {
        const key = kw.toLowerCase();
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      });
  };


  const parseMaybeJson = (value, fallback = null) => {
    if (value == null) return fallback;
    if (typeof value !== 'string') return value;
    const trimmed = value.trim();
    if (!trimmed) return fallback;
    try {
      return JSON.parse(trimmed);
    } catch (_) {
      return fallback;
    }
  };

  const getSummaryOverview = (data) => {
    if (!data) return '';
    return data.overview || data.summary || data.gpt_raw || '';
  };

  const getSummaryEnvelope = (data) => {
    const parsedCore = parseMaybeJson(data?.coreContents, null);
    if (parsedCore && !Array.isArray(parsedCore) && typeof parsedCore === 'object') return parsedCore;
    return { sections: Array.isArray(parsedCore) ? parsedCore : null };
  };

  const getSummaryKeywords = (data) => {
    if (!data) return [];
    const envelope = getSummaryEnvelope(data);
    return removeDummyKeywords(data.keywords?.length ? data.keywords : (data.key_points?.length ? data.key_points : (envelope.keywords || envelope.key_points || [])));
  };

  // 요약 강화: 학습 포인트 / 실습·적용 포인트 / AI 학습 질문 (DTO 또는 envelope에서)
  const getSummaryStringList = (data, key) => {
    if (!data) return [];
    if (Array.isArray(data[key]) && data[key].length) return data[key].filter(Boolean);
    const envelope = getSummaryEnvelope(data);
    const list = envelope[key];
    return Array.isArray(list) ? list.filter(Boolean) : [];
  };

  const getSummarySections = (data) => {
    if (!data) return [];
    const envelope = getSummaryEnvelope(data);
    const candidates = data.sections || envelope.sections || data.coreContents;
    const parsed = parseMaybeJson(candidates, candidates);
    const list = Array.isArray(parsed) ? parsed : [];
    if (list.length > 0) {
      return list
        .map((item, idx) => {
          if (typeof item === 'string') return { title: `${idx + 1}. 핵심 요약`, content: item };
          if (!item || typeof item !== 'object') return null;
          return {
            title: item.title || item.heading || `${idx + 1}. 핵심 요약`,
            content: item.content || item.description || item.summary || '',
          };
        })
        .filter((item) => item && item.content);
    }
    if (typeof data.coreContents === 'string' && data.coreContents.trim() && !['[]', '{}'].includes(data.coreContents.trim())) {
      return data.coreContents
        .split('\n')
        .map((line) => line.replace(/^[-\d.\s*]+/, '').trim())
        .filter(Boolean)
        .map((line, idx) => ({ title: `${idx + 1}. 핵심 요약`, content: line }));
    }
    return [];
  };

  // B. 핵심 내용(core_contents) — ai07 신규 필드 우선, 없으면 sections/포인트/키워드로 fallback 생성. 최소 10개 목표. 모두 sanitize.
  const getCoreContents = (data) => {
    if (!data) return [];
    const envelope = getSummaryEnvelope(data);
    const direct = data.core_contents || envelope.core_contents;
    if (Array.isArray(direct) && direct.length) {
      return direct.map((it, i) => (typeof it === 'string'
        ? { title: `핵심 내용 ${i + 1}`, content: sanitizeMarkdownText(it) }
        : { title: sanitizeMarkdownText(it.title || it.heading || `핵심 내용 ${i + 1}`), content: sanitizeMarkdownText(it.content || it.description || it.summary || '') }))
        .filter((x) => x.content);
    }
    // fallback: sections(제목+본문) + 실습/학습 포인트 + 키워드를 카드화하여 10개 이상 확보
    const items = [];
    getSummarySections(data).forEach((s) => {
      const content = sanitizeMarkdownText(s.content);
      if (content) items.push({ title: sanitizeMarkdownText(s.title) || `핵심 내용 ${items.length + 1}`, content });
    });
    [...sanitizeList(data.practicePoints), ...sanitizeList(data.learningPoints)].forEach((p) => {
      items.push({ title: p.split(/[:：.]/)[0].slice(0, 40) || '핵심 내용', content: p });
    });
    if (items.length < 10) {
      sanitizeList(data.key_points?.length ? data.key_points : data.keywords).forEach((kp) => {
        items.push({ title: kp.split(/[:：.]/)[0].slice(0, 40) || '핵심 내용', content: kp });
      });
    }
    // 중복 제거
    const seen = new Set();
    return items.filter((it) => { const k = it.content.slice(0, 60); if (seen.has(k)) return false; seen.add(k); return true; });
  };

  // C. 세부 핵심 내용(detailed_core_contents) — ai07 신규 필드 우선, 없으면 sections/포인트/키워드를 줄 단위로 분해. 최소 40줄 목표. 모두 sanitize.
  const getDetailedCoreContents = (data) => {
    if (!data) return [];
    const envelope = getSummaryEnvelope(data);
    const direct = data.detailed_core_contents || envelope.detailed_core_contents;
    if (Array.isArray(direct) && direct.length) {
      return direct.map((it, i) => (typeof it === 'string'
        ? { title: `세부 핵심 내용 ${i + 1}`, content: sanitizeMarkdownText(it) }
        : { title: sanitizeMarkdownText(it.title || `세부 핵심 내용 ${i + 1}`), content: sanitizeMarkdownText(it.content || it.description || '') }))
        .filter((x) => x.content);
    }
    // fallback: 모든 텍스트 소스를 줄/문장 단위로 분해
    const lines = [];
    const pushLines = (text) => {
      sanitizeMarkdownText(text).split(/\n+/).forEach((ln) => {
        ln.split(/(?<=[.。!?])\s+/).forEach((seg) => { const t = seg.trim(); if (t.length > 3) lines.push(t); });
      });
    };
    getSummarySections(data).forEach((s) => pushLines(s.content));
    sanitizeList(data.practicePoints).forEach(pushLines);
    sanitizeList(data.learningPoints).forEach(pushLines);
    sanitizeList(data.studyQuestions).forEach(pushLines);
    sanitizeList(data.key_points?.length ? data.key_points : data.keywords).forEach(pushLines);
    const seen = new Set();
    const out = [];
    lines.forEach((l) => { const k = l.slice(0, 60); if (!seen.has(k)) { seen.add(k); out.push({ title: `세부 핵심 내용 ${out.length + 1}`, content: l }); } });
    return out;
  };

  // O. 핵심 내용을 '한 카드'에 담기 위한 단일 텍스트.
  //    우선순위: core_content_text → coreContentText → core_contents 줄바꿈 join → coreContents 줄바꿈 join
  const getCoreContentText = (data) => {
    if (!data) return '';
    const env = getSummaryEnvelope(data);
    const direct = data.core_content_text || env.core_content_text || data.coreContentText || env.coreContentText;
    if (direct && String(direct).trim()) return sanitizeMarkdownText(direct);
    return getCoreContents(data).map((it) => it.content).filter(Boolean).join('\n');
  };
  // O. 세부 핵심 내용을 '한 카드'에 담기 위한 단일 텍스트.
  //    우선순위: detailed_content_text → detailedContentText → detailed_core_contents join → detailedCoreContents join
  const getDetailedContentText = (data) => {
    if (!data) return '';
    const env = getSummaryEnvelope(data);
    const direct = data.detailed_content_text || env.detailed_content_text || data.detailedContentText || env.detailedContentText;
    if (direct && String(direct).trim()) return sanitizeMarkdownText(direct);
    return getDetailedCoreContents(data).map((it) => it.content).filter(Boolean).join('\n');
  };

  // D. 학습일지 본문 구성 — 마크다운 없는 일반 텍스트
  const buildStudyLogContent = (overview, keywords, core, detailed, questions) => {
    const out = [];
    out.push(`자료 제목: ${sanitizeMarkdownText(material?.title || '')}`);
    out.push('');
    out.push('문서 개요:');
    out.push(sanitizeMarkdownText(overview) || '-');
    out.push('');
    out.push('핵심 키워드:');
    out.push((keywords || []).map(sanitizeMarkdownText).join(', ') || '-');
    out.push('');
    out.push('핵심 내용:');
    core.forEach((c, i) => { out.push(`${i + 1}. ${c.title}`); if (c.content && c.content !== c.title) out.push(`   ${c.content}`); });
    out.push('');
    out.push('세부 핵심 내용:');
    detailed.forEach((d, i) => { out.push(`${i + 1}. ${d.content}`); });
    if (questions && questions.length) {
      out.push('');
      out.push('학습 질문:');
      questions.forEach((q, i) => out.push(`${i + 1}. ${sanitizeMarkdownText(q)}`));
    }
    return out.join('\n');
  };

  const handleAddToStudyLog = async () => {
    if (isAddingStudyLog || !summaryData) return;
    try {
      setIsAddingStudyLog(true);
      const overview = getSummaryOverview(summaryData);
      const kws = getSummaryKeywords(summaryData);
      const keywords = (kws.length ? kws : removeDummyKeywords(material?.keywords)).map(sanitizeMarkdownText);
      const core = getCoreContents(summaryData);
      const detailed = getDetailedCoreContents(summaryData);
      const questions = sanitizeList(getSummaryStringList(summaryData, 'studyQuestions'));
      const content = buildStudyLogContent(overview, keywords, core, detailed, questions);
      await materialService.createStudyLog({
        title: `${material?.title || '자료'} 요약`,
        keywords: keywords.join(', '),
        studyDate: new Date().toISOString().split('T')[0],
        learningContent: content,
        nextPlan: '',
      });
      alert('학습일지에 추가되었습니다.');
    } catch (e) {
      console.error('학습일지 추가 실패:', e);
      alert('학습일지 추가에 실패했습니다. 다시 시도해주세요.');
    } finally {
      setIsAddingStudyLog(false);
    }
  };

  // day.tasks 항목을 문자열로 정규화 (ai07 day.tasks = {title, description, ...} 객체 또는 문자열)
  const normalizeDayTask = (t) => {
    if (typeof t === 'string') return t;
    if (t && typeof t === 'object') return t.title || t.content || t.description || '';
    return String(t ?? '');
  };

  const normalizeRoadmapSteps = (source) => {
    const parsed = parseMaybeJson(source, source);
    const root = parsed?.roadmap || parsed?.roadmapData?.roadmap || parsed?.roadmapData || parsed || {};
    const weeks = root.weeks || root.steps || parsed?.weeks || parsed?.steps || [];
    if (!Array.isArray(weeks)) return [];
    return weeks.map((week, idx) => {
      const rawTasks = Array.isArray(week.tasks) ? week.tasks : [];
      // 신(新) 84일 구조: week.days[]가 있으면 일자별로 정규화
      const rawDays = Array.isArray(week.days) ? week.days : [];
      const weekNo = Number(week.week || week.weekNumber || week.stepOrder || idx + 1);
      const days = rawDays.map((day, dayIdx) => ({
        dayIndex: Number(day.day_index || dayIdx + 1),
        dayLabel: day.day_label || `${dayIdx + 1}일차`,
        title: day.title || `${dayIdx + 1}일차 학습`,
        objective: day.objective || '',
        coreConcepts: Array.isArray(day.core_concepts) ? day.core_concepts : [],
        tasks: (Array.isArray(day.tasks) ? day.tasks : []).map(normalizeDayTask).filter(Boolean),
        reviewQuestions: Array.isArray(day.review_questions) ? day.review_questions : [],
        practice: day.practice || '',
        deliverable: day.deliverable || '',
        checkpoint: day.checkpoint || '',
        completed: !!day.completed,
      }));
      return {
        stepId: week.stepId || week.id || `week-${weekNo}`,
        stepOrder: weekNo,
        title: week.title || `${idx + 1}주차`,
        description: week.objective || week.goal || week.description || week.week_summary || '',
        weekSummary: week.week_summary || '',
        days,
        tasks: rawTasks.map((task, taskIdx) => (typeof task === 'string'
          ? { taskId: `week-${idx + 1}-task-${taskIdx + 1}`, taskOrder: taskIdx + 1, content: task, isCompleted: false }
          : { taskId: task.taskId || task.id || `week-${idx + 1}-task-${taskIdx + 1}`, taskOrder: task.taskOrder || taskIdx + 1, content: task.content || task.title || String(task), isCompleted: !!task.isCompleted }))
      };
    });
  };

  const renderAiStatus = (response, onRetry) => {
    const normalized = normalizeAiResponse(response);
    if (normalized.success !== false) return null;
    return (
      <div className="glass-panel" style={{ padding: '16px', borderLeft: '4px solid #EF4444', backgroundColor: '#FEF2F2', color: '#991B1B', marginBottom: '16px' }}>
        <div style={{ fontWeight: 700, marginBottom: '6px' }}>{normalized.message}</div>
        {normalized.errorCode && <div style={{ fontSize: '12px', color: '#B45309' }}>오류 코드: {normalized.errorCode}</div>}
        {isRetryableAiError(normalized) && onRetry && (
          <button className="btn-outline" style={{ width: 'auto', marginTop: '12px', padding: '8px 16px', borderRadius: '20px' }} onClick={onRetry}>
            다시 생성
          </button>
        )}
      </div>
    );
  };

  // ---------------- 인증 체크 ----------------
  useEffect(() => {
    if (!userId) {
      alert('로그인이 필요한 기능입니다. 로그인 페이지로 이동합니다.');
      navigate('/login');
    }
  }, [userId, navigate]);

  // ---------------- 데이터 로딩 ----------------
  const loadMaterialDetail = async () => {
    try {
      setIsLoadingDetail(true);
      const detail = await materialService.getMaterialDetail(id);
      setMaterial(detail);
      if (detail.extractionStatus === 'SUCCESS') {
        loadTabData(detail.materialId);
      }
    } catch (e) {
      console.error('자료 상세 정보 로드 실패:', e);
    } finally {
      setIsLoadingDetail(false);
    }
  };

  const loadTabData = async (materialId) => {
    // 1. 요약 정보 로드
    setSummaryLoading(true);
    try {
      const summary = await materialService.getSummary(materialId);
      setSummaryData(summary);
    } catch (e) {
      console.warn('AI 요약 정보가 아직 없습니다:', e);
    } finally {
      setSummaryLoading(false);
    }

    // 2. 퀴즈 정보 로드
    try {
      const quizList = await materialService.getQuizzes(materialId);
      setQuizzes(Array.isArray(quizList) ? quizList : []);
    } catch (e) {
      console.warn('AI 퀴즈 정보 로드 실패:', e);
    }

    // 2-1. 이미 생성된 오답노트 로드 → quizId별 매핑(버튼 "오답노트 보기" 판별)
    try {
      const { items } = await reviewNoteService.getReviewNotes();
      const map = {};
      (items || []).forEach((n) => { if (n.quizId != null) map[n.quizId] = n; });
      setReviewNotesByQuiz(map);
    } catch (e) {
      console.warn('오답노트 목록 로드 실패:', e);
    }

    // 3. 로드맵 정보 로드
    try {
      const roadmap = await materialService.getRoadmap(materialId);
      setRoadmapData(roadmap);
      setRoadmapSteps(normalizeRoadmapSteps(roadmap?.roadmapData || roadmap));
    } catch (e) {
      console.warn('AI 로드맵 정보 로드 실패:', e);
    }

    // 4. 메모 정보 로드
    try {
      const memo = await materialService.getMemo(materialId);
      setMemoText(memo?.content || '');
    } catch (e) {
      console.warn('메모 정보 로드 실패:', e);
    }
  };

  useEffect(() => {
    if (userId && id) {
      loadMaterialDetail();
    }
  }, [userId, id]);

  // ---------------- PENDING / PROCESSING 폴링 ----------------
  useEffect(() => {
    let pollInterval;
    if (material && (material.extractionStatus === 'PENDING' || material.extractionStatus === 'PROCESSING')) {
      pollInterval = setInterval(async () => {
        try {
          const freshDetail = await materialService.getMaterialDetail(id);
          if (freshDetail.extractionStatus !== 'PENDING' && freshDetail.extractionStatus !== 'PROCESSING') {
            setMaterial(freshDetail);
            loadTabData(freshDetail.materialId);
          }
        } catch (e) {
          console.error("폴링 오류:", e);
        }
      }, 5000);
    }
    return () => {
      if (pollInterval) clearInterval(pollInterval);
    };
  }, [material, id]);

  // 채팅 메시지 끝으로 자동 스크롤
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatMessages]);

  // ---------------- 핸들러 ----------------

  // 퀴즈 옵션 선택
  const handleSelectOption = (questionIdx, optionIdx) => {
    setUserAnswers(prev => ({
      ...prev,
      [questionIdx]: optionIdx
    }));
  };

  // 오답노트 작성하기: 현재 퀴즈에서 틀린 문제를 모아 백엔드로 전송 → AI(또는 폴백) PDF 오답노트 생성
  const handleCreateReviewNote = async (quizId, questions) => {
    if (isCreatingReviewNote) return;
    const wrong = questions.filter((q, idx) => userAnswers[idx] !== undefined && userAnswers[idx] !== q.answer);
    if (wrong.length === 0) { alert('틀린 문제가 없어 오답노트를 생성하지 않았습니다.'); return; }
    try {
      setIsCreatingReviewNote(true);
      const note = await reviewNoteService.createFromQuiz(quizId, userAnswers, {
        materialId: Number(id),
        materialTitle: material?.title,
        difficulty: quizSettings.difficulty,
      });
      setReviewNotesByQuiz((prev) => ({ ...prev, [quizId]: note }));
      setReviewNoteResult(note);
    } catch (e) {
      console.error('오답노트 생성 실패:', e);
      const msg = e?.response?.data?.message || '오답노트 생성에 실패했습니다. 잠시 후 다시 시도해주세요.';
      setReviewNoteResult({ error: true, message: msg, errorCode: e?.response?.data?.error_code || 'REVIEW_NOTE_CREATE_FAILED', _retryQuizId: quizId, _retryQuestions: questions });
    } finally {
      setIsCreatingReviewNote(false);
    }
  };

  // 오답노트 PDF 컴퓨터에 저장 (GET /api/review-notes/{id}/download)
  const handleDownloadReviewNote = async (reviewNoteId, fallbackUrl) => {
    try {
      const data = await reviewNoteService.getDownloadUrl(reviewNoteId);
      const url = data?.url || data?.downloadUrl || fallbackUrl;
      if (!url) { alert('이 오답노트에는 아직 PDF가 없습니다.'); return; }
      window.open(url, '_blank', 'noopener');
    } catch (e) {
      console.error('오답노트 다운로드 실패:', e);
      alert('PDF를 여는 중 문제가 발생했습니다.');
    }
  };

  // ---------------- 로드맵 → 플래너 생성 (플래너 도메인 전용) ----------------
  // roadmapData.weeks[].days[] 를 플래너 84개 항목으로 변환한다. 주간일정과 절대 연결하지 않는다.
  const buildPlannerItemsFromRoadmap = () => {
    const src = roadmapData?.roadmapData || roadmapData;
    let parsed = src;
    try { if (typeof src === 'string') parsed = JSON.parse(src); } catch { parsed = {}; }
    const root = parsed?.roadmap || parsed?.roadmapData?.roadmap || parsed?.roadmapData || parsed || {};
    const weeks = root.weeks || root.steps || parsed?.weeks || [];
    if (!Array.isArray(weeks)) return [];
    const items = [];
    weeks.forEach((w, wi) => {
      const weekNo = Number(w.week || w.weekNumber || wi + 1);
      const days = Array.isArray(w.days) ? w.days : [];
      days.forEach((d, di) => {
        const rawTasks = Array.isArray(d.tasks) ? d.tasks : [];
        const tasks = rawTasks
          .map((t) => (typeof t === 'string' ? t : [t.title, t.description].filter(Boolean).join(': ')))
          .filter(Boolean);
        const minutes = rawTasks.reduce((s, t) => s + (typeof t === 'object' ? Number(t.estimated_minutes || t.estimatedMinutes || 0) : 0), 0);
        items.push({
          week: weekNo,
          dayIndex: Number(d.day_index || di + 1),
          title: d.title || `${di + 1}일차 학습`,
          objective: d.objective || '',
          tasks,
          coreConcepts: Array.isArray(d.core_concepts) ? d.core_concepts : [],
          reviewQuestions: Array.isArray(d.review_questions) ? d.review_questions : [],
          checkpoint: d.checkpoint || '',
          deliverable: d.deliverable || '',
          targetMinutes: minutes > 0 ? minutes : null,
        });
      });
    });
    return items;
  };

  const handleOpenPlannerModal = () => {
    setPlannerError(null);
    setPlannerResult(null);
    const items = buildPlannerItemsFromRoadmap();
    if (items.length !== 84) {
      setPlannerError('84일 로드맵이 필요합니다. 먼저 AI 84일 로드맵을 재생성해주세요.');
      return;
    }
    setPlannerStartDate(new Date().toISOString().slice(0, 10));
    setIsPlannerModalOpen(true);
  };

  const handleCreatePlanner = async (force = false) => {
    if (isCreatingPlanner) return;
    const items = buildPlannerItemsFromRoadmap();
    if (items.length !== 84) { setPlannerError('84일 로드맵이 필요합니다. 먼저 AI 84일 로드맵을 재생성해주세요.'); return; }
    try {
      setIsCreatingPlanner(true);
      setPlannerError(null);
      const res = await plannerService.createFromRoadmap({
        materialId: Number(id),
        roadmapId: roadmapData?.roadmapId,
        sourceTitle: material?.title,
        subject: material?.title,
        startDate: plannerStartDate,
        force,
        items,
      });
      if (res?.duplicate && !force) {
        if (window.confirm('이미 이 로드맵으로 생성된 플래너가 있습니다. 다시 생성하면 기존 항목을 유지한 채 추가됩니다. 계속하시겠습니까?')) {
          await handleCreatePlanner(true);
        }
        return;
      }
      setPlannerResult({ createdCount: res?.createdCount ?? items.length, message: res?.message || `${items.length}개의 플래너가 생성되었습니다.` });
    } catch (e) {
      console.error('플래너 생성 실패:', e);
      setPlannerError(e?.response?.data?.message || '플래너 생성에 실패했습니다. 잠시 후 다시 시도해주세요.');
    } finally {
      setIsCreatingPlanner(false);
    }
  };

  // 퀴즈 생성 신청
  const handleGenerateQuiz = async () => {
    try {
      setIsGeneratingQuiz(true);
      // G. 생성 시작 즉시 이전/실패 퀴즈를 화면에서 내린다(stale quiz 방지).
      setQuizError(null);
      setSelectedQuizId(null);
      // R. 문항 수 5~20 보정 (빈 값/미입력 → 10). 보정값을 상태에도 반영.
      let appliedCount = parseInt(quizSettings.count, 10);
      if (Number.isNaN(appliedCount)) appliedCount = 10;
      if (appliedCount < 5) appliedCount = 5;
      if (appliedCount > 20) appliedCount = 20;
      if (appliedCount !== quizSettings.count) setQuizSettings((s) => ({ ...s, count: appliedCount }));
      const req = {
        difficulty: quizSettings.difficulty,
        questionCount: appliedCount,
        pageRange: quizSettings.range,
        sourceMode: 'PDF_BASED', // 퀴즈는 PDF/DOCX 자료 본문 기준(로드맵 day 아님)
      };
      const newQuiz = await materialService.generateQuiz(id, req);

      // F. 서버 실패 또는 H. hard 클라이언트 보조검증 실패 → 문제 카드를 렌더링하지 않는다.
      const serverFailed = newQuiz?.success === false;
      const hardInvalid = !serverFailed && isQuizHardInvalid(newQuiz);
      if (serverFailed || hardInvalid) {
        setQuizError(serverFailed
          ? normalizeAiResponse(newQuiz)
          : normalizeAiResponse({
              success: false,
              errorCode: 'QUIZ_VALIDATE_FAILED',
              message: '요청한 어려움 난이도가 충분히 반영되지 않았습니다. 다시 생성해 주세요.',
              retryable: true,
              difficultyValidation: newQuiz?.difficultyValidation,
            }));
        setSelectedQuizId(null); // 불합격/이전 퀴즈 숨김
        return;                  // quizzes 목록에 추가하지 않음
      }

      setQuizError(null);
      setQuizzes(prev => [newQuiz, ...prev]);
      setSelectedQuizId(newQuiz.quizId);
      setUserAnswers({});
      setIsQuizSettingsOpen(false);
    } catch (e) {
      console.error('퀴즈 생성 실패:', e);
      setSelectedQuizId(null);
      setQuizError(normalizeAiException(e));
    } finally {
      setIsGeneratingQuiz(false);
    }
  };

  // 로드맵 주차별 태스크 토글
  const handleToggleTask = async (taskId) => {
    try {
      // Optimistic update
      setRoadmapSteps(prevSteps => {
        return prevSteps.map(step => ({
          ...step,
          tasks: step.tasks.map(task => {
            if (task.taskId === taskId) {
              return { ...task, isCompleted: !task.isCompleted };
            }
            return task;
          })
        }));
      });
      // Call API
      await materialService.toggleRoadmapTask(id, taskId);
    } catch (e) {
      console.error('상태 변경 실패:', e);
      // Revert optimistic update
      setRoadmapSteps(prevSteps => {
        return prevSteps.map(step => ({
          ...step,
          tasks: step.tasks.map(task => {
            if (task.taskId === taskId) {
              return { ...task, isCompleted: !task.isCompleted };
            }
            return task;
          })
        }));
      });
      alert('상태 변경 도중 오류가 발생했습니다.');
    }
  };

  // 84일 로드맵 일자(day) 완료 토글
  const handleToggleDay = async (weekNo, dayIndex) => {
    const flip = (steps) => steps.map(step => (Number(step.stepOrder) !== Number(weekNo) ? step : {
      ...step,
      days: (step.days || []).map(d => (Number(d.dayIndex) === Number(dayIndex) ? { ...d, completed: !d.completed } : d)),
    }));
    setRoadmapSteps(prev => flip(prev));
    try {
      await materialService.toggleRoadmapDay(id, Number(weekNo), Number(dayIndex));
    } catch (e) {
      console.error('일자 상태 변경 실패:', e);
      setRoadmapSteps(prev => flip(prev)); // revert
      alert('상태 변경 도중 오류가 발생했습니다.');
    }
  };

  // 84일 로드맵 재생성 (레거시 → 신규 교체) — 난이도 반영
  const ROADMAP_LEVELS = [
    { value: 'beginner', label: '초보자', desc: '기본 개념·용어·환경 설정·따라 하기 중심' },
    { value: 'intermediate', label: '중급자', desc: '응용·코드 흐름 이해·오류 분석·구조 비교 포함' },
    { value: 'advanced', label: '상급자', desc: '고급 개념·설계 판단·테스트·예외 처리·유지보수 관점' },
  ];
  const handleRegenerateRoadmap = async () => {
    if (isRegeneratingRoadmap) return;
    const levelLabel = ROADMAP_LEVELS.find(l => l.value === roadmapLevel)?.label || '중급자';
    if (!window.confirm(`AI가 ${levelLabel} 난이도로 12주 × 7일(84일) 로드맵을 다시 생성합니다. 기존 로드맵은 교체됩니다. 계속할까요?`)) return;
    try {
      setIsRegeneratingRoadmap(true);
      setRoadmapError(null);
      const roadmap = await materialService.regenerateRoadmap(id, roadmapLevel);
      // C. 실패 응답(HTTP 200 + success:false)으로 기존 정상 로드맵을 덮어쓰지 않는다.
      const normalized = normalizeAiResponse(roadmap);
      const newSteps = normalizeRoadmapSteps(roadmap?.roadmapData || roadmap);
      if (normalized.success === false || newSteps.length === 0) {
        setRoadmapError(normalized.success === false
          ? normalized
          : normalizeAiResponse({ success: false, errorCode: 'ROADMAP_VALIDATE_FAILED', message: '로드맵 재생성에 실패했습니다. 잠시 후 다시 시도해주세요.', retryable: true }));
        return; // roadmapData/roadmapSteps 유지
      }
      setRoadmapData(roadmap);
      setRoadmapSteps(newSteps);
    } catch (e) {
      console.error('로드맵 재생성 실패:', e);
      // 네트워크/타임아웃 등 예외도 generic alert 대신 오류 코드/메시지 카드로 표시.
      setRoadmapError(normalizeAiException(e));
    } finally {
      setIsRegeneratingRoadmap(false);
    }
  };

  // 메모 저장
  const handleSaveMemo = async () => {
    try {
      setIsSavingMemo(true);
      await materialService.saveMemo(id, memoText);
      alert('메모가 저장되었습니다.');
    } catch (e) {
      console.error('메모 저장 실패:', e);
      alert('메모 저장 도중 오류가 발생했습니다.');
    } finally {
      setIsSavingMemo(false);
    }
  };

  // 자료 삭제
  const handleDeleteMaterial = async () => {
    if (window.confirm('정말로 이 자료를 삭제하시겠습니까? 삭제 후에는 복구할 수 없습니다.')) {
      try {
        await materialService.deleteMaterial(id);
        alert('자료가 삭제되었습니다.');
        navigate('/archive');
      } catch (e) {
        console.error('자료 삭제 실패:', e);
        alert('자료 삭제 중 오류가 발생했습니다.');
      }
    }
  };

  // AI 챗봇 메시지 전송
  const handleSendChat = async (e) => {
    if (e) e.preventDefault();
    if (!chatInput.trim()) return;

    const userMsg = chatInput.trim();
    setChatInput('');
    setChatMessages(prev => [...prev, { sender: 'user', text: userMsg }]);

    try {
      setIsAskingQuestion(true);
      setChatMessages(prev => [...prev, { sender: 'ai', text: '질문 답변을 생성하는 중입니다...', isThinking: true }]);
      const res = await materialService.askQuestion(id, { userQuestion: userMsg });
      const normalized = normalizeAiResponse(res);
      setChatMessages(prev => {
        const filtered = prev.filter(m => !m.isThinking);
        return [...filtered, { sender: 'ai', text: normalized.success === false ? normalized.message : (res.aiAnswer || '문서 기준으로는 확인되지 않습니다.'), response: normalized }];
      });
    } catch (e) {
      console.error('AI 질문 실패:', e);
      const normalized = normalizeAiException(e);
      setChatMessages(prev => {
        const filtered = prev.filter(m => !m.isThinking);
        return [...filtered, { sender: 'ai', text: normalized.message, response: normalized }];
      });
    } finally {
      setIsAskingQuestion(false);
    }
  };

  // ---------------- 로드맵 노드 색상 설정 ----------------
  const getNodeColor = (week) => {
    if (week === 7) return '#F59E0B';
    if ([3, 4, 8, 9].includes(week)) return '#06B6D4';
    return '#10B981';
  };

  // ---------------- 퀴즈 파서 ----------------
  const parseQuizQuestions = (quizSource) => {
    try {
      const parsedRaw = typeof quizSource === 'string' ? parseMaybeJson(quizSource, []) : quizSource;
      const parsed = Array.isArray(parsedRaw)
        ? parsedRaw
        : (parsedRaw?.quizzes || parsedRaw?.questions || parseMaybeJson(parsedRaw?.quizData, []));
      return (Array.isArray(parsed) ? parsed : []).map((item, idx) => {
        const options = item.options || item.choices || item.answers || [];
        let answerIndex = typeof item.answerIndex === 'number' ? item.answerIndex : (typeof item.answer === 'number' ? item.answer : 0);
        if (typeof item.answer === 'string' && Array.isArray(options) && options.includes(item.answer)) answerIndex = options.indexOf(item.answer);
        return {
          q: item.question || item.q || `Q${idx + 1}. 문제`,
          options,
          answer: answerIndex,
          explanation: item.explanation || '',
          difficulty: item.difficulty || quizSettings.difficulty,
        };
      });
    } catch (e) {
      console.error("Quiz JSON 파싱 실패:", e);
      return [];
    }
  };

  // H. hard 퀴즈 클라이언트 보조 검증 — ai07이 단순 문제를 내려보내면 화면에 띄우지 않는다.
  const HARD_SIMPLE_PATTERNS = [/주요 목적은 무엇인가요/, /주요 역할은 무엇인가요/, /정의는 무엇인가요/, /사용 이유는 무엇인가요/];
  const labelToDifficultyCode = { '쉬움': 'easy', '보통': 'normal', '어려움': 'hard' };
  const isQuizHardInvalid = (quiz) => {
    if (!quiz) return false;
    const requested = quiz.difficultyRequested || labelToDifficultyCode[quiz.difficulty] || 'normal';
    if (requested !== 'hard') return false;
    if (quiz.difficultyValidation?.passed === false) return true;
    if (quiz.difficultyApplied && quiz.difficultyApplied !== 'hard') return true;
    const questions = parseQuizQuestions(quiz.quizzes?.length ? quiz.quizzes : quiz.quizData);
    if (questions.length === 0) return false; // 빈 퀴즈는 검증 실패 경로에서 처리
    return questions.some((q) => {
      const text = (q.q || '').trim();
      if (text.length < 80) return true;
      return HARD_SIMPLE_PATTERNS.some((p) => p.test(text));
    });
  };

  // ---------------- 렌더링 도우미 ----------------
  const renderPdfRightPanel = () => {
    switch (activePdfTool) {
      case 'summary': {
        const summaryStatus = normalizeAiResponse(summaryData);
        const summaryTextStatusMessage = getTextStatusMessage(summaryData?.textStatus);
        const summaryOverview = sanitizeMarkdownText(getSummaryOverview(summaryData));
        const summaryKeywords = getSummaryKeywords(summaryData);
        const cleanKeywords = (summaryKeywords.length > 0 ? summaryKeywords : removeDummyKeywords(material?.keywords)).map(sanitizeMarkdownText).filter(Boolean);
        const coreContents = getCoreContents(summaryData);           // B. 핵심 내용 (≥10 목표)
        const detailedCore = getDetailedCoreContents(summaryData);   // C. 세부 핵심 내용 (≥40 목표)
        const visibleDetailed = showAllDetailed ? detailedCore : detailedCore.slice(0, 10);
        // O. 핵심/세부 핵심 내용을 '한 카드'에 담는 단일 텍스트 (여러 카드 생성 금지, 개수 표시 금지)
        const coreContentText = getCoreContentText(summaryData);
        const detailedContentText = getDetailedContentText(summaryData);
        const learningPoints = sanitizeList(getSummaryStringList(summaryData, 'learningPoints'));
        const practicePoints = sanitizeList(getSummaryStringList(summaryData, 'practicePoints'));
        const studyQuestions = sanitizeList(getSummaryStringList(summaryData, 'studyQuestions'));

        // C. PDF_TEXT_EMPTY 류 친화적 안내
        const emptyCodes = ['PDF_TEXT_EMPTY', 'PDF_OCR_REQUIRED', 'PDF_EXTRACTION_FAILED'];
        const isTextEmpty = summaryStatus.success === false && emptyCodes.includes(summaryStatus.errorCode);
        const isPlannerMaterial = (material?.materialType === 'PLANNER') || !!material?.plannerId;
        // F. 로딩 중(아직 요약 없음) → skeleton + 단계별 진행 표시
        const showAnalyzing = summaryLoading && !summaryData;

        return (
            <div className="animate-fade-in" style={{ paddingBottom: '32px' }}>
              <h3 style={{ margin: '0 0 24px', fontSize: '20px' }}>AI 핵심 요약 노트</h3>
              <p style={{ color: 'var(--color-text-muted)', fontSize: '15px', marginBottom: '24px' }}>
                문서 전체 맥락을 분석하여 도출된 종합 핵심 요약입니다.
              </p>

              {showAnalyzing ? (
                <AnalyzingProgress />
              ) : isTextEmpty ? (
                <div className="glass-panel" style={{ padding: '20px', borderLeft: '4px solid #F59E0B', backgroundColor: '#FFFBEB', marginBottom: '8px' }}>
                  <h4 style={{ margin: '0 0 8px', fontSize: '16px', color: '#92400E' }}>⚠️ PDF에서 추출 가능한 텍스트가 없습니다.</h4>
                  <p style={{ margin: '0 0 8px', fontSize: '14px', color: '#92400E' }}>다음과 같은 경우에 발생할 수 있어요:</p>
                  <ul style={{ margin: '0 0 16px', paddingLeft: '18px', color: '#92400E', fontSize: '14px', lineHeight: '1.7' }}>
                    <li>이미지 기반 PDF (그림/사진으로만 구성)</li>
                    <li>빈 양식 PDF</li>
                    <li>스캔본 PDF</li>
                    <li>생성된 플래너 PDF가 텍스트 레이어 없이 이미지로 저장된 경우</li>
                  </ul>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                    <button className="btn-primary" style={{ width: 'auto', padding: '8px 16px', borderRadius: '20px' }}
                      onClick={() => loadTabData(material.materialId)}>다시 생성</button>
                    <button className="btn-outline" style={{ width: 'auto', padding: '8px 16px', borderRadius: '20px' }}
                      onClick={() => { alert('OCR 재분석은 서버에서 자료를 다시 추출한 뒤 동작합니다. 잠시 후 다시 생성 버튼을 눌러주세요.'); loadTabData(material.materialId); }}>OCR로 다시 분석</button>
                    {isPlannerMaterial && (
                      <button className="btn-outline" style={{ width: 'auto', padding: '8px 16px', borderRadius: '20px' }}
                        onClick={() => navigate('/planner')}>플래너 데이터 기반으로 분석</button>
                    )}
                    <button className="btn-outline" style={{ width: 'auto', padding: '8px 16px', borderRadius: '20px' }}
                      onClick={() => alert('선택 가능한 텍스트가 포함된 원본 PDF(텍스트 레이어 있는 PDF)를 업로드하면 요약 품질이 가장 좋습니다.')}>원본 텍스트 PDF 업로드 안내</button>
                  </div>
                </div>
              ) : (
                <>
                  {renderAiStatus(summaryStatus, () => loadTabData(material.materialId))}
                  {summaryTextStatusMessage && summaryStatus.success !== false && (
                    <div className="glass-panel" style={{ padding: '14px 16px', borderLeft: '4px solid #F59E0B', backgroundColor: '#FFFBEB', color: '#92400E', marginBottom: '16px' }}>
                      {summaryTextStatusMessage}
                    </div>
                  )}
                </>
              )}

              {!isTextEmpty && !showAnalyzing && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                {/* 1. 문서 개요 */}
                <div className="glass-panel" style={{ padding: '20px', borderLeft: '4px solid var(--color-primary)' }}>
                  <h4 style={{ margin: '0 0 12px', fontSize: '16px', color: 'var(--color-text-main)' }}>📌 문서 개요</h4>
                  <p style={{ margin: 0, fontSize: '15px', lineHeight: '1.7', color: 'var(--color-text-muted)', whiteSpace: 'pre-wrap' }}>
                    {summaryStatus.success === false ? getAiErrorMessage(summaryStatus.errorCode, summaryStatus.textStatus, summaryStatus.message) : (summaryOverview || (summaryData ? '요약 내용이 아직 생성되지 않았습니다.' : '문서 내용을 분석하고 있습니다.'))}
                  </p>
                </div>

                {/* 2. 핵심 키워드 (클릭 가능) */}
                <div>
                  <h4 style={{ margin: '0 0 8px', fontSize: '16px', color: 'var(--color-text-main)' }}>🔑 핵심 키워드</h4>
                  <p style={{ margin: '0 0 12px', fontSize: '13px', color: 'var(--color-text-muted)' }}>키워드를 클릭하면 GPT/Wikipedia 기반 개념 정의를 볼 수 있어요.</p>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                    {cleanKeywords.length > 0 ? (
                        cleanKeywords.map((kw) => (
                            <button
                              key={kw}
                              onClick={() => setActiveKeyword(kw)}
                              className="tag"
                              style={{ backgroundColor: '#F3F4F6', color: 'var(--color-text-main)', border: '1px solid var(--color-border)', cursor: 'pointer', transition: 'all 0.15s' }}
                              onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = '#ECFDF5'; e.currentTarget.style.borderColor = 'var(--color-primary)'; }}
                              onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = '#F3F4F6'; e.currentTarget.style.borderColor = 'var(--color-border)'; }}
                            >#{kw}</button>
                        ))
                    ) : (
                        <span style={{ color: 'var(--color-text-muted)', fontSize: '14px' }}>핵심 키워드가 아직 생성되지 않았습니다.</span>
                    )}
                  </div>
                </div>

                {/* 3. 핵심 내용 (O. 한 카드에 전체 렌더링, 개수 표시/카드 분할 금지) */}
                <div>
                  <h4 style={{ margin: '0 0 4px', fontSize: '16px', color: 'var(--color-text-main)' }}>🧩 핵심 내용</h4>
                  <p style={{ margin: '0 0 16px', fontSize: '13px', color: 'var(--color-text-muted)' }}>문서에서 도출한 핵심 내용입니다.</p>
                  <div className="glass-panel" style={{ padding: '18px 20px', borderLeft: '4px solid var(--color-primary)' }}>
                    {coreContentText ? (
                      <p style={{ margin: 0, fontSize: '14.5px', lineHeight: '1.8', color: 'var(--color-text-main)', whiteSpace: 'pre-line' }}>
                        {coreContentText}
                      </p>
                    ) : (
                      <p style={{ margin: 0, color: 'var(--color-text-muted)', fontSize: '14px' }}>{summaryStatus.success === false ? getAiErrorMessage(summaryStatus.errorCode, summaryStatus.textStatus, summaryStatus.message) : '요약 내용이 아직 생성되지 않았습니다.'}</p>
                    )}
                  </div>
                </div>

                {/* 4. 세부 핵심 내용 (O. 한 카드에 전체 렌더링, 개수 표시/카드 분할 금지) */}
                <div>
                  <h4 style={{ margin: '0 0 4px', fontSize: '16px', color: 'var(--color-text-main)' }}>📑 세부 핵심 내용</h4>
                  <p style={{ margin: '0 0 16px', fontSize: '13px', color: 'var(--color-text-muted)' }}>문서의 세부 내용을 줄 단위로 정리했습니다.</p>
                  <div className="glass-panel" style={{ padding: '18px 20px', borderLeft: '4px solid var(--color-primary)' }}>
                    {detailedContentText ? (
                      <p style={{ margin: 0, fontSize: '14px', lineHeight: '1.8', color: 'var(--color-text-main)', whiteSpace: 'pre-line' }}>
                        {detailedContentText}
                      </p>
                    ) : (
                      <p style={{ margin: 0, color: 'var(--color-text-muted)', fontSize: '14px' }}>{summaryStatus.success === false ? getAiErrorMessage(summaryStatus.errorCode, summaryStatus.textStatus, summaryStatus.message) : '세부 핵심 내용이 아직 생성되지 않았습니다.'}</p>
                    )}
                  </div>
                </div>

                {/* 4. 학습 포인트 */}
                {learningPoints.length > 0 && (
                  <div>
                    <h4 style={{ margin: '0 0 12px', fontSize: '16px', color: 'var(--color-text-main)' }}>🎯 학습 포인트</h4>
                    <div className="glass-panel" style={{ padding: '16px 18px', borderLeft: '4px solid #3B82F6' }}>
                      <ul style={{ margin: 0, paddingLeft: '18px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                        {learningPoints.map((p, i) => (
                          <li key={i} style={{ fontSize: '14px', lineHeight: '1.6', color: 'var(--color-text-muted)' }}>{p}</li>
                        ))}
                      </ul>
                    </div>
                  </div>
                )}

                {/* 5. 실습 관점 정리 */}
                {practicePoints.length > 0 && (
                  <div>
                    <h4 style={{ margin: '0 0 12px', fontSize: '16px', color: 'var(--color-text-main)' }}>🛠️ 실습 관점 정리</h4>
                    <div className="glass-panel" style={{ padding: '16px 18px', borderLeft: '4px solid #8B5CF6' }}>
                      <ul style={{ margin: 0, paddingLeft: '18px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                        {practicePoints.map((p, i) => (
                          <li key={i} style={{ fontSize: '14px', lineHeight: '1.6', color: 'var(--color-text-muted)' }}>{p}</li>
                        ))}
                      </ul>
                    </div>
                  </div>
                )}

                {/* 6. AI 학습 질문 */}
                {studyQuestions.length > 0 && (
                  <div>
                    <h4 style={{ margin: '0 0 12px', fontSize: '16px', color: 'var(--color-text-main)' }}>❓ AI 학습 질문</h4>
                    <div className="glass-panel" style={{ padding: '16px 18px', borderLeft: '4px solid #F59E0B' }}>
                      <ul style={{ margin: 0, paddingLeft: '18px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                        {studyQuestions.map((q, i) => (
                          <li key={i} style={{ fontSize: '14px', lineHeight: '1.6', color: 'var(--color-text-muted)' }}>{q}</li>
                        ))}
                      </ul>
                    </div>
                  </div>
                )}

                {/* D. 학습일지에 추가 */}
                {summaryStatus.success !== false && (summaryOverview || coreContents.length > 0) && (
                  <div style={{ display: 'flex', justifyContent: 'flex-end', borderTop: '1px solid var(--color-border)', paddingTop: '20px' }}>
                    <button
                      onClick={handleAddToStudyLog}
                      disabled={isAddingStudyLog}
                      className="btn-primary"
                      style={{ width: 'auto', padding: '12px 28px', borderRadius: '24px', fontWeight: 'bold', fontSize: '15px', cursor: isAddingStudyLog ? 'default' : 'pointer', opacity: isAddingStudyLog ? 0.6 : 1, display: 'inline-flex', alignItems: 'center', gap: '8px' }}
                    >
                      <Edit3 size={16} /> {isAddingStudyLog ? '추가 중…' : '학습일지에 추가'}
                    </button>
                  </div>
                )}
              </div>
              )}
            </div>
        );
      }
      case 'quiz': {
        const activeQuiz = quizzes.find(q => q.quizId === selectedQuizId);
        const activeQuizStatus = normalizeAiResponse(activeQuiz);
        const rawParsedQuestions = activeQuiz ? parseQuizQuestions(activeQuiz.quizzes?.length ? activeQuiz.quizzes : activeQuiz.quizData) : [];
        // F/H. hard 보조검증 실패한 퀴즈는 문제 카드를 렌더링하지 않는다(단순 문제 노출 차단).
        const activeQuizHardInvalid = isQuizHardInvalid(activeQuiz);
        const parsedQuestions = activeQuizHardInvalid ? [] : rawParsedQuestions;

        // 오답노트 작성하기 버튼 상태 (B)
        const rnAnsweredCount = parsedQuestions.filter((q, i) => userAnswers[i] !== undefined).length;
        const rnWrongCount = parsedQuestions.filter((q, i) => userAnswers[i] !== undefined && userAnswers[i] !== q.answer).length;
        const rnExistingNote = activeQuiz ? reviewNotesByQuiz[activeQuiz.quizId] : null;
        let rnButtonLabel = '오답노트 작성하기';
        let rnButtonDisabled = true;
        let rnButtonGuide = '';
        if (rnExistingNote) {
          rnButtonLabel = '오답노트 보기';
          rnButtonDisabled = false;
        } else if (!activeQuiz || parsedQuestions.length === 0 || rnAnsweredCount === 0) {
          rnButtonDisabled = true;
          rnButtonGuide = '퀴즈를 풀고 틀린 문제가 있으면 오답노트를 만들 수 있습니다.';
        } else if (rnWrongCount === 0) {
          rnButtonDisabled = true;
          rnButtonGuide = '틀린 문제가 없어 오답노트를 생성하지 않았습니다.';
        } else {
          rnButtonDisabled = false;
        }
        const onReviewNoteButton = () => {
          if (rnExistingNote) { navigate('/review-notes'); return; }
          handleCreateReviewNote(activeQuiz.quizId, parsedQuestions);
        };

        return (
            <div className="animate-fade-in" style={{ paddingBottom: '24px', display: 'flex', flexDirection: 'column', height: '100%' }}>
              {/* 상단 액션 영역 */}
              <div className="glass-panel" style={{ padding: '24px', marginBottom: '24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px' }}>
                <div style={{ flex: '1 1 auto', minWidth: '200px' }}>
                  <h3 style={{ margin: '0 0 8px', fontSize: '20px', color: 'var(--color-text-main)' }}>퀴즈 생성</h3>
                  <p style={{ margin: 0, color: 'var(--color-text-muted)', fontSize: '14px', wordBreak: 'keep-all' }}>원하는 문제 유형, 난이도 등으로 퀴즈 세트를 만들어보세요.</p>
                </div>
                <div style={{ display: 'flex', gap: '12px', alignItems: 'center', flex: '0 0 auto' }}>
                  <button
                      className="btn-outline"
                      style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 20px', borderRadius: '30px', whiteSpace: 'nowrap', flexShrink: 0, width: 'auto' }}
                      onClick={() => setIsQuizSettingsOpen(true)}
                      disabled={isGeneratingQuiz}
                  >
                    설정
                  </button>
                  <button
                      className="btn-primary"
                      style={{ padding: '10px 24px', borderRadius: '30px', fontWeight: 'bold', whiteSpace: 'nowrap', flexShrink: 0, width: 'auto' }}
                      onClick={handleGenerateQuiz}
                      disabled={isGeneratingQuiz}
                  >
                    {isGeneratingQuiz ? '생성 중...' : '생성'}
                  </button>
                  {/* A/B. 오답노트 작성하기 (틀린 문제가 있을 때 활성화, 이미 생성 시 "오답노트 보기") */}
                  <button
                      className={rnExistingNote ? 'btn-outline' : 'btn-primary'}
                      title={rnButtonGuide || undefined}
                      style={{ padding: '10px 20px', borderRadius: '30px', fontWeight: 'bold', whiteSpace: 'nowrap', flexShrink: 0, width: 'auto',
                        backgroundColor: rnExistingNote ? '#fff' : (rnButtonDisabled ? '#E5E7EB' : '#DC2626'),
                        color: rnExistingNote ? '#DC2626' : (rnButtonDisabled ? '#9CA3AF' : '#fff'),
                        borderColor: rnExistingNote ? '#DC2626' : undefined,
                        cursor: (rnButtonDisabled || isCreatingReviewNote) ? 'not-allowed' : 'pointer', opacity: isCreatingReviewNote ? 0.6 : 1 }}
                      onClick={onReviewNoteButton}
                      disabled={rnButtonDisabled || isCreatingReviewNote}
                  >
                    {isCreatingReviewNote ? '오답노트 생성 중…' : rnButtonLabel}
                  </button>
                </div>
              </div>
              {rnButtonGuide && (
                <div style={{ marginTop: '-12px', marginBottom: '20px', fontSize: '12.5px', color: 'var(--color-text-muted)', textAlign: 'right' }}>
                  {rnButtonGuide}
                </div>
              )}

              {renderAiStatus(quizError, handleGenerateQuiz)}

              {/* 퀴즈 내용 영역 */}
              {selectedQuizId === null ? (
                  <div className="animate-fade-in" style={{ flex: 1 }}>
                    <h4 style={{ margin: '0 0 16px', fontSize: '16px', color: 'var(--color-text-main)' }}>내 퀴즈</h4>
                    {quizzes.length === 0 ? (
                        <p style={{ color: 'var(--color-text-muted)', fontSize: '14px' }}>출제된 퀴즈가 없습니다. 우측 상단의 생성 버튼을 눌러보세요!</p>
                    ) : (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                          {quizzes.map(quiz => (
                              <div
                                  key={quiz.quizId}
                                  className="glass-panel hover-scale"
                                  style={{ padding: '20px', cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center', transition: 'all 0.2s', border: '1px solid transparent' }}
                                  onMouseEnter={(e) => e.currentTarget.style.border = '1px solid var(--color-primary)'}
                                  onMouseLeave={(e) => e.currentTarget.style.border = '1px solid transparent'}
                                  onClick={() => {
                                    setSelectedQuizId(quiz.quizId);
                                    setUserAnswers({});
                                  }}
                              >
                                <div>
                                  <h5 style={{ margin: '0 0 8px', fontSize: '16px', color: 'var(--color-text-main)' }}>
                                    {quiz.createdAt ? quiz.createdAt.split('T')[0] + ' ' + quiz.createdAt.split('T')[1].substring(0, 5) : '작성일 없음'}
                                  </h5>
                                  <p style={{ margin: 0, fontSize: '14px', color: 'var(--color-text-muted)' }}>문항: {quiz.questionCount}개 • 난이도: {quiz.difficulty} • 범위: {quiz.pageRange || '전체'}</p>
                                </div>
                                <ChevronRight size={20} color="var(--color-text-muted)" />
                              </div>
                          ))}
                        </div>
                    )}
                  </div>
              ) : (
                  <div className="animate-fade-in" style={{ flex: 1 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '24px' }}>
                      <button
                          className="btn-outline"
                          style={{ width: '40px', height: '40px', padding: 0, display: 'flex', justifyContent: 'center', alignItems: 'center', borderRadius: '50%' }}
                          onClick={() => setSelectedQuizId(null)}
                      >
                        <ArrowLeft size={20} />
                      </button>
                      <h4 style={{ margin: 0, fontSize: '18px', color: 'var(--color-text-main)' }}>퀴즈 풀이</h4>
                    </div>
                    {renderAiStatus(activeQuizStatus, handleGenerateQuiz)}
                    {(() => {
                      // G/H. 난이도 정책 표시 + hard fallback 경고
                      const labelToCode = { '쉬움': 'easy', '보통': 'normal', '어려움': 'hard' };
                      const codeToLabel = { easy: '쉬움', normal: '보통', hard: '어려움' };
                      const requested = activeQuiz?.difficultyRequested || labelToCode[activeQuiz?.difficulty] || 'normal';
                      const applied = activeQuiz?.difficultyApplied || null;
                      const POLICY = { easy: 'PDF에 직접 나온 내용 중심', normal: 'PDF 내용 기반에 응용 개념을 살짝 추가', hard: 'PDF 내용 기반에 응용 또는 실무 상황을 많이 포함' };
                      const sourceTrace = activeQuiz?.sourceTrace || null;
                      const policyText = activeQuiz?.difficultyPolicy || POLICY[requested] || '';
                      const validationReason = activeQuiz?.difficultyValidation?.reason;
                      // 단순 문제 패턴 탐지 (hard인데 "주요 역할은 무엇인가요?" 류)
                      const simplePat = /(주요 )?역할은 무엇인가요|무엇인가요\??$|무엇입니까\??$/;
                      const looksSimple = rawParsedQuestions.length > 0 && rawParsedQuestions.every(q => simplePat.test((q.q || '').trim()));
                      // activeQuizHardInvalid가 true면 무조건 경고 + 다시 생성 노출(문제 카드는 이미 숨겨짐).
                      const hardNotApplied = activeQuizHardInvalid || (requested === 'hard' && (
                        (applied && applied !== 'hard') ||
                        activeQuiz?.difficultyValidation?.passed === false ||
                        (!applied && looksSimple)
                      ));
                      return (
                        <div style={{ marginBottom: '16px' }}>
                          <div className="glass-panel" style={{ padding: '12px 16px', borderLeft: '4px solid var(--color-primary)', fontSize: '13.5px', color: 'var(--color-text-muted)' }}>
                            <div><b style={{ color: 'var(--color-text-main)' }}>출제 기준:</b> PDF 자료 기반</div>
                            <div><b style={{ color: 'var(--color-text-main)' }}>난이도:</b> {codeToLabel[applied] || codeToLabel[requested] || activeQuiz?.difficulty}</div>
                            <div><b style={{ color: 'var(--color-text-main)' }}>정책:</b> {policyText}</div>
                            {validationReason && <div><b style={{ color: 'var(--color-text-main)' }}>검증:</b> {sanitizeMarkdownText(validationReason)}</div>}
                            {sourceTrace && (sourceTrace.concepts || sourceTrace.evidence) && (
                              <div style={{ marginTop: '6px', fontSize: '12px', color: '#9CA3AF' }}>
                                {Array.isArray(sourceTrace.concepts) && sourceTrace.concepts.length > 0 && <span>근거 개념: {sourceTrace.concepts.join(', ')} </span>}
                                {sourceTrace.evidence && <span>· {sanitizeMarkdownText(String(sourceTrace.evidence))}</span>}
                              </div>
                            )}
                          </div>
                          {hardNotApplied && (
                            <div className="glass-panel" style={{ marginTop: '10px', padding: '12px 16px', borderLeft: '4px solid #F59E0B', backgroundColor: '#FFFBEB', color: '#92400E', fontSize: '13.5px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
                              <span>요청한 난이도가 충분히 반영되지 않았습니다. 같은 PDF 자료를 기준으로 다시 생성해주세요.</span>
                              <button className="btn-outline" style={{ padding: '6px 14px', borderRadius: '16px', fontSize: '12.5px', whiteSpace: 'nowrap' }} onClick={handleGenerateQuiz}>다시 생성</button>
                            </div>
                          )}
                        </div>
                      );
                    })()}
                    {parsedQuestions.length === 0 ? (
                        <p style={{ color: 'var(--color-text-muted)', fontSize: '14px' }}>{activeQuizStatus.success === false ? getAiErrorMessage(activeQuizStatus.errorCode, activeQuizStatus.textStatus, activeQuizStatus.message) : '퀴즈 형식 검증에 실패했습니다. 다시 생성해주세요.'}</p>
                    ) : (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '32px' }}>
                          {parsedQuestions.map((q, idx) => (
                              <div key={idx} className="glass-panel" style={{ padding: '24px', borderLeft: '4px solid var(--color-primary)' }}>
                                <h5 style={{ margin: '0 0 20px', fontSize: '16px', color: 'var(--color-text-main)', lineHeight: '1.5' }}>{q.q}</h5>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                                  {q.options.map((opt, optIdx) => {
                                    const isSelected = userAnswers[idx] === optIdx;
                                    const isCorrectAnswer = optIdx === q.answer;
                                    const hasAnswered = userAnswers[idx] !== undefined;

                                    let optionBgColor = 'white';
                                    let optionTextColor = 'var(--color-text-main)';
                                    let optionBorderColor = 'var(--color-border)';

                                    if (isSelected) {
                                      if (isCorrectAnswer) {
                                        optionBgColor = '#DCFCE7';
                                        optionBorderColor = '#86EFAC';
                                        optionTextColor = '#166534';
                                      } else {
                                        optionBgColor = '#FEE2E2';
                                        optionBorderColor = '#FCA5A5';
                                        optionTextColor = '#991B1B';
                                      }
                                    } else if (hasAnswered && isCorrectAnswer) {
                                      optionBgColor = '#DCFCE7';
                                      optionBorderColor = '#86EFAC';
                                      optionTextColor = '#166534';
                                    }

                                    return (
                                        <button
                                            key={optIdx}
                                            onClick={() => handleSelectOption(idx, optIdx)}
                                            className="btn-outline"
                                            style={{
                                              width: '100%', height: 'auto', display: 'flex', alignItems: 'center',
                                              textAlign: 'left', fontWeight: 'normal', justifyContent: 'flex-start',
                                              fontSize: '15px', padding: '16px', borderRadius: '12px',
                                              backgroundColor: optionBgColor,
                                              borderColor: optionBorderColor,
                                              color: optionTextColor,
                                              transition: 'all 0.2s'
                                            }}
                                        >
                                          {opt}
                                        </button>
                                    );
                                  })}
                                </div>
                                {q.explanation && userAnswers[idx] !== undefined && (
                                  <p style={{ margin: '14px 0 0', fontSize: '13px', color: 'var(--color-text-muted)', lineHeight: 1.5 }}>해설: {q.explanation}</p>
                                )}
                              </div>
                          ))}
                        </div>
                    )}
                    {/* 채점 요약 (오답노트 생성은 상단 "오답노트 작성하기" 버튼으로 일원화) */}
                    {parsedQuestions.length > 0 && (() => {
                      const answered = parsedQuestions.filter((q, idx) => userAnswers[idx] !== undefined);
                      const wrong = parsedQuestions.filter((q, idx) => userAnswers[idx] !== undefined && userAnswers[idx] !== q.answer);
                      if (answered.length === 0) return null;
                      return (
                        <div className="glass-panel" style={{ marginTop: '24px', padding: '20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '16px', flexWrap: 'wrap' }}>
                          <div style={{ fontSize: '14px', color: 'var(--color-text-main)' }}>
                            <b>채점:</b> {answered.length}문제 중 <b style={{ color: '#16A34A' }}>{answered.length - wrong.length}개 정답</b>
                            {wrong.length > 0 && <> · <b style={{ color: '#DC2626' }}>{wrong.length}개 오답</b></>}
                          </div>
                          {wrong.length > 0 && !rnExistingNote && (
                            <span style={{ fontSize: '13px', color: 'var(--color-text-muted)' }}>상단의 <b style={{ color: '#DC2626' }}>오답노트 작성하기</b> 버튼으로 오답노트를 만들 수 있어요.</span>
                          )}
                        </div>
                      );
                    })()}
                  </div>
              )}

              {/* E. 오답노트 생성 성공/실패 모달 */}
              {reviewNoteResult && (
                <div className="modal-overlay" style={{ zIndex: 1000 }} onClick={() => setReviewNoteResult(null)}>
                  <div className="glass-panel modal-content animate-fade-in" style={{ width: '440px', maxWidth: '92vw', padding: '28px', borderRadius: '20px' }} onClick={(e) => e.stopPropagation()}>
                    {reviewNoteResult.error ? (
                      <>
                        <h3 style={{ margin: '0 0 8px', fontSize: '18px', color: '#991B1B' }}>오답노트 생성에 실패했습니다.</h3>
                        <p style={{ margin: '0 0 6px', fontSize: '13px', color: '#B45309' }}>오류 코드: {reviewNoteResult.errorCode}</p>
                        <p style={{ margin: '0 0 20px', fontSize: '13.5px', color: 'var(--color-text-muted)' }}>{reviewNoteResult.message}</p>
                        <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
                          <button className="btn-outline" style={{ padding: '9px 16px', borderRadius: '16px' }} onClick={() => setReviewNoteResult(null)}>닫기</button>
                          <button className="btn-primary" style={{ padding: '9px 16px', borderRadius: '16px' }} onClick={() => { const q = reviewNoteResult._retryQuizId, qs = reviewNoteResult._retryQuestions; setReviewNoteResult(null); handleCreateReviewNote(q, qs); }}>다시 시도</button>
                        </div>
                      </>
                    ) : (
                      <>
                        <h3 style={{ margin: '0 0 8px', fontSize: '18px', color: '#15803D' }}>오답노트가 저장되었습니다.</h3>
                        <p style={{ margin: '0 0 20px', fontSize: '13.5px', color: 'var(--color-text-muted)' }}>{reviewNoteResult.message || '오답노트가 자료보관함과 오답노트 탭에 저장되었습니다.'}</p>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                          <button className="btn-primary" style={{ padding: '11px', borderRadius: '14px', fontWeight: 'bold' }} onClick={() => navigate('/review-notes')}>오답노트에서 보기</button>
                          {reviewNoteResult.archiveMaterialId && (
                            <button className="btn-outline" style={{ padding: '11px', borderRadius: '14px' }} onClick={() => navigate(`/archive/pdf/${reviewNoteResult.archiveMaterialId}`)}>자료보관함에서 보기</button>
                          )}
                          <button className="btn-outline" style={{ padding: '11px', borderRadius: '14px' }} onClick={() => handleDownloadReviewNote(reviewNoteResult.id, reviewNoteResult.pdfUrl)}>컴퓨터에 저장</button>
                          <button className="btn-close" style={{ alignSelf: 'flex-end', marginTop: '4px', fontSize: '13px', color: 'var(--color-text-muted)' }} onClick={() => setReviewNoteResult(null)}>닫기</button>
                        </div>
                      </>
                    )}
                  </div>
                </div>
              )}

              {/* 설정 모달 */}
              {isQuizSettingsOpen && (
                  <div className="modal-overlay" style={{ zIndex: 1000 }}>
                    <div className="glass-panel modal-content animate-fade-in" style={{ width: '420px', padding: '32px', borderRadius: '24px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '32px' }}>
                        <h3 style={{ margin: 0, fontSize: '20px', color: 'var(--color-text-main)' }}>퀴즈 설정</h3>
                        <button className="btn-close" onClick={() => setIsQuizSettingsOpen(false)}><X size={24} /></button>
                      </div>

                      <div style={{ display: 'flex', flexDirection: 'column', gap: '28px' }}>
                        <div>
                          <label style={{ display: 'block', marginBottom: '12px', fontWeight: '600', fontSize: '15px', color: 'var(--color-text-main)' }}>난이도</label>
                          <div style={{ display: 'flex', gap: '8px' }}>
                            {['쉬움', '보통', '어려움'].map(level => (
                                <button
                                    key={level}
                                    className="btn-outline"
                                    style={{
                                      flex: 1, padding: '12px', borderRadius: '12px', transition: 'all 0.2s',
                                      backgroundColor: quizSettings.difficulty === level ? 'var(--color-primary)' : 'white',
                                      color: quizSettings.difficulty === level ? 'white' : 'var(--color-text-main)',
                                      borderColor: quizSettings.difficulty === level ? 'var(--color-primary)' : 'var(--color-border)',
                                      fontWeight: quizSettings.difficulty === level ? 'bold' : 'normal',
                                    }}
                                    onClick={() => setQuizSettings({ ...quizSettings, difficulty: level })}
                                >
                                  {level}
                                </button>
                            ))}
                          </div>
                          {/* E. 퀴즈 난이도 정책 (PDF 자료 기반) */}
                          <div style={{ marginTop: '10px', fontSize: '12.5px', color: 'var(--color-text-muted)', lineHeight: 1.6 }}>
                            {quizSettings.difficulty === '쉬움' && 'PDF에 직접 나온 내용 중심으로 출제합니다.'}
                            {quizSettings.difficulty === '보통' && 'PDF 내용 기반에 응용 개념을 살짝 추가해 출제합니다.'}
                            {quizSettings.difficulty === '어려움' && 'PDF 내용 기반에 응용 또는 실무 상황을 많이 포함해 출제합니다.'}
                          </div>
                        </div>

                        <div>
                          <label style={{ display: 'block', marginBottom: '12px', fontWeight: '600', fontSize: '15px', color: 'var(--color-text-main)' }}>문항 수 (5~20)</label>
                          <input
                              type="number"
                              className="input-field"
                              min={5}
                              max={20}
                              value={quizSettings.count}
                              // R. 입력 중에는 자유롭게, blur 시 5~20 보정(빈 값→10)
                              onChange={(e) => {
                                const raw = e.target.value;
                                setQuizSettings({ ...quizSettings, count: raw === '' ? '' : (parseInt(raw, 10) || '') });
                              }}
                              onBlur={(e) => {
                                let n = parseInt(e.target.value, 10);
                                if (Number.isNaN(n)) n = 10;        // 빈 값/미입력 → 10
                                if (n < 5) n = 5;                    // 5 미만 → 5
                                if (n > 20) n = 20;                  // 20 초과 → 20
                                setQuizSettings({ ...quizSettings, count: n });
                              }}
                              style={{ width: '100%', padding: '16px', borderRadius: '12px', backgroundColor: '#F9FAFB', border: '1px solid var(--color-border)' }}
                          />
                          <p style={{ margin: '8px 0 0', fontSize: '12.5px', color: 'var(--color-text-muted)' }}>최소 5개, 최대 20개까지 생성할 수 있습니다.</p>
                        </div>

                        <div>
                          <label style={{ display: 'block', marginBottom: '12px', fontWeight: '600', fontSize: '15px', color: 'var(--color-text-main)' }}>페이지 범위</label>
                          <input
                              type="text"
                              className="input-field"
                              placeholder="예: 1-10 또는 전체"
                              value={quizSettings.range}
                              onChange={(e) => setQuizSettings({ ...quizSettings, range: e.target.value })}
                              style={{ width: '100%', padding: '16px', borderRadius: '12px', backgroundColor: '#F9FAFB', border: '1px solid var(--color-border)' }}
                          />
                        </div>
                      </div>

                      <div style={{ display: 'flex', gap: '12px', marginTop: '40px' }}>
                        <button className="btn-outline" style={{ flex: 1, padding: '16px', borderRadius: '12px', fontWeight: 'bold' }} onClick={() => setIsQuizSettingsOpen(false)}>취소</button>
                        <button className="btn-primary" style={{ flex: 1, padding: '16px', borderRadius: '12px', fontWeight: 'bold' }} onClick={() => setIsQuizSettingsOpen(false)}>확인</button>
                      </div>
                    </div>
                  </div>
              )}
            </div>
        );
      }
      case 'roadmap': {
        const roadmapStatus = normalizeAiResponse(roadmapData);
        const normalizedRoadmapSteps = roadmapSteps.length > 0 ? roadmapSteps : normalizeRoadmapSteps(roadmapData?.roadmapData || roadmapData);
        // 신(新) 84일 구조 판별: 어느 주차든 days[]가 있으면 days 기준 렌더링
        const hasDays = normalizedRoadmapSteps.some(w => Array.isArray(w.days) && w.days.length > 0);

        // 진행률 계산 — 절대 하드코딩 금지. days가 있으면 일(日) 단위, 없으면 태스크 단위.
        let doneCount, totalCount, progressLabel;
        if (hasDays) {
          const allDays = normalizedRoadmapSteps.flatMap(s => s.days || []);
          totalCount = allDays.length;
          doneCount = allDays.filter(d => d.completed).length;
          progressLabel = `${doneCount}/${totalCount}일`;
        } else {
          const allTasks = normalizedRoadmapSteps.flatMap(s => s.tasks || []);
          totalCount = allTasks.length;
          doneCount = allTasks.filter(t => t.isCompleted).length;
          progressLabel = `${doneCount}/${totalCount}`;
        }
        const progressPercent = totalCount > 0 ? Math.round((doneCount / totalCount) * 100) : 0;

        const totalDaysNow = (roadmapSteps || []).reduce((sum, w) => sum + (w.days?.length || 0), 0);

        const regenerateBtn = (
          <>
            <button
              onClick={handleRegenerateRoadmap}
              disabled={isRegeneratingRoadmap}
              className="btn-outline"
              style={{ padding: '8px 18px', fontSize: '13.5px', borderRadius: '20px', whiteSpace: 'nowrap', cursor: isRegeneratingRoadmap ? 'default' : 'pointer', opacity: isRegeneratingRoadmap ? 0.6 : 1 }}
            >
              {isRegeneratingRoadmap ? 'AI 생성 중…' : 'AI 84일 로드맵 재생성'}
            </button>
            {/* J/K/L. 플래너 생성: 84일 로드맵 → 플래너 84개 (플래너 도메인 전용, 주간일정과 무관) */}
            <button
              onClick={handleOpenPlannerModal}
              disabled={isCreatingPlanner || totalDaysNow !== 84}
              title={totalDaysNow !== 84 ? '84일 로드맵이 필요합니다. 먼저 AI 84일 로드맵을 재생성해주세요.' : undefined}
              className="btn-primary"
              style={{ padding: '8px 18px', fontSize: '13.5px', borderRadius: '20px', whiteSpace: 'nowrap',
                opacity: (isCreatingPlanner || totalDaysNow !== 84) ? 0.55 : 1,
                cursor: (isCreatingPlanner || totalDaysNow !== 84) ? 'not-allowed' : 'pointer' }}
            >
              {isCreatingPlanner ? '플래너 생성 중…' : '플래너 생성'}
            </button>
          </>
        );

        return (
            <div className="animate-fade-in" style={{ paddingBottom: '32px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px', gap: '12px', flexWrap: 'wrap' }}>
                <h2 style={{ margin: 0, color: 'var(--color-text-main)' }}>주차별 학습 로드맵</h2>
                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                  {regenerateBtn}
                </div>
              </div>

              {/* 플래너 생성 안내/오류 (예: 84일 미충족) */}
              {plannerError && (
                <div className="glass-panel" style={{ padding: '12px 16px', marginBottom: '12px', borderLeft: '4px solid #F59E0B', backgroundColor: '#FFFBEB', color: '#92400E', fontSize: '13.5px' }}>
                  {plannerError}
                </div>
              )}

              {/* L. 플래너 생성 모달 (시작일 선택 → 84개 생성) */}
              {isPlannerModalOpen && (
                <div className="modal-overlay" style={{ zIndex: 1000 }} onClick={() => { if (!isCreatingPlanner) { setIsPlannerModalOpen(false); setPlannerResult(null); } }}>
                  <div className="glass-panel modal-content animate-fade-in" style={{ width: '420px', maxWidth: '92vw', padding: '28px', borderRadius: '20px' }} onClick={(e) => e.stopPropagation()}>
                    {plannerResult ? (
                      <>
                        <h3 style={{ margin: '0 0 8px', fontSize: '18px', color: '#15803D' }}>{plannerResult.message}</h3>
                        <p style={{ margin: '0 0 20px', fontSize: '13.5px', color: 'var(--color-text-muted)' }}>로드맵 84일이 플래너 항목으로 저장되었습니다.</p>
                        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
                          <button className="btn-outline" style={{ padding: '10px 16px', borderRadius: '14px' }} onClick={() => { setIsPlannerModalOpen(false); setPlannerResult(null); }}>닫기</button>
                          <button className="btn-primary" style={{ padding: '10px 18px', borderRadius: '14px', fontWeight: 'bold' }} onClick={() => navigate('/planner')}>플래너에서 보기</button>
                        </div>
                      </>
                    ) : (
                      <>
                        <h3 style={{ margin: '0 0 6px', fontSize: '18px', color: 'var(--color-text-main)' }}>플래너 생성</h3>
                        <p style={{ margin: '0 0 18px', fontSize: '13.5px', color: 'var(--color-text-muted)' }}>84일 로드맵을 학습 플래너 84개로 만듭니다. 시작일을 선택하세요.</p>
                        <label style={{ display: 'block', fontSize: '13px', fontWeight: 600, color: 'var(--color-text-main)', marginBottom: '8px' }}>시작일</label>
                        <input type="date" value={plannerStartDate} onChange={(e) => setPlannerStartDate(e.target.value)}
                          style={{ width: '100%', boxSizing: 'border-box', padding: '12px', borderRadius: '12px', border: '1px solid var(--color-border)', backgroundColor: '#F9FAFB', marginBottom: '22px' }} />
                        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
                          <button className="btn-outline" style={{ padding: '10px 16px', borderRadius: '14px' }} disabled={isCreatingPlanner} onClick={() => setIsPlannerModalOpen(false)}>취소</button>
                          <button className="btn-primary" style={{ padding: '10px 18px', borderRadius: '14px', fontWeight: 'bold', opacity: isCreatingPlanner ? 0.6 : 1 }} disabled={isCreatingPlanner} onClick={() => handleCreatePlanner(false)}>
                            {isCreatingPlanner ? '생성 중…' : '84개 플래너 생성'}
                          </button>
                        </div>
                      </>
                    )}
                  </div>
                </div>
              )}

              {/* B. 난이도 선택 (초보자 / 중급자 / 상급자, 기본 중급자) */}
              <div className="glass-panel" style={{ padding: '14px 16px', marginBottom: '16px' }}>
                <div style={{ fontSize: '13.5px', fontWeight: 700, color: 'var(--color-text-main)', marginBottom: '8px' }}>로드맵 난이도</div>
                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                  {ROADMAP_LEVELS.map((lv) => (
                    <button
                      key={lv.value}
                      onClick={() => setRoadmapLevel(lv.value)}
                      title={lv.desc}
                      style={{
                        padding: '7px 16px', borderRadius: '20px', fontSize: '13px', cursor: 'pointer',
                        border: `1px solid ${roadmapLevel === lv.value ? 'var(--color-primary)' : 'var(--color-border)'}`,
                        backgroundColor: roadmapLevel === lv.value ? 'var(--color-primary)' : 'white',
                        color: roadmapLevel === lv.value ? 'white' : 'var(--color-text-main)',
                        fontWeight: roadmapLevel === lv.value ? 'bold' : 'normal',
                      }}
                    >{lv.label}</button>
                  ))}
                </div>
                <p style={{ margin: '8px 0 0', fontSize: '12.5px', color: 'var(--color-text-muted)' }}>
                  {ROADMAP_LEVELS.find(l => l.value === roadmapLevel)?.desc}
                </p>
              </div>

              <p style={{ color: 'var(--color-text-muted)', marginBottom: '24px' }}>
                업로드한 자료를 기반으로 AI가 설계한 12주 × 7일(84일) 학습 로드맵입니다.{totalDaysNow > 0 ? ` (현재 ${totalDaysNow}일)` : ''}
              </p>

              {/* 재생성 실패 카드 — 기존 로드맵은 보존하고 오류 코드/사유만 표시 */}
              {renderAiStatus(roadmapError, handleRegenerateRoadmap)}
              {renderAiStatus(roadmapStatus, () => loadTabData(material.materialId))}

              {/* 레거시(이전 형식) 안내: days가 없고 태스크 기반이면 재생성 유도 */}
              {!hasDays && normalizedRoadmapSteps.length > 0 && (
                <div className="glass-panel" style={{ padding: '16px 20px', marginBottom: '20px', borderLeft: '4px solid #F59E0B', backgroundColor: '#FFFBEB', color: '#92400E' }}>
                  <div style={{ fontWeight: 700, marginBottom: '4px' }}>이 로드맵은 이전 형식입니다.</div>
                  <div style={{ fontSize: '13.5px' }}>84일(12주 × 7일) 구조로 다시 생성하려면 우측 상단의 “AI 84일 로드맵 재생성” 버튼을 눌러주세요.</div>
                </div>
              )}

              <div className="glass-panel" style={{ padding: '20px', marginBottom: '32px', borderLeft: '4px solid var(--color-primary)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                  <span style={{ fontWeight: 'bold', fontSize: '15px', color: 'var(--color-text-main)' }}>전체 학습 진행률</span>
                  <span style={{ fontWeight: 'bold', fontSize: '18px', color: 'var(--color-primary)' }}>{progressPercent}% <span style={{ fontSize: '13px', color: 'var(--color-text-muted)', fontWeight: 'normal' }}>({progressLabel})</span></span>
                </div>
                <div style={{ width: '100%', height: '10px', backgroundColor: '#E5E7EB', borderRadius: '5px', overflow: 'hidden' }}>
                  <div style={{ width: `${progressPercent}%`, height: '100%', backgroundColor: 'var(--color-primary)', transition: 'width 0.6s cubic-bezier(0.4, 0, 0.2, 1)' }}></div>
                </div>
              </div>

              {normalizedRoadmapSteps.length === 0 ? (
                  <p style={{ color: 'var(--color-text-muted)', fontSize: '14px' }}>{roadmapStatus.success === false ? getAiErrorMessage(roadmapStatus.errorCode, roadmapStatus.textStatus, roadmapStatus.message) : '로드맵 미생성'}</p>
              ) : hasDays ? (
                  /* ===== 신(新) 84일 구조: 주차 → 1일차~7일차 ===== */
                  <div className="roadmap-timeline">
                    {normalizedRoadmapSteps.map((step, idx) => {
                      const days = step.days || [];
                      const weekDone = days.length > 0 && days.every(d => d.completed);
                      return (
                          <div key={step.stepId} className="timeline-item" style={{ opacity: weekDone ? 0.65 : 1, transition: 'opacity 0.3s' }}>
                            <div className="timeline-left">
                              <div className="timeline-circle" style={{ backgroundColor: weekDone ? '#9CA3AF' : getNodeColor(step.stepOrder) }}>{step.stepOrder}</div>
                              {idx < normalizedRoadmapSteps.length - 1 && <div className="timeline-line"></div>}
                            </div>
                            <div className="timeline-card glass-panel" style={{ borderLeftColor: weekDone ? '#9CA3AF' : getNodeColor(step.stepOrder), padding: '24px', backgroundColor: weekDone ? '#F3F4F6' : 'white', transition: 'all 0.3s' }}>
                              <h4 style={{ margin: '0 0 6px', fontSize: '17px', color: 'var(--color-text-main)', fontWeight: 'bold' }}>{step.stepOrder}주차 · {step.title}</h4>
                              {step.description && <div style={{ fontSize: '14px', color: 'var(--color-text-muted)', marginBottom: '4px' }}><b>주차 목표:</b> {step.description}</div>}
                              {step.weekSummary && <div style={{ fontSize: '13px', color: 'var(--color-text-muted)', marginBottom: '12px' }}>{step.weekSummary}</div>}

                              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', borderTop: '1px solid var(--color-border)', paddingTop: '14px', marginTop: '8px' }}>
                                {days.map((day) => (
                                    <div key={`${step.stepOrder}-${day.dayIndex}`} style={{ border: '1px solid var(--color-border)', borderRadius: '12px', padding: '14px 16px', backgroundColor: day.completed ? '#F0FDF4' : '#FFFFFF' }}>
                                      <div onClick={() => handleToggleDay(step.stepOrder, day.dayIndex)} style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer' }}>
                                        {day.completed ? <CheckCircle2 size={18} color="var(--color-primary)" /> : <Circle size={18} color="var(--color-text-muted)" />}
                                        <span style={{ fontWeight: 700, fontSize: '14.5px', color: 'var(--color-primary)' }}>{day.dayLabel}</span>
                                        <span style={{ fontSize: '14.5px', fontWeight: 600, textDecoration: day.completed ? 'line-through' : 'none', color: day.completed ? 'var(--color-text-muted)' : 'var(--color-text-main)' }}>{day.title}</span>
                                      </div>

                                      {day.objective && <div style={{ fontSize: '13px', color: 'var(--color-text-muted)', margin: '8px 0 0', paddingLeft: '28px' }}><b>오늘 목표:</b> {day.objective}</div>}

                                      {day.coreConcepts.length > 0 && (
                                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', margin: '8px 0 0', paddingLeft: '28px' }}>
                                          {day.coreConcepts.map((c, ci) => (
                                            <span key={ci} style={{ fontSize: '11.5px', padding: '3px 10px', borderRadius: '12px', backgroundColor: '#EEF2FF', color: '#4338CA', fontWeight: 600 }}>{c}</span>
                                          ))}
                                        </div>
                                      )}

                                      {day.tasks.length > 0 && (
                                        <div style={{ margin: '10px 0 0', paddingLeft: '28px' }}>
                                          <div style={{ fontSize: '12.5px', fontWeight: 700, color: 'var(--color-text-muted)', marginBottom: '4px' }}>할 일</div>
                                          <ul style={{ margin: 0, paddingLeft: '18px', display: 'flex', flexDirection: 'column', gap: '3px' }}>
                                            {day.tasks.map((t, ti) => <li key={ti} style={{ fontSize: '13px', color: 'var(--color-text-main)' }}>{t}</li>)}
                                          </ul>
                                        </div>
                                      )}

                                      {day.reviewQuestions.length > 0 && (
                                        <div style={{ margin: '10px 0 0', paddingLeft: '28px' }}>
                                          <div style={{ fontSize: '12.5px', fontWeight: 700, color: 'var(--color-text-muted)', marginBottom: '4px' }}>복습 질문</div>
                                          <ul style={{ margin: 0, paddingLeft: '18px', display: 'flex', flexDirection: 'column', gap: '3px' }}>
                                            {day.reviewQuestions.map((q, qi) => <li key={qi} style={{ fontSize: '12.5px', color: 'var(--color-text-muted)' }}>{q}</li>)}
                                          </ul>
                                        </div>
                                      )}

                                      {day.deliverable && <div style={{ fontSize: '12.5px', color: 'var(--color-text-muted)', margin: '10px 0 0', paddingLeft: '28px' }}><b>산출물:</b> {day.deliverable}</div>}
                                    </div>
                                ))}
                              </div>
                            </div>
                          </div>
                      );
                    })}
                  </div>
              ) : (
                  /* ===== 레거시 fallback: 주차 → 태스크 체크리스트 ===== */
                  <div className="roadmap-timeline">
                    {normalizedRoadmapSteps.map((step, idx) => {
                      const isStepDone = step.tasks && step.tasks.length > 0 && step.tasks.every(t => t.isCompleted);
                      return (
                          <div key={step.stepId} className="timeline-item" style={{ opacity: isStepDone ? 0.6 : 1, transition: 'opacity 0.3s' }}>
                            <div className="timeline-left">
                              <div className="timeline-circle" style={{ backgroundColor: isStepDone ? '#9CA3AF' : getNodeColor(step.stepOrder) }}>{step.stepOrder}</div>
                              {idx < normalizedRoadmapSteps.length - 1 && <div className="timeline-line"></div>}
                            </div>
                            <div className="timeline-card glass-panel" style={{ borderLeftColor: isStepDone ? '#9CA3AF' : getNodeColor(step.stepOrder), padding: '24px', backgroundColor: isStepDone ? '#F3F4F6' : 'white', transition: 'all 0.3s' }}>
                              <h4 style={{ margin: '0 0 12px', fontSize: '16px', textDecoration: isStepDone ? 'line-through' : 'none', color: isStepDone ? 'var(--color-text-muted)' : 'var(--color-text-main)', fontWeight: 'bold' }}>{step.title}</h4>
                              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '14px', marginBottom: '16px' }}>
                                <div><span style={{ fontWeight: 'bold', color: 'var(--color-text-muted)', marginRight: '8px' }}>주제 개요:</span> <span style={{ textDecoration: isStepDone ? 'line-through' : 'none' }}>{step.description}</span></div>
                              </div>

                              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', borderTop: '1px solid var(--color-border)', paddingTop: '12px' }}>
                                {step.tasks && step.tasks.map((task) => (
                                    <div
                                        key={task.taskId}
                                        onClick={() => task.taskId && handleToggleTask(task.taskId)}
                                        style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: task.taskId ? 'pointer' : 'default', padding: '4px 0' }}
                                    >
                                      {task.isCompleted ? (
                                          <CheckCircle2 size={18} color="var(--color-primary)" />
                                      ) : (
                                          <Circle size={18} color="var(--color-text-muted)" />
                                      )}
                                      <span style={{ fontSize: '13.5px', textDecoration: task.isCompleted ? 'line-through' : 'none', color: task.isCompleted ? 'var(--color-text-muted)' : 'var(--color-text-main)' }}>
                                        {task.content}
                                      </span>
                                    </div>
                                ))}
                              </div>
                            </div>
                          </div>
                      );
                    })}
                  </div>
              )}
            </div>
        );
      }
      case 'memo':
        return (
            <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', height: '100%', paddingBottom: '24px' }}>
              <h3 style={{ margin: '0 0 16px', fontSize: '20px' }}>나의 학습 메모</h3>
              <p style={{ color: 'var(--color-text-muted)', fontSize: '14px', marginBottom: '16px' }}>문서와 관련된 아이디어나 핵심 정리 사항을 메모로 기록해보세요.</p>
              <textarea
                  style={{
                    flex: 1,
                    padding: '24px',
                    borderRadius: '16px',
                    border: '1px solid var(--color-border)',
                    backgroundColor: '#FFFDF5',
                    color: 'var(--color-text-main)',
                    fontSize: '16px',
                    lineHeight: '1.7',
                    fontFamily: 'inherit',
                    resize: 'none',
                    boxShadow: 'inset 0 2px 8px rgba(0,0,0,0.03)',
                    minHeight: '300px'
                  }}
                  placeholder="이 자료를 보며 중요하게 기억할 부분을 자유롭게 입력하세요."
                  value={memoText}
                  onChange={(e) => setMemoText(e.target.value)}
              />
              <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '20px' }}>
                <button
                    className="btn-primary"
                    style={{ width: 'auto', padding: '12px 32px', borderRadius: '30px', fontWeight: 'bold' }}
                    onClick={handleSaveMemo}
                    disabled={isSavingMemo}
                >
                  {isSavingMemo ? '저장 중...' : '메모 저장'}
                </button>
              </div>
            </div>
        );

      case 'chat': {
        const currentTextStatus = summaryData?.textStatus || roadmapData?.textStatus || quizzes.find(q => q?.textStatus)?.textStatus;
        const textBlocked = currentTextStatus?.hasText === false || currentTextStatus?.status === 'EMPTY';
        const textStatusMessage = getTextStatusMessage(currentTextStatus);
        return (
            <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: '450px' }}>
              <h3 style={{ margin: '0 0 16px', fontSize: '20px' }}>AI 질문</h3>
              {textStatusMessage && (
                <div className="glass-panel" style={{ padding: '14px 16px', borderLeft: '4px solid #F59E0B', backgroundColor: '#FFFBEB', color: '#92400E', marginBottom: '12px' }}>
                  {textStatusMessage}
                </div>
              )}
              <div style={{ flex: 1, backgroundColor: '#F9FAFB', borderRadius: '12px', padding: '24px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '20px', border: '1px solid var(--color-border)', maxHeight: '350px' }}>
                {chatMessages.map((msg, idx) => (
                    <div
                        key={idx}
                        style={{
                          alignSelf: msg.sender === 'user' ? 'flex-end' : 'flex-start',
                          backgroundColor: msg.sender === 'user' ? 'var(--color-primary)' : 'white',
                          color: msg.sender === 'user' ? 'white' : 'var(--color-text-main)',
                          padding: '16px 20px',
                          borderRadius: '20px',
                          borderTopLeftRadius: msg.sender === 'ai' ? '4px' : '20px',
                          borderTopRightRadius: msg.sender === 'user' ? '4px' : '20px',
                          maxWidth: '85%',
                          boxShadow: '0 1px 4px rgba(0,0,0,0.05)',
                          fontSize: '15px',
                          lineHeight: '1.6',
                          whiteSpace: 'pre-wrap',
                          overflowWrap: 'anywhere',
                          maxHeight: msg.sender === 'ai' ? '220px' : 'none',
                          overflowY: msg.sender === 'ai' ? 'auto' : 'visible'
                        }}
                    >
                      {/* P. AI 답변은 마크다운 기호 제거 후 표시(코드 텍스트는 보존). 사용자 메시지는 원본 유지. */}
                      {msg.sender === 'ai' ? sanitizeMarkdownText(msg.text) : msg.text}
                    </div>
                ))}
                <div ref={chatEndRef} />
              </div>
              <div style={{ marginTop: '16px' }}>
                <form onSubmit={handleSendChat} style={{ display: 'flex', gap: '12px', width: '100%' }}>
                  <input
                      type="text"
                      className="input-field"
                      style={{ flex: 1, minWidth: 0, margin: 0, borderRadius: '30px', backgroundColor: '#F3F4F6', border: 'none', padding: '16px 24px', fontSize: '15px', height: '50px' }}
                      placeholder={textBlocked ? '문서 텍스트 추출 후 질문할 수 있습니다.' : '자료 내용에 대해 궁금한 점을 입력하세요.'}
                      value={chatInput}
                      onChange={(e) => setChatInput(e.target.value)}
                      disabled={textBlocked || isAskingQuestion}
                  />
                  <button type="submit" disabled={textBlocked || isAskingQuestion || !chatInput.trim()} className="btn-primary" style={{ width: '50px', height: '50px', borderRadius: '50%', padding: 0, flexShrink: 0, display: 'flex', justifyContent: 'center', alignItems: 'center', opacity: (textBlocked || isAskingQuestion || !chatInput.trim()) ? 0.55 : 1 }}>
                    <Send size={20} />
                  </button>
                </form>
              </div>
            </div>
        );
      }
      default:
        return null;
    }
  };

  if (isLoadingDetail) {
    return (
        <div className="container-main" style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '50vh', color: 'var(--color-primary)', fontWeight: 'bold' }}>
          상세 분석 자료를 불러오는 중입니다...
        </div>
    );
  }

  if (!material) {
    return (
        <div className="container-main" style={{ textAlign: 'center', marginTop: '100px' }}>
          <h2>자료를 찾을 수 없습니다.</h2>
          <button className="btn-primary" style={{ width: 'auto', padding: '0 24px', margin: '20px auto' }} onClick={() => navigate('/archive')}>목록으로 돌아가기</button>
        </div>
    );
  }

  // AI 분석 대기/추출 상태 뷰
  if (material.extractionStatus === 'PENDING' || material.extractionStatus === 'PROCESSING') {
    return (
        <div className="container-main animate-fade-in" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '60vh', textAlign: 'center' }}>
          <div className="glass-panel" style={{ padding: '60px 40px', maxWidth: '600px', borderRadius: '16px' }}>
            <div className="animate-spin-custom" style={{ width: '48px', height: '48px', border: '4px solid #E5E7EB', borderTopColor: 'var(--color-primary)', borderRadius: '50%', margin: '0 auto 24px' }}></div>
            <h2 style={{ margin: '0 0 16px', color: 'var(--color-text-main)' }}>AI가 문서를 열심히 분석하고 있습니다 🧠</h2>
            <p style={{ color: 'var(--color-text-muted)', lineHeight: '1.6', marginBottom: '24px' }}>
              문서에서 핵심 정보를 읽고 주차별 로드맵, 핵심 요약, 메모 및 AI 퀴즈 데이터베이스를 조율하는 과정입니다. 분석이 완료되면 자동으로 화면이 전환됩니다. 잠시만 기다려주세요!
            </p>
            <button className="btn-outline" style={{ width: 'auto', padding: '8px 24px' }} onClick={() => navigate('/archive')}>목록으로 돌아가기</button>
          </div>
          <style dangerouslySetInnerHTML={{__html: `
          @keyframes spin {
            to { transform: rotate(360deg); }
          }
          .animate-spin-custom {
            animation: spin 1.2s linear infinite;
          }
        `}} />
        </div>
    );
  }

  return (
      <div className="archive-detail-container animate-fade-in">
        <style dangerouslySetInnerHTML={{__html: `
        .archive-detail-container, .archive-detail-container * {
          box-sizing: border-box;
        }
      `}} />
        {type === 'pdf' && (
            <div className="archive-action-bar" style={{ padding: '16px 24px', borderBottom: '1px solid var(--color-border)', backgroundColor: 'white', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '16px', flex: 1, minWidth: 0 }}>
                <button className="btn-outline" style={{ width: 'auto', padding: '8px 16px', border: 'none', flexShrink: 0 }} onClick={() => navigate('/archive')}>
                  <ArrowLeft size={18} /> 목록
                </button>
                <span style={{ fontWeight: '600', fontSize: '18px', color: 'var(--color-text-main)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }} title={material.title || material.originalFileName}>
                  {material.title || material.originalFileName}
                </span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '16px', flexShrink: 0 }}>
                {/* 뷰어 너비 */}
                <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                  <span style={{ fontSize: '12px', color: 'var(--color-text-muted)', marginRight: '4px' }}>뷰어 너비:</span>
                  {[30, 50, 70].map(pct => (
                      <button
                          key={pct}
                          onClick={() => setLeftWidth(pct)}
                          style={{
                            padding: '4px 8px',
                            fontSize: '11px',
                            borderRadius: '4px',
                            border: '1px solid var(--color-border)',
                            backgroundColor: leftWidth === pct ? 'var(--color-primary)' : 'white',
                            color: leftWidth === pct ? 'white' : 'var(--color-text-main)',
                            cursor: 'pointer',
                            fontWeight: leftWidth === pct ? 'bold' : 'normal',
                            transition: 'all 0.15s'
                          }}
                      >
                        {pct}%
                      </button>
                  ))}
                </div>
                {/* 기존 AI 버튼들 */}
                <div style={{ display: 'flex', gap: '8px' }}>
                  <button className={`archive-action-btn ${activePdfTool === 'summary' ? 'active' : ''}`} onClick={() => setActivePdfTool('summary')}><AlignLeft size={16} /> 요약</button>
                  <button className={`archive-action-btn ${activePdfTool === 'quiz' ? 'active' : ''}`} onClick={() => setActivePdfTool('quiz')}><HelpCircle size={16} /> 퀴즈/문제 생성</button>
                  <button className={`archive-action-btn ${activePdfTool === 'roadmap' ? 'active' : ''}`} onClick={() => setActivePdfTool('roadmap')}><Map size={16} /> 주차별 로드맵</button>
                  <button className={`archive-action-btn ${activePdfTool === 'memo' ? 'active' : ''}`} onClick={() => setActivePdfTool('memo')}><Edit3 size={16} /> 메모</button>
                  <button className={`archive-action-btn ${activePdfTool === 'chat' ? 'active' : ''}`} onClick={() => setActivePdfTool('chat')}><MessageSquare size={16} /> AI 질문</button>
                </div>
                {/* 삭제 버튼 */}
                <button className="btn-outline" style={{ width: 'auto', padding: '8px 16px', border: 'none', color: '#EF4444' }} onClick={handleDeleteMaterial}>
                  <Trash2 size={18} /> 삭제
                </button>
              </div>
            </div>
        )}

        {type === 'journal' && (
            <div style={{ padding: '16px 24px', backgroundColor: 'white', borderBottom: '1px solid var(--color-border)', display: 'flex', alignItems: 'center', gap: '16px' }}>
              <button className="btn-outline" style={{ width: 'auto', padding: '8px 16px', border: 'none' }} onClick={() => navigate('/archive')}>
                <ArrowLeft size={18} /> 목록
              </button>
              <button className="btn-outline" style={{ width: 'auto', padding: '8px 16px', border: 'none', color: '#EF4444' }} onClick={handleDeleteMaterial}>
                <Trash2 size={18} /> 삭제
              </button>
              <div style={{ display: 'flex', flexDirection: 'column' }}>
                <h2 style={{ margin: 0, fontSize: '18px' }}>{material.title}</h2>
                <span style={{ fontSize: '13px', color: 'var(--color-text-muted)' }}>
                  {material.studyDate || (material.uploadedAt ? material.uploadedAt.split('T')[0] : '')} • 학습일지
                </span>
              </div>
            </div>
        )}

        <div className="archive-split-view">
          <div className="archive-left-panel" style={{ width: type === 'pdf' ? `${leftWidth}%` : '50%', flex: 'none', overflowY: 'auto' }}>
            {type === 'pdf' && (material?.originalFileName || '').toLowerCase().endsWith('.docx') ? (
                /* DOCX는 PDF 뷰어(iframe)에 넣지 않고 별도 분석 결과 패널을 보여준다. */
                <div className="glass-panel" style={{ padding: '32px', height: '100%', overflowY: 'auto' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '8px' }}>
                    <span style={{ fontSize: '12px', fontWeight: 700, color: '#2563EB', backgroundColor: '#DBEAFE', padding: '3px 10px', borderRadius: '12px' }}>DOCX</span>
                    <h2 style={{ margin: 0, color: 'var(--color-text-main)' }}>DOCX 문서 분석 결과</h2>
                  </div>
                  <p style={{ margin: '0 0 24px', color: 'var(--color-text-muted)', fontSize: '14px' }}>워드(.docx) 문서는 미리보기를 제공하지 않습니다. AI 요약·핵심 키워드·로드맵·메모·AI 질문은 오른쪽 탭에서 확인하세요.</p>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                    <div>
                      <h4 style={{ margin: '0 0 6px', fontSize: '14px', color: 'var(--color-text-muted)', fontWeight: 600 }}>파일명</h4>
                      <p style={{ margin: 0, fontSize: '15px', color: 'var(--color-text-main)', fontWeight: 'bold', wordBreak: 'break-all' }}>{material.originalFileName || material.title}</p>
                    </div>
                    <div>
                      <h4 style={{ margin: '0 0 6px', fontSize: '14px', color: 'var(--color-text-muted)', fontWeight: 600 }}>업로드일</h4>
                      <p style={{ margin: 0, fontSize: '15px', color: 'var(--color-text-main)' }}>{material.uploadedAt ? material.uploadedAt.split('T')[0] : '-'}</p>
                    </div>
                    <div>
                      <h4 style={{ margin: '0 0 6px', fontSize: '14px', color: 'var(--color-text-muted)', fontWeight: 600 }}>파일 형식</h4>
                      <p style={{ margin: 0, fontSize: '15px', color: 'var(--color-text-main)' }}>DOCX</p>
                    </div>
                    <div>
                      <h4 style={{ margin: '0 0 6px', fontSize: '14px', color: 'var(--color-text-muted)', fontWeight: 600 }}>핵심 키워드</h4>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                        {material.keywords ? material.keywords.split(',').map((kw) => (
                          <span key={kw} className="tag" style={{ backgroundColor: '#F3F4F6', color: 'var(--color-text-main)' }}>#{kw.trim()}</span>
                        )) : <span style={{ color: 'var(--color-text-muted)', fontSize: '14px' }}>등록된 키워드가 없습니다.</span>}
                      </div>
                    </div>
                    {material.s3PresignedUrl && (
                      <a href={material.s3PresignedUrl} target="_blank" rel="noopener noreferrer" download style={{ textDecoration: 'none' }}>
                        <button className="btn-primary" style={{ padding: '12px 24px', borderRadius: '8px', fontSize: '15px', fontWeight: 'bold', cursor: 'pointer' }}>원본 다운로드</button>
                      </a>
                    )}
                  </div>
                </div>
            ) : type === 'pdf' ? (
                <div style={{ width: '100%', height: '100%', backgroundColor: 'white', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                  {material.s3PresignedUrl ? (
                      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%' }}>

                        <div style={{ flex: 1, position: 'relative' }}>
                          <iframe src={material.s3PresignedUrl} style={{ width: '100%', height: '100%', border: 'none' }} title="Document Viewer" />
                        </div>
                      </div>
                  ) : (
                      <div style={{ width: '100%', height: '100%', display: 'flex', justifyContent: 'center', alignItems: 'center', flexDirection: 'column', padding: '40px' }}>
                        <div style={{ padding: '40px', backgroundColor: '#F3F4F6', borderRadius: '8px', marginBottom: '24px' }}>
                          <span style={{ fontSize: '48px', color: '#9CA3AF' }}>PDF</span>
                        </div>
                        <h3 style={{ margin: '0 0 8px', color: 'var(--color-text-main)' }}>{material.title}</h3>
                        <p style={{ color: 'var(--color-text-muted)', margin: 0, textAlign: 'center' }}>첨부된 PDF 파일이 없어 미리보기를 표시할 수 없습니다.</p>
                      </div>
                  )}
                </div>
            ) : (
                <div className="glass-panel" style={{ padding: '32px' }}>
                  <div>
                    <h2 style={{ margin: '0 0 8px', color: 'var(--color-text-main)' }}>학습일지 상세</h2>
                    <p style={{ margin: 0, color: 'var(--color-text-muted)', fontSize: '14px' }}>학습일지 내용을 확인합니다.</p>
                  </div>

                  <hr style={{ border: 'none', borderTop: '1px solid var(--color-border)', margin: '24px 0' }} />

                  <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                    <div>
                      <h4 style={{ margin: '0 0 8px', fontSize: '15px', color: 'var(--color-text-muted)', fontWeight: '600' }}>제목</h4>
                      <p style={{ margin: 0, fontSize: '16px', color: 'var(--color-text-main)', fontWeight: 'bold' }}>{material.title}</p>
                    </div>

                    <div>
                      <h4 style={{ margin: '0 0 8px', fontSize: '15px', color: 'var(--color-text-muted)', fontWeight: '600' }}>날짜</h4>
                      <p style={{ margin: 0, fontSize: '15px', color: 'var(--color-text-main)' }}>{material.studyDate || (material.uploadedAt ? material.uploadedAt.split('T')[0] : '')}</p>
                    </div>

                    <div>
                      <h4 style={{ margin: '0 0 8px', fontSize: '15px', color: 'var(--color-text-muted)', fontWeight: '600' }}>핵심 키워드</h4>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                        {material.keywords ? (
                            material.keywords.split(',').map((kw) => (
                                <span key={kw} className="tag" style={{ backgroundColor: '#F3F4F6', color: 'var(--color-text-main)' }}>#{kw.trim()}</span>
                            ))
                        ) : (
                            <span style={{ color: 'var(--color-text-muted)', fontSize: '14px' }}>등록된 키워드가 없습니다.</span>
                        )}
                      </div>
                    </div>

                    <div>
                      <h4 style={{ margin: '0 0 8px', fontSize: '15px', color: 'var(--color-text-muted)', fontWeight: '600' }}>학습 내용</h4>
                      <p style={{ margin: 0, lineHeight: '1.6', whiteSpace: 'pre-wrap', color: 'var(--color-text-main)' }}>{material.learningContent || '작성된 내용이 없습니다.'}</p>
                    </div>

                    <div>
                      <h4 style={{ margin: '0 0 8px', fontSize: '15px', color: 'var(--color-text-muted)', fontWeight: '600' }}>다음 학습 계획</h4>
                      <p style={{ margin: 0, lineHeight: '1.6', whiteSpace: 'pre-wrap', color: 'var(--color-text-main)' }}>{material.nextPlan || '작성된 계획이 없습니다.'}</p>
                    </div>
                  </div>
                </div>
            )}
          </div>
          {type === 'pdf' && (
              <div
                  style={{
                    width: '1px',
                    backgroundColor: 'var(--color-border)',
                    zIndex: 10,
                  }}
              />
          )}
          <div className="archive-right-panel" style={{ width: type === 'pdf' ? `${100 - leftWidth}%` : '50%', flex: 'none', overflowY: 'auto', overflowX: 'hidden', boxSizing: 'border-box', backgroundColor: type === 'journal' ? 'var(--color-bg-base)' : 'white', borderLeft: type === 'pdf' ? 'none' : '1px solid var(--color-border)' }}>
            {type === 'pdf' ? (
                renderPdfRightPanel()
            ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                  <div className="glass-panel animate-fade-in" style={{ padding: '24px' }}>
                    <h3 style={{ margin: '0 0 16px', fontSize: '18px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <AlignLeft size={18} color="var(--color-primary)" /> AI 요약
                    </h3>
                    <p style={{ margin: 0, fontSize: '15px', lineHeight: '1.6', color: 'var(--color-text-main)' }}>
                      {summaryData?.overview || '학습일지의 AI 요약을 생성하는 중이거나 내용이 부족합니다.'}
                    </p>
                  </div>

                  <div className="glass-panel animate-fade-in" style={{ padding: '24px' }}>
                    <h3 style={{ margin: '0 0 16px', fontSize: '18px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <MessageSquare size={18} color="var(--color-primary)" /> AI 피드백
                    </h3>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                      {summaryData?.overview ? (
                          <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
                            <div style={{ width: '24px', height: '24px', borderRadius: '50%', backgroundColor: 'var(--color-primary)', color: 'white', display: 'flex', justifyContent: 'center', alignItems: 'center', fontSize: '12px', fontWeight: 'bold', flexShrink: 0 }}>1</div>
                            <p style={{ margin: 0, fontSize: '14px', lineHeight: '1.5', color: 'var(--color-text-main)' }}>
                              학습일지 분석 결과, 주제에 맞게 핵심 지식을 정확히 성찰하였습니다.
                            </p>
                          </div>
                      ) : (
                          <p style={{ color: 'var(--color-text-muted)', fontSize: '14px', margin: 0 }}>AI 피드백이 생성되지 않았습니다.</p>
                      )}
                    </div>
                  </div>
                </div>
            )}
          </div>
        </div>

        {activeKeyword && (
          <KeywordDefineModal
            materialId={material?.materialId || id}
            keyword={activeKeyword}
            context={summaryData?.overview || material?.learningContent}
            onClose={() => setActiveKeyword(null)}
          />
        )}

      </div>
  );
}
