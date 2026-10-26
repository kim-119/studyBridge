export const REPORT_REASONS = [
  { value: 'SPAM', label: '스팸' },
  { value: 'ABUSE', label: '욕설·비방' },
  { value: 'INAPPROPRIATE_CONTENT', label: '부적절한 내용' },
  { value: 'OTHER', label: '기타' },
];

export const IMAGE_ACCEPT = 'image/jpeg,image/png,image/gif,image/webp';
export const PDF_ACCEPT = 'application/pdf';

const ACCEPTED_TYPES = {
  image: IMAGE_ACCEPT.split(','),
  pdf: [PDF_ACCEPT],
};

const ATTACHMENT_TYPE_ERROR = {
  image: 'JPG, PNG, GIF, WEBP 이미지만 첨부할 수 있습니다.',
  pdf: 'PDF 파일만 첨부할 수 있습니다.',
};

export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024;

export function attachmentError(file, kind) {
  if (!file) return null;
  if (!ACCEPTED_TYPES[kind].includes(file.type)) return ATTACHMENT_TYPE_ERROR[kind];
  if (file.size > MAX_UPLOAD_BYTES) return '파일은 50MB 이하만 첨부할 수 있습니다.';
  return null;
}

export function totalUploadError(files) {
  const totalBytes = files.filter(Boolean).reduce((sum, file) => sum + (file.size || 0), 0);
  return totalBytes > MAX_UPLOAD_BYTES ? '첨부 파일 용량의 합이 50MB를 넘습니다.' : null;
}

export function postsFromResponse(response) {
  if (Array.isArray(response)) return response;
  return response?.content || [];
}

export function formatPostTime(value) {
  const text = String(value || '');
  if (!text) return '';
  return text.slice(0, 16).replace('T', ' ');
}

export function likeStateOf(post) {
  return {
    likedByCurrentUser: Boolean(post?.likedByCurrentUser),
    likeCount: Number(post?.likeCount ?? 0),
  };
}

export function toggledLikeState(state) {
  const liked = !state.likedByCurrentUser;
  return {
    likedByCurrentUser: liked,
    likeCount: Math.max(0, state.likeCount + (liked ? 1 : -1)),
  };
}

export function updatePostIn(data, blogId, updater) {
  if (!data) return data;
  if (Array.isArray(data)) return data.map((post) => (post.blogId === blogId ? updater(post) : post));
  if (Array.isArray(data.content)) return { ...data, content: updatePostIn(data.content, blogId, updater) };
  return data.blogId === blogId ? updater(data) : data;
}

export function isOwnedBy(entity, userId) {
  if (!entity || userId === null || userId === undefined || userId === '') return false;
  return String(entity.authorId ?? '') === String(userId);
}

export function commentIdOf(comment) {
  return comment.commentId ?? comment.id;
}
