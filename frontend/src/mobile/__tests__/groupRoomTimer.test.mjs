import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { elapsedSecondsSince, enterRoomClock, formatRoomElapsed } from '../screens/groupstudy/roomClock.js';

function source(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8');
}

test('T5 방에 입장하면 입장 시각을 기준으로 타이머가 시작된다', () => {
  const clock = enterRoomClock(null, 1_000);

  assert.deepEqual(clock, { enteredAt: 1_000 });
  assert.equal(formatRoomElapsed(clock.enteredAt, 1_000), '00:00:00');
  assert.equal(formatRoomElapsed(clock.enteredAt, 2_000), '00:00:01');
  assert.match(source('../screens/groupstudy/VideoSessionScreen.jsx'), /setRoomClock\(\(clock\) => enterRoomClock\(clock, Date\.now\(\)\)\)/);
});

test('T6 방 제목 옆에 경과 시간을 표시한다', () => {
  const header = source('../screens/groupstudy/room/RoomHeader.jsx');

  assert.match(header, /<h1>\{title\}<\/h1>\s*<RoomElapsedTime enteredAt=\{enteredAt\} \/>/);
  assert.equal(formatRoomElapsed(0, 3_000), '00:00:03');
});

test('T7 같은 방에서 다시 렌더링되거나 입장 처리가 반복돼도 0초로 돌아가지 않는다', () => {
  const firstEntry = enterRoomClock(null, 10_000);
  const repeatedEntry = enterRoomClock(firstEntry, 50_000);

  assert.equal(repeatedEntry, firstEntry);
  assert.equal(formatRoomElapsed(repeatedEntry.enteredAt, 70_000), '00:01:00');
});

test('T8 멤버 관리(그룹 상세) 화면에는 타이머가 없다', () => {
  const detailScreen = source('../screens/groupstudy/GroupDetailScreen.jsx');
  const participantsPanel = source('../screens/groupstudy/room/ParticipantsPanel.jsx');

  assert.doesNotMatch(detailScreen, /Timer|timerService/);
  assert.doesNotMatch(participantsPanel, /Timer|timerService/);
  assert.equal(existsSync(new URL('../screens/groupstudy/StudyTimerCard.jsx', import.meta.url)), false);
});

test('T9 백그라운드에서 틱이 멈춰도 복귀 시 실제 경과 시간으로 계산한다', () => {
  const enteredAt = Date.UTC(2026, 8, 28, 9, 0, 0);
  const afterBackground = enteredAt + (1 * 3600 + 2 * 60 + 5) * 1000;

  assert.equal(elapsedSecondsSince(enteredAt, afterBackground), 3725);
  assert.equal(formatRoomElapsed(enteredAt, afterBackground), '01:02:05');
  assert.equal(elapsedSecondsSince(enteredAt, enteredAt - 5_000), 0);
  assert.equal(elapsedSecondsSince(null, afterBackground), 0);
});
