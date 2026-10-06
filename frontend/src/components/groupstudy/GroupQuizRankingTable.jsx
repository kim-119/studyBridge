import React, { useCallback, useEffect, useState } from 'react';
import { RefreshCw, Trophy } from 'lucide-react';
import { groupService } from '../../services/api';

// 그룹 퀴즈 랭킹(GET /api/groups/{id}/stats/quiz-ranking). 순위/닉네임/점수/정답률/정답 수.
//  · 점수 = Σ points_awarded(서버 집계, RDS 정본). 동점 정렬·미참여자 0점·순위 산정은 서버 계약을 그대로 표시한다.
//  · 어두운 스터디룸 모달과 밝은 화면 모두에서 쓰도록 variant 만 다르다. 모바일에선 표가 좁은 폭에서 가로 스크롤 컨테이너 안에 갇힌다.
export default function GroupQuizRankingTable({ groupId, variant = 'dark', userId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const dark = variant === 'dark';
  const fg = dark ? '#E5E7EB' : 'var(--color-text-main)';
  const muted = dark ? '#9CA3AF' : 'var(--color-text-muted)';
  const line = dark ? '1px solid rgba(255,255,255,0.06)' : '1px solid var(--color-border)';

  const load = useCallback(async () => {
    if (!groupId) return;
    setLoading(true);
    try {
      const r = await groupService.getQuizRanking(groupId);
      setData(r);
      setError('');
    } catch (err) {
      setError(err.response?.data?.message || '랭킹을 불러오지 못했습니다.');
    } finally { setLoading(false); }
  }, [groupId]);

  useEffect(() => { load(); }, [load]);

  const members = data?.members || [];
  return (
    <div className="gs-ranking" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: fg, fontWeight: 700, fontSize: '14px' }}>
          <Trophy size={16} color="var(--color-primary)" /> 퀴즈 랭킹
          <span style={{ fontSize: '12px', fontWeight: 500, color: muted }}>누적 점수 · 세션 {data?.sessionCount ?? 0}회 · 멤버 {data?.memberCount ?? members.length}명</span>
        </div>
        <button type="button" onClick={load} disabled={loading} aria-label="랭킹 새로고침" style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '6px 10px', borderRadius: 'var(--radius-btn)', border: line, backgroundColor: 'transparent', color: muted, fontSize: '12px', cursor: 'pointer' }}>
          <RefreshCw size={13} /> 새로고침
        </button>
      </div>
      {error && <div style={{ fontSize: '12px', color: 'var(--color-danger)' }}>{error}</div>}
      <div style={{ overflowX: 'auto', WebkitOverflowScrolling: 'touch' }}>
        <table className="gs-ranking-table" style={{ width: '100%', minWidth: '440px', borderCollapse: 'collapse', textAlign: 'left', fontSize: '13px', color: fg }}>
          <thead>
            <tr style={{ color: muted, fontSize: '12px', borderBottom: line }}>
              <th style={{ padding: '10px 12px', fontWeight: 500, width: '56px' }}>순위</th>
              <th style={{ padding: '10px 12px', fontWeight: 500 }}>닉네임</th>
              <th style={{ padding: '10px 12px', fontWeight: 500, textAlign: 'right' }}>점수</th>
              <th style={{ padding: '10px 12px', fontWeight: 500, textAlign: 'right' }}>정답률</th>
              <th style={{ padding: '10px 12px', fontWeight: 500, textAlign: 'right' }}>정답 수</th>
            </tr>
          </thead>
          <tbody>
            {members.length === 0 && !loading && (
              <tr><td colSpan={5} style={{ padding: '18px 12px', color: muted, textAlign: 'center' }}>아직 랭킹이 없습니다. 실시간 퀴즈에 참여하면 점수가 누적됩니다.</td></tr>
            )}
            {members.map((m) => {
              const isMe = m.isMe || (userId != null && Number(m.userId) === Number(userId));
              return (
                <tr key={m.userId} style={{ borderBottom: line, backgroundColor: isMe ? (dark ? 'rgba(96,201,90,0.12)' : 'rgba(96,201,90,0.10)') : 'transparent' }}>
                  <td style={{ padding: '10px 12px', fontWeight: 800 }}>{m.rank}위</td>
                  <td style={{ padding: '10px 12px', fontWeight: isMe ? 700 : 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '180px' }}>
                    {m.nickname}{isMe ? ' (나)' : ''}
                    {m.role === 'LEADER' && <span style={{ marginLeft: '6px', fontSize: '11px', color: muted }}>방장</span>}
                  </td>
                  <td style={{ padding: '10px 12px', textAlign: 'right', fontWeight: 700, color: 'var(--color-primary)' }}>{m.score} P</td>
                  <td style={{ padding: '10px 12px', textAlign: 'right' }}>{Number(m.accuracy ?? 0).toFixed(1)}%</td>
                  <td style={{ padding: '10px 12px', textAlign: 'right' }}>{m.correctCount} / {m.totalQuestions}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
