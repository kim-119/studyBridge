import test from 'node:test';
import assert from 'node:assert/strict';
import {
  DEVICE_TOGGLE,
  INITIAL_MEDIA_STATE,
  MEDIA_ACTION,
  MEDIA_PHASE,
  describeMediaStatus,
  mediaSessionReducer,
  planDeviceToggle,
  planLocalMedia,
  publishAttempts,
  resolvePermissionGrants,
  withoutCamera,
} from '../screens/groupstudy/mediaJoinModel.js';
import {
  buildLocalTile,
  buildParticipantTiles,
  describeStreamMedia,
  indexMemberPhotos,
} from '../screens/groupstudy/participantTileModel.js';

const ALL_GRANTED = { camera: true, microphone: true };

test('네이티브 권한 결과를 장치별 허용 여부로 나눈다', () => {
  assert.deepEqual(resolvePermissionGrants({ camera: 'granted', microphone: 'denied', granted: false }), {
    camera: true,
    microphone: false,
  });
  assert.deepEqual(resolvePermissionGrants({ granted: true }), ALL_GRANTED);
  assert.deepEqual(resolvePermissionGrants(null), { camera: false, microphone: false });
});

test('카메라·마이크 켬/끔 네 가지 조합 모두 입장 계획을 만든다', () => {
  const combos = [
    [true, true, { useCamera: true, useMicrophone: true, shouldPublish: true }],
    [true, false, { useCamera: true, useMicrophone: false, shouldPublish: true }],
    [false, true, { useCamera: false, useMicrophone: true, shouldPublish: true }],
    [false, false, { useCamera: false, useMicrophone: false, shouldPublish: false }],
  ];

  combos.forEach(([wantsCamera, wantsMicrophone, expected]) => {
    const plan = planLocalMedia({ wantsCamera, wantsMicrophone, grants: ALL_GRANTED });
    assert.deepEqual(
      { useCamera: plan.useCamera, useMicrophone: plan.useMicrophone, shouldPublish: plan.shouldPublish },
      expected
    );
    assert.equal(plan.notice, null);
  });
});

test('권한이 거부되어도 입장은 막지 않고 해당 장치만 끈 채 안내한다', () => {
  const plan = planLocalMedia({ wantsCamera: true, wantsMicrophone: true, grants: { camera: false, microphone: true } });
  assert.equal(plan.useCamera, false);
  assert.equal(plan.useMicrophone, true);
  assert.equal(plan.shouldPublish, true);
  assert.match(plan.notice, /카메라 권한이 없어/);

  const denied = planLocalMedia({ wantsCamera: true, wantsMicrophone: true, grants: { camera: false, microphone: false } });
  assert.equal(denied.shouldPublish, false);
  assert.match(denied.notice, /카메라와 마이크 권한이 없어/);
});

test('카메라를 열지 못하면 음성 전용으로 낮추고, 마이크도 없으면 보기 전용이 된다', () => {
  const audioOnly = withoutCamera(planLocalMedia({ wantsCamera: true, wantsMicrophone: true, grants: ALL_GRANTED }), '다른 앱이 사용 중입니다.');
  assert.equal(audioOnly.useCamera, false);
  assert.equal(audioOnly.shouldPublish, true);
  assert.match(audioOnly.notice, /카메라 없이 참여합니다/);

  const viewOnly = withoutCamera(planLocalMedia({ wantsCamera: true, wantsMicrophone: false, grants: ALL_GRANTED }), '실패');
  assert.equal(viewOnly.shouldPublish, false);
});

test('송출 실패 시 음성 전용, 영상 전용 순서로 다시 시도한다', () => {
  assert.deepEqual(publishAttempts({ useCamera: true, useMicrophone: true }), [
    { useCamera: true, useMicrophone: true },
    { useCamera: false, useMicrophone: true },
    { useCamera: true, useMicrophone: false },
  ]);
  assert.deepEqual(publishAttempts({ useCamera: false, useMicrophone: true }), [{ useCamera: false, useMicrophone: true }]);
  assert.deepEqual(publishAttempts({ useCamera: false, useMicrophone: false }), []);
});

test('장치 토글은 트랙이 있으면 음소거 전환, 없으면 다시 송출한다', () => {
  assert.equal(planDeviceToggle({ enable: false, hasPublisher: true, hasTrack: true }), DEVICE_TOGGLE.MUTE);
  assert.equal(planDeviceToggle({ enable: false, hasPublisher: false, hasTrack: false }), DEVICE_TOGGLE.NONE);
  assert.equal(planDeviceToggle({ enable: true, hasPublisher: true, hasTrack: true }), DEVICE_TOGGLE.UNMUTE);
  assert.equal(planDeviceToggle({ enable: true, hasPublisher: true, hasTrack: false }), DEVICE_TOGGLE.REPUBLISH);
  assert.equal(planDeviceToggle({ enable: true, hasPublisher: false, hasTrack: false }), DEVICE_TOGGLE.REPUBLISH);
});

test('화상 연결 상태 리듀서는 실패해도 안내만 바꾸고 방 상태와 분리된다', () => {
  let state = mediaSessionReducer(INITIAL_MEDIA_STATE, { type: MEDIA_ACTION.CONNECT_STARTED, isReconnect: false });
  assert.equal(state.phase, MEDIA_PHASE.CONNECTING);

  state = mediaSessionReducer(state, { type: MEDIA_ACTION.CONNECT_FAILED, message: '토큰 발급 실패' });
  assert.equal(state.phase, MEDIA_PHASE.FAILED);
  assert.match(describeMediaStatus(state), /화상 연결에 실패했습니다\. 토큰 발급 실패 채팅·AI·자료는 계속 사용할 수 있습니다\./);

  state = mediaSessionReducer(state, { type: MEDIA_ACTION.RECONNECT_SCHEDULED, attempt: 2 });
  assert.deepEqual([state.phase, state.reconnectAttempt], [MEDIA_PHASE.RECONNECTING, 2]);

  state = mediaSessionReducer(state, { type: MEDIA_ACTION.CONNECTED });
  assert.deepEqual([state.phase, state.errorMessage, state.reconnectAttempt], [MEDIA_PHASE.CONNECTED, null, 0]);
  assert.equal(describeMediaStatus(state), null);

  state = mediaSessionReducer(state, { type: MEDIA_ACTION.NOTICE_CHANGED, message: '마이크 권한 없음' });
  assert.equal(state.notice, '마이크 권한 없음');

  assert.deepEqual(mediaSessionReducer(state, { type: MEDIA_ACTION.LEFT }), INITIAL_MEDIA_STATE);
});

test('원격 스트림의 hasAudio/hasVideo와 active 값으로 카메라·마이크 상태를 정한다', () => {
  assert.deepEqual(describeStreamMedia(null), { cameraOn: false, micOn: false });
  assert.deepEqual(describeStreamMedia({ hasVideo: true, videoActive: true, hasAudio: true, audioActive: false }), {
    cameraOn: true,
    micOn: false,
  });
  assert.deepEqual(describeStreamMedia({ hasVideo: false, videoActive: true, hasAudio: true, audioActive: true }), {
    cameraOn: false,
    micOn: true,
  });
});

test('타일은 내 타일을 먼저 두고, 멤버 사진을 userId로 붙이며, 스트림이 없으면 꺼짐으로 표시한다', () => {
  const photos = indexMemberPhotos([
    { userId: 7, photoUrl: 'https://cdn.test/7.png' },
    { userId: 8, photoUrl: null },
  ]);
  const localTile = buildLocalTile({
    userId: 7,
    displayName: '나',
    photoUrl: photos.get('7'),
    publisher: null,
    isCameraOn: true,
    isMicrophoneOn: true,
  });

  const tiles = buildParticipantTiles({
    localTile,
    remoteParticipants: [
      { connectionId: 'c8', userId: 8, name: '친구', streamManager: null, cameraOn: true, micOn: true },
      { connectionId: 'c9', userId: 9, name: '동료', streamManager: {}, cameraOn: false, micOn: true },
    ],
    memberPhotos: photos,
  });

  assert.deepEqual(
    tiles.map((tile) => [tile.connectionId, tile.isMe, tile.photoUrl, tile.cameraOn, tile.micOn]),
    [
      ['local', true, 'https://cdn.test/7.png', false, false],
      ['c8', false, null, false, false],
      ['c9', false, null, false, true],
    ]
  );
});

test('내 송출이 음성 전용이면 내 타일은 카메라 꺼짐, 마이크 켜짐으로 보인다', () => {
  const publisher = { stream: { hasVideo: false, videoActive: false, hasAudio: true, audioActive: true } };
  const tile = buildLocalTile({ userId: 7, displayName: '나', publisher, isCameraOn: false, isMicrophoneOn: true });
  assert.deepEqual([tile.cameraOn, tile.micOn, tile.streamManager], [false, true, publisher]);
});
