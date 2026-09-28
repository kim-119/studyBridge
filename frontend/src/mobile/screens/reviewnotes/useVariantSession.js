import { useEffect, useState } from 'react';
import { reviewNoteService } from '../../../services/api';
import { useSubmit } from '../../data/useAsync';
import {
  clearVariantSession,
  loadVariantSession,
  saveVariantSession,
} from '../../data/reviewNoteVariantSession';
import { DEFAULT_VARIANT_SETTINGS, buildVariantRequest, readVariantResponse } from './reviewNoteModel';
import {
  appendMissingQuestions,
  canRequestMissing,
  checkVariantCount,
  numberVariantQuestions,
} from './variantCountModel';

function loadSession(reviewNoteId) {
  return loadVariantSession(reviewNoteId, DEFAULT_VARIANT_SETTINGS);
}

async function requestVariants(reviewNoteId, request) {
  const response = await reviewNoteService.variantQuestion(reviewNoteId, request);
  return readVariantResponse(response);
}

function applyGeneratedResult(session, request, result) {
  const questions = numberVariantQuestions(result.questions);
  return {
    ...session,
    lastRequest: request,
    questions,
    usedFallback: result.usedFallback,
    hasResult: true,
    activeId: questions[0]?.id ?? null,
    answers: {},
    submitted: {},
  };
}

function applyMissingResult(session, merged, result) {
  return {
    ...session,
    questions: merged.questions,
    usedFallback: session.usedFallback || result.usedFallback,
    activeId: session.activeId ?? merged.questions[0]?.id ?? null,
  };
}

export default function useVariantSession(reviewNoteId) {
  const [loadedId, setLoadedId] = useState(reviewNoteId);
  const [session, setSession] = useState(() => loadSession(reviewNoteId));
  const [missingResult, setMissingResult] = useState(null);

  if (loadedId !== reviewNoteId) {
    setLoadedId(reviewNoteId);
    setSession(loadSession(reviewNoteId));
    setMissingResult(null);
  }

  useEffect(() => {
    saveVariantSession(reviewNoteId, session);
  }, [reviewNoteId, session]);

  const countCheck = checkVariantCount(session.lastRequest?.count, session.questions.length);

  const generate = useSubmit(async () => {
    const request = buildVariantRequest(session.settings);
    const result = await requestVariants(reviewNoteId, request);
    setMissingResult(null);
    setSession((previous) => applyGeneratedResult(previous, request, result));
  });

  const requestMissing = useSubmit(async () => {
    if (!canRequestMissing(countCheck)) return;
    const request = { ...session.lastRequest, count: countCheck.missing };
    const result = await requestVariants(reviewNoteId, request);
    const merged = appendMissingQuestions(session.questions, result.questions);
    setMissingResult({ requested: countCheck.missing, ...merged });
    setSession((previous) => applyMissingResult(previous, merged, result));
  });

  const updateSession = (changes) => setSession((previous) => ({ ...previous, ...changes }));

  return {
    session,
    countCheck,
    missingResult,
    generate,
    requestMissing,
    isBusy: generate.isSubmitting || requestMissing.isSubmitting,
    changeSettings: (settings) => updateSession({ settings }),
    selectQuestion: (activeId) => updateSession({ activeId }),
    pickAnswer: (questionId, index) =>
      setSession((previous) => ({ ...previous, answers: { ...previous.answers, [questionId]: index } })),
    submitAnswer: (questionId) =>
      setSession((previous) => ({ ...previous, submitted: { ...previous.submitted, [questionId]: true } })),
    clear: () => clearVariantSession(reviewNoteId),
  };
}
