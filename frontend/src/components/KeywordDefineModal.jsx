import React, { useEffect, useState, useCallback } from 'react';
import { X, BookOpen, Sparkles, AlertTriangle, RotateCcw, ExternalLink } from 'lucide-react';
import { materialService } from '../services/api';

/**
 * 핵심 키워드 개념 정의 우측 슬라이드 패널.
 *  - chip 클릭 시 열림. loading / error / retry 상태.
 *  - 개념명 / 짧은 정의 / 자세한 정의 / 중요성 / 예시 / 관련개념 / sourceUsed 뱃지.
 *  - 브라우저 → Spring(/api/materials/{id}/keywords/define) → FastAPI.
 */
export default function KeywordDefineModal({ materialId, keyword, context, level = 'undergraduate', onClose }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [data, setData] = useState(null);

  const fetchDefine = useCallback(async () => {
    if (!keyword) return;
    setLoading(true);
    setError(null);
    setData(null);
    try {
      const res = await materialService.defineKeyword(materialId, {
        keyword,
        source: 'auto',
        level,
        context: context ? String(context).slice(0, 1500) : undefined,
      });
      if (res && res.success === false) {
        setError(res.message || '개념 정의를 가져오지 못했습니다.');
      } else {
        setData(res);
      }
    } catch (e) {
      setError('개념 정의 요청 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.');
    } finally {
      setLoading(false);
    }
  }, [materialId, keyword, context, level]);

  useEffect(() => { fetchDefine(); }, [fetchDefine]);

  // ESC 닫기
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose?.(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const sourceBadgeColor = (src) => {
    if (src === 'Wikipedia') return { bg: '#EFF6FF', fg: '#1D4ED8' };
    if (src === 'Mixed') return { bg: '#F0FDF4', fg: '#15803D' };
    return { bg: '#EEF2FF', fg: '#4338CA' }; // AI
  };

  // GPT/OpenAI 등 브랜드명을 노출하지 않고 "AI 개념 정의"로 통일 표시
  const sourceBadgeLabel = (src) => {
    if (src === 'Wikipedia') return 'Wikipedia';
    if (src === 'Mixed') return 'AI + Wikipedia';
    return 'AI 개념 정의';
  };

  return (
    <div
      onClick={onClose}
      style={{ position: 'fixed', inset: 0, backgroundColor: 'rgba(17,24,39,0.35)', zIndex: 1000, display: 'flex', justifyContent: 'flex-end' }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="animate-fade-in"
        style={{
          width: 'min(440px, 92vw)', height: '100%', backgroundColor: '#fff',
          boxShadow: '-8px 0 30px rgba(0,0,0,0.12)', display: 'flex', flexDirection: 'column',
          borderTopLeftRadius: '16px', borderBottomLeftRadius: '16px', overflow: 'hidden',
        }}
      >
        {/* 헤더 */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '18px 20px', borderBottom: '1px solid var(--color-border)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <BookOpen size={18} color="var(--color-primary)" />
            <span style={{ fontSize: '16px', fontWeight: 700, color: 'var(--color-text-main)' }}>개념 정의</span>
          </div>
          <button onClick={onClose} style={{ border: 'none', background: 'transparent', cursor: 'pointer', color: 'var(--color-text-muted)' }}>
            <X size={20} />
          </button>
        </div>

        {/* 본문 */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px', flexWrap: 'wrap' }}>
            <span className="tag" style={{ backgroundColor: '#F3F4F6', color: 'var(--color-text-main)', fontSize: '15px', fontWeight: 700 }}>#{keyword}</span>
            {data?.sourceUsed && (
              <span style={{
                fontSize: '12px', fontWeight: 700, padding: '4px 10px', borderRadius: '999px',
                backgroundColor: sourceBadgeColor(data.sourceUsed).bg, color: sourceBadgeColor(data.sourceUsed).fg,
                display: 'inline-flex', alignItems: 'center', gap: '4px',
              }}>
                <Sparkles size={12} /> {sourceBadgeLabel(data.sourceUsed)}
              </span>
            )}
          </div>

          {loading && (
            <div style={{ textAlign: 'center', padding: '48px 0', color: 'var(--color-text-muted)' }}>
              <div className="spinner" style={{ margin: '0 auto 16px' }} />
              <p style={{ margin: 0, fontSize: '14px' }}>“{keyword}” 개념을 분석하고 있습니다…</p>
            </div>
          )}

          {!loading && error && (
            <div style={{ padding: '20px', borderRadius: '12px', backgroundColor: '#FEF2F2', border: '1px solid #FECACA', color: '#991B1B' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 700, marginBottom: '8px' }}>
                <AlertTriangle size={16} /> 정의를 불러오지 못했습니다
              </div>
              <p style={{ margin: '0 0 16px', fontSize: '14px' }}>{error}</p>
              <button
                onClick={fetchDefine}
                className="btn-outline"
                style={{ width: 'auto', padding: '8px 16px', borderRadius: '20px', display: 'inline-flex', alignItems: 'center', gap: '6px' }}
              >
                <RotateCcw size={14} /> 다시 시도
              </button>
            </div>
          )}

          {!loading && !error && data && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
              {data.name && data.name !== keyword && (
                <h3 style={{ margin: 0, fontSize: '18px', color: 'var(--color-text-main)' }}>{data.name}</h3>
              )}
              {data.shortDefinition && (
                <Section label="짧은 정의" text={data.shortDefinition} accent="var(--color-primary)" />
              )}
              {data.detailedDefinition && (
                <Section label="자세한 정의" text={data.detailedDefinition} />
              )}
              {data.importance && (
                <Section label="왜 중요한가" text={data.importance} accent="#F59E0B" />
              )}
              {Array.isArray(data.examples) && data.examples.length > 0 && (
                <ListSection label="예시" items={data.examples} />
              )}
              {Array.isArray(data.relatedConcepts) && data.relatedConcepts.length > 0 && (
                <div>
                  <h5 style={{ margin: '0 0 8px', fontSize: '14px', color: 'var(--color-text-main)' }}>관련 개념</h5>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                    {data.relatedConcepts.map((c, i) => (
                      <span key={i} className="tag" style={{ backgroundColor: '#F3F4F6', color: 'var(--color-text-muted)' }}>{c}</span>
                    ))}
                  </div>
                </div>
              )}
              {data.wikiUrl && (
                <a href={data.wikiUrl} target="_blank" rel="noreferrer"
                   style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '13px', color: '#1D4ED8', textDecoration: 'none' }}>
                  <ExternalLink size={14} /> Wikipedia에서 더 보기
                </a>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Section({ label, text, accent = 'var(--color-border)' }) {
  return (
    <div style={{ borderLeft: `3px solid ${accent}`, paddingLeft: '12px' }}>
      <h5 style={{ margin: '0 0 6px', fontSize: '14px', color: 'var(--color-text-main)' }}>{label}</h5>
      <p style={{ margin: 0, fontSize: '14px', lineHeight: '1.7', color: 'var(--color-text-muted)', whiteSpace: 'pre-wrap' }}>{text}</p>
    </div>
  );
}

function ListSection({ label, items }) {
  return (
    <div>
      <h5 style={{ margin: '0 0 8px', fontSize: '14px', color: 'var(--color-text-main)' }}>{label}</h5>
      <ul style={{ margin: 0, paddingLeft: '18px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
        {items.map((it, i) => (
          <li key={i} style={{ fontSize: '14px', lineHeight: '1.6', color: 'var(--color-text-muted)' }}>{it}</li>
        ))}
      </ul>
    </div>
  );
}
