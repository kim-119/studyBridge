import React from 'react';
import DefaultAvatar from '../DefaultAvatar';

// GENERAL 입장 준비: 선택된 프로필(이모지 / 이미지 / 기본 아바타 fallback)을 중앙에 크게 보여주고 닉네임을 함께 표시한다.
//  선택 즉시 상위 state 가 바뀌어 리렌더되므로 새로고침 없이 반영된다.
export default function AvatarPreview({ avatar, displayName, size = 160 }) {
  const hasImage = avatar?.kind === 'image' && avatar.url;
  const isEmoji = avatar?.kind === 'emoji' && avatar.value;
  const frame = { width: size, height: size, borderRadius: '50%', border: '4px solid #FFFFFF', boxShadow: '0 8px 24px rgba(0,0,0,0.12)', boxSizing: 'border-box' };
  return (
    <div data-testid="prejoin-avatar-preview" data-avatar-kind={avatar?.kind || 'default'} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '14px' }}>
      {isEmoji ? (
        <div data-testid="prejoin-avatar-emoji" role="img" aria-label={`프로필 이모지 ${avatar.value}`} style={{ ...frame, display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: 'var(--color-secondary)', fontSize: Math.round(size * 0.52), lineHeight: 1 }}>
          {avatar.value}
        </div>
      ) : hasImage ? (
        <img
          src={avatar.url}
          alt={displayName ? `${displayName} 프로필` : '프로필'}
          style={{ ...frame, objectFit: 'cover' }}
        />
      ) : (
        <DefaultAvatar size={size} style={{ border: '4px solid #FFFFFF', boxShadow: '0 8px 24px rgba(0,0,0,0.12)' }} />
      )}
      <div data-testid="prejoin-avatar-name" style={{ fontSize: '18px', fontWeight: '700', color: 'var(--color-text-main)', maxWidth: '100%', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {displayName || '사용자'}
      </div>
    </div>
  );
}
