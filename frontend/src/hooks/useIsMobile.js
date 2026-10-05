import { useEffect, useState } from 'react';

// 모바일 웹 공통 breakpoint(index.css 의 @media (max-width: 768px) 와 동일 기준).
// 웹 반응형 presentation 전용 훅 — Capacitor/네이티브 API 와 무관하게 matchMedia 만 사용한다.
export const MOBILE_MEDIA_QUERY = '(max-width: 768px)';

export function useIsMobile(query = MOBILE_MEDIA_QUERY) {
  const getMatch = () => typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    ? window.matchMedia(query).matches
    : false;
  const [isMobile, setIsMobile] = useState(getMatch);

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return undefined;
    const mql = window.matchMedia(query);
    const onChange = (e) => setIsMobile(e.matches);
    setIsMobile(mql.matches);
    if (typeof mql.addEventListener === 'function') {
      mql.addEventListener('change', onChange);
      return () => mql.removeEventListener('change', onChange);
    }
    mql.addListener(onChange);
    return () => mql.removeListener(onChange);
  }, [query]);

  return isMobile;
}

export default useIsMobile;
