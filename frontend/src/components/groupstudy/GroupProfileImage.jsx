import React from 'react';
import { Users, Video } from 'lucide-react';
import { STUDY_TYPES } from '../../utils/groupStudy';

// 그룹 프로필 표시 정책(카드/상세/프리조인/설정 공통):
//   customProfileImage(coverImageUrl) 있음 → 그 이미지
//   없음 && studyType === CAM          → 캠 스터디 기본 아이콘(Video)
//   없음                                → 일반 스터디 기본 아이콘(Users)
// 외부 아이콘/이미지 API 없이 lucide-react(기존 의존성)만 사용하고, 색은 기존 토큰(--color-primary/--color-secondary)만 쓴다.
export const groupDefaultIcon = (studyType) => (studyType === STUDY_TYPES.CAM ? Video : Users);

export default function GroupProfileImage({ imageUrl, studyType, alt = '그룹 프로필', iconSize = 40, fill = false, style, className }) {
  const Icon = groupDefaultIcon(studyType);
  const base = fill
    ? { position: 'absolute', top: 0, left: 0, width: '100%', height: '100%' }
    : { width: '100%', height: '100%' };
  if (imageUrl) {
    return <img src={imageUrl} alt={alt} className={className} style={{ ...base, objectFit: 'cover', display: 'block', ...style }} />;
  }
  return (
    <div
      className={className}
      role="img"
      aria-label={alt}
      style={{ ...base, display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: 'var(--color-secondary)', color: 'var(--color-primary)', ...style }}
    >
      <Icon size={iconSize} />
    </div>
  );
}
