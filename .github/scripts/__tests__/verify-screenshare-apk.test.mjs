// 화면공유 APK 검증 스크립트의 매니페스트 판정 테스트(SDK 없이 실행).
//   node --test .github/scripts/__tests__/verify-screenshare-apk.test.mjs
// 픽스처는 CI 가 만든 실제 app-debug.apk 의 binary 매니페스트를 aapt2 dump xmltree 형식으로 옮긴 것이다.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SCRIPT = path.resolve(HERE, '../verify-screenshare-apk.sh');
const REAL_DUMP = readFileSync(path.join(HERE, 'fixtures/screenshare-manifest.aapt2.txt'), 'utf8');
const FGS = 'foregroundServiceType(0x01010599)=0x00000020';
const work = mkdtempSync(path.join(tmpdir(), 'verify-screenshare-'));

function check(dump, name = 'manifest.txt') {
  const file = path.join(work, name);
  writeFileSync(file, dump);
  const result = spawnSync('bash', [SCRIPT, '--check-manifest-dump', file], { encoding: 'utf8' });
  return { code: result.status, output: `${result.stdout}${result.stderr}` };
}

function checkMerged(xml) {
  const file = path.join(work, 'AndroidManifest.xml');
  writeFileSync(file, xml);
  const result = spawnSync('bash', [SCRIPT, '--check-merged-manifest', file], { encoding: 'utf8' });
  return { code: result.status, output: `${result.stdout}${result.stderr}` };
}

test('실제 APK 매니페스트: aapt2 의 0x%08x 형식(0x00000020)을 mediaProjection 으로 인정한다', () => {
  assert.ok(REAL_DUMP.includes(FGS), '픽스처에 실제 aapt2 형식 값이 있어야 한다');
  const result = check(REAL_DUMP);
  assert.equal(result.code, 0, result.output);
  assert.match(result.output, /foregroundServiceType=0x00000020\(mediaProjection\) exported=false/);
});

test('수정 전 정규식은 같은 실제 값을 거부했다(CI 실패 재현)', () => {
  const before = /foregroundServiceType\(0x[0-9a-f]+\)=(32|0x20|mediaProjection)/;
  assert.equal(before.test(REAL_DUMP), false);
});

test('10진(32)·결합 플래그(mediaProjection|camera = 0x60)도 인정한다', () => {
  assert.equal(check(REAL_DUMP.replace(FGS, 'foregroundServiceType(0x01010599)=32')).code, 0);
  assert.equal(check(REAL_DUMP.replace(FGS, 'foregroundServiceType(0x01010599)=0x00000060')).code, 0);
});

test('mediaProjection 비트가 없으면(camera 0x40) 실패한다', () => {
  const result = check(REAL_DUMP.replace(FGS, 'foregroundServiceType(0x01010599)=0x00000040'));
  assert.equal(result.code, 1);
  assert.match(result.output, /mediaProjection\(0x20\)이 없습니다: 0x00000040/);
});

test('foregroundServiceType 이 없으면 실패한다', () => {
  const lines = REAL_DUMP.split('\n').filter((line) => !line.includes('foregroundServiceType'));
  const result = check(lines.join('\n'));
  assert.equal(result.code, 1);
  assert.match(result.output, /foregroundServiceType 이 없습니다/);
});

test('다른 서비스의 mediaProjection 으로 ScreenShareService 를 통과시키지 않는다(요소 범위 확인)', () => {
  const withoutType = REAL_DUMP.split('\n').filter((line) => !line.includes('foregroundServiceType')).join('\n');
  const otherService = [
    '    E: service (line=90)',
    '      A: http://schemas.android.com/apk/res/android:name(0x01010003)="com.example.OtherService" (Raw: "com.example.OtherService")',
    `      A: http://schemas.android.com/apk/res/android:${FGS}`,
  ].join('\n');
  const dump = withoutType.replace('    E: activity', `${otherService}\n    E: activity`);
  assert.ok(dump.includes('com.example.OtherService'));
  const result = check(dump);
  assert.equal(result.code, 1, result.output);
});

test('ScreenShareService 가 없거나 exported=true 이면 실패한다', () => {
  assert.equal(check(REAL_DUMP.replaceAll('kr.co.studybridge.screenshare.ScreenShareService', 'kr.co.studybridge.Other')).code, 1);
  const exported = check(REAL_DUMP.replace('android:exported(0x01010010)=false\n      A: http://schemas.android.com/apk/res/android:stopWithTask', 'android:exported(0x01010010)=true\n      A: http://schemas.android.com/apk/res/android:stopWithTask'));
  assert.equal(exported.code, 1);
  assert.match(exported.output, /exported=false/);
});

test('필수 권한이 빠지면 실패한다', () => {
  const result = check(REAL_DUMP.replaceAll('android.permission.FOREGROUND_SERVICE_MEDIA_PROJECTION', 'android.permission.X'));
  assert.equal(result.code, 1);
  assert.match(result.output, /FOREGROUND_SERVICE_MEDIA_PROJECTION/);
});

test('libwebrtc 가 요구하는 ACCESS_NETWORK_STATE 가 빠지면 실패한다(없으면 네이티브 SIGABRT)', () => {
  const result = check(REAL_DUMP.replaceAll('android.permission.ACCESS_NETWORK_STATE', 'android.permission.X'));
  assert.equal(result.code, 1);
  assert.match(result.output, /ACCESS_NETWORK_STATE/);
});

test('Gradle 병합 매니페스트(텍스트)에서도 서비스와 mediaProjection 을 확인한다', () => {
  const merged = `<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="kr.co.studybridge.app">
    <application>
        <service
            android:name="kr.co.studybridge.screenshare.ScreenShareService"
            android:exported="false"
            android:foregroundServiceType="mediaProjection"
            android:stopWithTask="true" />
    </application>
</manifest>`;
  assert.equal(checkMerged(merged).code, 0, checkMerged(merged).output);
  assert.equal(checkMerged(merged.replace('mediaProjection', 'camera')).code, 1);
  assert.equal(checkMerged(merged.replace('ScreenShareService', 'OtherService')).code, 1);
});
