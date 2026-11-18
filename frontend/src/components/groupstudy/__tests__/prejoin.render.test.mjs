// node --test frontend/src/components/groupstudy/__tests__
//  vitest/jsdom 미도입 → esbuild(vite 의존성)로 JSX 를 번들한 뒤 react-dom/server 로 정적 렌더해 DOM 구조를 단언한다.
//  (effect 는 실행되지 않으므로 getUserMedia 호출 정책은 utils 테스트(buildMicConstraints 등)와 소스 가드 테스트로 검증)
import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(__dirname, '../../../..');
const require = createRequire(path.join(frontendRoot, 'package.json'));
const esbuild = require('esbuild');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');

// 번들 출력은 frontend/node_modules/.cache 아래(react 등 external 을 같은 node_modules 에서 해석하기 위함. git 미추적).
const cacheRoot = path.join(frontendRoot, 'node_modules', '.cache');
fs.mkdirSync(cacheRoot, { recursive: true });
const outDir = fs.mkdtempSync(path.join(cacheRoot, 'sb-prejoin-test-'));
test.after(() => { try { fs.rmSync(outDir, { recursive: true, force: true }); } catch (e) { /* ignore */ } });
async function load(relPath) {
  const outfile = path.join(outDir, relPath.replace(/[\\/]/g, '_') + '.mjs');
  await esbuild.build({
    entryPoints: [path.join(frontendRoot, 'src', relPath)],
    bundle: true, format: 'esm', platform: 'node', outfile, jsx: 'automatic', logLevel: 'silent',
    external: ['react', 'react-dom', 'react/jsx-runtime', 'lucide-react'],
  });
  return import(pathToFileURL(outfile).href);
}

const html = (el) => renderToStaticMarkup(el);
const has = (markup, testid) => markup.includes(`data-testid="${testid}"`);

const noop = () => {};
const micProps = { isMicOn: true, micStatus: 'available', micLevel: 0, onToggle: noop, mics: [{ deviceId: 'm1', label: 'USB Mic' }], selectedMic: 'm1', onSelectMic: noop, showDeviceSelector: true };
const navProps = { isLeader: true, showInfo: false, showSettings: true, showLeaderConsole: false, onInfo: noop, onLeaderConsole: noop, onSettings: noop };
const generalProps = {
  avatar: { kind: 'default', url: null }, displayName: '김도현',
  profile: { mode: 'default', emoji: null, profilePhotoUrl: null, uploadedFileName: null, onSelectMode: noop, onSelectEmoji: noop, onPickFile: noop, onError: noop },
  mic: micProps, nav: navProps,
};
const camProps = {
  camera: { videoRef: { current: null }, isVideoOn: true, cameraStatus: 'available', camError: '', photoUrl: null, onToggle: noop, onRetry: noop, onUseDefaultCamera: noop, onEnterWithoutCamera: noop },
  mic: { ...micProps },
  devices: { show: true, cameras: [{ deviceId: 'c1', label: 'FaceTime' }], selectedCamera: 'c1', onCameraChange: noop },
  nav: navProps,
};

test('GENERAL prejoin renders AvatarPreview/ProfileSelector/MicrophoneToggle/MicrophoneDeviceSelector and no camera UI', async () => {
  const { default: PreJoinMediaPanel } = await load('components/groupstudy/prejoin/PreJoinMediaPanel.jsx');
  const m = html(React.createElement(PreJoinMediaPanel, { studyType: 'GENERAL', general: generalProps, cam: camProps }));
  assert.ok(has(m, 'prejoin-panel-general'));
  assert.ok(has(m, 'prejoin-avatar-preview'));
  assert.ok(has(m, 'prejoin-profile-selector'));
  assert.ok(has(m, 'prejoin-mic-toggle'));
  assert.ok(has(m, 'prejoin-mic-device-selector'));
  assert.ok(m.includes('김도현'));
  assert.ok(m.includes('마이크 켜짐'));
  // 카메라 요소 금지: preview / 검은 영상 박스 / video tile / 카메라 토글 / 카메라 device selector
  assert.equal(has(m, 'prejoin-camera-preview'), false);
  assert.equal(has(m, 'prejoin-camera-toggle'), false);
  assert.equal(has(m, 'prejoin-camera-device-selector'), false);
  assert.equal(has(m, 'prejoin-device-settings'), false);
  assert.equal(m.includes('<video'), false);
  assert.equal(m.includes('카메라'), false);
  // 프로필 업로드 input 은 PNG/JPG/JPEG/WEBP 만
  assert.ok(m.includes('accept="image/png,image/jpeg,image/webp,.png,.jpg,.jpeg,.webp"'));
  // 마이크 장치 선택 현재값 표시
  assert.ok(m.includes('선택: USB Mic'));
});

test('GENERAL prejoin: avatar priority rendering (image vs default) and mic 꺼짐/없음 states', async () => {
  const { default: GeneralPreJoinPanel } = await load('components/groupstudy/prejoin/GeneralPreJoinPanel.jsx');
  let m = html(React.createElement(GeneralPreJoinPanel, { ...generalProps, avatar: { kind: 'image', url: 'https://s3/u.png' } }));
  assert.ok(m.includes('src="https://s3/u.png"'));
  assert.equal(has(m, 'default-avatar'), false);
  m = html(React.createElement(GeneralPreJoinPanel, { ...generalProps, avatar: { kind: 'default', url: null } }));
  assert.ok(has(m, 'default-avatar'));
  m = html(React.createElement(GeneralPreJoinPanel, { ...generalProps, mic: { ...micProps, isMicOn: false } }));
  assert.ok(m.includes('마이크 꺼짐'));
  m = html(React.createElement(GeneralPreJoinPanel, { ...generalProps, mic: { ...micProps, micStatus: 'unavailable', mics: [] } }));
  assert.ok(m.includes('마이크 없음'));
  assert.ok(m.includes('연결된 마이크 없음'));
});

test('CAM prejoin renders CameraPreview/CameraToggle/MicrophoneToggle/DeviceSettings (existing video features)', async () => {
  const { default: PreJoinMediaPanel } = await load('components/groupstudy/prejoin/PreJoinMediaPanel.jsx');
  const m = html(React.createElement(PreJoinMediaPanel, { studyType: 'CAM', general: generalProps, cam: camProps }));
  assert.ok(has(m, 'prejoin-panel-cam'));
  assert.ok(has(m, 'prejoin-camera-preview'));
  assert.ok(has(m, 'prejoin-camera-video'));
  assert.ok(m.includes('<video'));
  assert.ok(has(m, 'prejoin-camera-toggle'));
  assert.ok(has(m, 'prejoin-mic-toggle'));
  assert.ok(has(m, 'prejoin-device-settings'));
  assert.ok(has(m, 'prejoin-camera-device-selector'));
  assert.ok(has(m, 'prejoin-mic-device-selector'));
  assert.ok(m.includes('FaceTime'));
  assert.equal(has(m, 'prejoin-avatar-preview'), false);
  assert.equal(has(m, 'prejoin-profile-selector'), false);
});

test('unknown/missing studyType falls back to GENERAL (server enum only has GENERAL/CAM)', async () => {
  const { default: PreJoinMediaPanel } = await load('components/groupstudy/prejoin/PreJoinMediaPanel.jsx');
  const m = html(React.createElement(PreJoinMediaPanel, { studyType: undefined, general: generalProps, cam: camProps }));
  assert.ok(has(m, 'prejoin-panel-general'));
  assert.equal(has(m, 'prejoin-camera-preview'), false);
});

test('PendingMemberSection renders list + approve/reject; GENERAL participant tile shows avatar/name/mic state without video', async () => {
  const { default: PendingMemberSection } = await load('components/groupstudy/PendingMemberSection.jsx');
  let m = html(React.createElement(PendingMemberSection, { applications: [{ applicationId: 1, applicantName: '신청자', introduction: '열심히', createdAt: '2026-10-07T00:00:00' }] }));
  assert.ok(has(m, 'pending-member-section'));
  assert.ok(m.includes('가입 신청 대기자 명단 (1)'));
  assert.ok(m.includes('승인') && m.includes('거절'));

  const { default: ProfileParticipantTile } = await load('components/groupstudy/ProfileParticipantTile.jsx');
  m = html(React.createElement(ProfileParticipantTile, { avatar: { kind: 'image', url: 'https://s3/p.png' }, displayName: '김도현', isLocal: false, isMicOn: true, stream: null, streamManager: null, speakerId: 7 }));
  assert.ok(has(m, 'profile-participant-tile'));
  assert.ok(m.includes('src="https://s3/p.png"'));
  assert.ok(m.includes('김도현'));
  assert.ok(m.includes('data-mic-on="true"'));
  assert.equal(m.includes('<video'), false); // streamManager 없음 → 오디오 싱크도 없음, 카메라 tile 없음
  m = html(React.createElement(ProfileParticipantTile, { avatar: { kind: 'default', url: null }, displayName: '김도현', isLocal: true, isMicOn: false, stream: null, streamManager: null, speakerId: 7 }));
  assert.ok(has(m, 'default-avatar'));
  assert.ok(m.includes('data-mic-on="false"'));
  assert.ok(m.includes('OFF'));
});

test('source guard: GENERAL code paths never request video — prejoin camera effect is gated by isCamStudy and StudyRoom ladder is audio-only', () => {
  const groupStudy = fs.readFileSync(path.join(frontendRoot, 'src/pages/GroupStudy.jsx'), 'utf8');
  // 카메라 프리뷰 effect 는 CAM 에서만 getUserMedia(video) 를 호출한다.
  assert.ok(groupStudy.includes("if (!isCamStudy(preJoinStudy.studyType)) {\n      setCameraStatus('off');"));
  assert.ok(groupStudy.includes('navigator.mediaDevices.getUserMedia(buildMicConstraints(selectedMic))'));
  assert.ok(groupStudy.includes('navigator.mediaDevices.getUserMedia(constraints)')); // CAM: buildCameraPreviewConstraints
  assert.equal(/getUserMedia\(\{\s*audio:\s*true,\s*video:\s*true/.test(groupStudy), false);
  const studyRoom = fs.readFileSync(path.join(frontendRoot, 'src/components/StudyRoom.jsx'), 'utf8');
  assert.ok(studyRoom.includes('let hasAnyVideo = isCam;'));
  assert.ok(studyRoom.includes('if (!isCam) videoDeviceId = undefined;'));
  assert.ok(studyRoom.includes("if (isCam && hasHandoff && hasAnyVideo && isVideoOn !== false) {"));
  assert.ok(studyRoom.includes(': [{ publishVideo: false, tag: \'audio-only\' }];'));
  assert.ok(studyRoom.includes('if (!isCam) {') && studyRoom.includes('<ProfileParticipantTile'));
});

test('GENERAL profile picker: 아이콘 선택/이미지 업로드 buttons, emoji preview replaces UserRound fallback, image preview, tile emoji', async () => {
  const { default: GeneralPreJoinPanel } = await load('components/groupstudy/prejoin/GeneralPreJoinPanel.jsx');
  let m = html(React.createElement(GeneralPreJoinPanel, generalProps));
  assert.ok(has(m, 'prejoin-emoji-button') && m.includes('아이콘 선택'));
  assert.ok(has(m, 'prejoin-upload-button') && m.includes('이미지 업로드'));
  assert.equal(m.includes('기본 아이콘'), false);
  assert.ok(has(m, 'default-avatar')); // 아무것도 선택 안 함 → UserRound fallback
  assert.ok(m.includes('lucide-user-round') || m.includes('user-round'));
  // 이모지 선택 → fallback 제거, 이모지 렌더
  m = html(React.createElement(GeneralPreJoinPanel, { ...generalProps, avatar: { kind: 'emoji', value: '🐰', url: null }, profile: { ...generalProps.profile, mode: 'emoji', emoji: '🐰' } }));
  assert.ok(has(m, 'prejoin-avatar-emoji') && m.includes('🐰'));
  assert.equal(has(m, 'default-avatar'), false);
  assert.ok(m.includes('data-avatar-kind="emoji"'));
  // 이미지 선택 → 이미지 렌더
  m = html(React.createElement(GeneralPreJoinPanel, { ...generalProps, avatar: { kind: 'image', url: 'https://s3/u.png' }, profile: { ...generalProps.profile, mode: 'upload', uploadedFileName: 'u.png' } }));
  assert.ok(m.includes('src="https://s3/u.png"') && !has(m, 'prejoin-avatar-emoji'));
  // 룸 참가자 타일도 동일 이모지
  const { default: ProfileParticipantTile } = await load('components/groupstudy/ProfileParticipantTile.jsx');
  m = html(React.createElement(ProfileParticipantTile, { avatar: { kind: 'emoji', value: '🐼', url: null }, displayName: '김도현', isLocal: false, isMicOn: true, stream: null, streamManager: null, speakerId: 1 }));
  assert.ok(has(m, 'profile-participant-emoji') && m.includes('🐼') && m.includes('data-avatar-kind="emoji"'));
  assert.equal(m.includes('<video'), false);
});

test('EmojiProfilePicker renders 30+ equal grid options with selected state (border/background/check)', async () => {
  const { default: EmojiProfilePicker } = await load('components/groupstudy/prejoin/EmojiProfilePicker.jsx');
  const m = html(React.createElement(EmojiProfilePicker, { value: '🐰', onSelect: noop, onClose: noop }));
  const options = (m.match(/data-testid="emoji-option"/g) || []).length;
  assert.ok(options >= 30, `options=${options}`);
  assert.equal((m.match(/data-selected="true"/g) || []).length, 1);
  assert.ok(/data-emoji="🐰"[^>]*data-selected="true"[^>]*class="sb-emoji-option is-selected"/.test(m));
  assert.ok(m.includes('선택됨')); // Check 배지
  assert.ok(m.includes('선택 완료') && m.includes('aria-label="닫기"'));
  assert.ok(has(m, 'emoji-profile-picker'));
});
