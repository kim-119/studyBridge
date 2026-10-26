// 회귀 방지 smoke test (의존성 0, 러너 불필요)
//   실행:  node src/__tests__/groupcover.smoke.mjs   (frontend 디렉토리에서, Node 20+: 전역 File/Blob/Response)
//   목적:  그룹 생성 대표 이미지 3상태(preset / upload / none) 전환과 생성 요청 image 파트 결정을 검증한다.
//          utils/groupCover.js 를 직접 import 한다(asset import 가 없는 순수 모듈).
import {
  COVER_MODES, selectCoverPreset, selectCoverUpload, selectCoverNone, discardedCoverPreviewUrl, resolveCoverImageFile,
} from '../utils/groupCover.js';

let pass = 0;
let fail = 0;
const check = (name, cond) => {
  if (cond) { pass += 1; console.log(`PASS ${name}`); } else { fail += 1; console.log(`FAIL ${name}`); }
};

const PRESETS = [
  { id: 'notes', label: '노트', url: '/assets/cover-notes-abc.jpg' },
  { id: 'team', label: '팀 스터디', url: '/assets/cover-team-def.jpg' },
];
const jpegFetch = (calls) => async (url) => {
  calls.push(url);
  return new Response(new Blob([new Uint8Array([0xff, 0xd8, 0xff, 0xe0])], { type: 'image/jpeg' }), { status: 200 });
};
const base = { title: 't', studyType: 'GENERAL' };
const userFile = new File([new Uint8Array([1, 2, 3])], 'my-photo.png', { type: 'image/png' });

// ── 상태 전환 ───────────────────────────────────────────────
const p1 = selectCoverPreset(base, PRESETS[0]);
check('preset: mode/id/thumbnail', p1.coverMode === COVER_MODES.PRESET && p1.coverPresetId === 'notes' && p1.thumbnail === PRESETS[0].url);
check('preset: 다른 필드 보존', p1.title === 't' && p1.studyType === 'GENERAL');

const up = selectCoverUpload(p1, userFile, 'blob:upload-1');
check('upload: imageFile/thumbnail, presetId 해제', up.coverMode === COVER_MODES.UPLOAD && up.imageFile === userFile && up.thumbnail === 'blob:upload-1' && up.coverPresetId === null);

const backToPreset = selectCoverPreset(up, PRESETS[1]);
check('upload→preset: stale imageFile 초기화', backToPreset.imageFile === null && backToPreset.coverPresetId === 'team');
check('upload→preset: 버려진 objectURL 반환', discardedCoverPreviewUrl(up, backToPreset) === 'blob:upload-1');

const none = selectCoverNone(up);
check('upload→none: imageFile/thumbnail/presetId 모두 null', none.coverMode === COVER_MODES.NONE && none.imageFile === null && none.thumbnail === null && none.coverPresetId === null);
check('upload→none: 버려진 objectURL 반환', discardedCoverPreviewUrl(up, none) === 'blob:upload-1');
check('preset→none: 해제할 objectURL 없음', discardedCoverPreviewUrl(p1, selectCoverNone(p1)) === null);
check('upload 유지(같은 URL): 해제 안 함', discardedCoverPreviewUrl(up, up) === null);
check('폼 리셋(next=null): 업로드 objectURL 해제', discardedCoverPreviewUrl(up, null) === 'blob:upload-1');

// ── 생성 요청 image 파트 ────────────────────────────────────
{
  const calls = [];
  const f = await resolveCoverImageFile(backToPreset, PRESETS, jpegFetch(calls));
  check('preset → 해당 asset 을 받아 File 로 변환', calls.length === 1 && calls[0] === PRESETS[1].url);
  check('preset File: 이름/타입(서버 허용 MIME)', f instanceof File && f.name === 'group-cover-team.jpg' && f.type === 'image/jpeg' && f.size === 4);
}
{
  const calls = [];
  const f = await resolveCoverImageFile(up, PRESETS, jpegFetch(calls));
  check('upload → 사용자 파일 그대로(프리셋 fetch 없음)', f === userFile && calls.length === 0);
}
{
  const calls = [];
  const f = await resolveCoverImageFile(none, PRESETS, jpegFetch(calls));
  check('none → image 없음(null)', f === null && calls.length === 0);
}
{
  const f = await resolveCoverImageFile({ title: 'legacy' }, PRESETS, jpegFetch([]));
  check('coverMode 없음 → null', f === null);
}
{
  let threw = false;
  try { await resolveCoverImageFile(backToPreset, PRESETS, async () => new Response('nf', { status: 404 })); } catch { threw = true; }
  check('preset fetch 404 → throw(이미지 없이 조용히 생성하지 않음)', threw);
}
{
  let threw = false;
  try {
    await resolveCoverImageFile(backToPreset, PRESETS, async () => new Response(new Blob(['<html>'], { type: 'text/html' }), { status: 200 }));
  } catch { threw = true; }
  check('preset 응답이 SPA index.html(200) → throw', threw);
}
{
  let threw = false;
  try { await resolveCoverImageFile({ coverMode: COVER_MODES.PRESET, coverPresetId: 'gone' }, PRESETS, jpegFetch([])); } catch { threw = true; }
  check('알 수 없는 presetId → throw', threw);
}

console.log(`\nGROUPCOVER SMOKE pass=${pass} fail=${fail}`);
process.exit(fail ? 1 : 0);
