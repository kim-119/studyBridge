import React, { useRef, useState } from 'react';
import { Image, Smile, Upload } from 'lucide-react';
import { AVATAR_MODES } from '../../../utils/groupStudy';
import { validateProfileImageFile, PROFILE_IMAGE_ACCEPT } from '../GroupProfileField';
import EmojiProfilePicker from './EmojiProfilePicker';
import { ICON_SIZE, HINT_STYLE } from './prejoinUi';

// GENERAL 입장 준비: 이번 입장에서 쓸 프로필 선택.
//  · [아이콘 선택] → EmojiProfilePicker(Unicode 이모지 그리드, 클릭 즉시 preview 반영) / [이미지 업로드] → PNG/JPG/JPEG/WEBP.
//  · 이미지 ↔ 이모지 전환은 언제든 가능(마지막 선택이 이긴다). 계정 프로필 사진이 있으면 [내 프로필 사진]으로 되돌릴 수 있다.
//  · lucide-react 는 버튼 UI 아이콘(Smile/Upload/Image)에만 쓰고, 실제 프로필 이모지는 Unicode 문자열이다.
//  · 실제 S3 업로드는 기존 authService.uploadProfileImage 를 입장 시점에 상위가 호출한다(신규 API/컬럼 없음).
export default function ProfileSelector({ mode, emoji, profilePhotoUrl, uploadedFileName, onSelectMode, onSelectEmoji, onPickFile, onError }) {
  const inputRef = useRef(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const chip = (active) => ({
    display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: '6px',
    height: '40px', padding: '0 14px', borderRadius: 'var(--radius-btn)', fontSize: '13px', fontWeight: 600,
    cursor: 'pointer', boxSizing: 'border-box',
    border: `1px solid ${active ? 'var(--color-primary)' : 'var(--color-border)'}`,
    backgroundColor: active ? 'rgba(96, 201, 90, 0.12)' : '#FFFFFF',
    color: active ? 'var(--color-primary-hover)' : 'var(--color-text-main)',
  });
  const hint = mode === AVATAR_MODES.EMOJI && emoji
    ? `선택한 아이콘: ${emoji} (이번 입장에만 사용)`
    : mode === AVATAR_MODES.UPLOAD && uploadedFileName
      ? `선택한 이미지: ${uploadedFileName} (이번 입장에만 사용)`
      : '아이콘을 고르거나 PNG / JPG / JPEG / WEBP(5MB 이하) 이미지를 올리세요. 일반 스터디에서는 영상 대신 이 프로필이 표시됩니다.';
  return (
    <div data-testid="prejoin-profile-selector" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '10px', width: '100%' }}>
      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', justifyContent: 'center' }}>
        {profilePhotoUrl && (
          <button type="button" data-testid="prejoin-profile-photo-button" style={chip(mode === AVATAR_MODES.PROFILE)} onClick={() => onSelectMode?.(AVATAR_MODES.PROFILE)} aria-pressed={mode === AVATAR_MODES.PROFILE}>
            <Image size={ICON_SIZE} /> 내 프로필 사진
          </button>
        )}
        <button type="button" data-testid="prejoin-emoji-button" style={chip(mode === AVATAR_MODES.EMOJI)} onClick={() => setPickerOpen(true)} aria-pressed={mode === AVATAR_MODES.EMOJI} aria-haspopup="dialog">
          <Smile size={ICON_SIZE} /> 아이콘 선택
        </button>
        <button type="button" data-testid="prejoin-upload-button" style={chip(mode === AVATAR_MODES.UPLOAD)} onClick={() => inputRef.current?.click()} aria-pressed={mode === AVATAR_MODES.UPLOAD}>
          <Upload size={ICON_SIZE} /> {mode === AVATAR_MODES.UPLOAD ? '다른 이미지 업로드' : '이미지 업로드'}
        </button>
      </div>
      <span style={HINT_STYLE}>{hint}</span>
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
      {pickerOpen && (
        <EmojiProfilePicker
          value={mode === AVATAR_MODES.EMOJI ? emoji : null}
          onSelect={(v) => onSelectEmoji?.(v)}
          onClose={() => setPickerOpen(false)}
        />
      )}
    </div>
  );
}
