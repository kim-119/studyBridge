// 릴리스 노트 검증기 테스트. 화면과 같은 필터를 써야 의미가 있으므로 APP_RELEASE_JS(LLM-clean appRelease.js 사본) 가 필수다.
//   git show origin/LLM-clean:frontend/src/utils/appRelease.js > /tmp/appRelease.mjs
//   APP_RELEASE_JS=/tmp/appRelease.mjs node --test .github/scripts/__tests__/validate-release-notes.test.mjs
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { test } from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { parseNotesText, readNotesDir, readPrevious, validateReleaseNotes } from '../validate-release-notes.mjs';

const FILTER = process.env.APP_RELEASE_JS;
assert.ok(FILTER, 'APP_RELEASE_JS(화면 필터 appRelease.js 경로)가 필요합니다');
const { toUserReleaseNotes } = await import(pathToFileURL(path.resolve(FILTER)).href);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '../../..');
const CLI = path.join(ROOT, '.github/scripts/validate-release-notes.mjs');
const DIR = path.join(ROOT, 'android/release-notes');

const run = (lines, extra = {}) => validateReleaseNotes({ version: '1.4', lines, previous: null, toUserReleaseNotes, ...extra });
const codes = (r) => r.errors.map((e) => e.code);

test('정상 한국어 노트 1개 통과, 화면 표시 문장 그대로', () => {
  const r = run(['화면공유 개선: PC에서 공유한 화면을 앱에서 볼 수 있습니다.']);
  assert.equal(r.ok, true, JSON.stringify(r.errors));
  assert.deepEqual(r.notes, ['화면공유 개선: PC에서 공유한 화면을 앱에서 볼 수 있습니다.']);
  assert.equal(toUserReleaseNotes(r.notes).length, 1);
});

test('복수 항목 — 제목 없는 문장 포함', () => {
  const r = run(['그룹 개선: 참여자 정보를 한눈에 볼 수 있습니다.', '앱 안정성 개선: 화면 전환 중 멈추던 문제를 고쳤습니다.', '로그인 화면 문구를 다듬었습니다.']);
  assert.equal(r.ok, true, JSON.stringify(r.errors));
  assert.equal(toUserReleaseNotes(r.notes).length, 3);
});

test('파일 없음 → NOTES_MISSING (커밋 제목으로 대신 채우지 않음)', () => {
  const r = run(null);
  assert.equal(r.ok, false);
  assert.deepEqual(codes(r), ['NOTES_MISSING']);
});

test('빈 노트(주석·빈 줄만) → NOTES_EMPTY', () => {
  const r = run(parseNotesText('# 작성 안내\n\n   \n# 끝\n'));
  assert.deepEqual(codes(r), ['NOTES_EMPTY']);
});

test('개발용 커밋 메시지 → 화면에서 숨겨지므로 차단', () => {
  for (const msg of ['feat(android): 랭킹 탭 추가', 'WIP: preserve Android PDF quiz ranking', 'Merge pull request #108 from kim-119/feature/x',
    'ci: GitHub Actions 워크플로 수정', '버그 수정 (9b929955)']) {
    const r = run([msg]);
    assert.equal(r.ok, false, msg);
    assert.ok(codes(r).includes('FILTERED_AS_DEVELOPER_NOTE') || codes(r).includes('NOT_KOREAN'), `${msg} → ${codes(r)}`);
  }
});

test('정상 항목 사이에 개발용 문구가 하나라도 섞이면 차단', () => {
  const r = run(['화면공유 개선: 공유 화면을 크게 볼 수 있습니다.', 'chore: bump deps']);
  assert.equal(r.ok, false);
  assert.ok(codes(r).includes('FILTERED_AS_DEVELOPER_NOTE'));
});

test('중복 항목 → DUPLICATE_NOTE (공백·대소문자 차이 포함)', () => {
  const r = run(['화면공유 개선: 공유 화면을 볼 수 있습니다.', '화면공유 개선:  공유 화면을 볼 수 있습니다.']);
  assert.deepEqual(codes(r), ['DUPLICATE_NOTE']);
});

test('화면에서 문장이 바뀌는 항목(앞 번호·기호) → ALTERED_ON_RENDER', () => {
  // 실제 사고: "1.1 개선 사항 포함: …" 은 앞 "1." 이 목록 번호로 잘려 "1 개선 사항 포함" 으로 보였다.
  assert.ok(codes(run(['1.1 개선 사항 포함: 이전 기능이 모두 들어 있습니다.'])).includes('ALTERED_ON_RENDER'));
  assert.ok(codes(run(['- 화면공유 개선: 공유 화면을 볼 수 있습니다.'])).includes('ALTERED_ON_RENDER'));
});

test('한국어가 아닌 항목 → NOT_KOREAN', () => {
  assert.ok(codes(run(['Improved screen sharing on Android.'])).includes('NOT_KOREAN'));
});

test('9개 이상 → TOO_MANY_NOTES (화면은 8개까지만 표시)', () => {
  const lines = Array.from({ length: 9 }, (_, i) => `개선 ${String.fromCharCode(0xAC00 + i)}: 화면 항목 ${String.fromCharCode(0xAC00 + i)}입니다.`);
  assert.ok(codes(run(lines)).includes('TOO_MANY_NOTES'));
});

test('잘못된 직전 버전 JSON → PREVIOUS_INVALID', () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'rn-'));
  const bad = path.join(dir, 'prev.json');
  writeFileSync(bad, '{"versionName": "1.3", ');
  assert.equal(readPrevious(bad), 'INVALID');
  const r = run(['화면공유 개선: 공유 화면을 볼 수 있습니다.'], { previous: [] });
  assert.ok(codes(r).includes('PREVIOUS_INVALID'));
  assert.equal(readPrevious(path.join(dir, 'none.json')), null, '파일 없음은 첫 배포로 본다');
});

test('직전 공개 버전 노트 재사용 → REUSED_PREVIOUS_NOTES', () => {
  const prev = { versionName: '1.3', releaseNotes: ['기능 변경 없음: 1.2와 같습니다.', '업데이트 안내: 바로 업데이트하지 않아도 됩니다.'] };
  const r = run(['기능 변경 없음: 1.2와 같습니다.', '업데이트 안내:  바로 업데이트하지 않아도 됩니다.'], { previous: prev });
  assert.ok(codes(r).includes('REUSED_PREVIOUS_NOTES'));
  assert.equal(run(['기능 변경 없음: 1.3과 같습니다.'], { previous: prev }).ok, true, '일부 문장이 달라지면 통과');
});

test('다른 버전 파일 복사 → REUSED_PREVIOUS_NOTES', () => {
  const r = run(['화면공유 개선: 공유 화면을 볼 수 있습니다.'], { otherVersions: { '1.3': ['화면공유 개선: 공유 화면을 볼 수 있습니다.'] } });
  assert.ok(codes(r).includes('REUSED_PREVIOUS_NOTES'));
});

test('이미 공개된 버전 번호 → VERSION_ALREADY_PUBLISHED', () => {
  const r = validateReleaseNotes({ version: '1.3', lines: ['기능 변경 없음: 새 문장입니다.'], previous: { versionName: '1.3', releaseNotes: [] }, toUserReleaseNotes });
  assert.ok(codes(r).includes('VERSION_ALREADY_PUBLISHED'));
});

test('정확한 신규 버전 파일만 읽는다 (1.4 → 1.4.txt, 다른 파일은 재사용 비교용)', () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'rn-'));
  writeFileSync(path.join(dir, '1.3.txt'), '기능 변경 없음: 1.2와 같습니다.\n');
  writeFileSync(path.join(dir, '1.4.txt'), '# 주석\n화면공유 개선: 공유 화면을 볼 수 있습니다.\n');
  writeFileSync(path.join(dir, '1.40.txt'), '다른 버전입니다: 1.40 파일입니다.\n');
  const { lines, otherVersions } = readNotesDir(dir, '1.4');
  assert.deepEqual(lines, ['화면공유 개선: 공유 화면을 볼 수 있습니다.']);
  assert.deepEqual(Object.keys(otherVersions).sort(), ['1.3', '1.40']);
  assert.equal(readNotesDir(dir, '1.5').lines, null);
});

test('저장소의 1.2·1.3·1.4 노트 = 공개 메타데이터, 화면 필터 전부 통과', () => {
  for (const v of ['1.2', '1.3', '1.4']) {
    const { lines, otherVersions } = readNotesDir(DIR, v);
    const r = validateReleaseNotes({ version: v, lines, previous: null, otherVersions, toUserReleaseNotes });
    assert.equal(r.ok, true, `${v}: ${JSON.stringify(r.errors)}`);
    assert.equal(toUserReleaseNotes(r.notes).length, r.notes.length);
  }
});

test('CLI: 통과 시 --out 에 매니페스트용 JSON 배열, 실패 시 exit 1', () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'rn-'));
  writeFileSync(path.join(dir, '1.4.txt'), '화면공유 개선: 공유 화면을 볼 수 있습니다.\n앱 안정성 개선: 화면 전환 오류를 고쳤습니다.\n');
  const prev = path.join(dir, 'prev.json');
  writeFileSync(prev, JSON.stringify({ versionName: '1.3', versionCode: 4, releaseNotes: ['기능 변경 없음: 1.2와 같습니다.'] }));
  const out = path.join(dir, 'notes.json');
  execFileSync(process.execPath, [CLI, '--version', '1.4', '--dir', dir, '--filter', FILTER, '--previous', prev, '--out', out]);
  const notes = JSON.parse(execFileSync('cat', [out], { encoding: 'utf8' }));
  assert.deepEqual(notes, ['화면공유 개선: 공유 화면을 볼 수 있습니다.', '앱 안정성 개선: 화면 전환 오류를 고쳤습니다.']);
  assert.throws(() => execFileSync(process.execPath, [CLI, '--version', '1.5', '--dir', dir, '--filter', FILTER], { stdio: 'pipe' }),
    (e) => e.status === 1 && /NOTES_MISSING/.test(String(e.stderr)));
  assert.throws(() => execFileSync(process.execPath, [CLI, '--version', '1.4', '--dir', dir, '--filter', path.join(dir, 'nope.mjs')], { stdio: 'pipe' }),
    (e) => e.status === 2, '화면 필터 없이 통과시키지 않는다');
});
