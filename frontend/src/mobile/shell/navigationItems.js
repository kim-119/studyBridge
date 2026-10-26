import { Archive, GraduationCap, House, Menu, Users } from 'lucide-react';

export const HOME_PATH = '/';

export const TAB_ITEMS = [
  { key: 'home', label: '홈', path: HOME_PATH, icon: House },
  { key: 'studymate', label: '학습메이트', path: '/studymate', icon: GraduationCap },
  { key: 'groupstudy', label: '그룹스터디', path: '/groupstudy', icon: Users },
  { key: 'archive', label: '자료보관함', path: '/archive', icon: Archive },
  { key: 'more', label: '전체', path: '/more', icon: Menu },
];

const FEATURE_TABS = TAB_ITEMS.filter((item) => item.path !== HOME_PATH && item.key !== 'more');

export function findActiveTabKey(pathname) {
  if (pathname === HOME_PATH) return 'home';

  const match = FEATURE_TABS.find(
    (item) => pathname === item.path || pathname.startsWith(`${item.path}/`)
  );

  return match ? match.key : 'more';
}
