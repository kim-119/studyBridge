import { useEffect, useRef } from 'react';

export function useReloadWhenVisible(reload) {
  const latestReload = useRef(reload);
  latestReload.current = reload;

  useEffect(() => {
    const reloadIfVisible = () => {
      if (document.visibilityState === 'visible') latestReload.current().catch(() => {});
    };

    document.addEventListener('visibilitychange', reloadIfVisible);
    return () => document.removeEventListener('visibilitychange', reloadIfVisible);
  }, []);
}
