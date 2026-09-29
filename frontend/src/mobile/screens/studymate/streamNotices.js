import { neutralizeErrorText } from '../../../utils/studymate/errorText.js';

export const WATCHDOG_WARN_MS = 45000;
export const WATCHDOG_FAIL_MS = 90000;
export const GATEWAY_RETRY_DELAYS_MS = [6000, 12000];
export const INTERRUPTED_TEXT = 'AI 응답 연결이 중단되었습니다. 다시 시도해 주세요.';
export const PARTIAL_TEXT = 'AI 응답 일부가 도착했지만 최종 완료 신호를 받지 못했습니다. 이어서 다시 시도할 수 있습니다.';
export const USER_STOP_TEXT = '답변 생성을 중단했어요. 다시 시도할 수 있어요.';
export const SLOW_STREAM_TEXT = '응답이 평소보다 길어지고 있어요. 계속 기다리는 중…';

function describeClientError(error) {
  const status = typeof error?.status === 'number' ? error.status : null;
  if (status == null || status < 400) return null;
  if (status >= 500) return `서버 오류로 답변을 받지 못했습니다(HTTP ${status}). 다시 시도해 주세요.`;
  const detail = error.serverMessage ? ` ${neutralizeErrorText(error.serverMessage, '').slice(0, 120)}`.trimEnd() : '';
  return `요청이 거부되었습니다(HTTP ${status}).${detail} 입력을 확인한 뒤 다시 시도해 주세요.`;
}

export function describeStreamFailure(error, { watchdogTimedOut = false } = {}) {
  if (error?.authFailure) {
    return '로그인 세션이 만료되어 답변을 받지 못했습니다. 다시 시도해 주세요. (계속 실패하면 다시 로그인해 주세요)';
  }
  if (error?.forbidden) {
    return '이 학습방에 접근할 권한이 없습니다. 방이 삭제되었거나 다른 계정의 방일 수 있어요. 방 목록을 새로 고친 뒤 다시 시도해 주세요.';
  }
  if (error?.notFound) {
    return '학습방을 찾을 수 없습니다(다른 탭이나 기기에서 삭제되었을 수 있어요). 방 목록을 새로 고쳐 주세요.';
  }
  if (error?.retryable) {
    return `AI 서버 연결이 잠시 불안정합니다(HTTP ${error.status}). 서버가 재시작 중일 수 있어요. 잠시 후 다시 시도해 주세요.`;
  }

  const clientError = describeClientError(error);
  if (clientError) return clientError;
  if (watchdogTimedOut) return `${Math.round(WATCHDOG_FAIL_MS / 1000)}초 동안 AI 응답 신호가 없어 연결을 종료했습니다. 다시 시도해 주세요.`;
  return INTERRUPTED_TEXT;
}

export function buildStreamNotice({ parentId, text, retryMessage, isError = true }) {
  return {
    id: `${parentId}::stream-notice`,
    sender: 'AI',
    senderName: 'StudyMate',
    content: neutralizeErrorText(text, text),
    isError,
    isNotice: true,
    canRetry: true,
    retryMessage,
    createdAt: new Date().toISOString(),
    parentId: `${parentId}::notice`,
  };
}

export function buildWarnNotice({ parentId, text, senderName }) {
  return {
    id: `${parentId}::warn-notice`,
    sender: 'AI',
    senderName: senderName || 'StudyMate',
    content: text,
    routeAction: 'WARN',
    isNotice: true,
    createdAt: new Date().toISOString(),
    parentId: `${parentId}::warn`,
  };
}

export function buildGatewayRetryMessage({ parentId, attempt, waitMs }) {
  return {
    id: `${parentId}::gw-retry`,
    sender: 'AI',
    senderName: 'StudyMate',
    isPending: true,
    content: '',
    statusText: `서버가 잠시 재시작 중입니다. ${Math.round(waitMs / 1000)}초 후 자동으로 다시 시도합니다… (${attempt}/${GATEWAY_RETRY_DELAYS_MS.length})`,
    createdAt: new Date().toISOString(),
    parentId,
  };
}
