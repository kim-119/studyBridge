import { useCallback, useEffect, useRef, useState } from 'react';
import { groupService } from '../../../services/api';
import {
  discardScreenCaptureConsent,
  getScreenShareStatus,
  isNativeScreenShareAvailable,
  onScreenShareStateChange,
  requestScreenCaptureConsent,
  requestScreenShareNotificationPermission,
  startNativeScreenShare,
  stopNativeScreenShare,
} from '../../platform/screenShare';
import {
  SCREEN_DEVICE_TYPE,
  SHARE_PHASE,
  buildScreenShareStart,
  describeScreenShareError,
  phaseFromNative,
  precheckScreenShare,
  screenClientInstanceId,
  stopNoticeFrom,
} from './screenShareModel';

const defaultBridge = {
  isAvailable: isNativeScreenShareAvailable,
  getStatus: getScreenShareStatus,
  onStateChange: onScreenShareStateChange,
  requestNotificationPermission: requestScreenShareNotificationPermission,
  requestConsent: requestScreenCaptureConsent,
  discardConsent: discardScreenCaptureConsent,
  start: startNativeScreenShare,
  stop: stopNativeScreenShare,
};

/**
 * 그룹방에서 Android 전체 화면을 SCREEN 연결로 송출한다(WebView PRIMARY 카메라·마이크는 그대로).
 * 순서: 서버 슬롯 확인 → 시스템 화면 녹화 동의 → SCREEN 토큰(30초 안 접속) → 네이티브 Foreground Service 송출.
 */
export function useNativeScreenShare({ groupId, userId, displayName, session, bridge = defaultBridge }) {
  const isAvailable = bridge.isAvailable();
  const [phase, setPhase] = useState(SHARE_PHASE.IDLE);
  const [notice, setNotice] = useState(null);
  const [nativeStatus, setNativeStatus] = useState(null);
  const busyRef = useRef(false);
  const connectionIdRef = useRef(null);
  const instanceIdRef = useRef(null);

  const releaseSlot = useCallback(() => {
    const connectionId = connectionIdRef.current;
    connectionIdRef.current = null;
    if (connectionId) groupService.stopScreenShare(groupId, connectionId).catch(() => {});
  }, [groupId]);

  const applyStatus = useCallback(
    (status) => {
      if (!status) return;
      setNativeStatus(status);
      if (status.connectionId) connectionIdRef.current = status.connectionId;
      if (status.state === 'idle') {
        // 시작 전 단계(슬롯 확인·동의·토큰)는 JS 가 진행 중이므로 이전 송출의 idle 로 덮지 않는다.
        if (!busyRef.current) setPhase(SHARE_PHASE.IDLE);
        if (status.reason) {
          releaseSlot();
          const message = stopNoticeFrom(status);
          if (message) setNotice(message);
        }
        return;
      }
      setPhase(phaseFromNative(status));
    },
    [releaseSlot]
  );

  useEffect(() => {
    if (!isAvailable) return undefined;
    let isAlive = true;
    // 앱 재실행·WebView 재로딩 뒤에도 서비스가 송출 중이면 그 상태를 이어서 보여준다.
    bridge
      .getStatus()
      .then((status) => {
        if (isAlive && status?.state !== 'idle') applyStatus(status);
      })
      .catch(() => {});
    const unsubscribe = bridge.onStateChange((status) => {
      if (isAlive) applyStatus(status);
    });
    return () => {
      isAlive = false;
      unsubscribe();
    };
  }, [applyStatus, bridge, isAvailable]);

  const start = useCallback(async () => {
    if (!isAvailable || busyRef.current || phase !== SHARE_PHASE.IDLE) return;
    busyRef.current = true;
    setNotice(null);
    try {
      const primaryConnectionId = session.getPrimaryConnectionId?.() || null;
      if (!primaryConnectionId) throw new Error('화상 연결이 준비된 뒤에 화면을 공유할 수 있습니다.');

      setPhase(SHARE_PHASE.CHECKING);
      const precheck = precheckScreenShare(await groupService.getVideoConnections(groupId), userId);
      if (!precheck.ok) throw new Error(precheck.message);

      await bridge.requestNotificationPermission().catch(() => {});
      setPhase(SHARE_PHASE.CONSENT);
      const consent = await bridge.requestConsent();
      if (!consent?.granted) {
        setPhase(SHARE_PHASE.IDLE);
        setNotice('화면 녹화를 허용하지 않아 화면공유를 시작하지 않았습니다.');
        return;
      }

      setPhase(SHARE_PHASE.CONNECTING);
      instanceIdRef.current = instanceIdRef.current || screenClientInstanceId();
      let tokenResponse;
      try {
        tokenResponse = await groupService.getScreenShareToken(groupId, {
          primaryConnectionId,
          clientInstanceId: instanceIdRef.current,
          deviceType: SCREEN_DEVICE_TYPE,
        });
      } catch (error) {
        await bridge.discardConsent().catch(() => {});
        throw error;
      }

      connectionIdRef.current = tokenResponse?.connectionId || null;
      // 여기부터는 네이티브 stateChange 가 단계를 정한다(빠른 실패의 idle 도 바로 반영).
      busyRef.current = false;
      try {
        await bridge.start(
          buildScreenShareStart({ tokenResponse, iceServers: session.getIceServers?.(), userId, displayName })
        );
      } catch (error) {
        releaseSlot();
        throw error;
      }
    } catch (error) {
      setPhase(SHARE_PHASE.IDLE);
      setNotice(describeScreenShareError(error));
    } finally {
      busyRef.current = false;
    }
  }, [bridge, displayName, groupId, isAvailable, phase, releaseSlot, session, userId]);

  const stop = useCallback(async () => {
    if (!isAvailable) return;
    setPhase(SHARE_PHASE.STOPPING);
    try {
      await bridge.stop();
    } catch (error) {
      setNotice(describeScreenShareError(error));
    }
  }, [bridge, isAvailable]);

  // 그룹스터디에서 나가면(화면 이탈) 송출도 끝낸다.
  const phaseRef = useRef(phase);
  phaseRef.current = phase;
  useEffect(
    () => () => {
      if (isAvailable && phaseRef.current !== SHARE_PHASE.IDLE) bridge.stop().catch(() => {});
    },
    [bridge, isAvailable]
  );

  return {
    isAvailable,
    phase,
    isSharing: phase === SHARE_PHASE.PUBLISHING,
    isBusy: phase !== SHARE_PHASE.IDLE && phase !== SHARE_PHASE.PUBLISHING,
    notice,
    nativeStatus,
    start,
    stop,
    dismissNotice: () => setNotice(null),
  };
}
