// 회귀 방지 smoke test (의존성 0, 러너 불필요)
//   실행:  node src/__tests__/archive-routing.smoke.mjs   (frontend 디렉토리에서)
//   목적:  자료보관함 탭 정규화 / 타입별 라우팅 / isPlanner 판정 / 세부핵심 페이저 disabled /
//          ai07 신규·기존 page 필드 coalesce 의 핵심 분기를 코드 변경 없이 빠르게 검증한다.
//
//   주의: 아래 함수들은 Archive.jsx / ArchiveDetail.jsx 의 순수 로직을 "거울(mirror)"로 복제한 것이다.
//        해당 파일의 로직을 바꾸면 이 파일도 함께 갱신할 것. (러너/번들러 도입 없이 node 단독 실행 목적)

// ── MIRROR of Archive.jsx: ARCHIVE_TABS / normalizeArchiveTab ──────────────────
const ARCHIVE_TABS = [
  { key: 'LEARNING_PDF', label: '학습자료' },
  { key: 'PLANNER', label: '플래너' },
  { key: 'STUDY_LOG', label: '학습일지' },
];
const ARCHIVE_TAB_KEYS = ARCHIVE_TABS.map((t) => t.key);
const DEFAULT_ARCHIVE_TAB = 'LEARNING_PDF';
const normalizeArchiveTab = (v) => (ARCHIVE_TAB_KEYS.includes(v) ? v : DEFAULT_ARCHIVE_TAB);

// ── MIRROR of Archive.jsx: materialTabKind ────────────────────────────────────
function materialTabKind(m) {
  const raw = String(m.materialType ?? m.type ?? m.sourceType ?? m.category ?? '').toUpperCase();
  if (raw.includes('PLANNER') || raw.includes('PLAN') || raw.includes('SCHEDULE')) return 'PLANNER';
  if (raw.includes('STUDY_LOG') || raw.includes('LEARNING_LOG') || raw.includes('JOURNAL') || raw.includes('DIARY')) return 'STUDY_LOG';
  if (raw.includes('PDF') || raw.includes('MATERIAL') || raw.includes('DOCUMENT')) return 'LEARNING_PDF';
  const title = String(m.title ?? m.originalFileName ?? '').toLowerCase();
  if (title.endsWith('.pdf')) return 'LEARNING_PDF';
  return 'LEARNING_PDF';
}

// ── MIRROR of Archive.jsx: openMaterial 분기(순수 부분만) ──────────────────────
function materialOpenTarget(m) {
  const kind = String(m.materialType || '').toUpperCase();
  if (kind === 'STUDY_LOG') return { kind: 'journalModal' };
  return { kind: 'detail', path: `/archive/pdf/${m.materialId}` };
}

// ── MIRROR of ArchiveDetail.jsx: MaterialPdfViewer 입력 분기 ───────────────────
function pdfViewerState(material) {
  const isDocx = String(material?.originalFileName || '').toLowerCase().endsWith('.docx');
  const isPlanner = String(material?.materialType || '').toUpperCase() === 'PLANNER' || material?.plannerId != null;
  if (isDocx) return { kind: 'docx' };
  return {
    kind: 'pdf',
    title: isPlanner ? '플래너 PDF' : 'Document Viewer',
    fileUrl: material?.s3PresignedUrl || '',
  };
}

// ── MIRROR of ArchiveDetail.jsx: isPlanner 판정 ───────────────────────────────
const isPlannerMaterial = (material) =>
  String(material?.materialType || '').toUpperCase() === 'PLANNER' || material?.plannerId != null;

// ── MIRROR of ArchiveDetail.jsx DetailedPager: disabled 조건 + 필드 coalesce ──
const pagerAtFirst = (safe) => safe <= 0;
const pagerAtLast = (safe, total) => safe >= total - 1;
const list = (a) => (Array.isArray(a) ? a.filter((x) => x != null && String(x).trim() !== '') : []);
const firstList = (...c) => { for (const x of c) { const v = list(x); if (v.length) return v; } return []; };
const firstStr = (...c) => { for (const x of c) { if (x != null && String(x).trim() !== '') return String(x); } return ''; };
function coalescePage(p) {
  return {
    pageNo: p.pageNumber ?? p.page ?? null,
    src: String(firstStr(p.sourceQuality, p.detectedTextSource)).toUpperCase(),
    concepts: firstList(p.keywords, p.keyConcepts),
    bullets: firstList(p.bulletPoints, p.summaryBullets),
    overview: firstStr(p.oneLineSummary, p.pageOverview),
    takeaway: firstStr(p.takeaway, p.studyFocus),
    rawText: firstStr(p.extractedText, p.textPreview),
  };
}

// ── 미니 assert 러너 ──────────────────────────────────────────────────────────
let pass = 0, fail = 0;
const eq = (name, got, want) => {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) { pass++; } else { fail++; console.error(`✗ ${name}\n    got : ${g}\n    want: ${w}`); }
};

// 검증 A — 탭
eq('탭은 정확히 3개', ARCHIVE_TAB_KEYS, ['LEARNING_PDF', 'PLANNER', 'STUDY_LOG']);
eq("'전체'(ALL) 탭 없음", ARCHIVE_TAB_KEYS.includes('ALL'), false);
eq('기본 탭 = 학습자료', DEFAULT_ARCHIVE_TAB, 'LEARNING_PDF');
eq("?tab=all → 학습자료 fallback", normalizeArchiveTab('ALL'), 'LEARNING_PDF');
eq("소문자 all → 학습자료 fallback", normalizeArchiveTab('all'), 'LEARNING_PDF');
eq('undefined → 학습자료 fallback', normalizeArchiveTab(undefined), 'LEARNING_PDF');
eq('PLANNER 유지', normalizeArchiveTab('PLANNER'), 'PLANNER');
eq('STUDY_LOG 유지', normalizeArchiveTab('STUDY_LOG'), 'STUDY_LOG');

// 탭 필터 분류
eq('PLANNER 자료 → 플래너 탭', materialTabKind({ materialType: 'PLANNER' }), 'PLANNER');
eq('STUDY_LOG 자료 → 학습일지 탭', materialTabKind({ materialType: 'STUDY_LOG' }), 'STUDY_LOG');
eq('PDF 자료 → 학습자료 탭', materialTabKind({ materialType: 'PDF' }), 'LEARNING_PDF');
eq('알 수 없는 .pdf → 학습자료 탭', materialTabKind({ title: 'foo.pdf' }), 'LEARNING_PDF');
eq('완전 미상 → 학습자료 탭(누락 방지)', materialTabKind({}), 'LEARNING_PDF');

// 검증 B — 라우팅
eq('PLANNER → /archive/pdf/:id 분할뷰', materialOpenTarget({ materialType: 'PLANNER', materialId: 7 }), { kind: 'detail', path: '/archive/pdf/7' });
eq('PDF → /archive/pdf/:id', materialOpenTarget({ materialType: 'PDF', materialId: 3 }), { kind: 'detail', path: '/archive/pdf/3' });
eq('STUDY_LOG → 모달', materialOpenTarget({ materialType: 'STUDY_LOG', materialId: 9 }), { kind: 'journalModal' });
eq('PLANNER + PDF URL → 좌측 PDF 뷰어', pdfViewerState({ materialType: 'PLANNER', plannerId: 7, s3PresignedUrl: 'https://s3/p.pdf' }), { kind: 'pdf', title: '플래너 PDF', fileUrl: 'https://s3/p.pdf' });
eq('기존 PDF 자료 → 기존 PDF 뷰어 유지', pdfViewerState({ materialType: 'PDF', s3PresignedUrl: 'https://s3/a.pdf' }), { kind: 'pdf', title: 'Document Viewer', fileUrl: 'https://s3/a.pdf' });
eq('DOCX 자료 → PDF 뷰어로 보내지 않음', pdfViewerState({ originalFileName: 'note.docx' }), { kind: 'docx' });

// isPlanner 판정 — 표기 흔들림/식별자
eq("isPlanner 'PLANNER'", isPlannerMaterial({ materialType: 'PLANNER' }), true);
eq("isPlanner 'Planner'", isPlannerMaterial({ materialType: 'Planner' }), true);
eq("isPlanner 'planner'", isPlannerMaterial({ materialType: 'planner' }), true);
eq('isPlanner plannerId만 있어도 true', isPlannerMaterial({ plannerId: 5 }), true);
eq('isPlanner PDF는 false', isPlannerMaterial({ materialType: 'PDF' }), false);
eq('isPlanner 빈 객체 false(미정의 안전)', isPlannerMaterial({}), false);

// 검증 C — 페이저 disabled
eq('첫 페이지 ‹ disabled', pagerAtFirst(0), true);
eq('첫 페이지 › 활성', pagerAtLast(0, 3), false);
eq('마지막 페이지 › disabled', pagerAtLast(2, 3), true);
eq('마지막 페이지 ‹ 활성', pagerAtFirst(2), false);
eq('단일 페이지: ‹ › 모두 disabled', [pagerAtFirst(0), pagerAtLast(0, 1)], [true, true]);

// 작업3 — ai07 신규/기존 필드 coalesce (신규 우선, 둘 다 없어도 안전)
eq('신규 필드만 → 신규 사용', coalescePage({ pageNumber: 4, sourceQuality: 'TEXT', keywords: ['k'], bulletPoints: ['b'], oneLineSummary: 'o', takeaway: 't', extractedText: 'RAW' }),
  { pageNo: 4, src: 'TEXT', concepts: ['k'], bullets: ['b'], overview: 'o', takeaway: 't', rawText: 'RAW' });
eq('기존 필드만 → 기존 사용', coalescePage({ page: 2, detectedTextSource: 'OCR', keyConcepts: ['c'], summaryBullets: ['s'], pageOverview: 'po', studyFocus: 'sf' }),
  { pageNo: 2, src: 'OCR', concepts: ['c'], bullets: ['s'], overview: 'po', takeaway: 'sf', rawText: '' });
eq('필드 전무 → 빈 값(화면 안 깨짐)', coalescePage({}), { pageNo: null, src: '', concepts: [], bullets: [], overview: '', takeaway: '', rawText: '' });
eq('textPreview는 extractedText 없을 때 rawText로', coalescePage({ textPreview: 'PREVIEW' }).rawText, 'PREVIEW');

console.log(`\n${fail === 0 ? '✓ PASS' : '✗ FAIL'} — ${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);
