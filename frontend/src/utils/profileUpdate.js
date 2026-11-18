// MyPage 프로필 저장 payload 단일 지점(순수 함수 — node:test 로 검증).
//  백엔드 계약(UserDTO.UpdateProfileRequest): displayName(@NotBlank, 2~10자), major, photoUrl(S3 key).
//  · 조회 응답(GET /api/users/profile)의 photoUrl 은 1시간짜리 presigned URL(400자+)이다. 이를 그대로 되돌려 보내면
//    users.photo_url(varchar 255) 저장에 실패해 500 → "프로필 업데이트에 실패했습니다." 가 났다(2026-10-07 운영 재현).
//  · 따라서 photoUrl 은 (1) 새로 업로드한 s3Key, (2) 이미 key 형태인 값, (3) presigned URL 에서 복원한 key 만 보내고,
//    복원할 수 없으면 필드를 생략한다(백엔드는 생략/URL 을 "사진 미변경" 으로 처리해 기존 키를 보존한다).

export const DISPLAY_NAME_MIN = 2;
export const DISPLAY_NAME_MAX = 10;
export const DEFAULT_MAJOR_LABEL = '전공 미설정';
export const DISPLAY_NAME_RULE_MESSAGE = `닉네임은 ${DISPLAY_NAME_MIN}~${DISPLAY_NAME_MAX}자여야 합니다.`;

const S3_HOST_RE = /(^|\.)s3([.-][a-z0-9-]+)?\.amazonaws\.com$/i;

export const isAbsoluteUrl = (value) => typeof value === 'string' && /^https?:\/\//i.test(value.trim());

// S3 presigned/virtual-host URL → object key. S3 호스트가 아니거나 경로가 비면 null.
export const extractS3KeyFromPresignedUrl = (value) => {
  if (!isAbsoluteUrl(value)) return null;
  let url;
  try {
    url = new URL(value.trim());
  } catch {
    return null;
  }
  if (!S3_HOST_RE.test(url.hostname)) return null;
  let path = url.pathname.replace(/^\/+/, '');
  // path-style(s3.<region>.amazonaws.com/<bucket>/<key>)이면 첫 세그먼트(버킷)를 뗀다.
  if (/^s3([.-][a-z0-9-]+)?\.amazonaws\.com$/i.test(url.hostname)) {
    path = path.split('/').slice(1).join('/');
  }
  if (!path) return null;
  try {
    return decodeURIComponent(path);
  } catch {
    return path;
  }
};

// 현재 보여지는 사진 값(presigned URL 또는 key)에서 저장용 key 를 고른다. 모르면 null(필드 생략).
export const resolveStoredPhotoKey = (currentPhotoUrl) => {
  if (typeof currentPhotoUrl !== 'string') return null;
  const trimmed = currentPhotoUrl.trim();
  if (!trimmed) return null;
  if (trimmed.startsWith('blob:') || trimmed.startsWith('data:')) return null;
  if (!isAbsoluteUrl(trimmed)) return trimmed;
  return extractS3KeyFromPresignedUrl(trimmed);
};

export const resolveDisplayName = (name, email) => {
  const trimmed = typeof name === 'string' ? name.trim() : '';
  if (trimmed) return trimmed;
  const local = typeof email === 'string' ? email.split('@')[0] : '';
  return local || '';
};

// 저장 전 검증: 백엔드 @Size(2~10) 를 프론트에서 먼저 같은 문구로 막는다(400 왕복 방지).
export const validateProfileInput = ({ displayName, email } = {}) => {
  const resolved = resolveDisplayName(displayName, email);
  const length = Array.from(resolved).length;
  if (length < DISPLAY_NAME_MIN || length > DISPLAY_NAME_MAX) return DISPLAY_NAME_RULE_MESSAGE;
  return null;
};

/**
 * @param {{ displayName?: string, major?: string, email?: string, currentPhotoUrl?: string|null, uploadedS3Key?: string|null }} input
 * @returns {{ displayName: string, major: string, photoUrl?: string }}
 */
export const buildProfileUpdatePayload = ({ displayName, major, email, currentPhotoUrl, uploadedS3Key } = {}) => {
  const payload = {
    displayName: resolveDisplayName(displayName, email),
    major: (typeof major === 'string' ? major.trim() : '') || DEFAULT_MAJOR_LABEL,
  };
  const uploaded = typeof uploadedS3Key === 'string' ? uploadedS3Key.trim() : '';
  if (uploaded) {
    payload.photoUrl = uploaded;
    return payload;
  }
  const stored = resolveStoredPhotoKey(currentPhotoUrl);
  if (stored) payload.photoUrl = stored;
  return payload;
};

// authService.updateProfile 은 err.response.data(문자열 또는 {status,message}) 를 던진다 → userFacingError 가 읽을 수 있는 형태로.
export const normalizeProfileError = (error) => {
  if (typeof error === 'string') return { message: error };
  return error;
};
