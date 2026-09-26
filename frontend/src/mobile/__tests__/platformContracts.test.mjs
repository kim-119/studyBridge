// 실행: node --test frontend/src/mobile/__tests__
import test from 'node:test';
import assert from 'node:assert/strict';
import { extractDownloadUrl } from '../platform/downloadUrl.js';
import { TimeoutError, withTimeout } from '../data/withTimeout.js';
import { formatFileSize, matchesKeyword, sortItems } from '../screens/archive/archiveDomain.js';

test('다운로드 URL 은 엔드포인트별 키를 모두 해석한다', () => {
  assert.equal(extractDownloadUrl({ downloadUrl: 'a' }), 'a');
  assert.equal(extractDownloadUrl({ presignedUrl: 'b' }), 'b');
  assert.equal(extractDownloadUrl({ pdfUrl: 'c' }), 'c');
  assert.equal(extractDownloadUrl({ url: 'd', fileName: 'x.pdf' }), 'd');
  assert.equal(extractDownloadUrl('https://direct'), 'https://direct');
});

test('키를 못 찾으면 객체를 그대로 흘리지 않고 null 을 준다', () => {
  assert.equal(extractDownloadUrl({ unexpected: 'z' }), null);
  assert.equal(extractDownloadUrl(null), null);
});

test('withTimeout 은 제한 시간 안에 끝나면 결과를 그대로 준다', async () => {
  assert.equal(await withTimeout(Promise.resolve('ok'), 100), 'ok');
});

test('withTimeout 은 제한 시간을 넘기면 TimeoutError 로 끊는다', async () => {
  const never = new Promise(() => {});
  await assert.rejects(() => withTimeout(never, 20), (error) => error instanceof TimeoutError);
});

test('자료 검색은 제목·키워드·원본 파일명을 모두 본다', () => {
  const item = { title: '머신러닝', keywords: '회귀,분류', originalFileName: 'ml-final.pdf' };

  assert.equal(matchesKeyword(item, '머신'), true);
  assert.equal(matchesKeyword(item, '분류'), true);
  assert.equal(matchesKeyword(item, 'ml-final'), true);
  assert.equal(matchesKeyword(item, '자료구조'), false);
  assert.equal(matchesKeyword(item, ''), true);
});

test('정렬은 최신순·오래된순·이름순을 지원하며 원본을 바꾸지 않는다', () => {
  const items = [
    { title: '나', uploadedAt: '2026-01-02' },
    { title: '가', uploadedAt: '2026-01-03' },
    { title: '다', uploadedAt: '2026-01-01' },
  ];
  const original = [...items];

  assert.equal(sortItems(items, 'recent')[0].title, '가');
  assert.equal(sortItems(items, 'oldest')[0].title, '다');
  assert.equal(sortItems(items, 'title')[0].title, '가');
  assert.deepEqual(items, original);
});

test('파일 크기 표기', () => {
  assert.equal(formatFileSize(0), '');
  assert.equal(formatFileSize(512), '512 B');
  assert.equal(formatFileSize(2048), '2 KB');
  assert.equal(formatFileSize(5 * 1024 * 1024), '5.0 MB');
});
