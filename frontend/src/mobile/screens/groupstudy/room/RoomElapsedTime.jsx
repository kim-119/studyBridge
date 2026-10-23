import React, { useEffect, useState } from 'react';
import { formatRoomElapsed } from '../roomClock';

const TICK_MS = 1000;

function useNow(isActive) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!isActive) return undefined;

    const tick = () => setNow(Date.now());
    const timer = window.setInterval(tick, TICK_MS);
    document.addEventListener('visibilitychange', tick);
    tick();

    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', tick);
    };
  }, [isActive]);

  return now;
}

export default function RoomElapsedTime({ enteredAt }) {
  const isRunning = enteredAt != null;
  const now = useNow(isRunning);

  if (!isRunning) return null;

  const elapsed = formatRoomElapsed(enteredAt, now);

  return (
    <time className="mobile-room-header__timer" data-room-timer={elapsed} aria-label={`스터디 진행 시간 ${elapsed}`}>
      {elapsed}
    </time>
  );
}
