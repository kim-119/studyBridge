const AI_ERROR_MESSAGES = {
  PDF_TEXT_EMPTY: 'PDF에서 추출된 텍스트가 없습니다. 다시 분석을 시도해주세요.',
  PDF_TEXT_TOO_SHORT: '문서 텍스트가 너무 짧아 요약 품질이 낮을 수 있습니다.',
  PDF_EXTRACTION_FAILED: 'PDF 텍스트 추출에 실패했습니다.',
  PDF_OCR_REQUIRED: '이미지 기반 PDF라 텍스트 추출이 필요합니다. OCR 설정을 켠 뒤 다시 시도해주세요.',
  AI_TIMEOUT: 'AI 응답 시간이 초과되었습니다. 잠시 후 다시 시도해주세요.',
  OLLAMA_UNAVAILABLE: '로컬 AI 모델 연결에 실패했습니다.',
  OPENAI_UNAVAILABLE: 'AI 모델 연결에 실패했습니다.',
  AI_RESPONSE_PARSE_FAILED: 'AI 응답 형식 처리에 실패했습니다. 다시 생성해주세요.',
  QUIZ_VALIDATE_FAILED: '요청한 난이도가 충분히 반영되지 않았습니다. 같은 PDF 자료를 기준으로 다시 생성해주세요.',
  PDF_CONTEXT_REQUIRED: 'PDF 기반 퀴즈를 생성하려면 자료에서 추출된 텍스트나 요약이 필요합니다.',
  ROADMAP_VALIDATE_FAILED: '로드맵 형식 검증에 실패했습니다. 다시 생성해주세요.',
  SUMMARY_VALIDATE_FAILED: '요약 형식 검증에 실패했습니다. 다시 생성해주세요.',
  QA_VALIDATE_FAILED: '답변 검증에 실패했습니다. 다시 질문해주세요.',
  UNKNOWN_ERROR: 'AI 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.',
};

const TEXT_MISSING_ERROR_CODES = new Set(['PDF_TEXT_EMPTY', 'PDF_OCR_REQUIRED', 'PDF_EXTRACTION_FAILED']);

export function isAiFailure(response) {
  return response?.success === false;
}

export function aiFailureMessage(response) {
  if (response?.message) return response.message;
  if (response?.errorCode && AI_ERROR_MESSAGES[response.errorCode]) {
    return AI_ERROR_MESSAGES[response.errorCode];
  }
  if (response?.textStatus?.hasText === false) return AI_ERROR_MESSAGES.PDF_TEXT_EMPTY;
  if (response?.textStatus?.status === 'TOO_SHORT') return AI_ERROR_MESSAGES.PDF_TEXT_TOO_SHORT;
  return AI_ERROR_MESSAGES.UNKNOWN_ERROR;
}

export function isTextMissing(textStatus) {
  return textStatus?.hasText === false || textStatus?.status === 'EMPTY';
}

export function textStatusMessage(textStatus) {
  if (!textStatus) return null;
  if (isTextMissing(textStatus)) return AI_ERROR_MESSAGES.PDF_TEXT_EMPTY;
  if (textStatus.status === 'TOO_SHORT') return AI_ERROR_MESSAGES.PDF_TEXT_TOO_SHORT;
  return null;
}

export function isTextMissingFailure(response) {
  return isAiFailure(response) && TEXT_MISSING_ERROR_CODES.has(response.errorCode);
}

export function aiExceptionMessage(error) {
  const isTimeout = error?.code === 'ECONNABORTED' || /timeout|timed out/i.test(error?.message || '');
  if (isTimeout) return AI_ERROR_MESSAGES.AI_TIMEOUT;

  const body = error?.response?.data || {};
  if (!body.errorCode) return null;
  return aiFailureMessage({ errorCode: body.errorCode, message: body.message, textStatus: body.textStatus });
}
