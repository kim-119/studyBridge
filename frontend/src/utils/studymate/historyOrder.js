// 서버 history 를 "질문(USER) → 그 질문의 답변(AI)" 순으로 재배열한다.
//  Spring 은 클라이언트 절단(Stop/새 질문/새로고침)을 다음 이벤트 시점에 감지해 그때까지 받은 답변을 partial 영속하므로,
//  답변 행이 '다음 질문' 뒤에 저장될 수 있다. USER/AI 행이 같은 requestId 를 가지므로 AI 행을 자기 질문 블록 뒤로 옮긴다.
//  requestId 가 없는 레거시 행은 원래 순서를 유지한다(안정 정렬).
export function reorderHistoryByRequest(rows) {
  if (!Array.isArray(rows) || rows.length < 2) return rows || [];
  const userIdxByReq = new Map();
  rows.forEach((r, i) => { if (r && r.sender === 'USER' && r.requestId && !userIdxByReq.has(r.requestId)) userIdxByReq.set(r.requestId, i); });
  if (userIdxByReq.size === 0) return rows;
  const out = [];
  const deferred = new Map(); // requestId → AI rows that appeared before/after their USER block
  const flushFor = (rid) => { const d = deferred.get(rid); if (d) { out.push(...d); deferred.delete(rid); } };
  for (let i = 0; i < rows.length; i += 1) {
    const r = rows[i];
    if (r && r.sender === 'AI' && r.requestId && userIdxByReq.has(r.requestId)) {
      const uIdx = userIdxByReq.get(r.requestId);
      // 자기 질문 뒤에 이미 왔고 사이에 다른 USER 가 없으면 제자리, 아니면 질문 블록 뒤로 이동
      const between = rows.slice(uIdx + 1, i).some((x) => x && x.sender === 'USER');
      if (i > uIdx && !between) { out.push(r); continue; }
      if (!deferred.has(r.requestId)) deferred.set(r.requestId, []);
      deferred.get(r.requestId).push(r);
      continue;
    }
    out.push(r);
    if (r && r.sender === 'USER' && r.requestId) {
      // 이 질문 블록: 뒤따르는 같은-requestId AI 행들은 위 분기에서 제자리 처리되고, 뒤늦게 저장된 행은 블록 끝에서 flush
      let j = i + 1;
      while (j < rows.length && rows[j] && rows[j].sender === 'AI' && rows[j].requestId === r.requestId) { out.push(rows[j]); j += 1; }
      i = j - 1;
      // 뒤쪽(다음 질문 이후)에 있는 같은 requestId AI 행을 미리 끌어온다
      for (let k = j; k < rows.length; k += 1) {
        const x = rows[k];
        if (x && x.sender === 'AI' && x.requestId === r.requestId) { out.push(x); rows = rows.slice(0, k).concat([null], rows.slice(k + 1)); }
      }
      flushFor(r.requestId);
    }
  }
  for (const [, d] of deferred) out.push(...d);
  return out.filter(Boolean);
}
