// node --test frontend/src/utils/__tests__   (vitest/jest 미도입 — Node 내장 테스트 러너 사용)
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  toUserReleaseNotes,
  isDeveloperNote,
  formatReleaseDate,
  formatFileSize,
  safeDownloadUrl,
} from '../appRelease.js';

test('commit-shaped notes are hidden (current v1.1 / v1.0 production metadata)', () => {
  assert.deepEqual(toUserReleaseNotes(['ci(android-release): auto-publish on android-features push with auto-incrementing version']), []);
  assert.deepEqual(toUserReleaseNotes(['Merge pull request #106 from kim-119/android-features']), []);
});

test('developer note classes are detected by pattern, not by a fixed sentence', () => {
  const dev = [
    'feat(android): receive PC screen share, stabilize video tiles',
    'fix: crash on login',
    'chore!: drop node 16',
    'refactor(groupstudy): split model',
    'Merge branch "main" into LLM-clean',
    'Revert "feat: add banner"',
    'Bump version to 1.2',
    '화면 수정 [skip ci]',
    'Co-Authored-By: someone <a@b.c>',
    '화면공유 수정 (b7da1b4c)',
    'GitHub Actions 배포 단계 정리',
    'versionCode 자동 증가',
    'Gradle 빌드 캐시 적용',
  ];
  for (const note of dev) assert.equal(isDeveloperNote(note), true, note);
});

test('user-facing Korean notes are preserved verbatim, in order', () => {
  const notes = toUserReleaseNotes([
    '화면공유 수신 지원: PC에서 공유한 화면을 앱에서 볼 수 있습니다.',
    '참여자 정보 표시를 개선했습니다.',
  ]);
  assert.deepEqual(notes, [
    { title: '화면공유 수신 지원', body: 'PC에서 공유한 화면을 앱에서 볼 수 있습니다.' },
    { title: null, body: '참여자 정보 표시를 개선했습니다.' },
  ]);
});

test('mixed list keeps only the user notes', () => {
  const notes = toUserReleaseNotes([
    'ci(android-release): auto-publish',
    '전체화면 지원: 공유된 화면을 크게 볼 수 있습니다.',
    'Merge pull request #7 from a/b',
  ]);
  assert.equal(notes.length, 1);
  assert.equal(notes[0].title, '전체화면 지원');
});

test('empty, missing and malformed releaseNotes never throw', () => {
  for (const raw of [undefined, null, [], {}, 42, true, [null, 3, {}, ['x'], '', '   ']]) {
    assert.deepEqual(toUserReleaseNotes(raw), [], String(raw));
  }
});

test('a single string (older metadata shape) is accepted as one note', () => {
  assert.deepEqual(toUserReleaseNotes('로그인 오류를 해결했습니다.'), [{ title: null, body: '로그인 오류를 해결했습니다.' }]);
});

test('markup-like and invisible/control characters are not rendered as notes', () => {
  assert.deepEqual(toUserReleaseNotes(['<script>alert(1)</script>', '<img src=x onerror=alert(1)>']), []);
  const [n] = toUserReleaseNotes(['\u202E 속도\u0000 개선\u200B했습니다.\n']);
  assert.equal(n.body, '속도 개선했습니다.');
});

test('bullets are stripped, duplicates removed, long text and count capped', () => {
  const notes = toUserReleaseNotes(['- 알림 개선', '• 알림 개선', '1. 검색 개선', '① 설정 개선']);
  assert.deepEqual(notes.map((n) => n.body), ['알림 개선', '검색 개선', '설정 개선']);
  const [long] = toUserReleaseNotes(['가'.repeat(500)]);
  assert.ok(long.body.length <= 240 && long.body.endsWith('…'));
  assert.equal(toUserReleaseNotes(Array.from({ length: 20 }, (_, i) => `개선 항목 ${i}`)).length, 8);
});

test('title split needs "title: body" with a short title, and never splits times or URLs', () => {
  assert.equal(toUserReleaseNotes(['오전 10:30부터 점검합니다.'])[0].title, null);
  assert.equal(toUserReleaseNotes(['https://studybridge.co.kr: 새 주소'])[0].title, null);
  assert.equal(toUserReleaseNotes([`${'가'.repeat(40)}: 본문`])[0].title, null);
});

test('formatReleaseDate uses KST and rejects bad input', () => {
  assert.equal(formatReleaseDate('2026-10-27T17:56:41+09:00'), '2026년 10월 27일');
  // UTC 기준 전날 밤이어도 KST 날짜로 표시
  assert.equal(formatReleaseDate('2026-10-26T16:30:00Z'), '2026년 10월 27일');
  assert.equal(formatReleaseDate('not-a-date'), null);
  assert.equal(formatReleaseDate(undefined), null);
});

test('formatFileSize', () => {
  assert.equal(formatFileSize(18019588), '17.2 MB');
  assert.equal(formatFileSize(2048), '2 KB');
  assert.equal(formatFileSize(0), null);
  assert.equal(formatFileSize('abc'), null);
});

test('safeDownloadUrl keeps the API URL and blocks script schemes', () => {
  const url = 'https://studybridge.co.kr/downloads/android/StudyBridge-latest.apk';
  assert.equal(safeDownloadUrl(url), url);
  assert.equal(safeDownloadUrl('/downloads/android/StudyBridge-latest.apk'), '/downloads/android/StudyBridge-latest.apk');
  assert.equal(safeDownloadUrl('javascript:alert(1)'), null);
  assert.equal(safeDownloadUrl('//evil.example/x.apk'), null);
  assert.equal(safeDownloadUrl(null), null);
});
