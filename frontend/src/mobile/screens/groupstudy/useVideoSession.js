import { useCallback, useEffect, useRef, useState } from 'react';
import { groupService } from '../../../services/api';
import {
  forceSecureWebSocketTransport,
  parseConnectionMetadata,
  resolveIceServers,
} from '../../../utils/webrtc/iceServers';
import { describeApiError } from '../../data/useAsync';
import { registerAppStateChange } from '../../platform/nativeShell';
import {
  requestMediaPermissions,
  setSpeakerphone,
  startVoiceSession,
  stopVoiceSession,
} from '../../platform/mediaSession';

export const SESSION_STATE = {
  IDLE: 'idle',
  REQUESTING_PERMISSION: 'requesting-permission',
  CONNECTING: 'connecting',
  CONNECTED: 'connected',
  RECONNECTING: 'reconnecting',
  FAILED: 'failed',
};

const MAX_RECONNECT_ATTEMPTS = 3;
const RECONNECT_BACKOFF_MS = [2000, 4000, 8000];

const DEVICE_ERROR_MESSAGE = {
  NotAllowedError: '카메라 또는 마이크 권한이 거부되었습니다. 설정에서 권한을 허용해주세요.',
  PermissionDeniedError: '카메라 또는 마이크 권한이 거부되었습니다. 설정에서 권한을 허용해주세요.',
  NotFoundError: '사용할 수 있는 카메라 또는 마이크를 찾지 못했습니다.',
  NotReadableError: '카메라 또는 마이크를 다른 앱이 사용 중입니다.',
  OverconstrainedError: '이 기기에서 지원하지 않는 카메라 설정입니다.',
};

function describeSessionError(error) {
  if (error?.name && DEVICE_ERROR_MESSAGE[error.name]) return DEVICE_ERROR_MESSAGE[error.name];
  if (error?.message?.includes('permission')) return DEVICE_ERROR_MESSAGE.NotAllowedError;
  return describeApiError(error);
}

export function useVideoSession(groupId) {
  const [state, setState] = useState(SESSION_STATE.IDLE);
  const [errorMessage, setErrorMessage] = useState(null);
  const [participants, setParticipants] = useState({});
  const [isCameraOn, setCameraOn] = useState(true);
  const [isMicrophoneOn, setMicrophoneOn] = useState(true);
  const [isSpeakerphoneOn, setSpeakerphoneOn] = useState(true);
  const [reconnectAttempt, setReconnectAttempt] = useState(0);

  const sessionRef = useRef(null);
  const publisherRef = useRef(null);
  const openViduRef = useRef(null);
  const reconnectTimerRef = useRef(null);
  const isLeavingRef = useRef(false);
  const joinRef = useRef(null);

  const upsertParticipant = useCallback((connectionId, patch) => {
    setParticipants((previous) => ({
      ...previous,
      [connectionId]: { ...(previous[connectionId] || {}), connectionId, ...patch },
    }));
  }, []);

  const removeParticipant = useCallback((connectionId) => {
    setParticipants((previous) => {
      const next = { ...previous };
      delete next[connectionId];
      return next;
    });
  }, []);

  const teardown = useCallback(async () => {
    clearTimeout(reconnectTimerRef.current);

    publisherRef.current?.stream?.getMediaStream?.()?.getTracks?.().forEach((track) => track.stop());
    sessionRef.current?.disconnect();

    sessionRef.current = null;
    publisherRef.current = null;
    openViduRef.current = null;

    setParticipants({});
    await stopVoiceSession();
  }, []);

  const leave = useCallback(async () => {
    isLeavingRef.current = true;
    await teardown();
    setState(SESSION_STATE.IDLE);
    setReconnectAttempt(0);
  }, [teardown]);

  const scheduleReconnect = useCallback(() => {
    if (isLeavingRef.current) return;

    setReconnectAttempt((attempt) => {
      if (attempt >= MAX_RECONNECT_ATTEMPTS) {
        setErrorMessage('연결이 끊어졌습니다. 다시 참여해주세요.');
        setState(SESSION_STATE.FAILED);
        return attempt;
      }

      setState(SESSION_STATE.RECONNECTING);
      reconnectTimerRef.current = setTimeout(() => {
        joinRef.current?.({ isReconnect: true });
      }, RECONNECT_BACKOFF_MS[Math.min(attempt, RECONNECT_BACKOFF_MS.length - 1)]);

      return attempt + 1;
    });
  }, []);

  const join = useCallback(
    async ({ isReconnect = false } = {}) => {
      isLeavingRef.current = false;
      setErrorMessage(null);

      if (!isReconnect) {
        setReconnectAttempt(0);
        setState(SESSION_STATE.REQUESTING_PERMISSION);

        const permissions = await requestMediaPermissions();
        if (!permissions.granted) {
          setErrorMessage(DEVICE_ERROR_MESSAGE.NotAllowedError);
          setState(SESSION_STATE.FAILED);
          return;
        }
      }

      setState(isReconnect ? SESSION_STATE.RECONNECTING : SESSION_STATE.CONNECTING);

      try {
        await teardown();

        const { OpenVidu } = await import('openvidu-browser');
        const tokenResponse = await groupService.getVideoToken(groupId);
        const { token } = tokenResponse;

        const openVidu = new OpenVidu();
        forceSecureWebSocketTransport(openVidu);
        openVidu.setAdvancedConfiguration({ iceServers: resolveIceServers(tokenResponse) });
        openViduRef.current = openVidu;

        const session = openVidu.initSession();
        sessionRef.current = session;

        session.on('connectionCreated', (event) => {
          const { connectionId } = event.connection || {};
          if (!connectionId || connectionId === session.connection?.connectionId) return;

          const metadata = parseConnectionMetadata(event.connection);
          upsertParticipant(connectionId, { name: metadata.name || '참여자', isMe: false });
        });

        session.on('streamCreated', (event) => {
          const connectionId = event.stream.connection.connectionId;
          const metadata = parseConnectionMetadata(event.stream.connection);
          const subscriber = session.subscribe(event.stream, undefined);

          upsertParticipant(connectionId, {
            name: metadata.name || '참여자',
            isMe: false,
            streamManager: subscriber,
          });
        });

        session.on('streamDestroyed', (event) => {
          upsertParticipant(event.stream.connection.connectionId, { streamManager: null });
        });

        session.on('connectionDestroyed', (event) => {
          removeParticipant(event.connection.connectionId);
        });

        // 서버/네트워크가 끊어 세션이 종료된 경우에만 재연결한다(사용자 나가기는 제외).
        session.on('sessionDisconnected', (event) => {
          if (isLeavingRef.current || event?.reason === 'disconnect') return;
          scheduleReconnect();
        });

        session.on('reconnecting', () => setState(SESSION_STATE.RECONNECTING));
        session.on('reconnected', () => {
          setReconnectAttempt(0);
          setState(SESSION_STATE.CONNECTED);
        });

        await session.connect(token, JSON.stringify({ name: '나' }));

        const publisher = await openVidu.initPublisherAsync(undefined, {
          audioSource: undefined,
          videoSource: undefined,
          publishAudio: true,
          publishVideo: true,
          resolution: '480x640',
          frameRate: 24,
          mirror: true,
        });

        await session.publish(publisher);
        publisherRef.current = publisher;

        upsertParticipant(session.connection.connectionId, {
          name: '나',
          isMe: true,
          streamManager: publisher,
        });

        const audioState = await startVoiceSession({ speakerphone: true });
        setSpeakerphoneOn(Boolean(audioState.speakerphone));

        setCameraOn(true);
        setMicrophoneOn(true);
        setReconnectAttempt(0);
        setState(SESSION_STATE.CONNECTED);
      } catch (error) {
        console.warn('화상 스터디 연결에 실패했습니다.', error);

        if (isReconnect) {
          scheduleReconnect();
          return;
        }

        setErrorMessage(describeSessionError(error));
        setState(SESSION_STATE.FAILED);
        await teardown();
      }
    },
    [groupId, removeParticipant, scheduleReconnect, teardown, upsertParticipant]
  );

  joinRef.current = join;

  const toggleCamera = useCallback(() => {
    setCameraOn((previous) => {
      const next = !previous;
      publisherRef.current?.publishVideo(next);
      return next;
    });
  }, []);

  const toggleMicrophone = useCallback(() => {
    setMicrophoneOn((previous) => {
      const next = !previous;
      publisherRef.current?.publishAudio(next);
      return next;
    });
  }, []);

  const toggleSpeakerphone = useCallback(async () => {
    const next = !isSpeakerphoneOn;
    const audioState = await setSpeakerphone(next);
    setSpeakerphoneOn(Boolean(audioState.speakerphone ?? next));
  }, [isSpeakerphoneOn]);

  // 백그라운드 전환 시 카메라를 끊어 배터리/프라이버시를 지키고, 복귀 시 원래 상태로 되돌린다.
  const cameraBeforeBackgroundRef = useRef(true);

  useEffect(() => {
    return registerAppStateChange(({ isActive }) => {
      if (!publisherRef.current) return;

      if (!isActive) {
        cameraBeforeBackgroundRef.current = isCameraOn;
        publisherRef.current.publishVideo(false);
        setCameraOn(false);
        return;
      }

      if (cameraBeforeBackgroundRef.current) {
        publisherRef.current.publishVideo(true);
        setCameraOn(true);
      }
    });
  }, [isCameraOn]);

  useEffect(() => {
    return () => {
      isLeavingRef.current = true;
      clearTimeout(reconnectTimerRef.current);
      publisherRef.current?.stream?.getMediaStream?.()?.getTracks?.().forEach((track) => track.stop());
      sessionRef.current?.disconnect();
      stopVoiceSession();
    };
  }, []);

  return {
    state,
    errorMessage,
    participants: Object.values(participants),
    isCameraOn,
    isMicrophoneOn,
    isSpeakerphoneOn,
    reconnectAttempt,
    join,
    leave,
    toggleCamera,
    toggleMicrophone,
    toggleSpeakerphone,
  };
}
