import React, { useState } from 'react';
import { Plus, UserRound } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import ScreenState, { EmptyState } from '../../components/ScreenState';
import SubTabs from '../../components/SubTabs';
import MobileScreen from '../../shell/MobileScreen';
import { groupService } from '../../../services/api';
import { useAuth } from '../../../hooks/useAuth';
import { useAsync } from '../../data/useAsync';
import { VisibilityBadge } from './GroupInfoCard';
import { VISIBILITY, describeCardAction, selectVisibleGroups } from './groupStudyModel';

const VISIBILITY_TABS = [
  { key: VISIBILITY.PUBLIC, label: '공개 스터디' },
  { key: VISIBILITY.PRIVATE, label: '비공개방' },
];

function GroupCard({ card, onOpen }) {
  const action = describeCardAction(card);

  return (
    <li className="mobile-card mobile-group-card">
      <button type="button" className="mobile-group-card__cover" onClick={onOpen} aria-label={`${card.title} 상세 보기`}>
        <img src={card.coverUrl} alt="" loading="lazy" />
        <span className={card.isFull ? 'mobile-group-card__count is-full' : 'mobile-group-card__count'}>
          {card.currentCount}/{card.capacity}
          {card.isFull && ' (Full)'}
        </span>
      </button>

      <div className="mobile-group-card__body">
        <p className="mobile-group-card__meta">
          <VisibilityBadge isPublic={!card.isPrivate} />
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
          onClick={onOpen}
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
              <GroupCard key={card.id} card={card} onOpen={() => navigate(`/groupstudy/${card.id}`)} />
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
