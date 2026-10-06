import React from 'react';
import { Globe, Lock } from 'lucide-react';
import { GROUP_STATUS_LABEL, countStudyDays, parseHashtags } from './groupStudyModel';

function formatPeriod(group) {
  if (!group.startDate || !group.endDate) return '기간 미정';
  const days = countStudyDays(group.startDate, group.endDate);
  return `${group.startDate} ~ ${group.endDate}${days ? ` (총 ${days}일)` : ''}`;
}

export function VisibilityBadge({ isPublic }) {
  return (
    <span className={isPublic ? 'mobile-group-badge' : 'mobile-group-badge is-private'}>
      {isPublic ? <Globe size={12} /> : <Lock size={12} />}
      {isPublic ? '공개방' : '비공개'}
    </span>
  );
}

export default function GroupInfoCard({ group }) {
  const tags = parseHashtags(group.hashtags);

  return (
    <section className="mobile-card mobile-section">
      <p className="mobile-group-info__badges">
        <VisibilityBadge isPublic={Boolean(group.isPublic)} />
        {group.status && <span className="mobile-card__meta">{GROUP_STATUS_LABEL[group.status] || group.status}</span>}
      </p>

      <dl className="mobile-group-info">
        <dt>방장</dt>
        <dd>{group.leaderName || '방장'}</dd>
        <dt>가입 인원</dt>
        <dd>
          {group.currentCount ?? 0} / {group.capacity ?? 0}명
        </dd>
        <dt>운영 기간</dt>
        <dd>{formatPeriod(group)}</dd>
      </dl>

      {tags.length > 0 && (
        <ul className="mobile-chips">
          {tags.map((tag) => (
            <li key={tag}>#{tag}</li>
          ))}
        </ul>
      )}

      <p className="mobile-paragraph">{group.description || '소개가 없습니다.'}</p>
    </section>
  );
}
