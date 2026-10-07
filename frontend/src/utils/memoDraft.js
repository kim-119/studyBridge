// 오답노트 메모 초안(draft) 순수 헬퍼 — React 무관, node:test 로 검증.
//  · 초안은 노트 id 별로 독립이며 페이지 수준에서 보관한다(탭 전환/목록 갱신으로 카드가 다시 마운트돼도 유지).
//  · 입력 중에는 서버를 부르지 않는다(저장 버튼에서만 저장). textarea 는 저장 중에도 비활성화하지 않는다.
//  · 저장 응답이 돌아왔을 때 사용자가 그 사이 더 입력했으면(= dirty) 응답으로 초안을 덮지 않는다(latest-request guard).

export const draftOf = (drafts, id) => (drafts && Object.prototype.hasOwnProperty.call(drafts, id) ? drafts[id] : undefined);

// 화면에 보일 값: 초안이 있으면 초안, 없으면 저장된 메모.
export const displayMemo = (drafts, id, savedMemo) => {
  const d = draftOf(drafts, id);
  return d === undefined ? (savedMemo ?? '') : d;
};

export function setDraft(drafts, id, value) {
  return { ...(drafts || {}), [id]: value };
}

// 저장 성공 후 처리: 저장 시점 값(sentValue)과 현재 초안이 같으면 초안을 걷어 저장본이 원천이 되게 하고,
// 그 사이 더 입력했으면 초안을 그대로 둔다(사용자 입력이 서버 응답보다 우선).
export function settleAfterSave(drafts, id, sentValue) {
  const cur = draftOf(drafts, id);
  if (cur === undefined || cur !== sentValue) return drafts || {};
  const next = { ...drafts };
  delete next[id];
  return next;
}

// 요청 토큰 가드: 마지막으로 보낸 요청의 응답만 반영한다.
export const isLatest = (seqRef, mySeq) => seqRef.current === mySeq;
