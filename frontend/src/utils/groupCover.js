// 그룹 대표 이미지(생성 폼) 선택 상태 — 순수 함수만 둔다(번들 asset import 없음 → node 스모크로 검증 가능).
//  세 상태를 명확히 구분한다:
//   · preset : 기본 이미지(로컬 정적 asset) 선택. 생성 시 그 asset 을 실제 File 로 바꿔 image 로 보낸다
//              → 서버는 사용자 업로드와 같은 S3 경로(study-images/…)로 저장, 이후 presigned URL 로 조회.
//   · upload : 사용자가 고른 파일. 그대로 image 로 보낸다.
//   · none   : 이미지 없음. image 를 보내지 않는다 → coverImageKey=null → 카드/상세는 스터디 타입 기본 아이콘.
//  상태 전환 시 다른 상태의 흔적(stale imageFile / objectURL)을 남기지 않는다.
//  form.thumbnail 은 미리보기 URL(preset asset / objectURL / null) — 서버로 보내지 않는다.

export const COVER_MODES = { PRESET: 'preset', UPLOAD: 'upload', NONE: 'none' };

const findPreset = (presets, presetId) => (presets || []).find((p) => p.id === presetId) || null;

export const selectCoverPreset = (form, preset) => ({
  ...form,
  coverMode: COVER_MODES.PRESET,
  coverPresetId: preset.id,
  imageFile: null,
  thumbnail: preset.url,
});

export const selectCoverUpload = (form, file, previewUrl) => ({
  ...form,
  coverMode: COVER_MODES.UPLOAD,
  coverPresetId: null,
  imageFile: file,
  thumbnail: previewUrl,
});

export const selectCoverNone = (form) => ({
  ...form,
  coverMode: COVER_MODES.NONE,
  coverPresetId: null,
  imageFile: null,
  thumbnail: null,
});

// 전환으로 버려지는 업로드 미리보기(objectURL). 같은 URL 을 계속 쓰면 null.
export const discardedCoverPreviewUrl = (prev, next) => (
  prev?.coverMode === COVER_MODES.UPLOAD && prev.thumbnail && prev.thumbnail !== next?.thumbnail
    ? prev.thumbnail
    : null
);

const presetFileName = (preset, mime) => {
  const ext = mime === 'image/png' ? 'png' : mime === 'image/webp' ? 'webp' : 'jpg';
  return `group-cover-${preset.id}.${ext}`;
};

// 생성 요청의 image 파트. preset 은 asset 을 내려받아 File 로 만든다(실패 시 throw — 조용히 이미지 없이 만들지 않는다).
export const resolveCoverImageFile = async (form, presets, fetchImpl = globalThis.fetch) => {
  const mode = form?.coverMode;
  if (mode === COVER_MODES.UPLOAD) return form.imageFile || null;
  if (mode !== COVER_MODES.PRESET) return null;

  const preset = findPreset(presets, form.coverPresetId);
  if (!preset) throw new Error(`unknown cover preset: ${form.coverPresetId}`);
  const res = await fetchImpl(preset.url);
  if (!res.ok) throw new Error(`cover preset fetch failed: ${res.status}`);
  const blob = await res.blob();
  // SPA 폴백(index.html 200) 같은 비이미지 응답을 jpg 로 둔갑시켜 올리지 않는다.
  if (!blob.type.startsWith('image/')) throw new Error(`cover preset is not an image: ${blob.type || 'unknown'}`);
  return new File([blob], presetFileName(preset, blob.type), { type: blob.type });
};
