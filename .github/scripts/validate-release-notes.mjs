#!/usr/bin/env node
// Android 릴리스 노트 배포 전 검증기.
//
// android/release-notes/<다음 versionName>.txt 를 읽어, 다운로드 페이지(/app)가 실제로 쓰는 필터
// toUserReleaseNotes()(LLM-clean frontend/src/utils/appRelease.js 를 그대로 받아 --filter 로 넘김)로 렌더한 결과가
// 작성한 문장과 한 글자도 다르지 않을 때만 통과시킨다. 통과하지 못하면 APK 를 빌드·배포하지 않는다.
//   차단: 파일 없음 · 빈 파일 · 항목 수 초과 · 중복 · 한국어 아님 · 개발용 문구(필터링됨) · 렌더 시 문장이 바뀜
//        · 이미 배포된 버전 · 직전 공개 버전(또는 다른 버전 파일)과 같은 노트 재사용 · 직전 버전 응답 JSON 오류
//
// 사용: node validate-release-notes.mjs --version 1.4 --dir android/release-notes \
//         --filter /tmp/appRelease.mjs --previous /tmp/current-version.json --out /tmp/release-notes.json
import { existsSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

export const MAX_NOTES = 8;
const HANGUL = /[가-힣]/;

const normalize = (s) => String(s).replace(/\s+/g, ' ').trim();
const keyOf = (s) => normalize(s).toLowerCase();

/** 파일 본문 → 항목(줄) 목록. '#' 로 시작하는 줄은 작성 안내용 주석, 빈 줄은 무시. */
export function parseNotesText(text) {
  return String(text)
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l && !l.startsWith('#'));
}

function sameList(a, b) {
  const x = a.map(keyOf);
  const y = b.map(keyOf);
  return x.length === y.length && x.every((v, i) => v === y[i]);
}

/**
 * @param {object} p
 * @param {string} p.version 배포 예정 versionName (예: "1.4")
 * @param {string[]|null} p.lines 해당 버전 파일의 항목(파일이 없으면 null)
 * @param {object|null} p.previous 현재 공개 버전 응답(/api/app/version)
 * @param {Record<string,string[]>} p.otherVersions 다른 버전 파일의 항목들 { "1.3": [...] }
 * @param {(raw:any)=>{title:string|null, body:string}[]} p.toUserReleaseNotes 화면과 같은 필터
 * @returns {{ ok: boolean, errors: {code:string, message:string}[], notes: string[] }}
 */
export function validateReleaseNotes({ version, lines, previous, otherVersions = {}, toUserReleaseNotes }) {
  const errors = [];
  const err = (code, message) => errors.push({ code, message });
  if (typeof toUserReleaseNotes !== 'function') throw new Error('toUserReleaseNotes 필터가 필요합니다.');
  if (!/^\d+\.\d+(\.\d+)?$/.test(String(version || ''))) err('VERSION_INVALID', `배포 버전 형식이 올바르지 않습니다: '${version}'`);
  if (lines == null) {
    err('NOTES_MISSING', `android/release-notes/${version}.txt 가 없습니다. 이번 APK 에서 실제로 달라진 점을 한국어로 적어 주세요.`);
    return { ok: false, errors, notes: [] };
  }
  const notes = lines.map(normalize);
  if (notes.length === 0) err('NOTES_EMPTY', `android/release-notes/${version}.txt 에 항목이 없습니다.`);
  if (notes.length > MAX_NOTES) err('TOO_MANY_NOTES', `항목은 최대 ${MAX_NOTES}개까지 화면에 표시됩니다(현재 ${notes.length}개).`);

  const seen = new Set();
  notes.forEach((line, i) => {
    const no = `${i + 1}번째 항목`;
    if (seen.has(keyOf(line))) err('DUPLICATE_NOTE', `${no}이 앞 항목과 중복됩니다: "${line}"`);
    seen.add(keyOf(line));
    if (!HANGUL.test(line)) err('NOT_KOREAN', `${no}은 한국어 사용자 문구가 아닙니다: "${line}"`);
    const rendered = toUserReleaseNotes([line]);
    if (rendered.length === 0) {
      err('FILTERED_AS_DEVELOPER_NOTE', `${no}은 다운로드 페이지에서 개발용 문구로 숨겨집니다(커밋 제목·CI 용어·해시 등): "${line}"`);
      return;
    }
    const r = rendered[0];
    const shown = r.title ? `${r.title}: ${r.body}` : r.body;
    if (shown !== line) err('ALTERED_ON_RENDER', `${no}이 화면에서 "${shown}" 로 바뀌어 보입니다(앞 번호·기호 제거 등). 원문: "${line}"`);
  });

  if (previous !== null && previous !== undefined) {
    if (typeof previous !== 'object' || Array.isArray(previous)) {
      err('PREVIOUS_INVALID', '현재 공개 버전 응답이 JSON 객체가 아닙니다.');
    } else {
      if (previous.versionName && String(previous.versionName) === String(version)) {
        err('VERSION_ALREADY_PUBLISHED', `v${version} 은 이미 공개된 버전입니다. 새 버전 번호의 노트가 필요합니다.`);
      }
      const prevNotes = Array.isArray(previous.releaseNotes) ? previous.releaseNotes.filter((x) => typeof x === 'string') : [];
      if (notes.length && prevNotes.length && sameList(notes, prevNotes)) {
        err('REUSED_PREVIOUS_NOTES', `직전 공개 버전 v${previous.versionName} 의 노트를 그대로 재사용했습니다. 이번 버전에서 달라진 점을 적어 주세요.`);
      }
    }
  }
  for (const [v, other] of Object.entries(otherVersions)) {
    if (String(v) !== String(version) && notes.length && sameList(notes, other)) {
      err('REUSED_PREVIOUS_NOTES', `android/release-notes/${v}.txt 와 내용이 같습니다. 이번 버전에서 달라진 점을 적어 주세요.`);
    }
  }
  return { ok: errors.length === 0, errors, notes };
}

/** --previous 파일 → 객체. 파일이 없으면 null(첫 배포), JSON 이 깨졌으면 'INVALID'. */
export function readPrevious(file) {
  if (!file || !existsSync(file)) return null;
  try {
    return JSON.parse(readFileSync(file, 'utf8'));
  } catch {
    return 'INVALID';
  }
}

export function readNotesDir(dir, version) {
  const own = path.join(dir, `${version}.txt`);
  const lines = existsSync(own) ? parseNotesText(readFileSync(own, 'utf8')) : null;
  const otherVersions = {};
  if (existsSync(dir)) {
    for (const f of readdirSync(dir)) {
      const m = /^(\d+\.\d+(?:\.\d+)?)\.txt$/.exec(f);
      if (m && m[1] !== String(version)) otherVersions[m[1]] = parseNotesText(readFileSync(path.join(dir, f), 'utf8'));
    }
  }
  return { lines, otherVersions };
}

function arg(name) {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 ? process.argv[i + 1] : undefined;
}

async function main() {
  const version = arg('version');
  const dir = arg('dir') || 'android/release-notes';
  const filter = arg('filter');
  const out = arg('out');
  if (!filter || !existsSync(filter)) {
    console.error(`FAIL: 화면 필터(appRelease.js) 경로가 없습니다: '${filter}'. 화면과 같은 함수 없이 통과시키지 않습니다.`);
    process.exit(2);
  }
  const { toUserReleaseNotes } = await import(pathToFileURL(path.resolve(filter)).href);
  const { lines, otherVersions } = readNotesDir(dir, version);
  const prev = readPrevious(arg('previous'));
  const result = validateReleaseNotes({ version, lines, previous: prev === 'INVALID' ? [] : prev, otherVersions, toUserReleaseNotes });
  if (!result.ok) {
    console.error(`FAIL: v${version} 릴리스 노트 검증 실패 — APK 를 빌드·배포하지 않습니다.`);
    for (const e of result.errors) console.error(`  [${e.code}] ${e.message}`);
    process.exit(1);
  }
  console.log(`OK: v${version} 릴리스 노트 ${result.notes.length}개 — 다운로드 페이지에 그대로 표시됩니다.`);
  result.notes.forEach((n, i) => console.log(`  ${i + 1}. ${n}`));
  if (out) writeFileSync(out, JSON.stringify(result.notes));
}

if (import.meta.url === pathToFileURL(process.argv[1] || '').href) {
  main().catch((e) => {
    console.error(`FAIL: ${e && e.message ? e.message : e}`);
    process.exit(2);
  });
}
