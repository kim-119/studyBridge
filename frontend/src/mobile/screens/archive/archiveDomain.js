export const ARCHIVE_TABS = [
  { key: 'LEARNING_MATERIAL', label: '학습자료' },
  { key: 'PLANNER', label: '플래너' },
  { key: 'STUDY_JOURNAL', label: '학습일지' },
  { key: 'MINDMAP', label: '마인드맵' },
];

export const SORT_OPTIONS = [
  { key: 'recent', label: '최신순' },
  { key: 'oldest', label: '오래된순' },
  { key: 'title', label: '이름순' },
];

const UPLOADABLE_DOMAINS = new Set(['LEARNING_MATERIAL']);

export function canUploadInto(domain) {
  return UPLOADABLE_DOMAINS.has(domain);
}

export function formatDate(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toISOString().slice(0, 10);
}

export function formatFileSize(bytes) {
  if (!bytes || bytes < 0) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function comparableTime(item) {
  const value = item.uploadedAt || item.updatedAt || item.createdAt;
  const time = value ? new Date(value).getTime() : 0;
  return Number.isNaN(time) ? 0 : time;
}

export function sortItems(items, sortKey) {
  const sorted = [...items];

  if (sortKey === 'title') {
    return sorted.sort((left, right) =>
      String(left.title || left.name || '').localeCompare(String(right.title || right.name || ''), 'ko')
    );
  }

  if (sortKey === 'oldest') {
    return sorted.sort((left, right) => comparableTime(left) - comparableTime(right));
  }

  return sorted.sort((left, right) => comparableTime(right) - comparableTime(left));
}

export function matchesKeyword(item, keyword) {
  if (!keyword) return true;
  const haystack = `${item.title || item.name || ''} ${item.keywords || ''} ${item.originalFileName || ''}`;
  return haystack.toLowerCase().includes(keyword.toLowerCase());
}
