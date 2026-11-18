import React, { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Lock, Users, UserCheck, AlertTriangle } from 'lucide-react';
import { groupService } from '../services/api';
import { studyTypeLabel } from '../utils/groupStudy';
import GroupProfileImage from '../components/groupstudy/GroupProfileImage';

// 비공개 그룹 초대 링크 랜딩: /groups/invite/:token (로그인 필수 — PrivateRoute).
//  미리보기(유효성·그룹 요약) → [참여하기] → POST accept → 그룹스터디 페이지로 이동.
//  데스크톱/모바일/앱 공통 경로. 서버가 토큰·정원·닉네임 규칙을 최종 검증한다.
export default function GroupInvitePage() {
  const { token } = useParams();
  const navigate = useNavigate();
  const [preview, setPreview] = useState(null);
  const [loading, setLoading] = useState(true);
  const [joining, setJoining] = useState(false);
  const [nickname, setNickname] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const p = await groupService.previewInvite(token);
        if (alive) setPreview(p);
      } catch (err) {
        if (alive) setError(err.response?.data?.message || '초대 링크를 확인할 수 없습니다.');
      } finally { if (alive) setLoading(false); }
    })();
    return () => { alive = false; };
  }, [token]);

  const accept = async () => {
    setJoining(true);
    setError('');
    try {
      await groupService.acceptInvite(token, { nickname: nickname.trim() || undefined });
      navigate('/groupstudy', { replace: true, state: { joinedGroupId: preview?.groupId } });
    } catch (err) {
      setError(err.response?.data?.message || '참여에 실패했습니다.');
    } finally { setJoining(false); }
  };

  const card = { maxWidth: '520px', margin: '0 auto', padding: '24px' };
  return (
    <div className="container-main" style={{ minHeight: 'calc(100vh - 120px)', display: 'flex', alignItems: 'flex-start', justifyContent: 'center' }}>
      <div className="glass-panel gs-invite-page" style={{ ...card, width: '100%', boxSizing: 'border-box', display: 'flex', flexDirection: 'column', gap: '16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--color-text-main)', fontWeight: 800, fontSize: '18px' }}>
          <Lock size={18} color="var(--color-primary)" /> 스터디 초대
        </div>

        {loading && <div style={{ color: 'var(--color-text-muted)', fontSize: '14px' }}>초대 링크를 확인하는 중...</div>}

        {!loading && preview && (
          <>
            <div style={{ display: 'flex', gap: '14px', alignItems: 'center', minWidth: 0 }}>
              <div style={{ width: '64px', height: '64px', borderRadius: 'var(--radius-card)', overflow: 'hidden', flexShrink: 0, position: 'relative' }}>
                <GroupProfileImage imageUrl={preview.coverImageUrl} studyType={preview.studyType} iconSize={28} fill alt={preview.title} />
              </div>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontWeight: 700, fontSize: '16px', color: 'var(--color-text-main)', overflowWrap: 'anywhere' }}>{preview.title}</div>
                <div style={{ fontSize: '13px', color: 'var(--color-text-muted)', display: 'flex', flexWrap: 'wrap', gap: '4px 10px', marginTop: '4px' }}>
                  <span>{studyTypeLabel(preview.studyType)}</span>
                  <span><Users size={12} style={{ verticalAlign: '-2px' }} /> {preview.currentCount} / {preview.capacity}명</span>
                  <span>방장 {preview.leaderName}</span>
                </div>
              </div>
            </div>
            {preview.description && (
              <p style={{ margin: 0, fontSize: '14px', color: 'var(--color-text-muted)', lineHeight: 1.6, overflowWrap: 'anywhere' }}>{preview.description}</p>
            )}

            {!preview.valid ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '12px', borderRadius: 'var(--radius-btn)', backgroundColor: 'var(--color-secondary)', color: 'var(--color-danger)', fontSize: '14px', fontWeight: 600 }}>
                <AlertTriangle size={16} /> {preview.reason || '사용할 수 없는 초대 링크입니다.'}
              </div>
            ) : preview.alreadyMember ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '12px', borderRadius: 'var(--radius-btn)', backgroundColor: 'var(--color-secondary)', color: 'var(--color-text-main)', fontSize: '14px', fontWeight: 600 }}>
                <UserCheck size={16} color="var(--color-primary)" /> 이미 참여 중인 스터디입니다.
              </div>
            ) : (
              <>
                {preview.nicknameRuleEnabled && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    <label style={{ fontSize: '13px', fontWeight: 600, color: 'var(--color-text-main)' }}>그룹 닉네임 <span style={{ color: 'var(--color-danger)' }}>*</span></label>
                    <input className="input-field" value={nickname} onChange={(e) => setNickname(e.target.value)} placeholder={preview.nicknameRule ? `규칙: ${preview.nicknameRule}` : '그룹에서 사용할 닉네임'} maxLength={30} />
                    {preview.nicknameRule && <span style={{ fontSize: '12px', color: 'var(--color-text-muted)' }}>닉네임 규칙: {preview.nicknameRule}</span>}
                  </div>
                )}
                <div style={{ fontSize: '12px', color: 'var(--color-text-muted)' }}>참여를 누르면 승인 절차 없이 바로 멤버가 됩니다.</div>
              </>
            )}
          </>
        )}

        {error && <div style={{ fontSize: '13px', color: 'var(--color-danger)' }}>{error}</div>}

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px', marginTop: '4px' }}>
          {!loading && preview?.valid && !preview?.alreadyMember && (
            <button type="button" className="btn-primary" style={{ width: 'auto', padding: '10px 20px' }} onClick={accept} disabled={joining}>
              {joining ? '참여 중...' : '스터디 참여하기'}
            </button>
          )}
          <button type="button" className="btn-outline" style={{ width: 'auto', padding: '10px 20px' }} onClick={() => navigate('/groupstudy')}>
            {preview?.alreadyMember ? '스터디로 이동' : '그룹스터디 목록'}
          </button>
        </div>
      </div>
    </div>
  );
}
