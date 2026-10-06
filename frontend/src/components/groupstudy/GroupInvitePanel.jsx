import React, { useCallback, useEffect, useState } from 'react';
import { Link as LinkIcon, Copy, RefreshCw, Trash2, Check } from 'lucide-react';
import { groupService } from '../../services/api';

// 비공개 그룹 초대 링크 관리(방장 전용). 서버가 방장 여부를 최종 검증한다(403).
//  · 링크 = 현재 오리진 + invitePath → 데스크톱(studybridge.co.kr)/모바일(m.)/앱(원격 로드) 어디서 열어도 같은 SPA 라우트.
//  · 재생성 = 기존 링크 폐기 + 새 토큰. 폐기 = active=false.
//  · variant='dark' 는 스터디룸(어두운 배경)용 색만 다르고 동작은 같다.
const fmtDate = (iso) => (iso ? new Date(iso).toLocaleString('ko-KR', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '-');

export default function GroupInvitePanel({ groupId, variant = 'light', onNotify }) {
  const [invitation, setInvitation] = useState(null);
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState('');
  const dark = variant === 'dark';
  const notify = (title, msg) => (onNotify ? onNotify(title, msg) : window.alert(msg));

  const load = useCallback(async () => {
    if (!groupId) return;
    try {
      const list = await groupService.getActiveInvitations(groupId);
      setInvitation(Array.isArray(list) && list.length > 0 ? list[0] : null);
      setError('');
    } catch (err) {
      setError(err.response?.data?.message || '초대 링크를 불러오지 못했습니다.');
    }
  }, [groupId]);

  useEffect(() => { load(); }, [load]);

  const inviteUrl = invitation ? `${window.location.origin}${invitation.invitePath}` : '';

  const generate = async () => {
    setLoading(true);
    try {
      const created = await groupService.createInvitation(groupId, {});
      setInvitation(created);
      setCopied(false);
      setError('');
    } catch (err) {
      setError(err.response?.data?.message || '초대 링크 생성에 실패했습니다.');
    } finally { setLoading(false); }
  };

  const revoke = async () => {
    if (!invitation) return;
    setLoading(true);
    try {
      await groupService.revokeInvitation(groupId, invitation.id);
      setInvitation(null);
      setCopied(false);
    } catch (err) {
      setError(err.response?.data?.message || '초대 링크 폐기에 실패했습니다.');
    } finally { setLoading(false); }
  };

  const copy = async () => {
    if (!inviteUrl) return;
    let ok = false;
    try {
      if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(inviteUrl); ok = true; }
    } catch { ok = false; }
    if (!ok) {
      // 구형 WebView/비보안 컨텍스트 폴백
      try {
        const ta = document.createElement('textarea'); ta.value = inviteUrl; ta.setAttribute('readonly', ''); ta.style.position = 'fixed'; ta.style.opacity = '0';
        document.body.appendChild(ta); ta.select(); ok = document.execCommand('copy'); document.body.removeChild(ta);
      } catch { ok = false; }
    }
    setCopied(ok);
    if (!ok) notify('복사 실패', '링크를 길게 눌러 직접 복사해주세요.');
  };

  const fg = dark ? '#E5E7EB' : 'var(--color-text-main)';
  const muted = dark ? '#9CA3AF' : 'var(--color-text-muted)';
  const boxBg = dark ? 'rgba(255,255,255,0.03)' : 'var(--color-bg-base)';
  const border = dark ? '1px solid rgba(255,255,255,0.08)' : '1px solid var(--color-border)';
  const btn = { display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '8px 12px', borderRadius: 'var(--radius-btn)', fontSize: '13px', fontWeight: 600, cursor: loading ? 'wait' : 'pointer', border, backgroundColor: dark ? 'rgba(255,255,255,0.06)' : 'var(--color-bg-card)', color: fg, whiteSpace: 'nowrap' };
  const primaryBtn = { ...btn, backgroundColor: 'var(--color-primary)', color: '#fff', border: 'none' };

  return (
    <div className="gs-invite-panel" style={{ display: 'flex', flexDirection: 'column', gap: '10px', padding: '14px', borderRadius: 'var(--radius-card)', backgroundColor: boxBg, border }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: fg, fontWeight: 700, fontSize: '14px' }}>
        <LinkIcon size={16} color="var(--color-primary)" /> 초대하기
        <span style={{ fontSize: '12px', fontWeight: 500, color: muted }}>비공개 스터디는 이 링크로만 참여할 수 있습니다</span>
      </div>

      {invitation ? (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
            <input
              readOnly
              value={inviteUrl}
              onFocus={(e) => e.target.select()}
              aria-label="초대 링크"
              style={{ flex: 1, minWidth: 0, height: '38px', padding: '0 10px', borderRadius: 'var(--radius-input)', border, backgroundColor: dark ? 'rgba(0,0,0,0.25)' : 'var(--color-bg-card)', color: fg, fontSize: '13px', outline: 'none' }}
            />
            <button type="button" style={primaryBtn} onClick={copy} disabled={loading} aria-label="링크 복사">
              {copied ? <Check size={14} /> : <Copy size={14} />} {copied ? '복사됨' : '복사'}
            </button>
          </div>
          <div style={{ fontSize: '12px', color: muted, display: 'flex', flexWrap: 'wrap', gap: '6px 14px' }}>
            <span>초대 코드 <code style={{ fontSize: '12px', color: fg }}>{invitation.token}</code></span>
            <span>만료 {fmtDate(invitation.expiresAt)}</span>
            <span>사용 {invitation.usedCount}{invitation.maxUses ? ` / ${invitation.maxUses}` : ''}회</span>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
            <button type="button" style={btn} onClick={generate} disabled={loading}><RefreshCw size={14} /> 링크 재생성</button>
            <button type="button" style={{ ...btn, color: 'var(--color-danger)' }} onClick={revoke} disabled={loading}><Trash2 size={14} /> 링크 폐기</button>
          </div>
        </>
      ) : (
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '10px' }}>
          <span style={{ fontSize: '13px', color: muted }}>활성 초대 링크가 없습니다.</span>
          <button type="button" style={primaryBtn} onClick={generate} disabled={loading}><LinkIcon size={14} /> 초대 링크 생성</button>
        </div>
      )}
      {error && <div style={{ fontSize: '12px', color: 'var(--color-danger)' }}>{error}</div>}
    </div>
  );
}
