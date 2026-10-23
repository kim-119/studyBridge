import React, { useEffect, useState } from 'react';
import { Plus, UserRound } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import ScreenState, { EmptyState } from '../../components/ScreenState';
import SubTabs from '../../components/SubTabs';
import MobileScreen from '../../shell/MobileScreen';
import { groupService } from '../../../services/api';
import { useAuth } from '../../../hooks/useAuth';
import { useAsync } from '../../data/useAsync';
import { studyTypeLabel } from '../../../utils/groupStudy.js';
import { VisibilityBadge } from './GroupInfoCard';
import {
  CARD_TARGET,
  MEMBERSHIP,
  VISIBILITY,
  describeCardAction,
  isJoinedMember,
  needsMembershipCheck,
  selectVisibleGroups,
} from './groupStudyModel';

const VISIBILITY_TABS = [
  { key: VISIBILITY.PUBLIC, label: '공개 스터디' },
  { key: VISIBILITY.PRIVATE, label: '비공개방' },
];

async function fetchMembership(groupId, userId) {
  try {
    const members = await groupService.getMembers(groupId);
    return isJoinedMember(members, userId) ? MEMBERSHIP.MEMBER : MEMBERSHIP.GUEST;
  } catch (error) {
    console.warn('스터디 가입 여부를 확인하지 못했습니다.', groupId, error);
    return null;
  }
}

function useFullGroupMemberships(cards, userId) {
  const [memberships, setMemberships] = useState({});
  const uncheckedGroupIds = cards
    .filter(needsMembershipCheck)
    .map((card) => String(card.id))
    .filter((groupId) => !(groupId in memberships));
  const uncheckedKey = uncheckedGroupIds.join(',');

  useEffect(() => {
    if (!uncheckedKey || userId == null) return undefined;
    let isCancelled = false;

    Promise.all(
      uncheckedKey.split(',').map(async (groupId) => [groupId, await fetchMembership(groupId, userId)])
    ).then((results) => {
      if (isCancelled) return;
      const resolved = Object.fromEntries(results.filter(([, membership]) => membership !== null));
      setMemberships((previous) => ({ ...previous, ...resolved }));
    });

    return () => {
      isCancelled = true;
    };
  }, [uncheckedKey, userId]);

  return memberships;
}

function GroupCard({ card, membership, onOpen }) {
  const action = describeCardAction(card, membership);

  return (
    <li className="mobile-card mobile-group-card">
      <button type="button" className="mobile-group-card__cover" onClick={() => onOpen(CARD_TARGET.DETAIL)} aria-label={`${card.title} 상세 보기`}>
        <img src={card.coverUrl} alt="" loading="lazy" />
        <span className={card.isFull ? 'mobile-group-card__count is-full' : 'mobile-group-card__count'}>
          {card.currentCount}/{card.capacity}
          {card.isFull && ' (Full)'}
        </span>
      </button>

      <div className="mobile-group-card__body">
        <p className="mobile-group-card__meta">
          <VisibilityBadge isPublic={!card.isPrivate} />
          <span className="mobile-group-badge is-private">{studyTypeLabel(card.studyType)}</span>
          <span className="mobile-group-card__leader">
            <UserRound size={12} />
            {card.leaderName}
          </span>
        </p>
        <h2 className="mobile-group-card__title">{card.title}</h2>
        <p className="mobile-group-card__description">{card.description}</p>

        {card.tags.length > 0 && (
          <ul className="mobile-chips">
            {card.tags.map((tag) => (
              <li key={tag}>#{tag}</li>
            ))}
          </ul>
        )}

        <button
          type="button"
          className={action.disabled ? 'mobile-button mobile-button--secondary mobile-button--block' : 'mobile-button mobile-button--primary mobile-button--block'}
          disabled={action.disabled}
          onClick={() => onOpen(action.target)}
        >
          {action.label}
        </button>
      </div>
    </li>
  );
}

export default function GroupStudyScreen() {
  const navigate = useNavigate();
  const { userId } = useAuth();
  const [visibility, setVisibility] = useState(VISIBILITY.PUBLIC);
  const [keyword, setKeyword] = useState('');

  const groups = useAsync(() => groupService.getGroups(), []);
  const cards = selectVisibleGroups(groups.data, { userId, visibility, keyword });
  const memberships = useFullGroupMemberships(cards, userId);

  const openCard = (card, target) => {
    const path = target === CARD_TARGET.ROOM ? `/groupstudy/${card.id}/video` : `/groupstudy/${card.id}`;
    navigate(path);
  };

  return (
    <MobileScreen title="그룹스터디">
      <SubTabs tabs={VISIBILITY_TABS} activeKey={visibility} onChange={setVisibility} />

      <div className="mobile-toolbar">
        <input
          className="mobile-search"
          type="search"
          value={keyword}
          placeholder="스터디명 또는 기술 스택(태그) 검색"
          onChange={(event) => setKeyword(event.target.value)}
        />
      </div>

      <ScreenState query={groups} loadingLabel="스터디를 불러오는 중입니다">
        {cards.length === 0 ? (
          <EmptyState message={keyword.trim() ? '검색 결과가 없습니다.' : '조건에 맞는 스터디가 없습니다.'} />
        ) : (
          <ul className="mobile-group-list">
            {cards.map((card) => (
              <GroupCard
                key={card.id}
                card={card}
                membership={memberships[String(card.id)]}
                onOpen={(target) => openCard(card, target)}
              />
            ))}
          </ul>
        )}
      </ScreenState>

      <button type="button" className="mobile-group-fab" onClick={() => navigate('/groupstudy/new')}>
        <Plus size={20} />
        스터디
      </button>
    </MobileScreen>
  );
}
