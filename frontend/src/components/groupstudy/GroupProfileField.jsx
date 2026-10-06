import React, { useRef } from 'react';
import { groupDefaultIcon } from './GroupProfileImage';

// 대표 이미지 전용 검증(GroupStudy.jsx 의 validateCoverImageFile 과 동일 규칙): JPG/PNG/WEBP, 5MB.
const COVER_IMAGE_MIME_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp']);
const COVER_IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.webp'];
export const validateCoverImageFile = (file) => {
  const name = (file?.name || '').toLowerCase();
  const validMime = COVER_IMAGE_MIME_TYPES.has(file?.type);
  const validExt = COVER_IMAGE_EXTENSIONS.some((ext) => name.endsWith(ext));
  if (!validMime && !validExt) return '대표 이미지는 JPG, PNG, WEBP 파일만 업로드할 수 있습니다.';
  if (file.size > 5 * 1024 * 1024) return '대표 이미지는 5MB 이하만 업로드할 수 있습니다.';
  return null;
};

// 그룹 프로필 아바타: 대표 이미지가 있으면 이미지, 없으면 기본 그룹 아이콘.
//  · 스터디콘(studyIconId) asset 은 추후 사용자가 제공할 예정 → 지금은 기본 아이콘만 사용하고 외부 이미지를 내려받지 않는다.
export function GroupProfileAvatar({ imageUrl, size = 72, alt = '그룹 프로필', studyType }) {
  const Icon = groupDefaultIcon(studyType);
  return (
    <div className="gs-profile-avatar" style={{ width: size, height: size }}>
      {imageUrl
        ? <img src={imageUrl} alt={alt} />
        : <Icon size={Math.round(size * 0.45)} color="var(--color-primary)" />}
    </div>
  );
}

// 수정 모달용 프로필 필드: 미리보기 + 이미지 변경/기본으로 되돌리기.
export default function GroupProfileField({ previewUrl, onPickFile, onClear, onError, studyType }) {
  const inputRef = useRef(null);
  return (
    <div className="gs-profile">
      <GroupProfileAvatar imageUrl={previewUrl} studyType={studyType} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', minWidth: 0 }}>
        <div className="gs-profile-actions">
          <button type="button" className="btn-outline" onClick={() => inputRef.current?.click()}>이미지 변경</button>
          {previewUrl && (
            <button type="button" className="btn-outline" onClick={onClear}>기본 아이콘으로</button>
          )}
        </div>
        <span className="gs-form-hint">JPG/PNG/WEBP, 5MB 이하. 이미지가 없으면 스터디 타입(일반/캠) 기본 아이콘이 표시됩니다.</span>
        <input
          ref={inputRef}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          style={{ display: 'none' }}
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = '';
            if (!file) return;
            const err = validateCoverImageFile(file);
            if (err) { onError?.(err); return; }
            onPickFile(file);
          }}
        />
      </div>
    </div>
  );
}
