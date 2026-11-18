import React, { useEffect, useState } from 'react';
import { myReportService } from '../services/api';
const TYPES = { POST: '게시글', COMMENT: '댓글', USER: '사용자' };
const REASONS = { SPAM: '도배/스팸', ABUSE: '욕설/비방', INAPPROPRIATE_CONTENT: '부적절한 내용', OTHER: '기타' };
const STATUS = { PENDING: '접수됨', RESOLVED: '처리 완료', REJECTED: '반려' };
export default function MyReports() {
  const [source, setSource] = useState('KNOWLEDGE');
  const [page, setPage] = useState(0);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let alive = true;
    setLoading(true); setError('');
    myReportService.list(source, page).then(data => { if (alive) setItems(data || []); })
      .catch(() => { if (alive) setError('신고 내역을 불러오지 못했습니다. 다시 시도해 주세요.'); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [source, page, revision]);
  return <section aria-label="내 신고 내역" style={{ minWidth: 0, width: '100%' }}>
    <select aria-label="신고 분류" className="input-field" value={source} onChange={e => { setSource(e.target.value); setPage(0); }}>
      <option value="KNOWLEDGE">지식공유게시판 / 사용자 신고</option><option value="GROUP">그룹스터디 신고</option>
    </select>
    {loading ? <p role="status">신고 내역을 불러오는 중입니다.</p> : error ? <p role="alert">{error} <button className="btn-outline" onClick={() => setRevision(r => r + 1)}>재시도</button></p> : <>
      {!items.length && <p>접수한 신고가 없습니다.</p>}
      {items.map(r => <article key={`${r.source}-${r.reportId}`} data-testid="my-report" style={{ border: '1px solid var(--color-border)', borderRadius: 12, padding: 16, marginTop: 12, minWidth: 0, overflowWrap: 'anywhere' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
          <strong>{TYPES[r.targetType] || '대상'} 신고</strong>
          <span style={{ borderRadius: 20, padding: '4px 10px', fontSize: 12, whiteSpace: 'nowrap', background: r.status === 'RESOLVED' ? '#BBF7D0' : r.status === 'PENDING' ? '#FEF08A' : '#F3F4F6', color: r.status === 'RESOLVED' ? '#166534' : r.status === 'PENDING' ? '#854D0E' : '#4B5563' }}>{STATUS[r.status] || '접수 기록'}</span>
        </div>
        <p>{r.targetSummary}</p>
        {r.groupTitle && <p>{r.groupTitle}</p>}
        <p>신고 사유: {REASONS[r.reason] || r.details || '기타'}</p>
        {r.reason && r.details && <p style={{ whiteSpace: 'pre-wrap' }}>{r.details}</p>}
        <time dateTime={r.createdAt}>{r.createdAt?.replace('T', ' ').slice(0, 16)}</time>
      </article>)}
      <div style={{ display: 'flex', gap: 12, marginTop: 16 }}>
        <button className="btn-outline" disabled={page === 0} onClick={() => setPage(p => p - 1)}>이전</button>
        <button className="btn-outline" disabled={items.length < 20} onClick={() => setPage(p => p + 1)}>다음</button>
      </div>
    </>}
  </section>;
}
