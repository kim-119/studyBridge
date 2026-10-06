import { useCallback, useEffect, useLayoutEffect, useRef } from 'react';

const NEAR_BOTTOM_PX = 96;

function distanceFromBottom(element) {
  return element.scrollHeight - element.scrollTop - element.clientHeight;
}

export function useStickToBottom(contentVersion, isEnabled) {
  const containerRef = useRef(null);
  const isPinnedRef = useRef(true);
  const isEnabledRef = useRef(isEnabled);
  isEnabledRef.current = isEnabled;

  const scrollToBottom = useCallback(() => {
    const element = containerRef.current;
    if (!element || !isEnabledRef.current) return;
    element.scrollTop = element.scrollHeight;
    isPinnedRef.current = true;
  }, []);

  const handleScroll = useCallback(() => {
    const element = containerRef.current;
    if (element && isEnabledRef.current) isPinnedRef.current = distanceFromBottom(element) < NEAR_BOTTOM_PX;
  }, []);

  useLayoutEffect(() => {
    if (isEnabled) isPinnedRef.current = true;
  }, [isEnabled]);

  useLayoutEffect(() => {
    if (isPinnedRef.current) scrollToBottom();
  }, [contentVersion, isEnabled, scrollToBottom]);

  useEffect(() => {
    const element = containerRef.current;
    if (!element || typeof ResizeObserver === 'undefined') return undefined;

    const observer = new ResizeObserver(() => {
      if (isPinnedRef.current) scrollToBottom();
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [scrollToBottom]);

  return { containerRef, handleScroll, scrollToBottom };
}
