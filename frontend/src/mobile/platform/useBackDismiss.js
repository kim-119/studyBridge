import { useEffect, useRef } from 'react';
import { pushBackDismiss } from './backDismissStack';

export function useBackDismiss(isActive, onDismiss) {
  const latestOnDismiss = useRef(onDismiss);
  latestOnDismiss.current = onDismiss;

  useEffect(() => {
    if (!isActive) return undefined;
    return pushBackDismiss(() => latestOnDismiss.current());
  }, [isActive]);
}
