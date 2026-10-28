import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { groupService } from '../../../services/api';
import { useAsync } from '../../data/useAsync';
import { captureScreenFrame } from './screenFrameCapture';
import {
  analyzableShares,
  buildAnalyzeRequest,
  describeScreenAiError,
  limitsFrom,
  myShares,
  newClientRequestId,
  validateQuestion,
} from './screenAiModel';

const TIMEOUT_MARGIN_MS = 15_000;

function screenKey(remoteParticipants) {
  return (remoteParticipants || [])
    .filter((participant) => participant?.isScreenShare || participant?.videoKind === 'SCREEN')
    .map((participant) => `${participant.connectionId}:${participant.streamManager ? 1 : 0}`)
    .sort()
    .join('|');
}

// 화면 분석 요청 상태. 한 번에 1건만 진행하고(서버도 사용자당 1건), 대상 화면공유가 끝나거나 화면을 떠나면 취소한다.
export function useScreenAnalysis(groupId, remoteParticipants, { capture = captureScreenFrame } = {}) {
  const key = screenKey(remoteParticipants);
  const sharesQuery = useAsync(() => groupService.getScreenAiShares(groupId), [groupId, key]);
  const limits = limitsFrom(sharesQuery.data);
  const shares = useMemo(
    () => analyzableShares(sharesQuery.data, remoteParticipants),
    [sharesQuery.data, remoteParticipants]
  );

  const ownShares = useMemo(() => myShares(sharesQuery.data), [sharesQuery.data]);
  const [consentError, setConsentError] = useState(null);

  const setConsent = useCallback(
    async (connectionId, allowed) => {
      setConsentError(null);
      try {
        await groupService.setScreenAiConsent(groupId, connectionId, allowed);
      } catch (error) {
        setConsentError(describeScreenAiError(error).message);
      }
      await sharesQuery.reload().catch(() => {});
    },
    [groupId, sharesQuery]
  );

  const [entries, setEntries] = useState([]);
  const [pending, setPending] = useState(null);
  const inFlight = useRef(null);

  const finish = useCallback((clientRequestId, patch) => {
    setEntries((previous) => previous.map((entry) => (entry.id === clientRequestId ? { ...entry, ...patch } : entry)));
    if (inFlight.current?.clientRequestId === clientRequestId) inFlight.current = null;
    setPending((current) => (current === clientRequestId ? null : current));
  }, []);

  const cancel = useCallback((reason = '분석을 취소했습니다.') => {
    const current = inFlight.current;
    if (!current) return;
    inFlight.current = null;
    current.reason = reason;
    current.controller.abort();
    groupService.cancelScreenAnalysis(groupId, current.clientRequestId).catch(() => {});
  }, [groupId]);

  const analyze = useCallback(
    async (share, rawQuestion, { image } = {}) => {
      if (inFlight.current) return { ok: false, message: '이미 진행 중인 화면 분석이 있습니다.' };
      const checked = validateQuestion(rawQuestion, limits);
      if (!checked.ok) return checked;

      const clientRequestId = newClientRequestId();
      const controller = new AbortController();
      const request = { clientRequestId, controller, connectionId: share.connectionId, reason: null };
      inFlight.current = request;
      setPending(clientRequestId);
      setEntries((previous) => [
        ...previous,
        { id: clientRequestId, question: checked.question, sharerName: share.sharerName, status: 'pending' },
      ]);

      try {
        const frame = image ? { dataUrl: image } : await capture(share.streamManager, limits);
        if (controller.signal.aborted) throw Object.assign(new Error('canceled'), { code: 'ERR_CANCELED' });
        const body = buildAnalyzeRequest({ share, question: checked.question, image: frame.dataUrl, clientRequestId });
        const result = await groupService.analyzeScreen(groupId, body, {
          signal: controller.signal,
          timeoutMs: limits.timeoutSeconds * 1000 + TIMEOUT_MARGIN_MS,
        });
        finish(clientRequestId, { status: 'done', answer: result?.answer || '', model: result?.model || null });
        return { ok: true };
      } catch (error) {
        const described = controller.signal.aborted
          ? { message: request.reason || '분석을 취소했습니다.', cancelled: true }
          : error?.response || error?.code
            ? describeScreenAiError(error)
            : { message: error?.message };
        finish(clientRequestId, {
          status: described.cancelled ? 'cancelled' : 'failed',
          errorMessage: described.message || '화면 분석에 실패했습니다.',
        });
        const staleShare = described.shareEnded || ['SHARER_CONSENT_REQUIRED', 'SCREEN_STREAM_MISMATCH'].includes(described.code);
        if (staleShare) sharesQuery.reload().catch(() => {});
        return { ok: false, message: described.message };
      }
    },
    [capture, finish, groupId, limits, sharesQuery]
  );

  // 분석 중인 화면공유가 사라지면(공유 종료·퇴장) 즉시 취소한다.
  useEffect(() => {
    const current = inFlight.current;
    if (!current) return;
    const stillShared = (remoteParticipants || []).some(
      (participant) => participant.connectionId === current.connectionId && participant.streamManager
    );
    if (!stillShared) cancel('화면공유가 종료되어 분석을 중단했습니다.');
  }, [cancel, key, remoteParticipants]);

  useEffect(() => () => cancel(), [cancel]);

  return {
    sharesQuery,
    isEnabled: sharesQuery.data?.enabled !== false,
    viewerConnected: sharesQuery.data?.viewerConnected !== false,
    shares,
    ownShares,
    setConsent,
    consentError,
    limits,
    entries,
    isPending: pending !== null,
    analyze,
    cancel,
  };
}
