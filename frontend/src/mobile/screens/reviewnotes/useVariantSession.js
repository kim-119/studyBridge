import { useEffect, useState } from 'react';
import { reviewNoteService } from '../../../services/api';
import { useSubmit } from '../../data/useAsync';
import { useBackgroundTask } from '../../data/useBackgroundTask';
import {
  clearVariantSession,
  loadVariantSession,
  saveVariantSession,
} from '../../data/reviewNoteVariantSession';
import { DEFAULT_VARIANT_SETTINGS, buildVariantRequest, readVariantResponse } from './reviewNoteModel';
import { appendMissingQuestions, canRequestMissing, checkVariantCount } from './variantCountModel';
import {
  applyGeneratedResult,
  completeVariantSession,
  goToNextQuestion,
  progressOf,
  restartVariantSession,
  variantGenerationTaskKey,
} from './variantProgress';

function loadSession(reviewNoteId) {
  return loadVariantSession(reviewNoteId, DEFAULT_VARIANT_SETTINGS);
}

async function requestVariants(reviewNoteId, request) {
  const response = await reviewNoteService.variantQuestion(reviewNoteId, request);
  return readVariantResponse(response);
}

async function generateAndStoreSession(reviewNoteId, request) {
  const result = await requestVariants(reviewNoteId, request);
  const generatedSession = applyGeneratedResult(loadSession(reviewNoteId), request, result);
  saveVariantSession(reviewNoteId, generatedSession);
  return generatedSession;
}

function applyMissingResult(session, merged, result) {
  return {
    ...session,
    questions: merged.questions,
    usedFallback: session.usedFallback || result.usedFallback,
    activeId: session.activeId ?? merged.questions[0]?.id ?? null,
    completed: false,
  };
}

export default function useVariantSession(reviewNoteId) {
  const [loadedId, setLoadedId] = useState(reviewNoteId);
  const [session, setSession] = useState(() => loadSession(reviewNoteId));
  const [missingResult, setMissingResult] = useState(null);
  const generation = useBackgroundTask(variantGenerationTaskKey(reviewNoteId));
  const { isReady: isGenerated, result: generatedSession, reset: resetGeneration } = generation;

  if (loadedId !== reviewNoteId) {
    setLoadedId(reviewNoteId);
    setSession(loadSession(reviewNoteId));
    setMissingResult(null);
  }

  useEffect(() => {
    saveVariantSession(reviewNoteId, session);
  }, [reviewNoteId, session]);

  useEffect(() => {
    if (!isGenerated) return;
    setMissingResult(null);
    setSession(generatedSession);
    resetGeneration();
  }, [isGenerated, generatedSession, resetGeneration]);

  const countCheck = checkVariantCount(session.lastRequest?.count, session.questions.length);

  const submitGeneration = () =>
    generation.run(() => generateAndStoreSession(reviewNoteId, buildVariantRequest(session.settings)));

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
    progress: progressOf(session),
    countCheck,
    missingResult,
    generate: {
      submit: submitGeneration,
      isSubmitting: generation.isGenerating,
      error: generation.isFailed ? generation.error : null,
    },
    requestMissing,
    isBusy: generation.isGenerating || requestMissing.isSubmitting,
    changeSettings: (settings) => updateSession({ settings }),
    selectQuestion: (activeId) => updateSession({ activeId }),
    pickAnswer: (questionId, index) =>
      setSession((previous) => ({ ...previous, answers: { ...previous.answers, [questionId]: index } })),
    submitAnswer: (questionId) =>
      setSession((previous) => ({ ...previous, submitted: { ...previous.submitted, [questionId]: true } })),
    goToNext: () => setSession(goToNextQuestion),
    complete: () => setSession(completeVariantSession),
    restart: () => setSession(restartVariantSession),
    clear: () => clearVariantSession(reviewNoteId),
  };
}
