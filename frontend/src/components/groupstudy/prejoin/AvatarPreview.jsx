import React from 'react';
import DefaultAvatar from '../DefaultAvatar';

// GENERAL 입장 준비: 선택된 프로필(이미지 또는 기본 아바타)을 중앙에 크게 보여주고 닉네임을 함께 표시한다.
export default function AvatarPreview({ avatar, displayName, size = 160 }) {
  const hasImage = avatar?.kind === 'image' && avatar.url;
  return (
    <div data-testid="prejoin-avatar-preview" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '14px' }}>
      {hasImage ? (
        <img
          src={avatar.url}
          alt={displayName ? `${displayName} 프로필` : '프로필'}
          style={{ width: size, height: size, borderRadius: '50%', objectFit: 'cover', border: '4px solid #FFFFFF', boxShadow: '0 8px 24px rgba(0,0,0,0.12)' }}
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
