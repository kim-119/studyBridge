import React from 'react';
import { User } from 'lucide-react';

// StudyBridge 기본 프로필 아바타(사용자 이미지가 없을 때의 최종 fallback).
//  · 별도 PNG 자산 없이 기존 색상 토큰(--color-secondary/--color-primary) 위에 lucide User 아이콘만 그린다.
//  · 프로필 "이미지" 가 있을 때는 이 컴포넌트를 쓰지 않는다(UI 아이콘과 실제 프로필 구분).
export default function DefaultAvatar({ size = 80, iconSize, dark = false, alt = '기본 프로필', style, className }) {
  const icon = iconSize || Math.round(size / 2);
  return (
    <div
      role="img"
      aria-label={alt}
      className={className}
      data-testid="default-avatar"
      style={{
        width: size, height: size, borderRadius: '50%', flexShrink: 0,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        backgroundColor: dark ? '#334155' : 'var(--color-secondary)',
        color: dark ? '#9CA3AF' : 'var(--color-primary)',
        ...style,
      }}
    >
      <User size={icon} />
    </div>
  );
}
