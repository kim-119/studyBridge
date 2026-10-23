import { formatElapsed } from './groupStudyModel.js';

export function enterRoomClock(clock, now) {
  if (clock?.enteredAt != null) return clock;
  return { enteredAt: now };
}

export function elapsedSecondsSince(enteredAt, now) {
  if (enteredAt == null) return 0;
  return Math.max(0, Math.floor((now - enteredAt) / 1000));
}

export function formatRoomElapsed(enteredAt, now) {
  return formatElapsed(elapsedSecondsSince(enteredAt, now));
}
