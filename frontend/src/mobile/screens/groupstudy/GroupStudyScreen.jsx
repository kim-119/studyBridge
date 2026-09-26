import React, { useEffect, useMemo, useState } from 'react';
import { Users } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import Fab from '../../components/Fab';
import ListRow from '../../components/ListRow';
import ScreenState, { EmptyState } from '../../components/ScreenState';
import MobileScreen from '../../shell/MobileScreen';
import { groupService } from '../../../services/api';
import { useAsync } from '../../data/useAsync';

const SEARCH_DEBOUNCE_MS = 350;

export default function GroupStudyScreen() {
  const navigate = useNavigate();
  const [keyword, setKeyword] = useState('');
  const [appliedKeyword, setAppliedKeyword] = useState('');

  useEffect(() => {
    const timer = setTimeout(() => setAppliedKeyword(keyword.trim()), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [keyword]);

  const groups = useAsync(
    () => (appliedKeyword ? groupService.searchGroups(appliedKeyword) : groupService.getGroups()),
    [appliedKeyword]
  );

  const visibleGroups = useMemo(() => {
    const list = Array.isArray(groups.data) ? groups.data : groups.data?.content || [];
    return list;
  }, [groups.data]);

  return (
    <MobileScreen title="그룹스터디">
      <div className="mobile-toolbar">
        <input
          className="mobile-search"
          type="search"
          value={keyword}
          placeholder="스터디 검색"
          onChange={(event) => setKeyword(event.target.value)}
        />
      </div>

      <ScreenState query={groups} loadingLabel="스터디를 불러오는 중입니다">
        {visibleGroups.length === 0 ? (
          <EmptyState
            message={appliedKeyword ? '검색 결과가 없습니다.' : '아직 개설된 스터디가 없습니다.'}
          />
        ) : (
          <ul className="mobile-list">
            {visibleGroups.map((group) => (
              <li key={group.id}>
                <ListRow
                  icon={<Users size={20} />}
                  title={group.title}
                  subtitle={[group.leaderName, group.hashtags].filter(Boolean).join(' · ')}
                  meta={`${group.currentCount ?? 0}/${group.capacity ?? 0}`}
                  onClick={() => navigate(`/groupstudy/${group.id}`)}
                />
              </li>
            ))}
          </ul>
        )}
      </ScreenState>

      <Fab label="스터디 만들기" onClick={() => navigate('/groupstudy/new')} />
    </MobileScreen>
  );
}
