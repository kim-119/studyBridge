// 홈 "핵심 기능" 카드의 목적지 단일 출처. 카드 제목(핵심 기능명) → 실제 기능이 있는 라우트.
//  · PDF 요약/퀴즈 생성 = 자료보관함(PDF 업로드 후 요약·퀴즈), 로드맵 = 플래너(로드맵 플래너), AI 질의응답 = 학습메이트(/studymate canonical, 구 /learning-mate 는 리다이렉트),
//    그룹 스터디 = 그룹스터디, 학습 진도 관리 = 학습 리포트. 모든 카드가 /studymate 로 가던 문제를 고정한다.
export const FEATURE_ROUTES = Object.freeze({
  pdfSummary: '/archive',
  roadmap: '/planner',
  quiz: '/archive',
  aiQna: '/studymate',
  groupStudy: '/groupstudy',
  progress: '/study-report',
});
export const featureRoute = (key) => FEATURE_ROUTES[key] || '/';
