import { Archive, CalendarDays, GraduationCap, Menu, Users } from 'lucide-react';

export const TAB_ITEMS = [
  { key: 'studymate', label: '학습메이트', path: '/studymate', icon: GraduationCap },
  { key: 'groupstudy', label: '그룹스터디', path: '/groupstudy', icon: Users },
  { key: 'archive', label: '자료보관함', path: '/archive', icon: Archive },
  { key: 'planner', label: '플래너', path: '/planner', icon: CalendarDays },
  { key: 'more', label: '전체', path: '/more', icon: Menu },
];

const HOME_PATH = '/';

export function findActiveTabKey(pathname) {
  if (pathname === HOME_PATH) return 'more';

  const match = TAB_ITEMS.find(
    (item) => item.path !== '/more' && pathname.startsWith(item.path)
  );

  return match ? match.key : 'more';
}
