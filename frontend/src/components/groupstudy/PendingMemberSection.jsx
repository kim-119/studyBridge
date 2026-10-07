import React from 'react';
import { Users } from 'lucide-react';

// 방장 콘솔 "가입 신청 대기자 명단". 노출 여부는 상위가 resolveLeaderConsoleSections(utils/groupStudy) 로 결정하며,
// 승인 정책이 꺼져 있고 대기자도 없으면 이 컴포넌트는 아예 렌더되지 않는다(빈 박스 숨김이 아니라 DOM 미생성).
export default function PendingMemberSection({ applications = [], loading = false, onApprove, onReject, variant = 'light' }) {
  return (
    <div data-testid="pending-member-section" style={{ display: 'flex', flexDirection: 'column', minHeight: '240px' }}>
      <h4 style={{ margin: '0 0 12px 0', fontSize: '14px', fontWeight: '700', color: '#374151', display: 'flex', alignItems: 'center', gap: '6px' }}>
        <Users size={16} /> 가입 신청 대기자 명단 ({applications.length})
      </h4>

      <div style={{ flex: 1, overflowY: 'auto', border: '1px solid #E5E7EB', borderRadius: '8px', padding: '10px', backgroundColor: '#F9FAFB', display: 'flex', flexDirection: 'column', gap: '10px', maxHeight: '300px' }}>
        {loading ? (
          <div style={{ padding: '20px 0', textAlign: 'center', fontSize: '13px', color: '#9CA3AF' }}>불러오는 중...</div>
        ) : applications.length === 0 ? (
          <div style={{ padding: '40px 0', textAlign: 'center', fontSize: '13px', color: '#9CA3AF' }}>대기 중인 신청자가 없습니다.</div>
        ) : (
          applications.map(app => (
            <div key={app.applicationId} data-testid="pending-member-item" style={{ backgroundColor: '#ffffff', border: '1px solid #E5E7EB', borderRadius: '8px', padding: '12px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  {app.applicantPhotoUrl ? (
                    <img src={app.applicantPhotoUrl} alt={app.applicantName} style={{ width: '24px', height: '24px', borderRadius: '50%', objectFit: 'cover' }} />
                  ) : (
                    <div style={{ width: '24px', height: '24px', borderRadius: '50%', backgroundColor: 'var(--color-primary)', color: 'white', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '11px', fontWeight: 'bold' }}>
                      {app.applicantName ? app.applicantName.charAt(0) : '?'}
                    </div>
                  )}
                  <span style={{ fontWeight: '700', fontSize: '14px', color: '#111827' }}>{app.applicantName}</span>
                </div>
                <span style={{ fontSize: '11px', color: '#9CA3AF' }}>{app.createdAt ? app.createdAt.split('T')[0] : ''}</span>
              </div>
              <p style={{ margin: 0, fontSize: '13px', color: '#4B5563', backgroundColor: '#F3F4F6', padding: '8px 10px', borderRadius: '6px', wordBreak: 'break-all', lineHeight: '1.4' }}>
                {app.introduction}
              </p>
              {app.joinAnswer && (
                <p style={{ margin: 0, fontSize: '12px', color: '#374151', lineHeight: '1.5', wordBreak: 'break-all' }}>
                  <span style={{ color: '#6B7280' }}>Q. {app.joinQuestion || '가입 질문'}</span><br />A. {app.joinAnswer}
                </p>
              )}
              {app.nickname && (
                <p style={{ margin: 0, fontSize: '12px', color: '#374151' }}><span style={{ color: '#6B7280' }}>그룹 닉네임</span> {app.nickname}</p>
              )}
              <div style={{ display: 'flex', gap: '8px', marginTop: '4px' }}>
                <button type="button" onClick={() => onApprove?.(app.applicationId)} style={{ flex: 1, height: '32px', backgroundColor: '#10B981', color: 'white', border: 'none', borderRadius: '6px', fontWeight: '700', fontSize: '12px', cursor: 'pointer' }}>
                  승인
                </button>
                <button type="button" onClick={() => onReject?.(app.applicationId)} style={{ flex: 1, height: '32px', backgroundColor: '#EF4444', color: 'white', border: 'none', borderRadius: '6px', fontWeight: '700', fontSize: '12px', cursor: 'pointer' }}>
                  거절
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
