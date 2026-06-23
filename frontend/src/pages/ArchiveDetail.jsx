import React, { useState, useEffect, useRef } from 'react';
import { useLocation, useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, AlignLeft, HelpCircle, Map, MessageSquare, Edit3, Image, Download, Send, CheckCircle2, XCircle, Circle, Settings, ChevronRight, ChevronLeft, X, Trash2, Sparkles, ListChecks, ArrowRight, FileText, BarChart3, Brain, CalendarPlus, Award, RotateCcw, Copy } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import { AI_TIMEOUT_MS, materialService, reviewNoteService, plannerService, planAnalysisService, socraticReviewService } from '../services/api';
import SummarySectionCard from '../components/SummarySectionCard';
import KeywordDefineModal from '../components/KeywordDefineModal';
import ReviewNoteArchiveDetail from '../components/review-note/ReviewNoteArchiveDetail';
import ReviewNoteLearningEntry from '../components/review-note/ReviewNoteLearningEntry';
import { sanitizeMarkdownText, sanitizeList } from '../utils/markdown';
import { cleanLearningOrNull, filterLearningList } from '../utils/learningContent';

// detectedTextSource(페이지 텍스트 출처) 한글 라벨
const DETECTED_SOURCE_LABEL = {
  TEXT: '텍스트 추출', OCR: 'OCR 인식', CAPTION: '캡션 기반', TABLE: '표 기반',
  IMAGE_DESCRIPTION: '이미지 설명 기반', MIXED: '혼합 분석', INSUFFICIENT: '텍스트 부족',
};

// 세부 핵심 내용 — 페이지 단위 카드 1개씩 표시 + ‹ › 네비게이션.
//  · page 번호는 서버가 준 pageNumber/page 를 그대로 쓴다(PDF 페이지와 카드 index 어긋남 방지).
//  · 첫 페이지에서 ‹ 비활성, 마지막 페이지에서 › 비활성(순환하지 않음 — 명확한 끝 처리).
//  · ai07 신규 page 필드(pageNumber/oneLineSummary/keywords/bulletPoints/takeaway/sourceQuality/
//    extractedText/textPreview/extractedTextTruncated/warnings)와 기존 필드(page/pageOverview/
//    keyConcepts/summaryBullets/studyFocus/detectedTextSource)를 모두 수용한다(additive, 신규 우선).
//    Spring 은 pageSummaries 를 Map 그대로 전달하므로 신규 필드가 드롭되지 않는다 — 프론트만 보강하면 됨.
//  · ‘원문/추출 텍스트’: ai07 extractedText(원문) 또는 textPreview(부분)가 있으면 그 페이지 원문을 우선
//    표시하고, 없으면 추출·정리된 내용을 조립해 보여준다(동작 없는 dead 버튼 금지).
// HTML 엔티티 디코드 — 서버가 &quot; 등을 그대로 내려도 화면엔 정상 문자로 표시(DOM 비의존 안전 치환).
const HTML_ENTITY_MAP = { '&quot;': '"', '&#34;': '"', '&apos;': "'", '&#39;': "'", '&amp;': '&', '&#38;': '&', '&lt;': '<', '&#60;': '<', '&gt;': '>', '&#62;': '>', '&nbsp;': ' ' };
function decodeEntities(value) {
  if (value == null) return '';
  let s = String(value);
  s = s.replace(/&(?:quot|#34|apos|#39|amp|#38|lt|#60|gt|#62|nbsp);/g, (m) => HTML_ENTITY_MAP[m] || m);
  s = s.replace(/&#(\d+);/g, (_, n) => { const c = Number(n); return Number.isFinite(c) ? String.fromCharCode(c) : _; });
  return s;
}

// PDF 페이지 병합기 — minify(terser) 가 최상위 함수명을 망글링하므로, 운영 JS 에서도
// `resolveTotalPages`/`mergePageCards` 식별자가 보이도록 '객체 메서드'(속성 키는 망글링 제외)로 정의한다.
// ⚠️ 이 파일은 lucide-react 의 Map 아이콘을 import 하여 전역 Map 이 가려짐 → new Map() 금지(plain array 사용).
const pdfPager = {
  // PDF 총 페이지 수 결정 — 명시 필드(여러 별칭) 우선, 없으면 카드들의 최대 pageNumber/배열 길이.
  // 우선순위: totalPages → pageCount → pdfPageCount → totalPageCount → pageTotal → max(pageNumber) → max(len).
  // 단일 카드만 와도 명시 totalPages 가 있으면 1/N 이 유지되어 '1 / 1' 고정을 방지한다.
  resolveTotalPages(note) {
    const num = (v) => { const n = Number(v); return Number.isFinite(n) && n > 0 ? n : 0; };
    const explicit = num(note?.totalPages) || num(note?.pageCount) || num(note?.pdfPageCount)
      || num(note?.totalPageCount) || num(note?.pageTotal) || num(note?.numPages);
    const arrs = [note?.pageAnalyses, note?.detailedCoreContents, note?.pageSummaries]
      .map((a) => (Array.isArray(a) ? a : []));
    const maxPageNo = arrs.reduce((mx, list) => list.reduce((m, c) => {
      const pn = num(c?.pageNumber ?? c?.page ?? c?.pageNo ?? c?.page_no);
      return pn > m ? pn : m;
    }, mx), 0);
    const maxLen = Math.max(0, ...arrs.map((a) => a.length));
    return Math.max(explicit, maxPageNo, maxLen);
  },

  // pageSummaries + detailedCoreContents(+pageAnalyses) 를 pageNumber/page/pageNo 기준으로 병합.
  // 같은 페이지 번호의 카드는 하나로 합치고(번호 없으면 등장 순서로 채움), totalPages 길이만큼 1..N 슬롯을 보장한다.
  mergePageCards(note, total) {
    const arr = (a) => (Array.isArray(a) ? a : []);
    const pageNoOf = (c, fallback) => {
      const n = Number(c?.pageNumber ?? c?.page ?? c?.pageNo ?? c?.page_no);
      return Number.isFinite(n) && n > 0 ? n : fallback;
    };
    const byPage = []; // index = pageNumber-1
    const put = (card, src, fallbackNo) => {
      const pn = pageNoOf(card, fallbackNo);
      const k = pn - 1;
      if (k < 0) return;
      if (!byPage[k]) byPage[k] = { pageNumber: pn };
      byPage[k][src] = card;
    };
    arr(note?.pageAnalyses).forEach((c, i) => put(c, 'a', i + 1));
    arr(note?.detailedCoreContents).forEach((c, i) => put(c, 'd', i + 1));
    arr(note?.pageSummaries).forEach((c, i) => put(c, 's', i + 1));
    const span = Math.max(total || 0, byPage.length);
    if (!span || span < 1) return [];
    const pages = [];
    for (let i = 0; i < span; i += 1) {
      const slot = byPage[i] || {};
      const a = slot.a || {};
      const d = slot.d || {};
      const s = slot.s || {};
      pages.push({
        // 병합된 페이지 번호(없으면 index+1) — 좌우 이동 시 1 / N 정상 표기
        pageNumber: slot.pageNumber ?? (i + 1),
        title: a.title ?? d.title ?? s.title ?? '',
        oneLineSummary: a.oneLineSummary ?? a.summary ?? '',
        pageOverview: s.pageOverview ?? '',
        bulletPoints: a.bulletPoints ?? a.keyPoints ?? [],
        summaryBullets: s.summaryBullets ?? [],
        keywords: a.keywords ?? [],
        keyConcepts: s.keyConcepts ?? [],
        takeaway: a.takeaway ?? '',
        studyFocus: s.studyFocus ?? '',
        sourceQuality: a.sourceQuality ?? a.extractionStatus ?? s.sourceQuality ?? '',
        detectedTextSource: s.detectedTextSource ?? '',
        contentType: a.contentType ?? s.contentType ?? '',
        conceptExplanations: a.conceptExplanations ?? s.conceptExplanations ?? [],
        examples: a.examples ?? s.examples ?? [],
        extractionStatus: a.extractionStatus ?? '',
        extractedText: a.extractedText ?? s.extractedText ?? '',
        textPreview: a.textPreview ?? s.textPreview ?? '',
        warnings: a.warnings ?? s.warnings ?? [],
        detailContent: d.content ?? '',
      });
    }
    return pages;
  },
};

// 세부 핵심 내용 페이지 병합 — totalPages 를 먼저 해석한 뒤 pageNumber 기준으로 카드들을 병합한다.
function buildDetailedPages(note) {
  const total = pdfPager.resolveTotalPages(note);
  return pdfPager.mergePageCards(note, total);
}

// 보강 설명 정규화 + 프론트 최종 방어 필터(핵심 필터는 ai07 책임 — 프론트는 마지막 방어선).
const ENRICH_PAGE_TERMS = ['페이지', '자료', '본문', 'pdf', '텍스트', '내용'];
function normalizeEnrichment(note) {
  const arr = (a) => (Array.isArray(a) ? a : []);
  const raw = arr(note?.enrichment).length ? arr(note?.enrichment) : arr(note?.wikiSummaries);
  return raw
    .map((w) => ({
      term: decodeEntities(w?.term ?? w?.concept ?? w?.title ?? ''),
      explanation: decodeEntities(w?.explanation ?? w?.description ?? w?.summary ?? ''),
      pages: w?.pages ?? w?.relatedPages ?? w?.page ?? null,
      source: decodeEntities(w?.source ?? w?.reference ?? ''),
      used: !!w?.used,
    }))
    .filter((w) => {
      if (!w.explanation) return false;
      const t = w.term.trim().toLowerCase();
      if (ENRICH_PAGE_TERMS.includes(t)) return false;              // 문서 '페이지/자료/본문...' 의미 term 숨김
      if (/larry page|래리 페이지/i.test(w.explanation)) return false; // 'page' → 인물(래리 페이지) 오역 방어
      return true;
    });
}

// 학습 일지 저장용 마크다운 본문 조립(자료 분석 결과 — 핵심/페이지별 세부/보강 설명/출처).
function buildAnalysisJournalMarkdown(note, material) {
  const arr = (a) => (Array.isArray(a) ? a : []);
  const title = decodeEntities(material?.title || material?.originalFileName || '자료');
  const out = [`# ${title}`, ''];
  const core = arr(note?.coreContents).filter(Boolean);
  if (core.length) {
    out.push('## 핵심 내용');
    core.forEach((c) => out.push(`- ${decodeEntities(typeof c === 'string' ? c : (c?.content || c?.title || ''))}`));
    out.push('');
  }
  const pages = buildDetailedPages(note);
  if (pages.length) {
    out.push('## 페이지별 세부 핵심');
    pages.forEach((p) => {
      out.push(`### p.${p.pageNumber}${p.title ? ` ${decodeEntities(p.title)}` : ''}`);
      const summary = decodeEntities(p.oneLineSummary || p.pageOverview || '');
      if (summary) out.push(`- 요약: ${summary}`);
      const bullets = (p.bulletPoints?.length ? p.bulletPoints : p.summaryBullets) || [];
      arr(bullets).forEach((b) => { const t = decodeEntities(typeof b === 'string' ? b : (b?.text || b?.content || '')); if (t) out.push(`- ${t}`); });
      if (p.detailContent) out.push(`- ${decodeEntities(p.detailContent)}`);
      out.push('');
    });
  }
  // '보강 설명'(Wikipedia 보강)은 본문과 상이해 학습 일지 저장에서도 제외(사용자 요청).
  out.push('## 출처');
  out.push(`- 자료보관함 materialId: ${material?.materialId ?? material?.id ?? ''}`);
  return out.join('\n');
}

function DetailedPager({ pages }) {
  const list = (a) => (Array.isArray(a) ? a.filter((x) => x != null && String(x).trim() !== '') : []);
  const firstList = (...cands) => { for (const c of cands) { const v = list(c); if (v.length) return v; } return []; };
  const firstStr = (...cands) => { for (const c of cands) { if (c != null && String(c).trim() !== '') return String(c); } return ''; };
  const total = pages.length;
  const [idx, setIdx] = useState(0);
  const [showText, setShowText] = useState(false);
  const [copied, setCopied] = useState(false);
  const safe = Math.min(Math.max(idx, 0), total - 1);
  // 페이지 수가 줄어들면 인덱스 보정
  useEffect(() => { if (idx > total - 1) setIdx(Math.max(total - 1, 0)); }, [total, idx]);
  // 페이지 이동 시 추출 텍스트 패널/복사 상태 초기화
  useEffect(() => { setShowText(false); setCopied(false); }, [safe]);

  const p = pages[safe] || {};
  // 신규(ai07) 이름 우선 → 기존 이름 fallback. 둘 다 없으면 빈 값(화면 안 깨짐).
  const src = String(firstStr(p.sourceQuality, p.detectedTextSource)).toUpperCase();
  const insufficient = src === 'INSUFFICIENT' || src === 'NONE';
  const concepts = firstList(p.keywords, p.keyConcepts);
  const bullets = firstList(p.bulletPoints, p.summaryBullets);
  const overview = firstStr(p.oneLineSummary, p.pageOverview, p.detailContent);
  const takeaway = firstStr(p.takeaway, p.studyFocus);
  const contentType = firstStr(p.contentType);
  // 개념 설명: [{term, explanation}] 배열만 추림(문자열만 온 경우도 수용).
  const conceptExplanations = list(p.conceptExplanations)
    .map((c) => (typeof c === 'string' ? { term: c, explanation: '' } : c))
    .filter((c) => c && (c.term || c.explanation));
  const examples = list(p.examples).filter(Boolean);
  const warnings = list(p.warnings);
  const title = firstStr(p.title);
  const pageNo = p.pageNumber ?? p.page ?? (safe + 1);
  const atFirst = safe <= 0;
  const atLast = safe >= total - 1;

  // 원문 텍스트: ai07 extractedText(원문) 우선 → textPreview(부분) → 없으면 조립 fallback
  const rawText = firstStr(p.extractedText, p.textPreview);
  const isRaw = !!rawText;
  const truncated = isRaw && (p.extractedTextTruncated === true || (!p.extractedText && !!p.textPreview));
  const assembled = [
    title ? `[p.${pageNo}] ${title}` : `[p.${pageNo}]`,
    overview ? `\n${overview}` : '',
    ...(bullets.length ? ['', ...bullets.map((b) => `• ${b}`)] : []),
    takeaway ? `\n🎯 ${takeaway}` : '',
  ].filter(Boolean).join('\n').trim();
  const panelText = isRaw ? rawText : assembled;

  const copyText = async () => {
    try { await navigator.clipboard.writeText(panelText); setCopied(true); setTimeout(() => setCopied(false), 1500); }
    catch (e) { console.error('추출 텍스트 복사 실패:', e); setCopied(false); }
  };

  const navBtn = (disabled, onClick, label, Icon) => (
    <button
      type="button"
      onClick={(e) => { e.preventDefault(); e.stopPropagation(); if (!disabled) onClick(); }}
      disabled={disabled} aria-label={label} title={label}
      style={{
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: '32px', height: '32px',
        borderRadius: '8px', border: '1px solid var(--color-border)', background: disabled ? '#F3F4F6' : '#fff',
        color: disabled ? '#D1D5DB' : 'var(--color-text-main)', cursor: disabled ? 'default' : 'pointer', flexShrink: 0,
        // overlay/stacking 컨텍스트로 클릭이 막히지 않도록 명시적으로 올림
        position: 'relative', zIndex: 2, pointerEvents: disabled ? 'none' : 'auto',
      }}
    >
      <Icon size={18} />
    </button>
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
      {/* 네비게이션 바: 위치 표시 + ‹ › */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', position: 'relative', zIndex: 2 }}>
        <span style={{ fontSize: '12.5px', fontWeight: 700, color: 'var(--color-text-muted)' }}>{safe + 1} / {total} 페이지</span>
        <div style={{ display: 'flex', gap: '6px' }}>
          {navBtn(atFirst, () => setIdx(safe - 1), '이전 페이지', ChevronLeft)}
          {navBtn(atLast, () => setIdx(safe + 1), '다음 페이지', ChevronRight)}
        </div>
      </div>

      {/* 페이지 카드 */}
      <div style={{ border: `1px solid ${insufficient ? '#FDE68A' : 'var(--color-border)'}`, borderRadius: '10px', padding: '14px 16px', background: insufficient ? '#FFFBEB' : '#fff' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px', flexWrap: 'wrap', marginBottom: '8px' }}>
          <span style={{ fontWeight: 700, fontSize: '14px', color: 'var(--color-text-main)' }}>p.{pageNo}{title ? ` ${title}` : ''}</span>
          {(contentType || src) && (
            <span title="이 페이지의 콘텐츠 유형/출처" style={{ fontSize: '11px', fontWeight: 700, padding: '2px 8px', borderRadius: '6px', background: insufficient ? '#FEF3C7' : '#EFF6FF', color: insufficient ? '#92400E' : '#1D4ED8' }}>
              {contentType || DETECTED_SOURCE_LABEL[src] || src}
            </span>
          )}
        </div>
        {insufficient ? (
          <p style={{ margin: 0, fontSize: '13.5px', lineHeight: 1.6, color: '#92400E' }}>
            이 페이지는 PDF 텍스트 추출과 OCR 결과가 부족하여 핵심 내용을 명확히 식별하기 어렵습니다.
          </p>
        ) : (
          <>
            {overview && <p style={{ margin: '0 0 8px', fontSize: '13.5px', lineHeight: 1.6, color: 'var(--color-text-muted)' }}>{overview}</p>}
            {concepts.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '8px' }}>
                {concepts.map((c, k) => <span key={k} className="tag" style={{ backgroundColor: '#F3F4F6', color: 'var(--color-text-main)', border: '1px solid var(--color-border)' }}>{c}</span>)}
              </div>
            )}
            {conceptExplanations.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginBottom: '8px' }}>
                <span style={{ fontSize: '12px', fontWeight: 800, color: '#4338CA' }}>📘 개념 설명</span>
                {conceptExplanations.map((c, k) => (
                  <div key={k} style={{ fontSize: '13.5px', lineHeight: 1.6, color: 'var(--color-text-main)' }}>
                    <strong>{c.term}</strong>{c.explanation ? ` — ${c.explanation}` : ''}
                  </div>
                ))}
              </div>
            )}
            {examples.length > 0 && (
              <div style={{ background: '#FFFBEB', borderRadius: '6px', padding: '8px 12px', marginBottom: '8px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <span style={{ fontSize: '12px', fontWeight: 800, color: '#B45309' }}>💡 예시</span>
                <ul style={{ margin: 0, paddingLeft: '18px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  {examples.map((ex, k) => <li key={k} style={{ fontSize: '13.5px', lineHeight: 1.6, color: '#92400E' }}>{ex}</li>)}
                </ul>
              </div>
            )}
            {bullets.length > 0 && (
              <ul style={{ margin: '0 0 8px', paddingLeft: '18px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                {bullets.map((b, k) => <li key={k} style={{ fontSize: '13.5px', lineHeight: 1.6, color: 'var(--color-text-main)' }}>{b}</li>)}
              </ul>
            )}
            {takeaway && (
              <div style={{ fontSize: '13px', color: '#15803D', background: '#F0FDF4', borderRadius: '6px', padding: '6px 10px', marginBottom: '4px' }}>🎯 {takeaway}</div>
            )}
            {warnings.length > 0 && (
              <div style={{ marginTop: '4px', fontSize: '12px', color: '#92400E', background: '#FFFBEB', border: '1px solid #FDE68A', borderRadius: '6px', padding: '6px 10px' }}>
                {warnings.map((w, k) => <div key={k}>⚠️ {w}</div>)}
              </div>
            )}
          </>
        )}

        {/* 원문/추출 텍스트 보기(복사 가능) — ai07 extractedText 있으면 원문, 없으면 정리 내용 */}
        {!insufficient && panelText && (
          <div style={{ marginTop: '10px', borderTop: '1px dashed var(--color-border)', paddingTop: '10px' }}>
            <button
              type="button" onClick={() => setShowText((v) => !v)}
              style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '12.5px', fontWeight: 700, color: 'var(--color-primary)', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
            >
              <FileText size={14} /> {showText ? '접기' : (isRaw ? '이 페이지 원문 텍스트 보기' : '이 페이지 추출 내용 보기')}
            </button>
            {showText && (
              <div style={{ marginTop: '8px' }}>
                {truncated && (
                  <div style={{ marginBottom: '6px', fontSize: '11.5px', color: '#92400E' }}>※ 원문 일부만 표시됩니다(미리보기).</div>
                )}
                <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '6px' }}>
                  <button
                    type="button" onClick={copyText}
                    style={{ display: 'inline-flex', alignItems: 'center', gap: '5px', fontSize: '12px', padding: '4px 10px', borderRadius: '6px', border: '1px solid var(--color-border)', background: '#fff', cursor: 'pointer', color: copied ? '#15803D' : 'var(--color-text-main)' }}
                  >
                    {copied ? <CheckCircle2 size={13} /> : <Copy size={13} />} {copied ? '복사됨' : '복사'}
                  </button>
                </div>
                <pre style={{ margin: 0, maxHeight: '220px', overflowY: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: '12.5px', lineHeight: 1.6, color: 'var(--color-text-main)', background: '#F9FAFB', border: '1px solid var(--color-border)', borderRadius: '8px', padding: '10px 12px', fontFamily: 'inherit' }}>{panelText}</pre>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// AI 핵심 요약 노트(전공 분야·핵심 객체 중심) 결과 렌더 — 11개 섹션. studyNote.status==='SUCCESS' 일 때만 사용.
function StudyNoteView({ note, material, onKeyword }) {
  const list = (a) => (Array.isArray(a) ? a.filter(Boolean) : []);
  const kws = list(note.keywords);
  const core = list(note.coreContents);
  // 세부 핵심 내용: pageAnalyses(신규) → detailedCoreContents → pageSummaries 를 totalPages 기준으로 병합.
  const detailedPages = buildDetailedPages(note);
  const points = list(note.studyPoints);
  const questions = list(note.aiStudyQuestions);
  // 보강 설명: enrichment(신규) 우선 + 엔티티 디코드 + 프론트 최종 방어 필터.
  const enrich = normalizeEnrichment(note);
  const limits = list(note.limitations);

  // 학습 일지에 추가 — 기존 createStudyLog(POST /api/materials/log, 소유자 인증) 재사용.
  const [journalState, setJournalState] = useState('idle'); // idle | saving | done | error
  const addToJournal = async () => {
    if (journalState === 'saving' || journalState === 'done') return; // 중복 클릭 방지
    try {
      setJournalState('saving');
      const content = buildAnalysisJournalMarkdown(note, material);
      const keywords = list(note.keywords).join(', ');
      await materialService.createStudyLog({
        title: `[자료보관함] ${decodeEntities(material?.title || material?.originalFileName || '자료')} 핵심 정리`,
        keywords,
        studyDate: new Date().toISOString().slice(0, 10),
        learningContent: content,
        nextPlan: '',
      });
      setJournalState('done');
    } catch (e) {
      console.error('학습 일지 추가 실패:', e);
      setJournalState('error');
    }
  };
  const journalLabel = { idle: '학습 일지에 추가', saving: '추가 중…', done: '학습 일지에 추가됨', error: '다시 시도' }[journalState];
  const coreObj = note.coreObjectLabel || note.coreObject;
  const showOrig = note.coreObjectLabel && note.coreObject && note.coreObjectLabel !== note.coreObject;
  const Section = ({ title, color = 'var(--color-primary)', children }) => (
    <div className="glass-panel" style={{ padding: '18px 20px', borderLeft: `4px solid ${color}` }}>
      <h4 style={{ margin: '0 0 12px', fontSize: '16px', color: 'var(--color-text-main)' }}>{title}</h4>
      {children}
    </div>
  );
  const ulStyle = { margin: 0, paddingLeft: '18px', display: 'flex', flexDirection: 'column', gap: '8px' };
  const liStyle = { fontSize: '14px', lineHeight: '1.6', color: 'var(--color-text-muted)' };

  // 세부 핵심 내용: 병합된 detailedPages 를 수직 리스트 뷰(섹션별)로 모두 보여줌
  const renderDetailed = () => {
    if (detailedPages.length > 0) {
      return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {detailedPages.map((p, i) => (
            <div key={i} className="glass-panel" style={{ padding: '20px', borderLeft: '4px solid #3B82F6', display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
                <span style={{ backgroundColor: '#DBEAFE', color: '#1E40AF', padding: '4px 10px', borderRadius: '8px', fontSize: '13px', fontWeight: '800' }}>
                  {p.pageNumber ? `p.${p.pageNumber}` : `p.${i + 1}`}
                </span>
                <span style={{ fontWeight: '700', fontSize: '15px', color: 'var(--color-text-main)' }}>
                  {p.title || '페이지 핵심 요약'}
                </span>
                {/* 콘텐츠 유형(텍스트/이미지/표/혼합) 배지 — source 코드보다 사람이 읽기 쉬운 표기 우선 */}
                {(p.contentType || p.detectedTextSource) && (
                  <span style={{ fontSize: '11px', backgroundColor: '#EEF2FF', color: '#4338CA', padding: '2px 8px', borderRadius: '6px', fontWeight: '700', marginLeft: 'auto' }}>
                    {p.contentType || DETECTED_SOURCE_LABEL[p.detectedTextSource] || p.detectedTextSource}
                  </span>
                )}
              </div>

              {p.pageOverview && (
                <div style={{ fontSize: '14px', lineHeight: '1.6', color: 'var(--color-text-muted)' }}>
                  {p.pageOverview}
                </div>
              )}

              {/* 개념 설명: 이름만이 아니라 풀어쓴 설명 */}
              {Array.isArray(p.conceptExplanations) && p.conceptExplanations.length > 0 && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  <span style={{ fontSize: '12px', fontWeight: '800', color: '#4338CA' }}>📘 개념 설명</span>
                  {p.conceptExplanations
                    .map((c) => (typeof c === 'string' ? { term: c, explanation: '' } : c))
                    .filter((c) => c && (c.term || c.explanation))
                    .map((c, idx) => (
                      <div key={idx} style={{ fontSize: '14px', lineHeight: '1.6', color: 'var(--color-text-main)' }}>
                        <strong>{c.term}</strong>{c.explanation ? ` — ${c.explanation}` : ''}
                      </div>
                    ))}
                </div>
              )}

              {/* 추가 예시 */}
              {Array.isArray(p.examples) && p.examples.length > 0 && (
                <div style={{ backgroundColor: '#FFFBEB', borderRadius: '8px', padding: '10px 14px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <span style={{ fontSize: '12px', fontWeight: '800', color: '#B45309' }}>💡 예시</span>
                  <ul style={{ margin: 0, paddingLeft: '18px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    {p.examples.filter(Boolean).map((ex, idx) => (
                      <li key={idx} style={{ fontSize: '14px', lineHeight: '1.6', color: '#92400E' }}>{ex}</li>
                    ))}
                  </ul>
                </div>
              )}

              {((p.summaryBullets && p.summaryBullets.length > 0) || (p.bulletPoints && p.bulletPoints.length > 0)) && (
                <ul style={{ margin: 0, paddingLeft: '20px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  {(p.summaryBullets?.length ? p.summaryBullets : p.bulletPoints).map((b, idx) => (
                    <li key={idx} style={{ color: 'var(--color-text-main)', fontSize: '14px', lineHeight: '1.6' }}>{b}</li>
                  ))}
                </ul>
              )}
              
              {p.studyFocus && (
                <div style={{ backgroundColor: '#F0FDF4', color: '#166534', padding: '10px 14px', borderRadius: '8px', fontSize: '13px', fontWeight: '600', display: 'flex', alignItems: 'flex-start', gap: '8px', marginTop: '4px' }}>
                  <span style={{ fontSize: '14px' }}>🎯</span> <span style={{ flex: 1, lineHeight: '1.5' }}>{p.studyFocus}</span>
                </div>
              )}
            </div>
          ))}
        </div>
      );
    }
    return (
      <div style={{ borderRadius: '10px', border: '1px dashed var(--color-border)', background: '#F9FAFB', padding: '16px 18px' }}>
        <p style={{ margin: 0, color: 'var(--color-text-muted)', fontSize: '14px', lineHeight: 1.6 }}>
          아직 페이지별 세부 핵심 내용이 없습니다. 문서 분석이 끝나면 페이지별 핵심 내용이 여기에 표시됩니다.
        </p>
      </div>
    );
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {note.disclaimer && (
        <div className="glass-panel" style={{ padding: '12px 16px', borderLeft: '4px solid #9CA3AF', backgroundColor: '#F9FAFB', fontSize: '13px', color: 'var(--color-text-muted)' }}>ℹ️ {note.disclaimer}</div>
      )}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px' }}>
        {note.domainLabel && (
          <span style={{ padding: '6px 14px', borderRadius: '20px', fontSize: '13px', fontWeight: 700, background: '#ECFDF5', color: '#15803D', border: '1px solid #BBF7D0' }}>자동 분류 분야: {note.domainLabel}</span>
        )}
        {coreObj && (
          <span style={{ padding: '6px 14px', borderRadius: '20px', fontSize: '13px', fontWeight: 700, background: '#EFF6FF', color: '#1D4ED8', border: '1px solid #BFDBFE' }}>핵심 객체: {coreObj}{showOrig ? ` (${note.coreObject})` : ''}</span>
        )}
      </div>
      {note.documentOverview && (
        <Section title="📌 문서 개요"><p style={{ margin: 0, fontSize: '15px', lineHeight: '1.7', color: 'var(--color-text-muted)', whiteSpace: 'pre-wrap' }}>{note.documentOverview}</p></Section>
      )}
      {kws.length > 0 && (
        <div>
          <h4 style={{ margin: '0 0 8px', fontSize: '16px', color: 'var(--color-text-main)' }}>🔑 핵심 키워드</h4>
          <p style={{ margin: '0 0 12px', fontSize: '13px', color: 'var(--color-text-muted)' }}>키워드를 클릭하면 AI/Wikipedia 기반 개념 정의를 볼 수 있어요.</p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
            {kws.map((kw) => (
              <button key={kw} onClick={() => onKeyword && onKeyword(kw)} className="tag" style={{ backgroundColor: '#F3F4F6', color: 'var(--color-text-main)', border: '1px solid var(--color-border)', cursor: 'pointer' }}>#{kw}</button>
            ))}
          </div>
        </div>
      )}
      {core.length > 0 && (
        <Section title="🧩 핵심 내용"><ul style={ulStyle}>{core.map((c, i) => <li key={i} style={liStyle}>{c}</li>)}</ul></Section>
      )}
      <div>
        <h4 style={{ margin: '0 0 4px', fontSize: '16px', color: 'var(--color-text-main)' }}>📑 세부 핵심 내용</h4>
        <p style={{ margin: '0 0 16px', fontSize: '13px', color: 'var(--color-text-muted)' }}>PDF의 각 페이지에서 추출한 핵심 내용을 페이지별로 정리했습니다.</p>
        {renderDetailed()}
      </div>
      {points.length > 0 && (
        <Section title="🎯 학습 포인트" color="#3B82F6"><ul style={ulStyle}>{points.map((p, i) => <li key={i} style={liStyle}>{p}</li>)}</ul></Section>
      )}
      {questions.length > 0 && (
        <Section title="❓ AI 학습 질문" color="#F59E0B"><ul style={ulStyle}>{questions.map((q, i) => <li key={i} style={liStyle}>{q}</li>)}</ul></Section>
      )}
      {/* '📚 보강 설명'(Wikipedia 보강) 섹션은 자료 본문과 내용이 상이해 제거함(사용자 요청). */}
      {limits.length > 0 && (
        <Section title="⚠️ 한계" color="#9CA3AF"><ul style={ulStyle}>{limits.map((l, i) => <li key={i} style={liStyle}>{l}</li>)}</ul></Section>
      )}

      {/* 화면 하단 — 분석 결과(세부 핵심/보강 설명) 아래에 항상 보이는 학습 일지 추가 버튼 */}
      <div style={{ borderTop: '1px solid var(--color-border)', paddingTop: '16px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <button
          type="button"
          onClick={addToJournal}
          disabled={journalState === 'saving' || journalState === 'done'}
          className={journalState === 'done' ? 'btn-outline' : 'btn-primary'}
          style={{ width: 'auto', alignSelf: 'flex-start', padding: '10px 20px', borderRadius: '20px', display: 'inline-flex', alignItems: 'center', gap: '8px', cursor: (journalState === 'saving' || journalState === 'done') ? 'default' : 'pointer', opacity: journalState === 'saving' ? 0.7 : 1 }}
        >
          {journalState === 'done' ? <CheckCircle2 size={16} /> : <CalendarPlus size={16} />}
          {journalLabel}
        </button>
        {journalState === 'done' && (
          <span style={{ fontSize: '13px', color: '#15803D' }}>✓ 학습 일지에 추가되었습니다. 학습일지에서 확인할 수 있어요.</span>
        )}
        {journalState === 'error' && (
          <span style={{ fontSize: '13px', color: '#B91C1C' }}>학습 일지 추가에 실패했습니다. 다시 시도해주세요.</span>
        )}
      </div>
    </div>
  );
}

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

// AI 질문 기록 영속화 — materialId별 localStorage 저장/복구
const CHAT_INTRO = '업로드한 자료를 바탕으로 궁금한 점을 질문해보세요.';
const chatStorageKey = (mid) => `studybridge:material-chat:${mid}`;

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
  const [studyNote, setStudyNote] = useState(null); // AI 핵심 요약 노트(전공 분야·핵심 객체 중심), PDF 전용
  const [quizzes, setQuizzes] = useState([]);
  const [selectedQuizId, setSelectedQuizId] = useState(null);
  const [roadmapSteps, setRoadmapSteps] = useState([]);
  const [isRegeneratingRoadmap, setIsRegeneratingRoadmap] = useState(false);
  const [roadmapLevel, setRoadmapLevel] = useState('intermediate'); // beginner | intermediate | advanced
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [isAddingStudyLog, setIsAddingStudyLog] = useState(false);
  const [isSavingMemoJournal, setIsSavingMemoJournal] = useState(false); // 메모 → 학습일지 저장
  const [showAllDetailed, setShowAllDetailed] = useState(false);
  // 메모 탭(PDF 상세): 입력=memoText, 검증 통과(ACCEPT)분만 S3 저장. 검증결과=journalNotice
  const [memoText, setMemoText] = useState('');
  const [studyJournals, setStudyJournals] = useState([]);
  const [journalNotice, setJournalNotice] = useState(null); // 검증 사유/제안 {type, reason, suggestion}
  // 플래너 상세의 자유 메모(기존 /memo API) — 메모 탭의 검증 저장과 분리 유지
  const [plannerMemoText, setPlannerMemoText] = useState('');
  const [isSavingPlannerMemo, setIsSavingPlannerMemo] = useState(false);
  const [chatMessages, setChatMessages] = useState([{ sender: 'ai', text: CHAT_INTRO }]);
  const [chatInput, setChatInput] = useState('');

  const [roadmapData, setRoadmapData] = useState(null);
  const [roadmapError, setRoadmapError] = useState(null);
  // AI 로드맵 실패 시 deterministic fallback 로 대체했음을 알리는 안내(로드맵은 그대로 제공)
  const [roadmapFallbackNotice, setRoadmapFallbackNotice] = useState(null);
  const [quizError, setQuizError] = useState(null);
  // AI 퀴즈 생성 실패 시 deterministic fallback 으로 대체했음을 알리는 안내(문제는 그대로 제공)
  const [quizFallbackNotice, setQuizFallbackNotice] = useState(null);
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
  // 자료보관함 PLANNER 상세 전용 — 학습계획/일정 보기 전환(기본 학습계획). 메모/퀴즈/AI질문 없음.
  // 우측 학습 도구 탭: 'analysis'(AI 계획 분석) | 'next'(다음 학습 추천) | 'memo' | 'progress'
  // (레거시 보조 뷰: 'plan' | 'checklist' | 'roadmap')
  const [plannerDetailView, setPlannerDetailView] = useState('analysis');
  // AI 계획 분석(PDF/플래너 문장 단위) 상태 — DB 영속(plan_analysis)
  const [planAnalysis, setPlanAnalysis] = useState(null); // GET/POST 응답(Response)
  const [planLoading, setPlanLoading] = useState(false);
  const [planError, setPlanError] = useState(null); // { errorCode, message }
  const [planItemBusy, setPlanItemBusy] = useState(null); // 갱신 중인 itemId

  // 소크라테스 복습 세션 — React→Spring(/api/materials/{id}/socratic-review/*)만 호출. ai07 직접 호출 금지.
  const [socraticSession, setSocraticSession] = useState(null);  // 현재 턴 {sessionId, question, message, ...}
  const [socraticHistory, setSocraticHistory] = useState([]);    // [{role:'ai'|'user', text}]
  const [socraticAnswer, setSocraticAnswer] = useState('');
  const [socraticBusy, setSocraticBusy] = useState(false);       // start/answer/finish/schedule 진행 중(중복클릭 차단)
  const [socraticError, setSocraticError] = useState('');
  const [socraticUnavailable, setSocraticUnavailable] = useState(false); // ai07 신규 route 미배포(aiAvailable=false)
  const [socraticFinish, setSocraticFinish] = useState(null);    // 완료 요약 {overallMastery, weakConcepts, recommendedReviewDate, ...}
  const [socraticSchedule, setSocraticSchedule] = useState(null); // 복습일 등록 결과 {registered, alreadyRegistered, reviewDate, message}

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
    OPENAI_UNAVAILABLE: 'AI 모델 연결에 실패했습니다.',
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
    const deduped = removeDummyKeywords(data.keywords?.length ? data.keywords : (data.key_points?.length ? data.key_points : (envelope.keywords || envelope.key_points || [])));
    // 표시 전 2차 방어: 날짜/교수명/코스 제목 키워드 칩 제거
    return filterLearningList(deduped, material?.title);
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
      const keywords = filterLearningList((kws.length ? kws : removeDummyKeywords(material?.keywords)).map(sanitizeMarkdownText), material?.title);
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
    // 표시 전 2차 방어: PDF 표지 날짜/교수명/코스 제목이 섞인 항목은 정제/숨김. 자료 제목을 코스 제목 기준으로 사용.
    const courseTitle = material?.title || null;
    return weeks.map((week, idx) => {
      const rawTasks = Array.isArray(week.tasks) ? week.tasks : [];
      // 신(新) 84일 구조: week.days[]가 있으면 일자별로 정규화
      const rawDays = Array.isArray(week.days) ? week.days : [];
      const weekNo = Number(week.week || week.weekNumber || week.stepOrder || idx + 1);
      const days = rawDays.map((day, dayIdx) => ({
        dayIndex: Number(day.day_index || dayIdx + 1),
        dayLabel: day.day_label || `${dayIdx + 1}일차`,
        title: cleanLearningOrNull(day.title, courseTitle) || `${dayIdx + 1}일차 학습`,
        objective: cleanLearningOrNull(day.objective, courseTitle) || '',
        coreConcepts: filterLearningList(Array.isArray(day.core_concepts) ? day.core_concepts : [], courseTitle),
        tasks: filterLearningList((Array.isArray(day.tasks) ? day.tasks : []).map(normalizeDayTask), courseTitle),
        reviewQuestions: filterLearningList(Array.isArray(day.review_questions) ? day.review_questions : [], courseTitle),
        practice: day.practice || '',
        deliverable: cleanLearningOrNull(day.deliverable, courseTitle) || '',
        checkpoint: cleanLearningOrNull(day.checkpoint, courseTitle) || '',
        completed: !!day.completed,
      }));
      return {
        stepId: week.stepId || week.id || `week-${weekNo}`,
        stepOrder: weekNo,
        title: cleanLearningOrNull(week.title, courseTitle) || `${idx + 1}주차`,
        description: cleanLearningOrNull(week.objective || week.goal || week.description || week.week_summary, courseTitle) || '',
        weekSummary: cleanLearningOrNull(week.week_summary, courseTitle) || '',
        days,
        tasks: rawTasks.map((task, taskIdx) => (typeof task === 'string'
          ? { taskId: `week-${idx + 1}-task-${taskIdx + 1}`, taskOrder: taskIdx + 1, content: cleanLearningOrNull(task, courseTitle) || task, isCompleted: false }
          : { taskId: task.taskId || task.id || `week-${idx + 1}-task-${taskIdx + 1}`, taskOrder: task.taskOrder || taskIdx + 1, content: cleanLearningOrNull(task.content || task.title || String(task), courseTitle) || (task.content || task.title || String(task)), isCompleted: !!task.isCompleted }))
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
      // 오답노트(REVIEW_NOTE) 전용 복습 화면 진입 시에만 context 전달(백엔드 상세 차단 우회). 일반 자료는 차단 대상 아님.
      const detail = await materialService.getMaterialDetail(id, type === 'reviewNote' ? 'review-note' : undefined);
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
      setPlannerMemoText(memo?.content || '');
    } catch (e) {
      console.warn('메모 정보 로드 실패:', e);
    }

    // 4-1. 학습일지 목록 로드 (메타데이터만; 원문은 펼칠 때 S3에서 읽음)
    try {
      const journals = await materialService.getStudyJournals(materialId);
      setStudyJournals(Array.isArray(journals) ? journals : []);
    } catch (e) {
      console.warn('학습일지 목록 로드 실패:', e);
    }

    // 5. 저장된 AI 계획 분석 로드 (새로고침 후에도 결과/체크/숨김/진행률 유지)
    try {
      const pa = await planAnalysisService.get(materialId);
      setPlanAnalysis(pa && !pa.empty ? pa : null);
    } catch (e) {
      console.warn('AI 계획 분석 로드 실패:', e);
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
          const freshDetail = await materialService.getMaterialDetail(id, type === 'reviewNote' ? 'review-note' : undefined);
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

  // AI 핵심 요약 노트(전공 분야·핵심 객체 중심) 로드 + PENDING/RUNNING 폴링 (PDF 전용, 별도 버튼 없음)
  useEffect(() => {
    if (!userId || !id || !material) return;
    if (material.materialType !== 'PDF') { setStudyNote(null); return; }
    let cancelled = false;
    let timer;
    const tick = async () => {
      try {
        const data = await materialService.getStudyNote(id);
        if (cancelled) return;
        setStudyNote(data || null);
        if (data && (data.status === 'PENDING' || data.status === 'RUNNING')) {
          timer = setTimeout(tick, 5000);
        }
      } catch (e) {
        if (!cancelled) console.warn('AI 핵심 요약 노트 로드 실패:', e);
      }
    };
    tick();
    return () => { cancelled = true; if (timer) clearTimeout(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId, id, material?.materialId, material?.materialType, material?.extractionStatus]);

  // 채팅 메시지 끝으로 자동 스크롤
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatMessages]);

  // ---------------- AI 질문 기록 영속화 (materialId별 localStorage) ----------------
  // 상세 진입/새로고침/나갔다 들어오기 후에도 질문·답변·시간 유지. materialId 변경 시 해당 자료 기록만 로드.
  useEffect(() => {
    if (!id) return;
    try {
      const raw = localStorage.getItem(chatStorageKey(id));
      if (raw) {
        const saved = JSON.parse(raw);
        if (Array.isArray(saved) && saved.length > 0) { setChatMessages(saved); return; }
      }
    } catch (_) { /* 손상된 저장본 무시 */ }
    setChatMessages([{ sender: 'ai', text: CHAT_INTRO }]);
  }, [id]);

  // 대화가 바뀔 때마다 즉시 저장(생성 중 placeholder 제외)
  useEffect(() => {
    if (!id) return;
    try {
      const toSave = chatMessages.filter((m) => !m.isThinking);
      localStorage.setItem(chatStorageKey(id), JSON.stringify(toSave));
    } catch (_) { /* 용량 초과 등은 무시 */ }
  }, [chatMessages, id]);

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
    // 오답(WRONG) + 미응답(UNANSWERED) 모두 복습 대상. 미응답은 selectedAnswer 부재로 판별(서버도 동일하게 판별).
    const wrong = questions.filter((q, idx) => userAnswers[idx] !== undefined && userAnswers[idx] !== q.answer);
    const unanswered = questions.filter((q, idx) => userAnswers[idx] === undefined);
    if (wrong.length + unanswered.length === 0) { alert('복습할 문제가 없습니다. 모든 문제를 맞혔어요.'); return; }
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
  // PDF 새창으로 보기 — popup 차단 방지를 위해 클릭 이벤트 안에서 빈 창을 먼저 선점한 뒤 URL 주입.
  const handleViewReviewNotePdf = async (reviewNoteId, fallbackUrl) => {
    const win = window.open('', '_blank'); // 클릭 컨텍스트에서 즉시 선점
    try {
      const data = await reviewNoteService.getDownloadUrl(reviewNoteId);
      const url = data?.url || data?.downloadUrl || fallbackUrl;
      if (!url) { if (win) win.close(); alert('이 오답노트에는 아직 PDF가 없습니다.'); return; }
      if (win) win.location.href = url; else window.open(url, '_blank', 'noopener');
    } catch (e) {
      console.error('오답노트 PDF 열기 실패:', e);
      if (win) win.close();
      alert('PDF를 여는 중 문제가 발생했습니다.');
    }
  };

  // PDF 컴퓨터에 저장 — <a download> 로 직접 다운로드.
  const handleSaveReviewNotePdf = async (reviewNoteId, fallbackUrl, title) => {
    try {
      const data = await reviewNoteService.getDownloadUrl(reviewNoteId);
      const url = data?.url || data?.downloadUrl || fallbackUrl;
      if (!url) { alert('이 오답노트에는 아직 PDF가 없습니다.'); return; }
      const a = document.createElement('a');
      a.href = url;
      a.download = `${title || '오답노트'}.pdf`;
      document.body.appendChild(a); a.click(); a.remove();
    } catch (e) {
      console.error('오답노트 저장 실패:', e);
      alert('PDF 저장 중 문제가 발생했습니다.');
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
    // R. 문항 수 5~20 보정 (빈 값/미입력 → 10). try 밖에서 계산해 catch(fallback)에서도 사용.
    let appliedCount = parseInt(quizSettings.count, 10);
    if (Number.isNaN(appliedCount)) appliedCount = 10;
    if (appliedCount < 5) appliedCount = 5;
    if (appliedCount > 20) appliedCount = 20;

    // 공통: 퀴즈를 화면에 올리고 정리(성공/폴백 공용)
    const applyQuiz = (quiz, notice) => {
      setQuizError(null);
      setQuizFallbackNotice(notice || null);
      setQuizzes((prev) => [quiz, ...prev]);
      setSelectedQuizId(quiz.quizId);
      setUserAnswers({});
      setIsQuizSettingsOpen(false);
    };

    try {
      setIsGeneratingQuiz(true);
      // G. 생성 시작 즉시 이전/실패 퀴즈를 화면에서 내린다(stale quiz 방지).
      setQuizError(null);
      setQuizFallbackNotice(null);
      setSelectedQuizId(null);
      if (appliedCount !== quizSettings.count) setQuizSettings((s) => ({ ...s, count: appliedCount }));
      const req = {
        difficulty: quizSettings.difficulty,
        questionCount: appliedCount,
        pageRange: quizSettings.range,
        sourceMode: 'PDF_BASED', // 퀴즈는 PDF/DOCX 자료 본문 기준(로드맵 day 아님)
      };
      const newQuiz = await materialService.generateQuiz(id, req);

      // AI 응답이 정상(성공 + 난이도검증 통과 + 문제 ≥1)이면 그대로 사용.
      const serverFailed = newQuiz?.success === false;
      const hardInvalid = !serverFailed && isQuizHardInvalid(newQuiz);
      const aiQuestions = serverFailed ? [] : parseQuizQuestions(newQuiz?.quizzes?.length ? newQuiz.quizzes : newQuiz?.quizData);
      if (!serverFailed && !hardInvalid && aiQuestions.length > 0) {
        // ai07 신규 계약: 서버가 자체 fallback 문제를 내려준 경우(metadata.usedFallback) 안내만 표시(문제는 그대로 사용)
        const aiUsedFallback = newQuiz?.metadata?.usedFallback || newQuiz?.usedFallback;
        applyQuiz(newQuiz, aiUsedFallback ? 'AI가 문서 정보가 부족하여 기본 문제로 구성했습니다. 문제 풀이는 그대로 가능합니다.' : null);
        return;
      }

      // 실패/검증실패/빈 응답 → deterministic fallback 으로 "무조건" 문제 제공.
      const reason = serverFailed
        ? 'AI 문제 생성이 불안정하여 기본 문제로 생성했습니다. 문제 풀이는 그대로 가능합니다.'
        : hardInvalid
          ? '요청한 난이도가 충분히 반영되지 않아 기본 문제로 대체했습니다. 다시 생성하면 AI 문제를 재시도합니다.'
          : 'AI 문제 응답이 비어 있어 기본 문제로 생성했습니다.';
      applyQuiz(buildFallbackQuiz(appliedCount, quizSettings.difficulty), reason);
    } catch (e) {
      // timeout/404/500/parse 실패 모두 fallback 으로 흡수 — "생성 중" 고정·빈 화면 금지.
      console.error('퀴즈 생성 실패 → fallback:', e);
      applyQuiz(buildFallbackQuiz(appliedCount, quizSettings.difficulty), 'AI 서버 연결이 불안정하여 기본 문제로 생성했습니다.');
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
      setRoadmapFallbackNotice(null);
      const roadmap = await materialService.regenerateRoadmap(id, roadmapLevel);
      const normalized = normalizeAiResponse(roadmap);
      const newSteps = normalizeRoadmapSteps(roadmap?.roadmapData || roadmap);
      if (normalized.success === false || newSteps.length === 0) {
        // AI 실패/빈 응답 → UNKNOWN_ERROR로 끝내지 않고 deterministic fallback 로드맵을 "무조건" 제공.
        const fb = buildFallbackRoadmap(roadmapLevel);
        setRoadmapData(fb);
        setRoadmapSteps(normalizeRoadmapSteps(fb));
        setRoadmapError(null);
        setRoadmapFallbackNotice('AI 로드맵 생성이 불안정하여 기본 12주(84일) 로드맵으로 생성했습니다. 다시 생성하면 AI 로드맵을 재시도합니다.');
        return;
      }
      setRoadmapData(roadmap);
      setRoadmapSteps(newSteps);
      // ai07 신규 계약: 서버가 fallback 로드맵을 내려준 경우 안내(fallbackUsed/usedFallback)
      setRoadmapFallbackNotice((roadmap?.fallbackUsed || roadmap?.metadata?.usedFallback)
        ? 'AI가 문서 정보가 부족하여 기본 학습 절차 기반으로 로드맵을 구성했습니다.' : null);
    } catch (e) {
      console.error('로드맵 재생성 실패 → fallback:', e);
      // timeout/404/500/parse 실패 모두 fallback 으로 흡수 — UNKNOWN_ERROR·무한 pending 금지.
      const fb = buildFallbackRoadmap(roadmapLevel);
      setRoadmapData(fb);
      setRoadmapSteps(normalizeRoadmapSteps(fb));
      setRoadmapFallbackNotice('AI 서버 연결이 불안정하여 기본 12주(84일) 로드맵으로 생성했습니다. 다시 생성하면 AI 로드맵을 재시도합니다.');
    } finally {
      setIsRegeneratingRoadmap(false);
    }
  };

  // 플래너 상세의 자유 메모 저장(기존 /api/materials/{id}/memo). 메모 탭의 검증 저장과 분리.
  const handleSavePlannerMemo = async () => {
    try {
      setIsSavingPlannerMemo(true);
      await materialService.saveMemo(id, plannerMemoText);
      alert('메모가 저장되었습니다.');
    } catch (e) {
      console.error('메모 저장 실패:', e);
      alert('메모 저장 도중 오류가 발생했습니다.');
    } finally {
      setIsSavingPlannerMemo(false);
    }
  };

  // 메모 목록 재조회(메타데이터만; 원문은 펼칠 때 S3 GET). 저장/삭제 성공 후 호출.
  const reloadStudyJournals = async () => {
    try {
      const list = await materialService.listStudyJournals(id);
      setStudyJournals(Array.isArray(list) ? list : []);
    } catch (e) {
      console.warn('메모 목록 재조회 실패:', e);
    }
  };

  // 메모 탭 단일 저장: Spring → ai07 PDF 기반 검증 통과(ACCEPT)분만 S3 저장.
  // REQUEST_REVISION/BLOCK이면 저장하지 않고 입력 유지 + 사유/제안 안내.
  const handleSaveMemo = async () => {
    const content = (memoText || '').trim();
    if (!content) {
      setJournalNotice({ type: 'error', reason: '메모 내용을 입력해 주세요.', suggestion: '' });
      return;
    }
    try {
      setIsSavingMemo(true);
      setJournalNotice(null);
      await materialService.createStudyJournal(id, content);
      setMemoText('');
      // 저장 성공 후 목록 재조회(서버 기준 relationType/relationPath/작성일 반영)
      await reloadStudyJournals();
    } catch (e) {
      const status = e?.response?.status;
      const data = e?.response?.data;
      if (status === 422 && data) {
        // REQUEST_REVISION / BLOCK — 입력 유지 + 사유/제안 표시
        setJournalNotice({
          type: data.decision === 'BLOCK' ? 'block' : 'error',
          reason: data.reason || 'PDF 학습 자료와 연결되는 개념이나 질문이 부족합니다.',
          suggestion: data.suggestion || '',
        });
      } else {
        console.error('메모 저장 실패:', e);
        setJournalNotice({ type: 'error', reason: '메모 저장 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.', suggestion: '' });
      }
    } finally {
      setIsSavingMemo(false);
    }
  };

  // 메모 → 학습일지 저장: 현재 textarea 내용을 학습일지(STUDY_LOG)로 저장한다.
  //  · '메모 저장'(handleSaveMemo)은 자료 메모 목록(검증 통과분)에 저장 — 역할 분리.
  //  · 학습일지 본문에는 자료 제목/원문 보기 reference를 포함(자료 ID는 reference 경로로 연결).
  const handleSaveMemoAsJournal = async () => {
    const content = (memoText || '').trim();
    if (!content) {
      setJournalNotice({ type: 'error', reason: '저장할 메모 내용을 입력해주세요.', suggestion: '' });
      return;
    }
    try {
      setIsSavingMemoJournal(true);
      const refLine = material?.materialId ? `원문 보기: /archive/${material.materialId}` : '';
      const learningContent = [
        `자료 제목: ${material?.title || material?.originalFileName || '자료'}`,
        refLine,
        '',
        content,
      ].filter((l) => l !== null && l !== undefined).join('\n');
      await materialService.createStudyLog({
        title: `${material?.title || '자료'} 학습일지`,
        keywords: '',
        studyDate: new Date().toISOString().split('T')[0],
        learningContent,
        nextPlan: '',
      });
      alert('학습일지에 저장되었습니다.');
    } catch (e) {
      console.error('학습일지 저장 실패:', e);
      alert('학습일지 저장에 실패했습니다. 다시 시도해주세요.');
    } finally {
      setIsSavingMemoJournal(false);
    }
  };

  // 학습일지 펼치기(원문 S3 GET) / 접기
  const handleToggleJournal = async (journalId) => {
    const target = studyJournals.find((j) => j.id === journalId);
    if (!target) return;
    if (target._expanded) {
      setStudyJournals((prev) => prev.map((j) => (j.id === journalId ? { ...j, _expanded: false } : j)));
      return;
    }
    if (target.content != null) {
      setStudyJournals((prev) => prev.map((j) => (j.id === journalId ? { ...j, _expanded: true } : j)));
      return;
    }
    try {
      const detail = await materialService.getStudyJournal(id, journalId);
      setStudyJournals((prev) => prev.map((j) => (j.id === journalId ? { ...j, content: detail?.content || '', _expanded: true } : j)));
    } catch (e) {
      console.error('학습일지 원문 로드 실패:', e);
      alert('학습일지 본문을 불러오지 못했습니다.');
    }
  };

  // 학습일지 삭제(soft delete)
  const handleDeleteJournal = async (journalId) => {
    if (!window.confirm('이 학습일지를 삭제할까요?')) return;
    try {
      await materialService.deleteStudyJournal(id, journalId);
      // 삭제 성공 후 목록 재조회
      await reloadStudyJournals();
    } catch (e) {
      console.error('학습일지 삭제 실패:', e);
      alert('학습일지 삭제 중 오류가 발생했습니다.');
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
    setChatMessages(prev => [...prev, { sender: 'user', text: userMsg, createdAt: new Date().toISOString(), materialId: id }]);

    try {
      setIsAskingQuestion(true);
      setChatMessages(prev => [...prev, { sender: 'ai', text: '질문 답변을 생성하는 중입니다...', isThinking: true }]);
      const res = await materialService.askQuestion(id, { userQuestion: userMsg });
      const normalized = normalizeAiResponse(res);
      setChatMessages(prev => {
        const filtered = prev.filter(m => !m.isThinking);
        // Intent Router 라우팅 결과 반영 (없으면 기존 답변 그대로 — 무손상).
        const ra = res.routeAction;
        let text;
        if (normalized.success === false) text = normalized.message;
        else if (ra === 'WARN' && res.routeMessage) text = `⚠️ ${res.routeMessage}\n\n${res.aiAnswer || ''}`.trim();
        else if (ra === 'QUIZ_PIPELINE') text = `${res.aiAnswer || '문제를 생성했습니다.'} 상단 ‘퀴즈’ 탭에서 확인하세요.`;
        else if (ra === 'SUMMARY_PIPELINE') text = `${res.aiAnswer || '요약을 정리했습니다.'} 상단 ‘AI 요약’ 탭에서 확인하세요.`;
        else if (ra === 'ROADMAP_PIPELINE') text = `${res.aiAnswer || '로드맵을 불러왔습니다.'} 상단 ‘로드맵’ 탭에서 확인하세요.`;
        else text = res.aiAnswer || '문서 기준으로는 확인되지 않습니다.';
        return [...filtered, { sender: 'ai', text, routeAction: ra || null, pipeline: res.pipeline || null, response: normalized, createdAt: new Date().toISOString(), materialId: id }];
      });
    } catch (e) {
      console.error('AI 질문 실패:', e);
      const normalized = normalizeAiException(e);
      setChatMessages(prev => {
        const filtered = prev.filter(m => !m.isThinking);
        return [...filtered, { sender: 'ai', text: normalized.message, response: normalized, createdAt: new Date().toISOString(), materialId: id }];
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
    if (quiz.isFallback) return false; // deterministic fallback 은 항상 렌더(문제 무조건 제공)
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

  // ---------------- 퀴즈 deterministic fallback ----------------
  // AI 퀴즈가 형식/난이도 검증 실패·timeout·404·빈 응답이면, 추출 텍스트/요약/키워드 기반으로
  // 결정적(deterministic) 객관식 문제를 만들어 "무조건" 풀 수 있게 한다. 최소 3문제 보장.
  const buildFallbackQuiz = (count, difficultyLabel) => {
    const want = Math.max(3, Math.min(parseInt(count, 10) || 5, 20));
    const snip = (t) => { const x = String(t || '').trim(); return x.length > 70 ? x.slice(0, 70) + '…' : x; };

    // 1) 콘텐츠 풀: 섹션(제목+본문) 우선 → 학습/실습 포인트 → 본문 문장
    const pool = getSummarySections(summaryData)
      .map((s) => ({ term: sanitizeMarkdownText(s.title || '').replace(/^\d+\.\s*/, '').trim(), desc: sanitizeMarkdownText(s.content || '').trim() }))
      .filter((p) => p.term && p.desc && p.desc.length > 8);
    if (pool.length < 4) {
      [...sanitizeList(getSummaryStringList(summaryData, 'learningPoints')), ...sanitizeList(getSummaryStringList(summaryData, 'practicePoints'))]
        .forEach((p) => { const desc = String(p).trim(); if (desc.length > 8) pool.push({ term: desc.split(/[:：.]/)[0].slice(0, 40) || `핵심 ${pool.length + 1}`, desc }); });
    }
    if (pool.length < 4) {
      const text = sanitizeMarkdownText(material?.extractedText || getSummaryOverview(summaryData) || '');
      text.split(/(?<=[.。!?])\s+/).map((s) => s.trim()).filter((s) => s.length > 15).slice(0, 12)
        .forEach((s, i) => { pool.push({ term: s.split(/[\s,]/).slice(0, 3).join(' ').slice(0, 30) || `문장 ${i + 1}`, desc: s }); });
    }

    const questions = [];
    if (pool.length >= 2) {
      const n = Math.min(want, pool.length);
      for (let i = 0; i < n; i++) {
        const correct = pool[i];
        const others = pool.filter((_, j) => j !== i);
        const distract = [];
        for (let k = 0; k < others.length && distract.length < 3; k++) distract.push(others[(i + k) % others.length]);
        const choices = distract.map((d) => snip(d.desc));
        const answerIndex = i % (choices.length + 1);
        choices.splice(answerIndex, 0, snip(correct.desc));
        questions.push({
          question: `‘${correct.term}’에 대한 설명으로 가장 적절한 것은?`,
          choices, answerIndex, answer: answerIndex,
          explanation: `정답: ${snip(correct.desc)}`,
          page: 1, difficulty: difficultyLabel, source: 'FALLBACK',
        });
      }
    }
    // 최후 보루: 키워드 기반 최소 3문제(콘텐츠가 거의 없을 때)
    if (questions.length < 3) {
      const kws = getSummaryKeywords(summaryData).map(sanitizeMarkdownText).filter(Boolean);
      const base = kws.length ? kws : (material?.keywords ? String(material.keywords).split(',').map((s) => s.trim()).filter(Boolean) : []);
      for (let i = questions.length; i < 3; i++) {
        const correct = base[i % Math.max(base.length, 1)] || `핵심 개념 ${i + 1}`;
        const answerIndex = i % 4;
        const choices = ['해당 없음', '관련 없는 보기', '문서에 없는 내용'];
        choices.splice(answerIndex, 0, correct);
        questions.push({
          question: `이 자료의 핵심 내용과 가장 관련 있는 것은? (${i + 1})`,
          choices, answerIndex, answer: answerIndex,
          explanation: `이 자료의 핵심 키워드: ${correct}`,
          page: 1, difficulty: difficultyLabel, source: 'FALLBACK',
        });
      }
    }
    return {
      quizId: `fallback-${Date.now()}`,
      isFallback: true,
      difficulty: difficultyLabel,
      difficultyRequested: 'normal', // hard 보조검증 우회(이중 안전)
      quizzes: questions,
    };
  };

  // ---------------- 로드맵 deterministic fallback (12주 × 7일 = 84일) ----------------
  // AI 로드맵 실패(timeout/네트워크/빈 응답)여도 UNKNOWN_ERROR로 끝내지 않고, 요약/키워드 기반 기본 로드맵을 만들어 제공한다.
  const buildFallbackRoadmap = (level = 'intermediate') => {
    const WEEK_THEMES = [
      '핵심 개념 파악', '기본 예제 학습', '주요 구조·원리 이해', '심화 개념 학습',
      '응용 연습', '중간 점검 및 복습', '실전 적용', '사례·예제 분석',
      '문제 해결 연습', '통합 미니 프로젝트', '취약점 보완', '최종 정리 및 종합 복습',
    ];
    const kws = getSummaryKeywords(summaryData).map(sanitizeMarkdownText).filter(Boolean);
    const sections = getSummarySections(summaryData);
    const topicPool = (kws.length ? kws : (material?.keywords ? String(material.keywords).split(',').map(s => s.trim()).filter(Boolean) : []));
    const sectionTitles = sections.map(s => sanitizeMarkdownText(s.title || '').replace(/^\d+\.\s*/, '').trim()).filter(Boolean);
    const pick = (arr, i) => (arr.length ? arr[i % arr.length] : null);

    const weeks = [];
    for (let w = 0; w < 12; w++) {
      const theme = WEEK_THEMES[w];
      const weekTopic = pick(sectionTitles, w) || pick(topicPool, w) || theme;
      const days = [];
      for (let d = 0; d < 7; d++) {
        const dayIndex = w * 7 + d + 1;
        const topic = pick(topicPool, w * 7 + d) || pick(sectionTitles, w + d) || weekTopic;
        const isReviewDay = d === 6;
        const tasks = isReviewDay
          ? ['이번 주 학습 내용 복습', `‘${weekTopic}’ 핵심 요약 정리`, '이해 안 된 부분 다시 학습']
          : [
              topic ? `‘${topic}’ 개념 학습 및 정리` : `${theme} 학습`,
              '핵심 내용 요약 노트 작성',
              '관련 예제/문제 풀이',
            ];
        days.push({
          day_index: dayIndex,
          day_label: `${dayIndex}일차`,
          title: isReviewDay ? `${w + 1}주차 복습` : `${theme} (${d + 1}일차)`,
          objective: isReviewDay ? `${w + 1}주차에 학습한 내용을 점검하고 복습합니다.` : (topic ? `‘${topic}’를 이해하고 적용해 봅니다.` : `${theme}을(를) 진행합니다.`),
          core_concepts: topic ? [topic] : [],
          tasks,
          review_questions: [],
          checkpoint: isReviewDay ? '이번 주 목표를 달성했는지 스스로 점검' : '',
          completed: false,
        });
      }
      weeks.push({
        week: w + 1,
        title: `${w + 1}주차 · ${theme}`,
        objective: weekTopic ? `${theme} — ‘${weekTopic}’ 중심` : theme,
        week_summary: '',
        days,
      });
    }
    return { roadmap: { weeks }, weeks, fallbackUsed: true, level, isFallback: true };
  };

  // ---------------- 자료보관함 PLANNER 전용 ----------------
  // 자료보관함의 PLANNER 자료는 이미 저장된 자료다. "먼저 저장" 유도 없이 저장된 자료 기반으로 바로 분석을 보여준다.
  // 대소문자/표기 흔들림('PLANNER'|'Planner'|'planner') 및 플래너 식별자(plannerId) 모두 허용 — 분할뷰 고정.
  const isPlanner = String(material?.materialType || '').toUpperCase() === 'PLANNER' || material?.plannerId != null;

  // AI 계획 분석 — PDF/플래너 텍스트를 chunk→문장→행동 단위로 분해(서버 결정적 분석, DB 영속).
  const handlePlannerAnalyze = async () => {
    const materialId = material?.materialId || id;
    if (!materialId || planLoading) return;
    try {
      setPlanLoading(true);
      setPlanError(null);
      setPlannerDetailView('analysis');
      const res = await planAnalysisService.analyze(materialId);
      if (res?.errorCode) {
        setPlanError({ errorCode: res.errorCode, message: res.summary || 'AI 계획 분석에 실패했습니다. 다시 시도해 주세요.' });
        setPlanAnalysis(null);
      } else {
        setPlanAnalysis(res);
      }
    } catch (e) {
      const data = e?.response?.data;
      setPlanError({
        errorCode: data?.errorCode || 'PLAN_ANALYSIS_FASTAPI_FAILED',
        message: data?.summary || data?.message || 'AI 계획 분석에 실패했습니다. 다시 시도해 주세요.',
      });
    } finally {
      setPlanLoading(false);
    }
  };

  // 항목 체크/지우기 (서버 PATCH → 진행률 즉시 재계산, DB 영속)
  const patchPlanItem = async (itemId, patch) => {
    if (planItemBusy) return;
    try {
      setPlanItemBusy(itemId);
      const res = await planAnalysisService.patchItem(itemId, patch);
      setPlanAnalysis(res);
    } catch (e) {
      console.error('항목 갱신 실패:', e);
      alert('항목 상태 저장에 실패했습니다.');
    } finally {
      setPlanItemBusy(null);
    }
  };
  const handleToggleItem = (item) => patchPlanItem(item.id, { completed: !item.completed });
  // 지우기: 완료 처리 + 숨김 (로드맵처럼 목록에서 사라지되 진행률에 완료로 반영)
  const handleEraseItem = (item) => {
    if (!window.confirm('이 항목을 완료 처리하고 목록에서 숨길까요? (진행률에는 완료로 반영됩니다)')) return;
    patchPlanItem(item.id, { completed: true, hidden: true });
  };

  // 다음 학습 추천 재생성 (미완료 항목 기반)
  const handleNextRecommend = async () => {
    const materialId = material?.materialId || id;
    if (!materialId) return;
    if (!planAnalysis) { await handlePlannerAnalyze(); return; }
    try {
      setPlanLoading(true);
      const res = await planAnalysisService.recommend(materialId);
      setPlanAnalysis((prev) => prev ? { ...prev, recommendations: res.recommendations } : prev);
    } catch (e) {
      console.warn('다음 학습 추천 실패:', e);
    } finally {
      setPlanLoading(false);
    }
  };

  // ===== 소크라테스 복습 세션 =====
  // 백엔드가 ai07 응답을 화이트리스트 sanitize 하므로 내부 평가(rubric/eval/grounding)는 도달하지 않는다.
  // 응답에 aiAvailable:false 가 오면(=ai07 신규 route 미배포) 전체를 깨뜨리지 않고 안내만 표시한다.

  // ai07 한 턴 응답에서 화면에 보여줄 AI 발화 텍스트 추출
  const socraticTurnText = (res) =>
    (res?.question || res?.message || '').toString().trim();

  // 세션이 ai07 응답상 완료 상태인지(꼬리질문이 더 없는지) 판정
  const isSocraticCompleted = (res) => {
    const st = (res?.status || '').toString().toUpperCase();
    if (st === 'COMPLETED' || st === 'DONE' || st === 'FINISHED') return true;
    // 진행률이 끝까지 도달했고 더 줄 질문이 없으면 완료로 간주
    if (!socraticTurnText(res)) {
      const cur = res?.currentChunkIndex, tot = res?.totalChunks;
      if (typeof cur === 'number' && typeof tot === 'number' && tot > 0 && cur >= tot) return true;
    }
    return false;
  };

  const resetSocraticState = () => {
    setSocraticSession(null);
    setSocraticHistory([]);
    setSocraticAnswer('');
    setSocraticError('');
    setSocraticUnavailable(false);
    setSocraticFinish(null);
    setSocraticSchedule(null);
  };

  // 세션 시작
  const handleStartSocratic = async () => {
    const materialId = material?.materialId || id;
    if (!materialId || socraticBusy) return;
    setSocraticBusy(true);
    setSocraticError('');
    setSocraticUnavailable(false);
    setSocraticFinish(null);
    setSocraticSchedule(null);
    setSocraticHistory([]);
    try {
      const res = await socraticReviewService.start(materialId, {});
      if (res?.aiAvailable === false) {
        setSocraticUnavailable(true);
        setSocraticSession(null);
        return;
      }
      setSocraticSession(res);
      const t = socraticTurnText(res);
      if (t) setSocraticHistory([{ role: 'ai', text: t }]);
    } catch (e) {
      const msg = e?.response?.data?.message || '소크라테스 복습 세션을 시작하지 못했습니다. 잠시 후 다시 시도해 주세요.';
      setSocraticError(msg);
    } finally {
      setSocraticBusy(false);
    }
  };

  // ai07 finish 호출(완료 요약 캐시) — 답변 후 자동 또는 사용자가 '복습 마치기' 클릭 시
  const finishSocratic = async (materialId, sessionId) => {
    const res = await socraticReviewService.finish(materialId, sessionId);
    if (res?.aiAvailable === false) { setSocraticUnavailable(true); return null; }
    setSocraticFinish(res);
    setSocraticSession((prev) => prev ? { ...prev, status: 'COMPLETED' } : prev);
    return res;
  };

  // 답변 제출
  const handleSubmitSocraticAnswer = async () => {
    const materialId = material?.materialId || id;
    const sessionId = socraticSession?.sessionId;
    const answer = socraticAnswer.trim();
    if (!materialId || !sessionId || socraticBusy) return;
    if (!answer) { setSocraticError('답변을 입력해 주세요.'); return; }
    setSocraticBusy(true);
    setSocraticError('');
    // 사용자 답변을 먼저 화면에 반영하고 입력창 비움
    setSocraticHistory((prev) => [...prev, { role: 'user', text: answer }]);
    setSocraticAnswer('');
    try {
      const res = await socraticReviewService.answer(materialId, sessionId, answer);
      if (res?.aiAvailable === false) { setSocraticUnavailable(true); return; }
      setSocraticSession((prev) => ({ ...(prev || {}), ...res }));
      const t = socraticTurnText(res);
      if (t) setSocraticHistory((prev) => [...prev, { role: 'ai', text: t }]);
      // 더 줄 꼬리질문이 없으면 완료 요약을 받아온다.
      if (isSocraticCompleted(res)) {
        await finishSocratic(materialId, sessionId);
      }
    } catch (e) {
      const msg = e?.response?.data?.message || '답변을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.';
      setSocraticError(msg);
    } finally {
      setSocraticBusy(false);
    }
  };

  // 사용자가 직접 세션 마치기
  const handleFinishSocratic = async () => {
    const materialId = material?.materialId || id;
    const sessionId = socraticSession?.sessionId;
    if (!materialId || !sessionId || socraticBusy) return;
    setSocraticBusy(true);
    setSocraticError('');
    try {
      await finishSocratic(materialId, sessionId);
    } catch (e) {
      const msg = e?.response?.data?.message || '세션을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.';
      setSocraticError(msg);
    } finally {
      setSocraticBusy(false);
    }
  };

  // 다음 복습일 주간 일정(플래너 DB) 등록
  const handleScheduleSocraticReview = async () => {
    const materialId = material?.materialId || id;
    const sessionId = socraticSession?.sessionId;
    if (!materialId || !sessionId || socraticBusy) return;
    setSocraticBusy(true);
    setSocraticError('');
    try {
      const reviewDate = socraticFinish?.recommendedReviewDate || null;
      const res = await socraticReviewService.scheduleReview(materialId, sessionId, reviewDate);
      setSocraticSchedule(res);
    } catch (e) {
      const msg = e?.response?.data?.message || '복습 일정을 등록하지 못했습니다. 잠시 후 다시 시도해 주세요.';
      setSocraticError(msg);
    } finally {
      setSocraticBusy(false);
    }
  };

  // ===== 우측 학습 도구(신규 4탭) — plan_analysis(서버 DB) 기반 렌더 =====
  const renderLearningToolPanel = () => {
    const pa = planAnalysis;
    const progress = pa?.progress || { totalCount: 0, completedCount: 0, hiddenCount: 0, visibleCount: 0, percent: 0 };
    const allItems = Array.isArray(pa?.items) ? pa.items : [];
    const visibleItems = allItems.filter((it) => !it.hidden);
    const recommendations = Array.isArray(pa?.recommendations) ? pa.recommendations : [];

    // 코드/패키지명이 깨지지 않게: 단어 내부(특히 CJK) 분절 금지 + 넘칠 때만 줄바꿈 + 전체 tooltip
    const codeSafe = { overflowWrap: 'anywhere', wordBreak: 'keep-all', whiteSpace: 'pre-wrap', lineHeight: 1.6 };
    const sourceBadge = (it) => it.sourceType === 'PDF'
      ? (it.pageNumber ? `PDF p.${it.pageNumber}` : 'PDF')
      : it.sourceType === 'PLANNER' ? 'Planner' : (it.sourceType || '출처');

    const Card = ({ icon, title, right, children }) => (
      <div className="glass-panel animate-fade-in" style={{ padding: '22px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '14px', gap: '8px' }}>
          <h3 style={{ margin: 0, fontSize: '16px', display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--color-text-main)' }}>{icon} {title}</h3>
          {right}
        </div>
        {children}
      </div>
    );
    const ProgressBar = ({ percent }) => (
      <div style={{ height: '12px', borderRadius: '999px', background: '#E5E7EB', overflow: 'hidden' }}>
        <div style={{ width: `${percent}%`, height: '100%', background: 'linear-gradient(90deg,#22C55E,#15803D)', transition: 'width 0.4s' }} />
      </div>
    );
    const reanalyzeBtn = (
      <button className="btn-outline" style={{ width: 'auto', padding: '6px 12px', fontSize: '12px' }} onClick={handlePlannerAnalyze} disabled={planLoading}>
        <Sparkles size={14} /> {planLoading ? '분석 중…' : '재분석'}
      </button>
    );
    const wrap = (children) => (<div style={{ display: 'flex', flexDirection: 'column', gap: '20px', padding: '24px' }}>{children}</div>);

    // ── 다음 학습 추천 ──
    if (plannerDetailView === 'next') {
      return wrap(
        <Card icon={<ArrowRight size={17} color="#15803D" />} title="다음 학습 추천"
          right={<button className="btn-outline" style={{ width: 'auto', padding: '6px 12px', fontSize: '12px' }} onClick={handleNextRecommend} disabled={planLoading}>새로 추천</button>}>
          {!pa ? (
            <p style={{ margin: 0, fontSize: '14px', color: 'var(--color-text-muted)' }}>아직 분석 결과가 없습니다. ‘AI 계획 분석’을 먼저 실행하세요.</p>
          ) : recommendations.length === 0 ? (
            <p style={{ margin: 0, fontSize: '14px', color: 'var(--color-text-muted)' }}>미완료 항목이 없습니다. 모든 학습을 완료했어요! 🎉</p>
          ) : (
            <ul style={{ margin: 0, paddingLeft: '18px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {recommendations.map((r, i) => <li key={i} style={{ fontSize: '14px', color: 'var(--color-text-main)', ...codeSafe }} title={r}>{r}</li>)}
            </ul>
          )}
        </Card>
      );
    }

    // ── 메모 (materialId 기준 영속, 기존 /api/materials/{id}/memo 재사용) ──
    if (plannerDetailView === 'memo') {
      return wrap(
        <Card icon={<Edit3 size={17} color="#15803D" />} title="메모">
          <textarea value={plannerMemoText} onChange={(e) => setPlannerMemoText(e.target.value)}
            placeholder="이 자료/플래너에 대한 메모를 남기세요. (자료별로 저장되어 새로고침 후에도 유지됩니다)"
            style={{ width: '100%', minHeight: '200px', boxSizing: 'border-box', borderRadius: '12px', border: '1px solid var(--color-border)', padding: '12px', fontSize: '14px', lineHeight: 1.6, resize: 'vertical' }} />
          <button className="btn-primary" style={{ marginTop: '12px', width: 'auto', padding: '10px 18px', borderRadius: '12px', fontWeight: 'bold' }} onClick={handleSavePlannerMemo} disabled={isSavingPlannerMemo}>
            {isSavingPlannerMemo ? '저장 중…' : '메모 저장'}
          </button>
        </Card>
      );
    }

    // ── 소크라테스 복습 세션 (기존 '진행률' 탭 대체) ──
    // ai07 응답은 백엔드에서 화이트리스트 sanitize 됨(내부 평가/근거 미노출). 여기서는 질문/답변 흐름만 렌더.
    if (plannerDetailView === 'socratic') {
      const errorBox = socraticError ? (
        <div style={{ borderRadius: '12px', border: '1px solid #FECACA', background: '#FEF2F2', padding: '12px', marginTop: '12px', color: '#B91C1C', fontSize: '13.5px', lineHeight: 1.6 }}>{socraticError}</div>
      ) : null;

      // ai07 신규 route 미배포 안내
      if (socraticUnavailable) {
        return wrap(
          <Card icon={<Brain size={17} color="var(--color-primary)" />} title="소크라테스 복습">
            <div style={{ borderRadius: '12px', border: '1px solid #FDE2B3', background: '#FFF8E8', padding: '14px', color: '#8A6100', fontSize: '14px', lineHeight: 1.6 }}>
              소크라테스 복습 기능이 아직 AI 서버에 활성화되지 않았습니다. AI 서버 재시작 후 다시 시도해 주세요.
            </div>
            <button className="btn-outline" style={{ marginTop: '12px', width: 'auto', padding: '10px 18px', borderRadius: '12px' }} onClick={handleStartSocratic} disabled={socraticBusy}>다시 시도</button>
          </Card>
        );
      }

      // 시작 전 — 인트로
      if (!socraticSession) {
        return wrap(
          <Card icon={<Brain size={17} color="var(--color-primary)" />} title="소크라테스 복습">
            <p style={{ margin: '0 0 14px', fontSize: '14px', color: 'var(--color-text-main)', lineHeight: 1.7 }}>
              오늘 학습할 내용을 자료 흐름에 맞춰 정리했습니다. 위에서부터 하나씩 확인하면서 완료한 항목을 체크하면, 이 자료의 핵심 목표를 빠짐없이 점검할 수 있습니다.
            </p>
            <p style={{ margin: '0 0 16px', fontSize: '13px', color: 'var(--color-text-muted)', lineHeight: 1.7 }}>
              AI가 짧은 질문을 던지면 떠오르는 대로 답해 보세요. 답을 맞히는 시험이 아니라, 스스로 설명하면서 이해를 다지는 복습입니다.
            </p>
            {errorBox}
            <button className="btn-primary" style={{ marginTop: errorBox ? '14px' : 0, width: 'auto', padding: '11px 20px', borderRadius: '12px', fontWeight: 'bold' }} onClick={handleStartSocratic} disabled={socraticBusy}>
              <Brain size={16} /> {socraticBusy ? '세션 준비 중…' : '복습 시작'}
            </button>
          </Card>
        );
      }

      const completed = !!socraticFinish || (socraticSession?.status || '').toUpperCase() === 'COMPLETED';
      const cur = socraticSession?.currentChunkIndex, tot = socraticSession?.totalChunks;
      const turnBadge = (typeof cur === 'number' && typeof tot === 'number' && tot > 0)
        ? <span style={{ fontSize: '12px', fontWeight: 700, color: '#15803D', background: '#EEF8EB', borderRadius: '8px', padding: '3px 10px' }}>{Math.min(cur + 1, tot)} / {tot}</span>
        : null;
      const weak = Array.isArray(socraticFinish?.weakConcepts) ? socraticFinish.weakConcepts.filter(Boolean) : [];
      const mastery = socraticFinish?.overallMastery;

      return wrap(
        <>
          <Card icon={<Brain size={17} color="var(--color-primary)" />} title="소크라테스 복습" right={turnBadge}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', maxHeight: '46vh', overflowY: 'auto', paddingRight: '4px' }}>
              {socraticHistory.map((m, i) => (
                <div key={i} style={{ display: 'flex', justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start' }}>
                  <div style={{
                    maxWidth: '85%', padding: '10px 14px', borderRadius: '14px', fontSize: '13.5px', lineHeight: 1.65, ...codeSafe,
                    background: m.role === 'user' ? 'var(--color-primary)' : '#F3F4F6',
                    color: m.role === 'user' ? '#fff' : 'var(--color-text-main)',
                    borderTopRightRadius: m.role === 'user' ? '4px' : '14px',
                    borderTopLeftRadius: m.role === 'user' ? '14px' : '4px',
                  }}>{m.text}</div>
                </div>
              ))}
              {socraticBusy && !completed && (
                <div style={{ fontSize: '12.5px', color: 'var(--color-text-muted)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <Sparkles size={13} /> AI가 생각하고 있어요…
                </div>
              )}
            </div>
            {errorBox}
            {!completed && (
              <div style={{ marginTop: '14px', borderTop: '1px solid var(--color-border)', paddingTop: '14px' }}>
                <textarea
                  value={socraticAnswer}
                  onChange={(e) => setSocraticAnswer(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); handleSubmitSocraticAnswer(); } }}
                  placeholder="떠오르는 대로 답해 보세요. (Ctrl+Enter로 보내기)"
                  disabled={socraticBusy}
                  style={{ width: '100%', minHeight: '88px', boxSizing: 'border-box', borderRadius: '12px', border: '1px solid var(--color-border)', padding: '12px', fontSize: '13.5px', lineHeight: 1.6, resize: 'vertical' }}
                />
                <div style={{ display: 'flex', gap: '8px', marginTop: '10px', justifyContent: 'space-between' }}>
                  <button className="btn-outline" style={{ width: 'auto', padding: '9px 14px', borderRadius: '12px', fontSize: '13px' }} onClick={handleFinishSocratic} disabled={socraticBusy}>
                    복습 마치기
                  </button>
                  <button className="btn-primary" style={{ width: 'auto', padding: '9px 18px', borderRadius: '12px', fontWeight: 'bold', opacity: (socraticBusy || !socraticAnswer.trim()) ? 0.6 : 1 }} onClick={handleSubmitSocraticAnswer} disabled={socraticBusy || !socraticAnswer.trim()}>
                    <Send size={15} /> 답변 보내기
                  </button>
                </div>
              </div>
            )}
          </Card>

          {completed && (
            <Card icon={<Award size={17} color="#15803D" />} title="복습 요약">
              {mastery != null && (
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px', fontSize: '14px' }}>
                  <span style={{ color: 'var(--color-text-muted)' }}>전반적 이해도</span>
                  <b style={{ color: '#15803D' }}>{typeof mastery === 'number' ? `${Math.round(mastery <= 1 ? mastery * 100 : mastery)}%` : mastery}</b>
                </div>
              )}
              {weak.length > 0 && (
                <div style={{ marginBottom: '14px' }}>
                  <div style={{ fontSize: '13px', color: 'var(--color-text-muted)', marginBottom: '6px' }}>더 살펴보면 좋을 개념</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                    {weak.map((w, i) => (
                      <span key={i} style={{ fontSize: '12.5px', fontWeight: 600, color: '#92400E', background: '#FEF3C7', borderRadius: '8px', padding: '4px 10px', ...codeSafe }}>{w}</span>
                    ))}
                  </div>
                </div>
              )}
              {socraticFinish?.summaryForPlanner && (
                <p style={{ margin: '0 0 14px', fontSize: '13.5px', color: 'var(--color-text-main)', lineHeight: 1.7, ...codeSafe }}>{socraticFinish.summaryForPlanner}</p>
              )}
              {socraticFinish?.recommendedReviewDate && (
                <div style={{ fontSize: '13px', color: 'var(--color-text-muted)', marginBottom: '14px' }}>
                  추천 복습일: <b style={{ color: 'var(--color-text-main)' }}>{String(socraticFinish.recommendedReviewDate).slice(0, 10)}</b>
                </div>
              )}
              {errorBox}
              {socraticSchedule ? (
                <div style={{ borderRadius: '12px', border: '1px solid #DCFCE7', background: '#F0FDF4', padding: '14px', color: '#166534', fontSize: '13.5px', lineHeight: 1.6 }}>
                  {socraticSchedule.alreadyRegistered
                    ? '이미 주간 일정에 등록되어 있습니다.'
                    : socraticSchedule.registered
                      ? `주간 일정에 복습이 등록되었습니다${socraticSchedule.reviewDate ? ` (${String(socraticSchedule.reviewDate).slice(0, 10)})` : ''}.`
                      : (socraticSchedule.message || '복습 일정을 등록했습니다.')}
                  <button className="btn-outline" style={{ marginLeft: '10px', width: 'auto', padding: '5px 12px', borderRadius: '10px', fontSize: '12.5px' }} onClick={() => navigate('/planner')}>주간 일정 보기</button>
                </div>
              ) : (
                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                  <button className="btn-primary" style={{ width: 'auto', padding: '11px 18px', borderRadius: '12px', fontWeight: 'bold', opacity: socraticBusy ? 0.6 : 1 }} onClick={handleScheduleSocraticReview} disabled={socraticBusy}>
                    <CalendarPlus size={16} /> 다음 복습일 주간 일정에 등록하기
                  </button>
                  <button className="btn-outline" style={{ width: 'auto', padding: '11px 16px', borderRadius: '12px' }} onClick={() => { resetSocraticState(); handleStartSocratic(); }} disabled={socraticBusy}>
                    <RotateCcw size={15} /> 다시 복습
                  </button>
                </div>
              )}
            </Card>
          )}
        </>
      );
    }

    // ── AI 계획 분석 (기본 'analysis') ──
    if (planLoading && !pa) {
      return wrap(
        <Card icon={<Sparkles size={17} color="var(--color-primary)" />} title="AI 계획 분석 중…">
          <p style={{ margin: '0 0 12px', fontSize: '14px', color: 'var(--color-text-muted)' }}>PDF/플래너 문장을 분석 중입니다.</p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {[0, 1, 2].map((i) => (<div key={i} style={{ height: '14px', borderRadius: '6px', background: 'linear-gradient(90deg,#F3F4F6,#E5E7EB,#F3F4F6)', backgroundSize: '200% 100%', animation: 'pulse 1.4s ease-in-out infinite' }} />))}
          </div>
        </Card>
      );
    }
    if (planError) {
      return wrap(
        <Card icon={<Sparkles size={17} color="#EF4444" />} title="AI 계획 분석">
          <div style={{ borderRadius: '12px', border: '1px solid #FECACA', background: '#FEF2F2', padding: '14px', marginBottom: '14px' }}>
            <div style={{ fontWeight: 700, color: '#B91C1C', fontSize: '14px' }}>{planError.message}</div>
            <div style={{ fontSize: '12px', color: '#9CA3AF', marginTop: '4px' }}>{planError.errorCode}</div>
          </div>
          <button className="btn-primary" style={{ width: 'auto', padding: '10px 18px', borderRadius: '12px', fontWeight: 'bold' }} onClick={handlePlannerAnalyze}>다시 시도</button>
        </Card>
      );
    }
    if (!pa) {
      return wrap(
        <Card icon={<Sparkles size={17} color="var(--color-primary)" />} title="AI 계획 분석">
          <p style={{ margin: '0 0 14px', fontSize: '14px', color: 'var(--color-text-muted)' }}>아직 분석 결과가 없습니다. AI 계획 분석을 눌러 PDF/플래너 문장을 체크리스트로 만들어 보세요.</p>
          <button className="btn-primary" style={{ width: 'auto', padding: '10px 18px', borderRadius: '12px', fontWeight: 'bold' }} onClick={handlePlannerAnalyze} disabled={planLoading}>
            <Sparkles size={16} /> AI 계획 분석
          </button>
        </Card>
      );
    }
    return wrap(
      <>
        <Card icon={<AlignLeft size={17} color="var(--color-primary)" />} title="요약 / 핵심 학습 흐름" right={reanalyzeBtn}>
          <p style={{ margin: 0, fontSize: '14px', color: 'var(--color-text-main)', ...codeSafe }}>{pa.summary}</p>
          <div style={{ marginTop: '14px', display: 'flex', justifyContent: 'space-between', marginBottom: '6px', fontSize: '13px' }}>
            <span style={{ color: 'var(--color-text-muted)' }}>진행률</span><b style={{ color: '#15803D' }}>{progress.percent}% ({progress.completedCount}/{progress.totalCount})</b>
          </div>
          <ProgressBar percent={progress.percent} />
        </Card>
        <Card icon={<ListChecks size={17} color="#15803D" />} title={`문장 단위 체크리스트 (${visibleItems.filter((i) => i.completed).length}/${visibleItems.length})`}>
          {visibleItems.length === 0 ? (
            <p style={{ margin: 0, fontSize: '14px', color: 'var(--color-text-muted)' }}>표시할 항목이 없습니다. (모두 완료/숨김 처리됨)</p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '56vh', overflowY: 'auto' }}>
              {visibleItems.map((it) => (
                <div key={it.id} style={{ display: 'flex', alignItems: 'flex-start', gap: '10px', border: '1px solid var(--color-border)', background: it.completed ? '#F0FDF4' : '#fff', borderRadius: '10px', padding: '10px 12px' }}>
                  <button onClick={() => handleToggleItem(it)} disabled={planItemBusy === it.id} title={it.completed ? '완료 해제' : '완료'} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, marginTop: '1px', flexShrink: 0 }}>
                    {it.completed ? <CheckCircle2 size={18} color="#16A34A" /> : <Circle size={18} color="#9CA3AF" />}
                  </button>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <span style={{ display: 'block', fontSize: '13.5px', color: 'var(--color-text-main)', textDecoration: it.completed ? 'line-through' : 'none', ...codeSafe }} title={it.text}>{it.text}</span>
                    <span style={{ display: 'inline-block', marginTop: '4px', fontSize: '10px', fontWeight: 700, color: '#15803D', background: '#EEF8EB', borderRadius: '6px', padding: '1px 6px' }}>{sourceBadge(it)}</span>
                  </div>
                  <button onClick={() => handleEraseItem(it)} disabled={planItemBusy === it.id} title="완료 후 숨기기(지우기)" style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '2px', flexShrink: 0 }}>
                    <Trash2 size={15} color="#EF4444" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </Card>
      </>
    );
  };

  const renderPlannerRightPanel = () => {
    // 신규 4탭(AI 계획 분석 / 다음 학습 추천 / 메모 / 소크라테스 복습)은 renderLearningToolPanel 에서 렌더
    if (['analysis', 'next', 'memo', 'socratic'].includes(plannerDetailView)) {
      return renderLearningToolPanel();
    }
    const overview = getSummaryOverview(summaryData);
    const keywords = getSummaryKeywords(summaryData);
    const sections = getSummarySections(summaryData);
    const goals = sanitizeList(getSummaryStringList(summaryData, 'learningPoints'));
    const nextActions = sanitizeList(
      getSummaryStringList(summaryData, 'studyQuestions').length
        ? getSummaryStringList(summaryData, 'studyQuestions')
        : getSummaryStringList(summaryData, 'practicePoints')
    );
    const hasAnalysis = !!(overview || keywords.length || sections.length || goals.length || nextActions.length);

    const Card = ({ icon, title, children }) => (
      <div className="glass-panel animate-fade-in" style={{ padding: '22px' }}>
        <h3 style={{ margin: '0 0 14px', fontSize: '16px', display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--color-text-main)' }}>
          {icon} {title}
        </h3>
        {children}
      </div>
    );

    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', padding: '24px' }}>
        {/* 저장된 플래너 기반 안내 (먼저 저장 유도 금지) */}
        <div style={{ borderRadius: '14px', border: '1px solid #DCFCE7', background: '#F0FDF4', padding: '14px 16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 700, fontSize: '15px', color: '#15803D' }}>
            <Sparkles size={17} /> AI 피드백 및 다음 학습 추천
          </div>
          <p style={{ margin: '6px 0 0', fontSize: '13px', color: '#3F6212', lineHeight: 1.6 }}>
            저장된 플래너 자료를 기반으로 AI가 학습 계획을 정리하고 다음 행동을 추천합니다.
          </p>
        </div>

        {(() => {
          // 로드맵 일(日) 데이터 — 체크리스트/진행률 뷰에서 사용
          const allDays = (roadmapSteps || []).flatMap((s) => (s.days || []).map((d) => ({ ...d, week: Number(s.stepOrder) })));
          const doneDays = allDays.filter((d) => d.completed).length;
          const progressPct = allDays.length ? Math.round((doneDays / allDays.length) * 100) : 0;

          // ── 체크리스트 보기 ──
          if (plannerDetailView === 'checklist') {
            if (allDays.length === 0) return (
              <Card icon={<ListChecks size={17} color="var(--color-primary)" />} title="체크리스트">
                <p style={{ margin: 0, fontSize: '14px', color: 'var(--color-text-muted)' }}>아직 체크리스트로 만들 일정/로드맵이 없습니다. ‘일정/로드맵 보기’에서 먼저 로드맵을 생성하세요.</p>
              </Card>
            );
            return (
              <Card icon={<ListChecks size={17} color="#15803D" />} title={`체크리스트 (${doneDays}/${allDays.length} 완료)`}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '60vh', overflowY: 'auto' }}>
                  {allDays.map((d, i) => (
                    <button key={i} onClick={() => handleToggleDay(d.week, d.dayIndex)}
                      style={{ display: 'flex', alignItems: 'flex-start', gap: '10px', textAlign: 'left', border: '1px solid var(--color-border)', background: d.completed ? '#F0FDF4' : '#fff', borderRadius: '10px', padding: '10px 12px', cursor: 'pointer', width: '100%' }}>
                      {d.completed ? <CheckCircle2 size={18} color="#16A34A" style={{ flexShrink: 0, marginTop: '1px' }} /> : <Circle size={18} color="#9CA3AF" style={{ flexShrink: 0, marginTop: '1px' }} />}
                      <span style={{ flex: 1, fontSize: '13.5px', lineHeight: 1.5, color: 'var(--color-text-main)', textDecoration: d.completed ? 'line-through' : 'none', whiteSpace: 'normal', overflowWrap: 'anywhere' }}>
                        <b>{d.week}주 {d.dayLabel || `${d.dayIndex}일차`}</b> · {d.title || '학습'}
                      </span>
                    </button>
                  ))}
                </div>
              </Card>
            );
          }

          // ── 진행률 보기 ──
          if (plannerDetailView === 'progress') {
            return (
              <Card icon={<BarChart3 size={17} color="#15803D" />} title="진행률">
                {allDays.length === 0 ? (
                  <p style={{ margin: 0, fontSize: '14px', color: 'var(--color-text-muted)' }}>진행률을 계산할 일정/로드맵이 없습니다.</p>
                ) : (
                  <>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px', fontSize: '14px', color: 'var(--color-text-main)' }}>
                      <span>전체 진행률</span><b style={{ color: '#15803D' }}>{progressPct}% ({doneDays}/{allDays.length}일)</b>
                    </div>
                    <div style={{ height: '12px', borderRadius: '999px', background: '#E5E7EB', overflow: 'hidden' }}>
                      <div style={{ width: `${progressPct}%`, height: '100%', background: 'linear-gradient(90deg,#22C55E,#15803D)', transition: 'width 0.4s' }} />
                    </div>
                    <div style={{ marginTop: '16px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                      {(roadmapSteps || []).map((s, i) => {
                        const wd = s.days || []; const wdone = wd.filter((d) => d.completed).length;
                        const wpct = wd.length ? Math.round((wdone / wd.length) * 100) : 0;
                        return (
                          <div key={i} style={{ fontSize: '13px', color: 'var(--color-text-muted)' }}>
                            <span style={{ display: 'inline-block', width: '70px' }}>{s.stepOrder}주차</span>
                            <span style={{ color: wpct === 100 ? '#15803D' : 'var(--color-text-main)' }}>{wdone}/{wd.length}일 ({wpct}%)</span>
                          </div>
                        );
                      })}
                    </div>
                  </>
                )}
              </Card>
            );
          }

          // ── 다음 학습 추천 보기 ──
          if (plannerDetailView === 'next') {
            return nextActions.length > 0 ? (
              <Card icon={<ArrowRight size={17} color="#15803D" />} title="다음 학습 추천">
                <ul style={{ margin: 0, paddingLeft: '18px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {nextActions.map((a, i) => <li key={i} style={{ fontSize: '14px', lineHeight: 1.6, color: 'var(--color-text-main)' }}>{a}</li>)}
                </ul>
              </Card>
            ) : (
              <Card icon={<ArrowRight size={17} color="var(--color-primary)" />} title="다음 학습 추천">
                <p style={{ margin: '0 0 14px', fontSize: '14px', color: 'var(--color-text-muted)' }}>아직 추천이 없습니다. ‘AI 계획 분석’을 눌러 생성하세요.</p>
                <button className="btn-primary" style={{ width: 'auto', padding: '10px 18px', borderRadius: '12px', fontWeight: 'bold' }} onClick={handlePlannerAnalyze}>AI 계획 분석</button>
              </Card>
            );
          }

          // ── 일정/로드맵 보기 ──
          if (plannerDetailView === 'roadmap') {
            return (roadmapSteps && roadmapSteps.length > 0) ? (
              <Card icon={<Map size={17} color="var(--color-primary)" />} title="일정 / 로드맵">
                <ul style={{ margin: 0, paddingLeft: '18px', display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '60vh', overflowY: 'auto' }}>
                  {roadmapSteps.slice(0, 84).map((s, i) => (
                    <li key={i} style={{ fontSize: '14px', lineHeight: 1.6, color: 'var(--color-text-main)' }}>
                      {s.title || s.label || s.task || s.content || `단계 ${i + 1}`}
                    </li>
                  ))}
                </ul>
              </Card>
            ) : (
              <Card icon={<Map size={17} color="var(--color-primary)" />} title="일정 / 로드맵">
                <p style={{ margin: 0, fontSize: '14px', color: 'var(--color-text-muted)' }}>아직 등록된 일정/로드맵이 없습니다. 좌측 PDF 원문에서 계획을 확인하세요.</p>
              </Card>
            );
          }

          // ── 학습계획 보기(기본 'plan') — AI 분석 결과 ──
          if (summaryLoading && !hasAnalysis) return (
            <Card icon={<Sparkles size={17} color="var(--color-primary)" />} title="AI 계획 분석 중…">
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                {[0, 1, 2].map((i) => (
                  <div key={i} style={{ height: '14px', borderRadius: '6px', background: 'linear-gradient(90deg,#F3F4F6,#E5E7EB,#F3F4F6)', backgroundSize: '200% 100%', animation: 'pulse 1.4s ease-in-out infinite' }} />
                ))}
              </div>
            </Card>
          );
          if (!hasAnalysis) return (
            <Card icon={<Sparkles size={17} color="var(--color-primary)" />} title="AI 계획 분석">
              <p style={{ margin: '0 0 14px', fontSize: '14px', color: 'var(--color-text-muted)' }}>아직 분석 결과가 없습니다. AI 계획 분석을 눌러 생성하세요.</p>
              <button className="btn-primary" style={{ width: 'auto', padding: '10px 18px', borderRadius: '12px', fontWeight: 'bold' }} onClick={handlePlannerAnalyze}>AI 계획 분석</button>
            </Card>
          );
          return (
            <>
              {overview && (
                <Card icon={<AlignLeft size={17} color="var(--color-primary)" />} title="문서 개요 / 학습계획">
                  <p style={{ margin: 0, fontSize: '14.5px', lineHeight: 1.7, color: 'var(--color-text-main)', whiteSpace: 'pre-wrap' }}>{overview}</p>
                </Card>
              )}
              {keywords.length > 0 && (
                <Card icon={<Sparkles size={17} color="var(--color-primary)" />} title="핵심 키워드">
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                    {keywords.map((kw) => (
                      <span key={kw} className="tag" style={{ backgroundColor: '#F3F4F6', color: 'var(--color-text-main)' }}>#{String(kw).trim()}</span>
                    ))}
                  </div>
                </Card>
              )}
              {goals.length > 0 && (
                <Card icon={<CheckCircle2 size={17} color="#15803D" />} title="학습 목표">
                  <ul style={{ margin: 0, paddingLeft: '18px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {goals.map((g, i) => <li key={i} style={{ fontSize: '14px', lineHeight: 1.6, color: 'var(--color-text-main)' }}>{g}</li>)}
                  </ul>
                </Card>
              )}
              {sections.length > 0 && (
                <Card icon={<ListChecks size={17} color="#15803D" />} title="AI 정리 계획 / 피드백">
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    {sections.slice(0, 12).map((s, i) => (
                      <div key={i}>
                        <div style={{ fontSize: '14px', fontWeight: 700, color: 'var(--color-text-main)', marginBottom: '4px' }}>{s.title}</div>
                        <p style={{ margin: 0, fontSize: '13.5px', lineHeight: 1.65, color: 'var(--color-text-muted)', whiteSpace: 'pre-wrap' }}>{s.content}</p>
                      </div>
                    ))}
                  </div>
                </Card>
              )}
              {nextActions.length > 0 && (
                <Card icon={<ArrowRight size={17} color="#15803D" />} title="다음 학습 추천">
                  <ul style={{ margin: 0, paddingLeft: '18px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {nextActions.map((a, i) => <li key={i} style={{ fontSize: '14px', lineHeight: 1.6, color: 'var(--color-text-main)' }}>{a}</li>)}
                  </ul>
                </Card>
              )}
            </>
          );
        })()}
      </div>
    );
  };

  // ---------------- 렌더링 도우미 ----------------
  const renderPdfRightPanel = () => {
    switch (activePdfTool) {
      case 'summary': {
        const summaryStatus = normalizeAiResponse(summaryData);
        const summaryTextStatusMessage = getTextStatusMessage(summaryData?.textStatus);
        const summaryOverview = sanitizeMarkdownText(getSummaryOverview(summaryData));
        const summaryKeywords = getSummaryKeywords(summaryData);
        const cleanKeywords = filterLearningList((summaryKeywords.length > 0 ? summaryKeywords : removeDummyKeywords(material?.keywords)).map(sanitizeMarkdownText).filter(Boolean), material?.title);
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
                PDF의 전공 분야와 핵심 객체를 분석하여 생성한 학습용 핵심 요약 노트입니다.
              </p>

              {/* 전공 분야·핵심 객체 중심 학습 노트 상태 (PENDING/RUNNING/FAILED) */}
              {studyNote && studyNote.status !== 'SUCCESS' && (
                <div className="glass-panel" style={{ padding: '16px 18px', borderLeft: `4px solid ${studyNote.status === 'FAILED' ? '#EF4444' : 'var(--color-primary)'}`, marginBottom: '20px', color: 'var(--color-text-muted)', fontSize: '14px' }}>
                  {studyNote.status === 'PENDING' && 'AI 핵심 요약 노트 생성 대기 중입니다.'}
                  {studyNote.status === 'RUNNING' && 'AI 핵심 요약 노트를 생성 중입니다.'}
                  {studyNote.status === 'FAILED' && 'AI 핵심 요약 노트를 생성하지 못했습니다. PDF 텍스트, OCR, 캡션 또는 표 정보가 부족할 수 있습니다.'}
                </div>
              )}

              {/* 전공 분야·핵심 객체 중심 학습 노트 결과 (SUCCESS) */}
              {studyNote && studyNote.status === 'SUCCESS' && (
                <>
                  {studyNote.fallback && (
                    <div className="glass-panel" style={{ padding: '14px 16px', borderLeft: '4px solid #F59E0B', backgroundColor: '#FFFBEB', color: '#92400E', marginBottom: '20px', fontSize: '14px', lineHeight: 1.6 }}>
                      PDF에서 명확한 전공 핵심 객체를 충분히 식별하지 못해 기본 학습 가이드로 생성되었습니다.
                    </div>
                  )}
                  <StudyNoteView note={studyNote} material={material} onKeyword={setActiveKeyword} />
                </>
              )}

              {/* studyNote 결과가 없을 때만 기존 종합 요약을 폴백으로 표시(회귀 방지) */}
              {!(studyNote && studyNote.status === 'SUCCESS') && (<>
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
                  <p style={{ margin: '0 0 12px', fontSize: '13px', color: 'var(--color-text-muted)' }}>키워드를 클릭하면 AI/Wikipedia 기반 개념 정의를 볼 수 있어요.</p>
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
              </>)}
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

        // 오답노트 작성하기 버튼 상태 (B) — 오답(WRONG) + 미응답(UNANSWERED) 모두 복습 대상
        const rnAnsweredCount = parsedQuestions.filter((q, i) => userAnswers[i] !== undefined).length;
        const rnWrongCount = parsedQuestions.filter((q, i) => userAnswers[i] !== undefined && userAnswers[i] !== q.answer).length;
        const rnUnansweredCount = parsedQuestions.filter((q, i) => userAnswers[i] === undefined).length;
        const rnReviewCount = rnWrongCount + rnUnansweredCount;
        const rnExistingNote = activeQuiz ? reviewNotesByQuiz[activeQuiz.quizId] : null;
        let rnButtonLabel = '오답노트 작성하기';
        let rnButtonDisabled = true;
        let rnButtonGuide = '';
        if (rnExistingNote) {
          rnButtonLabel = '오답노트 보기';
          rnButtonDisabled = false;
        } else if (!activeQuiz || parsedQuestions.length === 0 || rnAnsweredCount === 0) {
          rnButtonDisabled = true;
          rnButtonGuide = '퀴즈를 풀어보세요. 틀리거나 못 푼 문제로 오답노트를 만들 수 있습니다.';
        } else if (rnReviewCount === 0) {
          rnButtonDisabled = true;
          rnButtonGuide = '모든 문제를 맞혔어요. 복습할 문제가 없습니다.';
        } else {
          rnButtonDisabled = false;
          rnButtonLabel = `오답노트 작성하기 (오답 ${rnWrongCount}·미응답 ${rnUnansweredCount})`;
        }
        const onReviewNoteButton = () => {
          if (rnExistingNote) {
            // "오답노트 보기" → 자료보관함 REVIEW_NOTE 상세에서 실제 복습 실행
            if (rnExistingNote.archiveMaterialId) navigate(`/archive/reviewNote/${rnExistingNote.archiveMaterialId}?tab=retry`);
            else navigate('/review-notes');
            return;
          }
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

              {/* 오답노트 학습 진입 — 이미 오답노트가 있으면 설명 카드만 보여주고, 클릭 시 자료보관함 오답노트 상세로 이동(여기서 직접 실행하지 않음) */}
              {rnExistingNote?.archiveMaterialId && (
                <ReviewNoteLearningEntry archiveMaterialId={rnExistingNote.archiveMaterialId} navigate={navigate} />
              )}

              {renderAiStatus(quizError, handleGenerateQuiz)}

              {/* AI 실패 시 기본(fallback) 문제 안내 — 문제는 그대로 풀 수 있음 */}
              {quizFallbackNotice && (
                <div style={{ margin: '0 0 16px', borderRadius: '12px', border: '1px solid #FDE68A', background: '#FFFBEB', padding: '12px 16px', display: 'flex', alignItems: 'flex-start', gap: '8px' }}>
                  <HelpCircle size={16} color="#B45309" style={{ marginTop: '2px', flexShrink: 0 }} />
                  <span style={{ fontSize: '13px', color: '#92400E', lineHeight: 1.6 }}>{quizFallbackNotice}</span>
                </div>
              )}

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
                          {(() => { const anyAnswered = parsedQuestions.some((_, i) => userAnswers[i] !== undefined); return parsedQuestions.map((q, idx) => {
                              const hasAnswered = userAnswers[idx] !== undefined;
                              const isCorrectPick = hasAnswered && userAnswers[idx] === q.answer;
                              return (
                              <div key={idx} className="glass-panel" style={{ padding: '24px', borderLeft: `4px solid ${hasAnswered ? (isCorrectPick ? '#16A34A' : '#DC2626') : 'var(--color-primary)'}` }}>
                                <div style={{ display: 'flex', alignItems: 'flex-start', gap: '10px', marginBottom: '20px' }}>
                                  <span style={{ flexShrink: 0, fontSize: '13px', fontWeight: 700, color: 'var(--color-text-muted)', marginTop: '2px' }}>Q{idx + 1}.</span>
                                  {/* 문제 문장: 길어도 잘리지 않고 줄바꿈 */}
                                  <h5 style={{ margin: 0, fontSize: '16px', color: 'var(--color-text-main)', lineHeight: '1.6', whiteSpace: 'normal', overflowWrap: 'anywhere', wordBreak: 'break-word', flex: 1 }}>{q.q}</h5>
                                  {/* 채점 후 정답/오답/미응답 배지 */}
                                  {hasAnswered ? (
                                    <span style={{ flexShrink: 0, display: 'inline-flex', alignItems: 'center', gap: '4px', fontSize: '12.5px', fontWeight: 700, padding: '4px 10px', borderRadius: '999px', backgroundColor: isCorrectPick ? '#DCFCE7' : '#FEE2E2', color: isCorrectPick ? '#15803D' : '#991B1B' }}>
                                      {isCorrectPick ? <><CheckCircle2 size={14} /> 정답</> : <><XCircle size={14} /> 오답</>}
                                    </span>
                                  ) : anyAnswered ? (
                                    <span style={{ flexShrink: 0, fontSize: '12.5px', fontWeight: 700, padding: '4px 10px', borderRadius: '999px', backgroundColor: '#FEF3C7', color: '#92400E' }}>미응답</span>
                                  ) : null}
                                </div>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                                  {q.options.map((opt, optIdx) => {
                                    const isSelected = userAnswers[idx] === optIdx;
                                    const isCorrectAnswer = optIdx === q.answer;

                                    let optionBgColor = 'white';
                                    let optionTextColor = 'var(--color-text-main)';
                                    let optionBorderColor = 'var(--color-border)';
                                    if (isSelected && isCorrectAnswer) {
                                      optionBgColor = '#DCFCE7'; optionBorderColor = '#86EFAC'; optionTextColor = '#166534';
                                    } else if (isSelected && !isCorrectAnswer) {
                                      optionBgColor = '#FEE2E2'; optionBorderColor = '#FCA5A5'; optionTextColor = '#991B1B';
                                    } else if (hasAnswered && isCorrectAnswer) {
                                      optionBgColor = '#DCFCE7'; optionBorderColor = '#86EFAC'; optionTextColor = '#166534';
                                    }

                                    // 채점 후 정답=초록 O, 사용자가 고른 오답=빨강 X
                                    let mark = <Circle size={18} color="#9CA3AF" style={{ flexShrink: 0, marginTop: '1px' }} />;
                                    if (hasAnswered && isCorrectAnswer) mark = <CheckCircle2 size={18} color="#16A34A" style={{ flexShrink: 0, marginTop: '1px' }} />;
                                    else if (isSelected && !isCorrectAnswer) mark = <XCircle size={18} color="#DC2626" style={{ flexShrink: 0, marginTop: '1px' }} />;

                                    return (
                                        <button
                                            key={optIdx}
                                            onClick={() => handleSelectOption(idx, optIdx)}
                                            className="btn-outline"
                                            style={{
                                              width: '100%', height: 'auto', display: 'flex', alignItems: 'flex-start', gap: '10px',
                                              textAlign: 'left', fontWeight: 'normal', justifyContent: 'flex-start',
                                              fontSize: '15px', lineHeight: '1.55', padding: '14px 16px', borderRadius: '12px',
                                              backgroundColor: optionBgColor,
                                              borderColor: optionBorderColor,
                                              color: optionTextColor,
                                              whiteSpace: 'normal', overflowWrap: 'anywhere', wordBreak: 'break-word',
                                              transition: 'all 0.2s'
                                            }}
                                        >
                                          {mark}
                                          <span style={{ flex: 1, whiteSpace: 'normal', overflowWrap: 'anywhere' }}>{opt}</span>
                                          {hasAnswered && isCorrectAnswer && <span style={{ flexShrink: 0, fontSize: '12px', fontWeight: 700, color: '#15803D' }}>○ 정답</span>}
                                          {isSelected && !isCorrectAnswer && <span style={{ flexShrink: 0, fontSize: '12px', fontWeight: 700, color: '#DC2626' }}>✕ 내 답</span>}
                                        </button>
                                    );
                                  })}
                                </div>
                                {q.explanation && hasAnswered && (
                                  <p style={{ margin: '14px 0 0', fontSize: '13px', color: 'var(--color-text-muted)', lineHeight: 1.6, whiteSpace: 'normal', overflowWrap: 'anywhere' }}>해설: {q.explanation}</p>
                                )}
                              </div>
                          ); }); })()}
                        </div>
                    )}
                    {/* 채점 요약 (오답노트 생성은 상단 "오답노트 작성하기" 버튼으로 일원화) */}
                    {parsedQuestions.length > 0 && (() => {
                      const answered = parsedQuestions.filter((q, idx) => userAnswers[idx] !== undefined);
                      const wrong = parsedQuestions.filter((q, idx) => userAnswers[idx] !== undefined && userAnswers[idx] !== q.answer);
                      const unanswered = parsedQuestions.filter((q, idx) => userAnswers[idx] === undefined);
                      if (answered.length === 0) return null;
                      return (
                        <div className="glass-panel" style={{ marginTop: '24px', padding: '20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '16px', flexWrap: 'wrap' }}>
                          <div style={{ fontSize: '14px', color: 'var(--color-text-main)' }}>
                            <b>채점:</b> {parsedQuestions.length}문제 중 <b style={{ color: '#16A34A' }}>{answered.length - wrong.length}개 정답</b>
                            {wrong.length > 0 && <> · <b style={{ color: '#DC2626' }}>{wrong.length}개 오답</b></>}
                            {unanswered.length > 0 && <> · <b style={{ color: '#B45309' }}>{unanswered.length}개 미응답</b></>}
                          </div>
                          {(wrong.length + unanswered.length) > 0 && !rnExistingNote && (
                            <span style={{ fontSize: '13px', color: 'var(--color-text-muted)' }}>상단의 <b style={{ color: '#DC2626' }}>오답노트 작성하기</b> 버튼으로 오답·미응답을 모아 복습할 수 있어요.</span>
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
                        <p style={{ margin: '0 0 10px', fontSize: '13.5px', color: 'var(--color-text-muted)' }}>{reviewNoteResult.message || '오답노트가 자료보관함과 오답노트 탭에 저장되었습니다.'}</p>
                        {(reviewNoteResult.wrongCount != null || reviewNoteResult.unansweredCount != null) && (
                          <p style={{ margin: '0 0 16px', fontSize: '13px', color: 'var(--color-text-main)' }}>
                            <b style={{ color: '#DC2626' }}>오답 {reviewNoteResult.wrongCount ?? 0}개</b>
                            {(reviewNoteResult.unansweredCount ?? 0) > 0 && <> · <b style={{ color: '#B45309' }}>미응답 {reviewNoteResult.unansweredCount}개</b></>}
                            {' · 복습 필요 '}<b>{reviewNoteResult.reviewCount ?? ((reviewNoteResult.wrongCount ?? 0) + (reviewNoteResult.unansweredCount ?? 0))}개</b>
                          </p>
                        )}
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                          <button className="btn-primary" style={{ padding: '11px', borderRadius: '14px', fontWeight: 'bold' }} onClick={() => handleViewReviewNotePdf(reviewNoteResult.id, reviewNoteResult.pdfUrl)}>PDF 보기 (새 창)</button>
                          <button className="btn-outline" style={{ padding: '11px', borderRadius: '14px' }} onClick={() => handleSaveReviewNotePdf(reviewNoteResult.id, reviewNoteResult.pdfUrl, reviewNoteResult.title)}>컴퓨터에 저장</button>
                          {reviewNoteResult.archiveMaterialId && (
                            <button className="btn-outline" style={{ padding: '11px', borderRadius: '14px' }} onClick={() => navigate(`/archive/reviewNote/${reviewNoteResult.archiveMaterialId}?tab=retry`)}>자료보관함에서 학습(다시 풀기·유사문제·AI 해설)</button>
                          )}
                          <button className="btn-outline" style={{ padding: '11px', borderRadius: '14px' }} onClick={() => navigate('/review-notes')}>오답노트에서 보기</button>
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

              {/* AI 실패 시 기본(fallback) 로드맵 안내 — 로드맵은 그대로 사용 가능 */}
              {roadmapFallbackNotice && (
                <div style={{ margin: '0 0 16px', borderRadius: '12px', border: '1px solid #FDE68A', background: '#FFFBEB', padding: '12px 16px', display: 'flex', alignItems: 'flex-start', gap: '8px' }}>
                  <Map size={16} color="#B45309" style={{ marginTop: '2px', flexShrink: 0 }} />
                  <span style={{ fontSize: '13px', color: '#92400E', lineHeight: 1.6 }}>{roadmapFallbackNotice}</span>
                </div>
              )}

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
            <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', height: '100%', overflowY: 'auto', paddingBottom: '24px' }}>
              {/* ── 나의 학습 메모 (PDF 기반 검증 통과분만 S3 저장) ─────────────── */}
              <h3 style={{ margin: '0 0 8px', fontSize: '20px' }}>나의 학습 메모</h3>
              <p style={{ color: 'var(--color-text-muted)', fontSize: '13.5px', lineHeight: '1.6', marginBottom: '14px' }}>
                PDF 내용과 관련된 개념 정리, 질문, 헷갈린 점, 학습 회고를 저장할 수 있습니다.{' '}
                PDF에 직접 나온 개념뿐 아니라 PDF 개념에서 이어지는 하위·선수·응용·비교 개념도 저장할 수 있습니다.{' '}
                욕설, 인신공격, 잡담, 무의미한 내용은 저장되지 않습니다.
              </p>
              <textarea
                  style={{
                    flex: 1,
                    padding: '18px',
                    borderRadius: '14px',
                    border: '1px solid var(--color-border)',
                    backgroundColor: '#FFFDF5',
                    color: 'var(--color-text-main)',
                    fontSize: '15px',
                    lineHeight: '1.7',
                    fontFamily: 'inherit',
                    resize: 'vertical',
                    minHeight: '200px',
                    boxShadow: 'inset 0 2px 8px rgba(0,0,0,0.03)'
                  }}
                  placeholder={'예: OOP에서 클래스는 객체를 만들기 위한 설계도이고, 객체는 실제 인스턴스라는 점을 정리했다.\n예: OOP를 공부하다 보니 상속에서 부모 클래스와 자식 클래스 관계가 헷갈린다.\n예: 다형성을 이해하려면 오버라이딩과 상속 관계를 같이 봐야 한다.'}
                  value={memoText}
                  onChange={(e) => setMemoText(e.target.value)}
              />
              {journalNotice && (
                  <div style={{
                    marginTop: '10px',
                    padding: '12px 16px',
                    borderRadius: '12px',
                    border: `1px solid ${journalNotice.type === 'block' ? '#F5C2C7' : '#FDE2B3'}`,
                    backgroundColor: journalNotice.type === 'block' ? '#FFF1F2' : '#FFF8E8',
                    color: journalNotice.type === 'block' ? '#B02A37' : '#8A6100',
                    fontSize: '14px',
                    lineHeight: '1.6'
                  }}>
                    <div>{journalNotice.reason}</div>
                    {journalNotice.suggestion && (
                        <div style={{ marginTop: '6px', color: 'var(--color-text-muted)' }}>💡 {journalNotice.suggestion}</div>
                    )}
                  </div>
              )}
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '12px', flexWrap: 'wrap' }}>
                <button
                    className="btn-outline"
                    style={{ width: 'auto', padding: '10px 24px', borderRadius: '30px', fontWeight: 'bold', display: 'inline-flex', alignItems: 'center', gap: '6px' }}
                    onClick={handleSaveMemoAsJournal}
                    disabled={isSavingMemoJournal}
                >
                  <Edit3 size={15} /> {isSavingMemoJournal ? '저장 중...' : '학습일지 저장'}
                </button>
                <button
                    className="btn-primary"
                    style={{ width: 'auto', padding: '10px 28px', borderRadius: '30px', fontWeight: 'bold' }}
                    onClick={handleSaveMemo}
                    disabled={isSavingMemo}
                >
                  {isSavingMemo ? '저장 중...' : '메모 저장'}
                </button>
              </div>

              {/* 메모 목록 (검증 통과분) — 비어 있으면 안내 문구 */}
              {studyJournals.length === 0 ? (
                  <div style={{ marginTop: '20px', padding: '24px', textAlign: 'center', color: 'var(--color-text-muted)', fontSize: '14px', border: '1px dashed var(--color-border)', borderRadius: '12px', backgroundColor: '#FBFBF9' }}>
                    아직 저장된 메모가 없습니다.
                  </div>
              ) : (
                  <div style={{ marginTop: '20px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
                    {studyJournals.map((j) => (
                        <div key={j.id} style={{
                          padding: '14px 16px',
                          borderRadius: '12px',
                          border: '1px solid var(--color-border)',
                          backgroundColor: '#FFFFFF'
                        }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px' }}>
                            <div style={{ display: 'flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap' }}>
                              {(j.relationPath || j.relationType) && (
                                  <span style={{ fontSize: '12px', padding: '2px 10px', borderRadius: '20px', backgroundColor: '#EEF4FF', color: '#3B5BDB' }}>{j.relationPath || j.relationType}</span>
                              )}
                              <span style={{ fontSize: '12px', color: 'var(--color-text-muted)' }}>
                                {j.createdAt ? String(j.createdAt).slice(0, 10) : ''}
                              </span>
                            </div>
                            <div style={{ display: 'flex', gap: '8px' }}>
                              <button onClick={() => handleToggleJournal(j.id)} style={{ border: 'none', background: 'none', color: '#3B5BDB', cursor: 'pointer', fontSize: '13px' }}>
                                {j._expanded ? '접기' : '원문 보기'}
                              </button>
                              <button onClick={() => handleDeleteJournal(j.id)} style={{ border: 'none', background: 'none', color: 'var(--color-text-muted)', cursor: 'pointer', fontSize: '13px' }}>삭제</button>
                            </div>
                          </div>
                          {j._expanded && (
                              <p style={{ marginTop: '10px', marginBottom: 0, fontSize: '14.5px', lineHeight: '1.7', whiteSpace: 'pre-wrap', color: 'var(--color-text-main)' }}>
                                {j.content}
                              </p>
                          )}
                        </div>
                    ))}
                  </div>
              )}
            </div>
        );

      case 'chat': {
        const currentTextStatus = summaryData?.textStatus || roadmapData?.textStatus || quizzes.find(q => q?.textStatus)?.textStatus;
        const textBlocked = currentTextStatus?.hasText === false || currentTextStatus?.status === 'EMPTY';
        const textStatusMessage = getTextStatusMessage(currentTextStatus);
        return (
            <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', minHeight: '680px' }}>
              <h3 style={{ margin: '0 0 16px', fontSize: '20px' }}>AI 질문</h3>
              {textStatusMessage && (
                <div className="glass-panel" style={{ padding: '14px 16px', borderLeft: '4px solid #F59E0B', backgroundColor: '#FFFBEB', color: '#92400E', marginBottom: '12px' }}>
                  {textStatusMessage}
                </div>
              )}
              <div style={{ flex: 1, minHeight: '400px', overflowY: 'auto', backgroundColor: '#F9FAFB', borderRadius: '12px', padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px', border: '1px solid var(--color-border)' }}>
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
                          wordBreak: 'break-word'
                        }}
                    >
                      {/* P. AI 답변은 마크다운 기호 제거 후 표시(코드 텍스트는 보존). 사용자 메시지는 원본 유지. */}
                      {msg.sender === 'ai' ? sanitizeMarkdownText(msg.text) : msg.text}
                    </div>
                ))}
                <div ref={chatEndRef} />
              </div>
              <div style={{ marginTop: '16px' }}>
                <form onSubmit={handleSendChat} style={{ display: 'flex', gap: '12px', width: '100%', alignItems: 'flex-end' }}>
                  <textarea
                      className="input-field"
                      rows={3}
                      style={{ flex: 1, minWidth: 0, margin: 0, borderRadius: '20px', backgroundColor: '#F3F4F6', border: 'none', padding: '14px 20px', fontSize: '15px', lineHeight: 1.6, minHeight: '96px', maxHeight: '240px', resize: 'vertical', fontFamily: 'inherit' }}
                      placeholder={textBlocked ? '문서 텍스트 추출 후 질문할 수 있습니다.' : '자료 내용에 대해 궁금한 점을 입력하세요. (Enter 전송 · Shift+Enter 줄바꿈)'}
                      value={chatInput}
                      onChange={(e) => setChatInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent?.isComposing) {
                          e.preventDefault();
                          handleSendChat(e);
                        }
                      }}
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


  // ── 오답노트(REVIEW_NOTE) 상세 ────────────────────────────────────────────────
  //  자료보관함의 REVIEW_NOTE material 카드 진입점. 실제 복습 기능(다시 풀기/유사문제/AI 해설/메모)은
  //  여기서만 실행한다. 상단바/레이아웃은 학습PDF 상세와 동일 스타일(ReviewNoteArchiveDetail).
  if (type === 'reviewNote') {
    return (
      <ReviewNoteArchiveDetail
        material={material}
        leftWidth={leftWidth}
        setLeftWidth={setLeftWidth}
        onDelete={handleDeleteMaterial}
        onBack={() => navigate('/archive')}
      />
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
                {/* AI 도구 버튼: PLANNER 는 플래너 전용(메모/퀴즈/AI질문 없음), 그 외 PDF 는 기존 학습 도구 유지 */}
                {isPlanner ? (
                  /* 우측 학습 도구: AI 계획 분석 / 다음 학습 추천 / 메모 / 소크라테스 복습 (보조 버튼·중복 진행률 제거) */
                  <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                    <button className={`archive-action-btn ${plannerDetailView === 'analysis' ? 'active' : ''}`} onClick={() => setPlannerDetailView('analysis')}><Sparkles size={16} /> AI 계획 분석</button>
                    <button className={`archive-action-btn ${plannerDetailView === 'next' ? 'active' : ''}`} onClick={() => setPlannerDetailView('next')}><ArrowRight size={16} /> 다음 학습 추천</button>
                    <button className={`archive-action-btn ${plannerDetailView === 'memo' ? 'active' : ''}`} onClick={() => setPlannerDetailView('memo')}><Edit3 size={16} /> 메모</button>
                    <button className={`archive-action-btn ${plannerDetailView === 'socratic' ? 'active' : ''}`} onClick={() => setPlannerDetailView('socratic')}><Brain size={16} /> 소크라테스 복습</button>
                  </div>
                ) : (
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <button className={`archive-action-btn ${activePdfTool === 'summary' ? 'active' : ''}`} onClick={() => setActivePdfTool('summary')}><AlignLeft size={16} /> 요약</button>
                    <button className={`archive-action-btn ${activePdfTool === 'quiz' ? 'active' : ''}`} onClick={() => setActivePdfTool('quiz')}><HelpCircle size={16} /> 퀴즈/문제 생성</button>
                    <button className={`archive-action-btn ${activePdfTool === 'roadmap' ? 'active' : ''}`} onClick={() => setActivePdfTool('roadmap')}><Map size={16} /> 주차별 로드맵</button>
                    <button className={`archive-action-btn ${activePdfTool === 'memo' ? 'active' : ''}`} onClick={() => setActivePdfTool('memo')}><Edit3 size={16} /> 메모</button>
                    <button className={`archive-action-btn ${activePdfTool === 'chat' ? 'active' : ''}`} onClick={() => setActivePdfTool('chat')}><MessageSquare size={16} /> AI 질문</button>
                  </div>
                )}
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
                isPlanner ? renderPlannerRightPanel() : renderPdfRightPanel()
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
