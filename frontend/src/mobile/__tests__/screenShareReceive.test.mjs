import test from 'node:test';
import assert from 'node:assert/strict';
import { CONNECTION_KIND, parseConnectionIdentity } from '../screens/groupstudy/connectionIdentity.js';
import { importMobileModule, registerComponentLoader } from './support/componentHarness.mjs';

registerComponentLoader();

const {
  describeStreamMedia,
  buildParticipantTiles,
  buildLocalTile,
  countDistinctParticipants,
  resolveVideoKind,
  VIDEO_KIND,
} = await importMobileModule('screens/groupstudy/participantTileModel.js');

test('typeOfVideo=SCREEN 스트림은 화면공유로 식별하고 카메라와 분리한다', () => {
  const media = describeStreamMedia({
    streamId: 'screen-1',
    typeOfVideo: 'SCREEN',
    hasVideo: true,
    videoActive: true,
    hasAudio: false,
    audioActive: false,
  });
  assert.equal(media.videoKind, VIDEO_KIND.SCREEN);
  assert.equal(media.screenOn, true);
  assert.equal(media.cameraOn, false);
  assert.equal(media.streamId, 'screen-1');
});

test('카메라 스트림은 screenOn=false, videoKind=CAMERA 로 식별한다', () => {
  const media = describeStreamMedia({
    streamId: 'cam-1',
    typeOfVideo: 'CAMERA',
    hasVideo: true,
    videoActive: true,
    hasAudio: true,
    audioActive: true,
  });
  assert.equal(media.videoKind, VIDEO_KIND.CAMERA);
  assert.equal(media.cameraOn, true);
  assert.equal(media.screenOn, false);
});

test('resolveVideoKind 는 대소문자와 누락을 안전하게 처리한다', () => {
  assert.equal(resolveVideoKind({ typeOfVideo: 'screen' }), VIDEO_KIND.SCREEN);
  assert.equal(resolveVideoKind({ typeOfVideo: 'CUSTOM' }), VIDEO_KIND.CAMERA);
  assert.equal(resolveVideoKind({}), VIDEO_KIND.CAMERA);
  assert.equal(resolveVideoKind(null), VIDEO_KIND.CAMERA);
});

test('같은 사용자의 카메라와 화면공유는 서로 덮어쓰지 않고 독립 타일로 나온다', () => {
  const localTile = buildLocalTile({ userId: 1, displayName: '나', publisher: null, isCameraOn: false, isMicrophoneOn: false });
  const tiles = buildParticipantTiles({
    localTile,
    remoteParticipants: [
      // 사용자 3의 카메라 연결
      { connectionId: 'c3-cam', userId: 3, name: '동료', streamManager: {}, videoKind: 'CAMERA', cameraOn: true, screenOn: false, micOn: true },
      // 사용자 3의 화면공유 연결(별도 Connection)
      { connectionId: 'c3-screen', userId: 3, name: '동료', streamManager: {}, videoKind: 'SCREEN', cameraOn: false, screenOn: true, micOn: false },
    ],
    memberPhotos: new Map(),
  });

  const cam = tiles.find((t) => t.connectionId === 'c3-cam');
  const screen = tiles.find((t) => t.connectionId === 'c3-screen');

  assert.ok(cam && screen, '카메라와 화면공유 타일이 모두 존재해야 한다');
  assert.equal(cam.isScreenShare, false);
  assert.equal(cam.cameraOn, true);
  assert.equal(cam.screenOn, false);
  assert.equal(screen.isScreenShare, true);
  assert.equal(screen.screenOn, true);
  assert.equal(screen.cameraOn, false);
});

test('화면공유 연결은 참여 인원 수에 포함하지 않는다', () => {
  const tiles = [
    { connectionId: 'local', userId: 1, isScreenShare: false },
    { connectionId: 'c3-cam', userId: 3, isScreenShare: false },
    { connectionId: 'c3-screen', userId: 3, isScreenShare: true },
  ];
  // 사용자 1, 3 → 2명. 화면공유 연결은 세지 않는다.
  assert.equal(countDistinctParticipants(tiles), 2);
});

test('화면공유 타일도 streamManager 가 없으면 영상 꺼짐으로 처리한다', () => {
  const localTile = buildLocalTile({ userId: 1, displayName: '나', publisher: null, isCameraOn: false, isMicrophoneOn: false });
  const tiles = buildParticipantTiles({
    localTile,
    remoteParticipants: [
      { connectionId: 'c9-screen', userId: 9, name: '공유중', streamManager: null, videoKind: 'SCREEN', screenOn: true },
    ],
    memberPhotos: new Map(),
  });
  const screen = tiles.find((t) => t.connectionId === 'c9-screen');
  assert.equal(screen.isScreenShare, true);
  assert.equal(screen.screenOn, false);
});

const serverData = (overrides = {}) =>
  JSON.stringify({ v: 1, app: 'studybridge', groupId: 51, userId: 7, kind: 'PRIMARY', ...overrides });
const clientData = (overrides = {}) => JSON.stringify({ userId: '7', clientData: '김민서', ...overrides });

test('연결 신원은 서버 serverData(마지막 세그먼트)를 신뢰하고 clientData 위조를 무시한다', () => {
  const forged = `${clientData({ userId: '999' })}%/%${serverData({ userId: 7 })}`;
  const identity = parseConnectionIdentity({ data: forged });
  assert.equal(identity.verified, true);
  assert.equal(identity.userId, '7');
  assert.equal(identity.name, '김민서');
  assert.equal(identity.kind, CONNECTION_KIND.PRIMARY);
});

test('serverData 가 없는 레거시 연결은 clientData 로 표시만 하고 PRIMARY 로 본다', () => {
  const identity = parseConnectionIdentity({ data: clientData({ kind: 'SCREEN' }) });
  assert.equal(identity.verified, false);
  assert.equal(identity.userId, '7');
  assert.equal(identity.kind, CONNECTION_KIND.PRIMARY, 'clientData 의 kind 는 신뢰하지 않는다');
  assert.equal(parseConnectionIdentity(null).userId, null);
  assert.equal(parseConnectionIdentity({ data: 'not json' }).verified, false);
});

test('단일 SCREEN 판정: 서버 SCREEN 연결은 typeOfVideo 가 CUSTOM 이어도 화면공유다(네이티브 송출)', () => {
  const screen = parseConnectionIdentity({
    data: `${clientData()}%/%${serverData({ kind: 'SCREEN', ownerConnectionId: 'con_primary' })}`,
  });
  assert.equal(screen.ownerConnectionId, 'con_primary');
  assert.equal(resolveVideoKind({ typeOfVideo: 'CUSTOM' }, screen), VIDEO_KIND.SCREEN);
  assert.equal(resolveVideoKind({ typeOfVideo: 'SCREEN' }, screen), VIDEO_KIND.SCREEN);

  const media = describeStreamMedia({ typeOfVideo: 'CUSTOM', hasVideo: true, videoActive: true }, screen);
  assert.equal(media.screenOn, true);
  assert.equal(media.cameraOn, false);
});

test('단일 SCREEN 판정: PRIMARY·레거시는 typeOfVideo=SCREEN 일 때만 화면공유, CUSTOM/IPCAM 은 카메라', () => {
  const primary = parseConnectionIdentity({ data: `${clientData()}%/%${serverData()}` });
  assert.equal(resolveVideoKind({ typeOfVideo: 'CAMERA' }, primary), VIDEO_KIND.CAMERA);
  assert.equal(resolveVideoKind({ typeOfVideo: 'CUSTOM' }, primary), VIDEO_KIND.CAMERA);
  assert.equal(resolveVideoKind({ typeOfVideo: 'IPCAM' }, primary), VIDEO_KIND.CAMERA);
  assert.equal(resolveVideoKind({ typeOfVideo: 'SCREEN' }, null), VIDEO_KIND.SCREEN, '레거시 PC 화면공유 수신 유지');
});
