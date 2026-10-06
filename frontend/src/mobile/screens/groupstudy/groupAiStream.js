import { refreshAccessToken } from '../../../services/api';
import { createSseParser } from '../../../utils/sse/sseParser';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

export class GroupAiStreamError extends Error {
  constructor(status) {
    super(`그룹 AI 스트림 요청이 실패했습니다. (HTTP ${status})`);
    this.name = 'GroupAiStreamError';
    this.status = status;
  }
}

export function describeGroupAiError(error) {
  if (error?.status === 401) return '로그인이 만료되었습니다. 다시 로그인해주세요.';
  if (error?.status === 403) return '스터디 멤버만 AI 질문을 사용할 수 있습니다.';
  if (error?.status >= 500) return 'AI 서버가 응답하지 않습니다. 잠시 후 다시 시도해주세요.';
  if (error?.name === 'TypeError') return '서버에 연결할 수 없습니다. 네트워크 상태를 확인해주세요.';
  return error?.message || 'AI 응답을 받지 못했습니다.';
}

function postStream(groupId, body, token, signal) {
  return fetch(`${API_BASE_URL}/api/groups/${groupId}/chats/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      Authorization: token ? `Bearer ${token}` : '',
    },
    body: JSON.stringify(body),
    signal,
  });
}

async function openStream(groupId, body, signal) {
  const response = await postStream(groupId, body, localStorage.getItem('token'), signal);
  if (response.status !== 401) return response;

  const refreshedToken = await refreshAccessToken();
  return postStream(groupId, body, refreshedToken, signal);
}

function parseFrameData(data) {
  try {
    return JSON.parse(data);
  } catch {
    return null;
  }
}

export async function streamGroupAiChat(groupId, body, { signal, onFrame }) {
  const response = await openStream(groupId, body, signal);
  if (!response.ok) throw new GroupAiStreamError(response.status);

  const parser = createSseParser((frame) => {
    if (frame.control) return;
    const parsed = parseFrameData(frame.data);
    if (parsed) onFrame({ event: frame.event, parsed });
  });

  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    parser.push(decoder.decode(value, { stream: true }));
  }

  parser.push(decoder.decode());
  parser.flush();
}
