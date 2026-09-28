export const COUNT_STATUS = {
  MATCHED: 'matched',
  SHORT: 'short',
  OVER: 'over',
};

function toCount(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? Math.floor(number) : 0;
}

export function checkVariantCount(requestedCount, receivedCount) {
  const requested = toCount(requestedCount);
  const received = toCount(receivedCount);

  if (received < requested) {
    return { status: COUNT_STATUS.SHORT, requested, received, missing: requested - received };
  }
  if (received > requested) {
    return { status: COUNT_STATUS.OVER, requested, received, missing: 0 };
  }
  return { status: COUNT_STATUS.MATCHED, requested, received, missing: 0 };
}

export function variantCountMessage(check) {
  if (check.status === COUNT_STATUS.SHORT) {
    return `${check.requested}문제 요청 중 ${check.received}문제만 생성되었습니다.`;
  }
  if (check.status === COUNT_STATUS.OVER) {
    return `${check.requested}문제를 요청했지만 서버가 ${check.received}문제를 반환했습니다. 반환된 문제를 모두 표시합니다.`;
  }
  return '';
}

export function generatedCountLabel(check) {
  if (check.requested === 0) return `생성된 유사문제 ${check.received}개`;
  return `생성된 유사문제 ${check.received}개 (요청 ${check.requested}개)`;
}

export function canRequestMissing(check) {
  return check.status === COUNT_STATUS.SHORT && check.missing > 0;
}

export function missingRequestMessage({ requested, addedCount, skippedCount }) {
  const parts = [
    addedCount > 0
      ? `부족분 ${requested}문제를 다시 요청해 ${addedCount}문제를 추가했습니다.`
      : `부족분 ${requested}문제를 다시 요청했지만 새로 추가된 문제가 없습니다.`,
  ];
  if (skippedCount > 0) parts.push(`이미 받은 문제와 같은 ${skippedCount}문제는 제외했습니다.`);
  return parts.join(' ');
}

function questionFingerprint(question) {
  return String(question?.question ?? '').replace(/\s+/g, ' ').trim();
}

function sourceIdOf(question) {
  return question?.sourceId ? `source:${question.sourceId}` : '';
}

function withPosition(question, position) {
  return { ...question, id: `sq-${position}`, number: position };
}

export function numberVariantQuestions(questions) {
  return questions.map((question, index) => withPosition(question, index + 1));
}

function isAlreadySeen(seen, question) {
  const sourceId = sourceIdOf(question);
  return seen.has(questionFingerprint(question)) || (sourceId !== '' && seen.has(sourceId));
}

function remember(seen, question) {
  seen.add(questionFingerprint(question));
  if (sourceIdOf(question)) seen.add(sourceIdOf(question));
}

export function appendMissingQuestions(existing, incoming) {
  const seen = new Set();
  existing.forEach((question) => remember(seen, question));
  const fresh = [];

  incoming.forEach((question) => {
    if (!questionFingerprint(question) || isAlreadySeen(seen, question)) return;
    remember(seen, question);
    fresh.push(question);
  });

  const appended = fresh.map((question, index) => withPosition(question, existing.length + index + 1));
  return {
    questions: [...existing, ...appended],
    addedCount: appended.length,
    skippedCount: incoming.length - appended.length,
  };
}
