// node --test frontend/src/utils/__tests__
// 회귀 가드(정적 소스 검사): services/api.js 의 업로드 함수가 공통 `api` 인스턴스(401 → refresh → 재시도 인터셉터)를
// 우회해 raw `axios.post/put` + 수동 Authorization 으로 나가지 않는지. (2026-10-07 모바일 PDF 업로드
// "Request failed with status code 401" 사고 — 만료 토큰이 갱신 없이 그대로 실패했다.)
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const src = fs.readFileSync(path.resolve(here, '../../services/api.js'), 'utf8');
const lines = src.split('\n');

// 소스에서 raw axios 호출 위치를 찾는다: axios.<method>(`${API_BASE_URL}/api/... 또는 axios.<method>('/api/...
const rawAxiosCalls = () => lines
  .map((l, i) => [i + 1, l])
  .filter(([, l]) => !l.trim().startsWith('//') && /\baxios\.(post|put|patch|get|delete)\s*\(\s*(`\$\{API_BASE_URL\}\/api\/|['"]\/api\/)/.test(l));

test('raw axios 호출은 토큰 갱신 엔드포인트(/api/users/refresh) 하나뿐이다', () => {
  const hits = rawAxiosCalls();
  const offenders = hits.filter(([, l]) => !l.includes('/api/users/refresh'));
  assert.deepEqual(offenders.map(([n, l]) => `${n}: ${l.trim()}`), [],
    'raw axios 로 /api 를 직접 치면 401 갱신/재시도 인터셉터를 우회한다 — 공통 api 인스턴스를 쓸 것');
  assert.equal(hits.length, 1, 'refresh 호출은 인터셉터 재귀를 피하려고 raw axios 여야 한다(정확히 1곳)');
});

test('수동 Authorization 헤더 조립(`Authorization: `Bearer ${token}``)은 axios 설정에 남아 있지 않다', () => {
  // 허용 예외: SSE fetch(streamMessage) 와 pagehide keepalive fetch 는 axios 가 아니라 fetch 라 인터셉터를 못 쓴다.
  const manual = lines
    .map((l, i) => [i + 1, l])
    .filter(([, l]) => /Authorization:\s*`Bearer \$\{token\}`/.test(l) || /\.\.\.\(token \? \{ Authorization: `Bearer \$\{token\}` \} : \{\}\)/.test(l));
  const inAxiosCall = manual.filter(([n]) => {
    const window = lines.slice(Math.max(0, n - 12), n).join('\n');
    return /\baxios\.(post|put|patch|get|delete)\s*\(/.test(window);
  });
  assert.deepEqual(inAxiosCall.map(([n, l]) => `${n}: ${l.trim()}`), []);
});

test('FormData 업로드 함수는 모두 api.<method>( 로 보내고 MULTIPART_HEADERS 를 쓴다', () => {
  const fns = ['uploadProfileImage', 'uploadMaterial', 'classifyBeforeSave', 'uploadQuizMaterial', 'createPost', 'updatePost'];
  for (const fn of fns) {
    const start = src.indexOf(`${fn}: async`);
    assert.ok(start > -1, `${fn} 정의를 찾을 수 없음`);
    const body = src.slice(start, src.indexOf('\n  },', start));
    assert.match(body, /new FormData\(\)/, `${fn}: FormData 를 쓰는 업로드 함수여야 한다`);
    assert.match(body, /\bapi\.(post|put)\(/, `${fn}: 공통 api 인스턴스를 써야 한다`);
    assert.doesNotMatch(body, /\baxios\.(post|put)\(/, `${fn}: raw axios 금지`);
    assert.doesNotMatch(body, /localStorage\.getItem\('token'\)/, `${fn}: 토큰은 요청 인터셉터가 붙인다`);
    // Content-Type 은 하드코딩하지 않고 단일 상수만 쓴다. (boundary 는 브라우저가 붙인다.)
    assert.match(body, /headers:\s*MULTIPART_HEADERS/, `${fn}: headers: MULTIPART_HEADERS 여야 한다`);
    assert.doesNotMatch(body, /boundary/i, `${fn}: boundary 하드코딩 금지`);
  }
});

// 문서화된 예외: `api` 기본 Content-Type 이 application/json 이라 axios 1.x transformRequest 가 FormData 를
// JSON 으로 직렬화해 버린다. 그래서 'multipart/form-data' 로 덮어쓰고(값만, boundary 없음) 브라우저 어댑터가 제거하게 둔다.
test('MULTIPART_HEADERS 는 boundary 없는 multipart/form-data 하나이며, api 기본 헤더가 JSON 인 전제가 유지된다', () => {
  assert.match(src, /export const MULTIPART_HEADERS = Object\.freeze\(\{ 'Content-Type': 'multipart\/form-data' \}\);/);
  const apiCreate = src.slice(src.indexOf('const api = axios.create({'), src.indexOf('});', src.indexOf('const api = axios.create({')));
  assert.match(apiCreate, /'Content-Type': 'application\/json'/);
});

test('401 인터셉터: refresh/login 요청은 재시도 대상에서 제외되고 _retry 로 한 번만 재시도한다(무한 루프 방지)', () => {
  const start = src.indexOf('api.interceptors.response.use(');
  const block = src.slice(start, src.indexOf('fastApi.interceptors.response.use(', start));
  assert.match(block, /err\.response\.status === 401/);
  assert.match(block, /!originalRequest\._retry/);
  assert.match(block, /originalRequest\._retry = true/);
  assert.match(block, /originalRequest\.url\.includes\('\/api\/users\/refresh'\)/);
  assert.match(block, /return api\(originalRequest\)/, '재시도는 같은 config(FormData body 포함)로 같은 인스턴스를 다시 탄다');
});
