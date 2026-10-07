import React, { useRef } from 'react';
import { User, Image, Upload } from 'lucide-react';
import { AVATAR_MODES } from '../../../utils/groupStudy';
import { validateProfileImageFile, PROFILE_IMAGE_ACCEPT } from '../GroupProfileField';
import { ICON_SIZE, HINT_STYLE } from './prejoinUi';

// GENERAL 입장 준비: 이번 입장에서 쓸 프로필 선택(기존 계정 프로필 / StudyBridge 기본 아바타 / 이미지 업로드).
//  · 업로드는 PNG/JPG/JPEG/WEBP 만 허용(validateProfileImageFile). 미리보기는 상위가 objectURL 로 즉시 반영한다.
//  · 실제 S3 업로드는 기존 authService.uploadProfileImage 를 입장 시점에 상위가 호출한다(신규 API/컬럼 없음).
export default function ProfileSelector({ mode, profilePhotoUrl, uploadedFileName, onSelectMode, onPickFile, onError }) {
  const inputRef = useRef(null);
  const chip = (active) => ({
    display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: '6px',
    height: '40px', padding: '0 14px', borderRadius: 'var(--radius-btn)', fontSize: '13px', fontWeight: 600,
    cursor: 'pointer', boxSizing: 'border-box',
    border: `1px solid ${active ? 'var(--color-primary)' : 'var(--color-border)'}`,
    backgroundColor: active ? 'rgba(96, 201, 90, 0.12)' : '#FFFFFF',
    color: active ? 'var(--color-primary-hover)' : 'var(--color-text-main)',
  });
  return (
    <div data-testid="prejoin-profile-selector" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '10px', width: '100%' }}>
      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', justifyContent: 'center' }}>
        {profilePhotoUrl && (
          <button type="button" style={chip(mode === AVATAR_MODES.PROFILE)} onClick={() => onSelectMode?.(AVATAR_MODES.PROFILE)} aria-pressed={mode === AVATAR_MODES.PROFILE}>
            <Image size={ICON_SIZE} /> 내 프로필 이미지
          </button>
        )}
        <button type="button" style={chip(mode === AVATAR_MODES.DEFAULT)} onClick={() => onSelectMode?.(AVATAR_MODES.DEFAULT)} aria-pressed={mode === AVATAR_MODES.DEFAULT}>
          <User size={ICON_SIZE} /> 기본 아이콘
        </button>
        <button type="button" style={chip(mode === AVATAR_MODES.UPLOAD)} onClick={() => inputRef.current?.click()} aria-pressed={mode === AVATAR_MODES.UPLOAD}>
          <Upload size={ICON_SIZE} /> {mode === AVATAR_MODES.UPLOAD ? '다른 이미지 업로드' : '이미지 업로드'}
        </button>
      </div>
      <span style={HINT_STYLE}>
        {mode === AVATAR_MODES.UPLOAD && uploadedFileName
          ? `선택한 이미지: ${uploadedFileName} (이번 입장에만 사용)`
          : 'PNG / JPG / JPEG / WEBP, 5MB 이하. 일반 스터디에서는 영상 대신 이 프로필이 표시됩니다.'}
      </span>
      <input
        ref={inputRef}
        type="file"
        accept={PROFILE_IMAGE_ACCEPT}
        data-testid="prejoin-profile-file-input"
        style={{ display: 'none' }}
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = '';
          if (!file) return;
          const err = validateProfileImageFile(file);
          if (err) { onError?.(err); return; }
          onPickFile?.(file);
        }}
      />
    </div>
  );
}
