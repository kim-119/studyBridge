// node --test frontend/src/utils/__tests__
// 회귀 가드: ArchiveDetail.jsx 는 lucide-react 의 `Map` 아이콘을 import 하므로 전역 Map 이 가려진다.
// `new Map(` 을 쓰면 운영 번들에서 "X is not a constructor" 로 퀴즈 탭 전체가 크래시한다(2026-09-28 배포 회귀).
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const src = fs.readFileSync(path.resolve(here, '../../pages/ArchiveDetail.jsx'), 'utf8');

test('ArchiveDetail imports lucide Map icon (the shadowing precondition still holds)', () => {
  const importLine = src.split('\n').find((l) => l.includes("from 'lucide-react'"));
  assert.ok(importLine && /\bMap\b/.test(importLine), 'lucide Map 아이콘 import 가 없으면 이 가드는 재검토 필요');
});

test('ArchiveDetail never calls `new Map(` (global Map is shadowed by the icon)', () => {
  const hits = src.split('\n').map((l, i) => [i + 1, l]).filter(([, l]) => !l.trim().startsWith('//') && /new\s+Map\s*\(/.test(l));
  assert.deepEqual(hits, [], `new Map( 사용 금지: ${hits.map(([n]) => n).join(',')}`);
});

// 같은 함정: lucide 아이콘 이름과 겹치는 전역 생성자(Set 은 lucide 에 없지만 방어적으로 확인)
test('files that import a lucide `Map` icon do not construct Map', () => {
  const root = path.resolve(here, '../../');
  const files = [];
  const walk = (d) => fs.readdirSync(d, { withFileTypes: true }).forEach((e) => {
    const p = path.join(d, e.name);
    if (e.isDirectory()) { if (!/node_modules|__tests__/.test(p)) walk(p); } else if (/\.(jsx?|tsx?)$/.test(e.name)) files.push(p);
  });
  walk(root);
  const offenders = files.filter((f) => {
    const t = fs.readFileSync(f, 'utf8');
    const lucideImport = (t.match(/import\s*\{([^}]*)\}\s*from\s*'lucide-react'/) || [])[1] || '';
    const code = t.split('\n').filter((l) => !l.trim().startsWith('//')).join('\n');
    return /\bMap\b/.test(lucideImport) && /new\s+Map\s*\(/.test(code);
  }).map((f) => path.relative(root, f));
  assert.deepEqual(offenders, []);
});
